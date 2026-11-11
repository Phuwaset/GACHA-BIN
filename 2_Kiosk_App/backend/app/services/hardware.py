"""Hardware Manager service coordinating GPIO configuration, bin-full checks, and sorting."""
import logging
from typing import Dict, Any, Tuple
from app.hal import get_hardware_controller
from app.services.db import SessionLocal, GpioSetting

logger = logging.getLogger("gachabin.hardware")
hw = get_hardware_controller()


def get_all_gpio_settings() -> Dict[str, Dict[str, Any]]:
    """Load all settings from gpio_settings table into a nested dictionary."""
    with SessionLocal() as db:
        rows = db.query(GpioSetting).all()
        result = {}
        for r in rows:
            result[r.setting_key] = {
                "gpio_pin": r.gpio_pin,
                "gpio_pin_secondary": r.gpio_pin_secondary,
                "val_center": r.val_center,
                "val_left": r.val_left,
                "val_right": r.val_right,
                "val_push": r.val_push,
                "duration_ms": r.duration_ms,
                "threshold_cm": r.threshold_cm,
                "hold_timer_sec": r.hold_timer_sec,
                "session_timeout_sec": r.session_timeout_sec,
            }
        return result


def check_bin_status() -> Dict[str, Any]:
    """
    Check current trash levels for both plastic and metal bins.
    Returns: {
        'plastic': {'distance_cm': float, 'threshold_cm': float, 'is_full': bool},
        'metal': {'distance_cm': float, 'threshold_cm': float, 'is_full': bool}
    }
    """
    settings = get_all_gpio_settings()
    p_cfg = settings.get("us_plastic", {})
    m_cfg = settings.get("us_metal", {})

    p_trig = p_cfg.get("gpio_pin", 23)
    p_echo = p_cfg.get("gpio_pin_secondary", 24)
    p_thresh = float(p_cfg.get("threshold_cm", 30.0))

    m_trig = m_cfg.get("gpio_pin", 5)
    m_echo = m_cfg.get("gpio_pin_secondary", 6)
    m_thresh = float(m_cfg.get("threshold_cm", 30.0))

    p_dist = hw.read_bin_distance(p_trig, p_echo)
    m_dist = hw.read_bin_distance(m_trig, m_echo)

    p_full = (p_dist <= p_thresh) if p_dist > 0.0 else False
    m_full = (m_dist <= m_thresh) if m_dist > 0.0 else False

    return {
        "plastic": {"distance_cm": p_dist, "threshold_cm": p_thresh, "is_full": p_full},
        "metal": {"distance_cm": m_dist, "threshold_cm": m_thresh, "is_full": m_full},
    }


def execute_sorting(item_type: str) -> Tuple[bool, str]:
    """
    Check if target bin is full; if not, execute 2-stage servo sorting.
    Returns (success, message).
    """
    item_lower = item_type.lower()
    bin_status = check_bin_status()
    target_bin = bin_status.get(item_lower)

    if target_bin and target_bin["is_full"]:
        hw.trigger_led("full")
        msg = f"ถังขยะ {item_lower.upper()} เต็มแล้ว (ระยะวัดได้ {target_bin['distance_cm']} cm) กรุณาติดต่อเจ้าหน้าที่"
        logger.warning("[HAL] Sorting aborted: %s", msg)
        return False, msg

    settings = get_all_gpio_settings()
    hw.trigger_led("sorting")
    ok = hw.sort_item(item_lower, settings)
    hw.trigger_led("success" if ok else "error")
    return ok, "Sorted successfully" if ok else "Servo error during sorting"
