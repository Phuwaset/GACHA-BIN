"""Hardware Abstraction Layer (HAL) package."""
from typing import Optional
from app.config import HARDWARE_MODE
from app.hal.base import BaseHardwareController
from app.hal.mock import MockHardwareController

_controller_instance: Optional[BaseHardwareController] = None


def get_hardware_controller() -> BaseHardwareController:
    """Return singleton hardware controller instance."""
    global _controller_instance
    if _controller_instance is None:
        if HARDWARE_MODE.lower() == "gpio":
            try:
                from app.hal.gpio import GPIOHardwareController
                _controller_instance = GPIOHardwareController()
            except Exception:
                _controller_instance = MockHardwareController()
        else:
            _controller_instance = MockHardwareController()
    return _controller_instance
