"""Gacha reward selection engine featuring True-Random 3-tier rolls and Raincheck flow."""
import logging
import secrets
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session
from app.config import GACHA_COST_POINTS, TIER_RATES
from app.services.db import User, GachaReward, GachaSpin

logger = logging.getLogger("gachabin.gacha")


def generate_claim_code() -> str:
    """Generate high-entropy alphanumeric ticket code, e.g. RWD-8F3A."""
    token = secrets.token_hex(2).upper()
    rand_alpha = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(2))
    return f"RWD-{token}{rand_alpha}"


def roll_tier() -> str:
    """
    Cryptographically secure float roll for 3-tier drop rate:
    - 0.00 <= R < 0.05: special (5%)
    - 0.05 <= R < 0.30: rare (25%)
    - 0.30 <= R < 1.00: common (70%)
    """
    # 6-decimal precision true random float [0.000000, 0.999999]
    r = secrets.randbelow(1_000_000) / 1_000_000.0
    cumulative = 0.0
    for tier, rate in TIER_RATES:
        cumulative += rate
        if r < cumulative:
            return tier
    return "common"


def execute_spin(db: Session, user: User) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute gacha spin:
    1. Validates user has >= 20 points.
    2. True-random roll determines Tier (Special 5%, Rare 25%, Common 70%).
    3. If reward in that tier has stock > 0:
       - score -= 20, stock -= 1
       - Record in gacha_spins with claim_status = 'pending'
    4. If reward in that tier is out of stock (stock == 0):
       - Raincheck Flow: score -= 20, ticket created with claim_status = 'waiting_restock'
       - User holds this ticket for next visit when staff restocks.
    """
    if user.score < GACHA_COST_POINTS:
        return False, {
            "error": "INSUFFICIENT_POINTS",
            "message": f"แต้มไม่เพียงพอ ต้องการ {GACHA_COST_POINTS} แต้ม (คุณมี {user.score} แต้ม)",
        }

    target_tier = roll_tier()
    rewards_in_tier = (
        db.query(GachaReward)
        .filter(GachaReward.tier == target_tier, GachaReward.is_active == True)
        .all()
    )

    if not rewards_in_tier:
        # Fallback to any active reward if tier is empty
        rewards_in_tier = db.query(GachaReward).filter(GachaReward.is_active == True).all()

    # Filter rewards that have physical stock
    in_stock_candidates = [r for r in rewards_in_tier if r.stock > 0]
    claim_code = generate_claim_code()

    if in_stock_candidates:
        # Pick one reward uniformly or weighted by drop_rate
        selected = secrets.choice(in_stock_candidates)
        user.score -= GACHA_COST_POINTS
        selected.stock -= 1

        spin_record = GachaSpin(
            key_id=user.key_id,
            reward_id=selected.id,
            points_spent=GACHA_COST_POINTS,
            claim_code=claim_code,
            claim_status="pending",
        )
        db.add(spin_record)
        db.commit()
        db.refresh(spin_record)
        db.refresh(user)

        logger.info("[Gacha] User %s won %s (%s) | Code: %s", user.username, selected.name, target_tier, claim_code)
        return True, {
            "status": "won",
            "tier": target_tier,
            "reward_name": selected.name,
            "category": selected.category,
            "image_url": selected.image_url,
            "claim_code": claim_code,
            "remaining_score": user.score,
            "message": f"ยินดีด้วย! คุณได้รับ '{selected.name}' นำรหัส {claim_code} ไปยื่นรับของกับเจ้าหน้าที่",
        }
    else:
        # Raincheck Flow: Tier is out of stock -> save session & ticket with waiting_restock status
        # Select representative item name for this tier
        rep_reward = rewards_in_tier[0] if rewards_in_tier else None
        reward_id = rep_reward.id if rep_reward else 1
        reward_name = rep_reward.name if rep_reward else f"ของรางวัลระดับ {target_tier.upper()}"

        user.score -= GACHA_COST_POINTS
        spin_record = GachaSpin(
            key_id=user.key_id,
            reward_id=reward_id,
            points_spent=GACHA_COST_POINTS,
            claim_code=claim_code,
            claim_status="waiting_restock",
        )
        db.add(spin_record)
        db.commit()
        db.refresh(spin_record)
        db.refresh(user)

        logger.info("[Gacha] Raincheck issued for User %s in tier %s | Code: %s", user.username, target_tier, claim_code)
        return True, {
            "status": "waiting_restock",
            "tier": target_tier,
            "reward_name": reward_name,
            "category": rep_reward.category if rep_reward else "",
            "image_url": rep_reward.image_url if rep_reward else "",
            "claim_code": claim_code,
            "remaining_score": user.score,
            "message": "เนื่องจากของรางวัลระดับนี้หมดชั่วคราว ระบบได้ล็อกสิทธิ์ไว้ในไอดีของคุณแล้ว สามารถมารับได้ทันทีเมื่อเจ้าหน้าที่เติมสต็อก",
        }


def allocate_waiting_tickets_on_restock(db: Session, reward_id: int) -> int:
    """
    When admin restocks a reward, automatically allocate waiting_restock tickets
    in that tier to 'pending' on a First-In-First-Out (FIFO) basis.
    Returns count of promoted tickets.
    """
    reward = db.query(GachaReward).filter(GachaReward.id == reward_id).first()
    if not reward or reward.stock <= 0:
        return 0

    waiting_spins = (
        db.query(GachaSpin)
        .join(GachaReward, GachaSpin.reward_id == GachaReward.id)
        .filter(GachaReward.tier == reward.tier, GachaSpin.claim_status == "waiting_restock")
        .order_by(GachaSpin.timestamp.asc())
        .all()
    )

    promoted = 0
    for spin in waiting_spins:
        if reward.stock <= 0:
            break
        spin.claim_status = "pending"
        spin.reward_id = reward.id
        reward.stock -= 1
        promoted += 1

    if promoted > 0:
        db.commit()
        logger.info("[Gacha] FIFO auto-allocated %d waiting tickets for reward %s", promoted, reward.name)
    return promoted
