"""Mock Hardware Controller for development, testing, and simulation."""
import logging
import math
import time
from typing import Dict, Any
from app.hal.base import BaseHardwareController

logger = logging.getLogger("gachabin.hal.mock")


class MockHardwareController(BaseHardwareController):
    """Simulated hardware driver for non-Pi / development environments."""

    def __init__(self) -> None:
        self.last_led_status: str = "idle"
        self.door_open: bool = False
        self.servo_angles: Dict[int, int] = {}
        # Simulated distances in cm (greater than 30 cm = NOT full)
        self.mock_distances: Dict[str, float] = {
            "plastic": 45.0,
            "metal": 45.0,
        }
        self.last_sorted_item: str = ""
        logger.info("[HAL-MOCK] Initialized Mock Hardware Controller (Concept v2.0)")

    def set_mock_distance(self, bin_type: str, distance_cm: float) -> None:
        """Helper for test suites to simulate bin full condition."""
        if math.isfinite(distance_cm):
            self.mock_distances[bin_type.lower()] = max(0.0, float(distance_cm))

    def set_servo_angle(self, pin: int, angle: int) -> bool:
        clamped = max(0, min(180, int(angle)))
        self.servo_angles[pin] = clamped
        logger.info("[HAL-MOCK] Servo on pin %d rotated to %d deg", pin, clamped)
        return True

    def sort_item(self, item_type: str, settings: Dict[str, Any]) -> bool:
        """
        Simulate 2-stage sorting sequence:
        Servo 1 tilts -> dwell -> Servo 2 pushes -> Servo 2 retracts -> Servo 1 centers.
        """
        item_lower = item_type.lower()
        self.last_sorted_item = item_lower

        div_cfg = settings.get("servo_diverter", {})
        push_cfg = settings.get("servo_pusher", {})

        pin_div = div_cfg.get("gpio_pin", 12)
        pin_push = push_cfg.get("gpio_pin", 13)

        angle_center = div_cfg.get("val_center", 90)
        target_angle = div_cfg.get("val_left", 45) if item_lower == "plastic" else div_cfg.get("val_right", 135)
        push_angle = push_cfg.get("val_push", 150)
        push_retract = push_cfg.get("val_center", 90)

        logger.info("[HAL-MOCK] [Stage 1] Servo 1 (pin %d) tilt to %d deg for %s", pin_div, target_angle, item_lower)
        self.set_servo_angle(pin_div, target_angle)

        logger.info("[HAL-MOCK] [Stage 2] Servo 2 (pin %d) push bottle at %d deg", pin_push, push_angle)
        self.set_servo_angle(pin_push, push_angle)

        logger.info("[HAL-MOCK] [Reset] Servo 2 retract to %d deg, Servo 1 center to %d deg", push_retract, angle_center)
        self.set_servo_angle(pin_push, push_retract)
        self.set_servo_angle(pin_div, angle_center)

        return True

    def read_bin_distance(self, trig_pin: int, echo_pin: int = 0) -> float:
        # Match trig pin or default to plastic/metal
        dist = self.mock_distances.get("plastic", 45.0)
        return dist

    def is_bin_full(self, trig_pin: int, echo_pin: int, threshold_cm: float) -> bool:
        dist = self.read_bin_distance(trig_pin, echo_pin)
        if not math.isfinite(dist) or dist <= 0.0:
            return True  # Default-unsafe: sensor error treated as full
        return dist <= threshold_cm

    def trigger_led(self, status: str) -> None:
        self.last_led_status = status
        logger.info("[HAL-MOCK] LED status set to: %s", status)

    def open_recycle_door(self) -> bool:
        self.door_open = True
        return True

    def close_recycle_door(self) -> bool:
        self.door_open = False
        return True

    def dispense_gacha(self, tier: str) -> bool:
        logger.info("[HAL-MOCK] Gacha dispense simulated for tier: %s", tier)
        return True
