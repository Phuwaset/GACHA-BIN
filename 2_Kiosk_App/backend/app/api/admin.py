"""Super Admin Management and Hardware Calibration API Endpoints."""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.api.auth import require_superadmin
from app.hal import get_hardware_controller
from app.services.db import get_db, User, GachaReward, GachaSpin, GpioSetting
from app.services.gacha_engine import allocate_waiting_tickets_on_restock

logger = logging.getLogger("gachabin.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])
hw = get_hardware_controller()


class RewardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    tier: str = Field(..., pattern="^(common|rare|special)$")
    category: str = Field(default="")
    stock: int = Field(default=0, ge=0)
    drop_rate: float = Field(default=1.0, gt=0.0)
    image_url: str = Field(default="")


class RewardUpdateRequest(BaseModel):
    name: Optional[str] = None
    tier: Optional[str] = None
    category: Optional[str] = None
    stock: Optional[int] = None
    drop_rate: Optional[float] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class GpioSettingItem(BaseModel):
    setting_key: str
    gpio_pin: int
    gpio_pin_secondary: int = 0
    val_center: int = 90
    val_left: int = 45
    val_right: int = 135
    val_push: int = 180
    duration_ms: int = 1200
    threshold_cm: float = 30.0
    hold_timer_sec: int = 5
    session_timeout_sec: int = 60


class ServoTestRequest(BaseModel):
    pin: int = Field(..., gt=0)
    angle: int = Field(..., ge=0, le=180)


class UltrasonicTestRequest(BaseModel):
    trig_pin: int = Field(..., gt=0)
    echo_pin: int = Field(default=0)


class UserScoreUpdateRequest(BaseModel):
    score: int = Field(..., ge=0)


# --- 1. Inventory Management CRUD ---

@router.get("/rewards")
def admin_list_rewards(_admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    rewards = db.query(GachaReward).order_by(GachaReward.id.desc()).all()
    return rewards


@router.post("/rewards")
def admin_create_reward(
    payload: RewardCreateRequest,
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    reward = GachaReward(
        name=payload.name.strip(),
        tier=payload.tier.lower(),
        category=payload.category.strip(),
        stock=payload.stock,
        drop_rate=payload.drop_rate,
        image_url=payload.image_url.strip(),
        is_active=True,
    )
    db.add(reward)
    db.commit()
    db.refresh(reward)

    if reward.stock > 0:
        allocate_waiting_tickets_on_restock(db, reward.id)

    return reward


@router.put("/rewards/{reward_id}")
def admin_update_reward(
    reward_id: int,
    payload: RewardUpdateRequest,
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    reward = db.query(GachaReward).filter(GachaReward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward not found")

    old_stock = reward.stock
    if payload.name is not None:
        reward.name = payload.name.strip()
    if payload.tier is not None:
        reward.tier = payload.tier.lower()
    if payload.category is not None:
        reward.category = payload.category.strip()
    if payload.stock is not None:
        reward.stock = payload.stock
    if payload.drop_rate is not None:
        reward.drop_rate = payload.drop_rate
    if payload.image_url is not None:
        reward.image_url = payload.image_url.strip()
    if payload.is_active is not None:
        reward.is_active = payload.is_active

    db.commit()
    db.refresh(reward)

    # If stock increased, allocate to oldest waiting tickets
    if reward.stock > old_stock:
        promoted = allocate_waiting_tickets_on_restock(db, reward.id)
        if promoted > 0:
            db.refresh(reward)

    return reward


@router.delete("/rewards/{reward_id}")
def admin_delete_reward(
    reward_id: int,
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    reward = db.query(GachaReward).filter(GachaReward.id == reward_id).first()
    if not reward:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward not found")
    reward.is_active = False  # Soft delete
    db.commit()
    return {"success": True, "message": "Reward removed from active pool"}


# --- 2. Claims & Handover Verification ---

@router.get("/claims")
def admin_list_claims(_admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    spins = (
        db.query(GachaSpin, GachaReward, User)
        .join(GachaReward, GachaSpin.reward_id == GachaReward.id)
        .join(User, GachaSpin.key_id == User.key_id)
        .order_by(GachaSpin.timestamp.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": spin.id,
            "claim_code": spin.claim_code,
            "claim_status": spin.claim_status,
            "reward_name": reward.name,
            "tier": reward.tier,
            "user_name": user.username,
            "user_phone": user.phone,
            "timestamp": spin.timestamp.isoformat() if spin.timestamp else "",
        }
        for spin, reward, user in spins
    ]


@router.post("/claims/{claim_code}/handover")
def admin_confirm_handover(
    claim_code: str,
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    spin = db.query(GachaSpin).filter(GachaSpin.claim_code == claim_code.strip()).first()
    if not spin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    spin.claim_status = "claimed"
    db.commit()
    return {"success": True, "message": f"ยืนยันส่งมอบของรางวัล {claim_code} สำเร็จแล้ว"}


# --- 3. Hardware Settings & Live Calibration ---

@router.get("/settings")
def admin_get_settings(_admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    return db.query(GpioSetting).all()


@router.post("/settings")
def admin_save_settings(
    payload: List[GpioSettingItem],
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    for item in payload:
        record = db.query(GpioSetting).filter(GpioSetting.setting_key == item.setting_key).first()
        if not record:
            record = GpioSetting(setting_key=item.setting_key)
            db.add(record)
        record.gpio_pin = item.gpio_pin
        record.gpio_pin_secondary = item.gpio_pin_secondary
        record.val_center = item.val_center
        record.val_left = item.val_left
        record.val_right = item.val_right
        record.val_push = item.val_push
        record.duration_ms = item.duration_ms
        record.threshold_cm = item.threshold_cm
        record.hold_timer_sec = item.hold_timer_sec
        record.session_timeout_sec = item.session_timeout_sec
    db.commit()
    return {"success": True, "message": "Settings saved successfully"}


@router.post("/test/servo")
def admin_test_servo(payload: ServoTestRequest, _admin: User = Depends(require_superadmin)):
    ok = hw.set_servo_angle(payload.pin, payload.angle)
    return {"success": ok, "pin": payload.pin, "angle": payload.angle}


@router.post("/test/ultrasonic")
def admin_test_ultrasonic(payload: UltrasonicTestRequest, _admin: User = Depends(require_superadmin)):
    dist = hw.read_bin_distance(payload.trig_pin, payload.echo_pin)
    return {"trig_pin": payload.trig_pin, "echo_pin": payload.echo_pin, "distance_cm": dist}


# --- 4. Users Management ---

@router.get("/users")
def admin_list_users(_admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.desc()).limit(100).all()


@router.put("/users/{key_id}/score")
def admin_update_user_score(
    key_id: str,
    payload: UserScoreUpdateRequest,
    _admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.key_id == key_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.score = payload.score
    db.commit()
    return {"success": True, "key_id": key_id, "score": user.score}
