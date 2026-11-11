"""Gacha Spin and Reward Pool Endpoints."""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.auth import get_current_user
from app.services.db import get_db, User, GachaReward, GachaSpin
from app.services.gacha_engine import execute_spin
from app.services.session_manager import session_manager

logger = logging.getLogger("gachabin.gacha")
router = APIRouter(prefix="/api/gacha", tags=["gacha"])


@router.get("/rewards")
def list_rewards(db: Session = Depends(get_db)):
    """List all active gacha rewards for standby showcase and mobile view."""
    rewards = (
        db.query(GachaReward)
        .filter(GachaReward.is_active == True)
        .order_by(GachaReward.tier.desc(), GachaReward.id.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "tier": r.tier,
            "category": r.category,
            "stock": r.stock,
            "image_url": r.image_url,
            "drop_rate": r.drop_rate,
        }
        for r in rewards
    ]


@router.post("/spin")
def spin_gacha(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Spin gacha wheel (costs 20 points).
    Features True-Random 3-tier drop rate and Raincheck flow when out of stock.
    """
    session_manager.touch_activity()
    ok, result = execute_spin(db, current_user)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Spin failed"),
        )
    return result


@router.get("/my-tickets")
def get_my_tickets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Retrieve all tickets (pending, waiting_restock, claimed) for the logged-in user."""
    spins = (
        db.query(GachaSpin, GachaReward)
        .join(GachaReward, GachaSpin.reward_id == GachaReward.id)
        .filter(GachaSpin.key_id == current_user.key_id)
        .order_by(GachaSpin.timestamp.desc())
        .all()
    )
    return [
        {
            "id": spin.id,
            "claim_code": spin.claim_code,
            "claim_status": spin.claim_status,
            "points_spent": spin.points_spent,
            "reward_name": reward.name,
            "tier": reward.tier,
            "category": reward.category,
            "image_url": reward.image_url,
            "timestamp": spin.timestamp.isoformat() if spin.timestamp else "",
        }
        for spin, reward in spins
    ]
