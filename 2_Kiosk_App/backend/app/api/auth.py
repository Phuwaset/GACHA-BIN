"""Authentication, Session Management, and Role-Based Access Endpoints."""
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.config import SUPERADMIN_PHONE, SUPERADMIN_DEFAULT_PIN
from app.services.db import get_db, User
from app.services.security import tokens, verify_pin, pin_limiter
from app.services.session_manager import session_manager, get_local_ip, get_wifi_ssid
from app.services.hardware import check_bin_status

router = APIRouter(prefix="/api/auth", tags=["auth"])
PHONE_REGEX = re.compile(r"^0\d{8,9}$")


def _clean_phone(raw: str) -> str:
    cleaned = raw.strip().replace("-", "").replace(" ", "")
    if not PHONE_REGEX.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="หมายเลขโทรศัพท์ไม่ถูกต้อง ต้องขึ้นต้นด้วย 0 และมี 9-10 หลัก",
        )
    return cleaned


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., description="Phone number starting with 0")
    pin: Optional[str] = Field(None, description="PIN code for superadmin accounts")
    client_type: Optional[str] = Field("kiosk", description="Client context: 'kiosk' or 'admin'")


def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    """Dependency to extract authenticated user from Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    res = tokens.resolve(token)
    if not res:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please log in again.")
    user = db.query(User).filter(User.key_id == res["key_id"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency restricting endpoint to superadmin role."""
    if current_user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Super Admin role required")
    return current_user


@router.post("/login")
def login_or_register(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate or register user via mobile:
    1. Validates phone number and username.
    2. If phone belongs to Super Admin, requires valid PIN.
    3. Acquires single-session lock or places user in queue.
    """
    cleaned_phone = _clean_phone(payload.phone)
    cleaned_name = payload.username.strip()

    user = db.query(User).filter(User.phone == cleaned_phone).first()

    # If new user, create record
    if not user:
        user = User(
            username=cleaned_name,
            phone=cleaned_phone,
            score=0,
            total_score=0,
            role="user",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Super Admin PIN check
    if user.role == "superadmin" or cleaned_phone == SUPERADMIN_PHONE:
        lock_remaining = pin_limiter.locked_for(cleaned_phone)
        if lock_remaining > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"ป้อน PIN ผิดเกินจำนวนครั้ง กรุณารอ {lock_remaining} วินาที",
            )
        if not payload.pin:
            return {
                "requires_pin": True,
                "message": "กรุณากรอกรหัส PIN สำหรับบัญชี Super Admin",
                "phone": cleaned_phone,
            }
        if not verify_pin(payload.pin, user.pin_code):
            pin_limiter.fail(cleaned_phone)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="รหัส PIN ไม่ถูกต้อง")
        pin_limiter.success(cleaned_phone)

    # Acquire session lock on Kiosk only for recycling clients (not Admin portal)
    if payload.client_type == "admin":
        is_active, is_queued, msg = False, False, "Admin logged in"
    else:
        is_active, is_queued, msg = session_manager.start_session(user)

    token = tokens.issue(user.key_id, user.role, ttl_sec=3600)

    return {
        "token": token,
        "key_id": user.key_id,
        "username": user.username,
        "phone": user.phone,
        "score": user.score,
        "total_score": user.total_score,
        "role": user.role,
        "is_active_session": is_active,
        "is_queued": is_queued,
        "message": msg,
    }


@router.get("/session/status")
def get_session_status():
    """Real-time status endpoint polled by Kiosk Standby Screen and Mobile clients."""
    status_info = session_manager.get_status()
    bin_status = check_bin_status()
    ip = get_local_ip()
    ssid = get_wifi_ssid()

    return {
        **status_info,
        "kiosk_ip": ip,
        "wifi_ssid": ssid,
        "bin_status": bin_status,
        "mobile_url": f"http://{ip}:8000/m",
    }


@router.post("/session/logout")
def logout_session(current_user: User = Depends(get_current_user)):
    """User manually finishes and unlocks the kiosk screen for the next in queue."""
    session_manager.end_session(current_user.key_id)
    return {"success": True, "message": "เซสชันสิ้นสุดเรียบร้อยแล้ว"}
