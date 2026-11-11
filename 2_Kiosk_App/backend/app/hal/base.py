"""Abstract Base Class for Hardware Controller (Concept v2.0)."""
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseHardwareController(ABC):
    """Interface for Dual MG995 Servos, Dual HC-SR04 Ultrasonics, and LED indicators."""

    @abstractmethod
    def sort_item(self, item_type: str, settings: Dict[str, Any]) -> bool:
        """
        Execute 2-stage mechanical sorting sequence:
        1. Servo 1 (Diverter) tilts to target angle (plastic: left, metal: right).
        2. Dwell for diverter transit.
        3. Servo 2 (Pusher) sweeps bottle along cylindrical chute.
        4. Servo 2 retracts to home position.
        5. Servo 1 returns to center 90-degree neutral position.
        """
        pass

    @abstractmethod
    def set_servo_angle(self, pin: int, angle: int) -> bool:
        """Directly drive a servo pin to an angle in degrees [0..180] for live testing."""
        pass

    @abstractmethod
    def read_bin_distance(self, trig_pin: int, echo_pin: int = 0) -> float:
        """
        Measure distance to trash level using ultrasonic pulse (cm).
        Supports 2-pin (Trig/Echo) or 1-pin (SIG) mode when echo_pin <= 0.
        Returns distance in cm (or 0.0 if sensor is disconnected/unreachable).
        """
        pass

    @abstractmethod
    def is_bin_full(self, trig_pin: int, echo_pin: int, threshold_cm: float) -> bool:
        """
        Check if bin level has reached the threshold (distance <= threshold_cm).
        Implements moving average filter over 3 readings to prevent false positives.
        Default-unsafe: unreadable or negative readings return True (treated as FULL).
        """
        pass

    @abstractmethod
    def trigger_led(self, status: str) -> None:
        """Set LED status indicator (e.g. 'idle', 'scanning', 'sorting', 'success', 'error', 'full')."""
        pass

    # Backward compatibility no-ops for legacy test suites
    def open_recycle_door(self) -> bool:
        return True

    def close_recycle_door(self) -> bool:
        return True

    def dispense_gacha(self, tier: str) -> bool:
        return True
