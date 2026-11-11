"""Raspberry Pi GPIO Hardware Controller (Concept v2.0 Dual-Servo & Ultrasonic)."""
import logging
import math
import threading
import time
from typing import Dict, Any, List
from app.hal.base import BaseHardwareController

logger = logging.getLogger("gachabin.hal.gpio")

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO = None
    GPIO_AVAILABLE = False


class GPIOHardwareController(BaseHardwareController):
    """Real GPIO Hardware Controller for Raspberry Pi 4/5."""

    # Default LED indicator pins
    PIN_LED_GREEN: int = 22
    PIN_LED_RED: int = 27

    def __init__(self) -> None:
        if not GPIO_AVAILABLE or GPIO is None:
            raise RuntimeError("RPi.GPIO is not available on this platform")

        self._lock = threading.Lock()
        self._active_pwms: Dict[int, Any] = {}

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        GPIO.setup(self.PIN_LED_GREEN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.PIN_LED_RED, GPIO.OUT, initial=GPIO.LOW)
        logger.info("[HAL-GPIO] Initialized GPIO Hardware Controller")

    def _angle_to_duty(self, angle: int) -> float:
        """Convert degree [0..180] to 50Hz PWM duty cycle [2.5%..12.5%]."""
        clamped = max(0, min(180, angle))
        return 2.5 + (clamped / 180.0) * 10.0

    def set_servo_angle(self, pin: int, angle: int) -> bool:
        if not GPIO or pin <= 0:
            return False
        with self._lock:
            try:
                GPIO.setup(pin, GPIO.OUT)
                pwm = self._active_pwms.get(pin)
                if pwm is None:
                    pwm = GPIO.PWM(pin, 50)  # 50Hz
                    pwm.start(self._angle_to_duty(angle))
                    self._active_pwms[pin] = pwm
                else:
                    pwm.ChangeDutyCycle(self._angle_to_duty(angle))

                # Allow servo time to travel, then stop pulse to prevent jitter/heating
                time.sleep(0.35)
                pwm.ChangeDutyCycle(0)
                return True
            except Exception as e:
                logger.error("[HAL-GPIO] Servo error on pin %d: %s", pin, e)
                return False

    def sort_item(self, item_type: str, settings: Dict[str, Any]) -> bool:
        """
        Execute 2-stage sorting sequence:
        1. Servo 1 tilts chute to target angle (45° for plastic, 135° for metal).
        2. Dwell to ensure chute completes tilt.
        3. Servo 2 sweeps pusher arm to push bottle down chute.
        4. Servo 2 retracts to home.
        5. Servo 1 centers back to 90°.
        """
        item_lower = item_type.lower()
        div_cfg = settings.get("servo_diverter", {})
        push_cfg = settings.get("servo_pusher", {})

        pin_div = div_cfg.get("gpio_pin", 12)
        pin_push = push_cfg.get("gpio_pin", 13)

        angle_center = div_cfg.get("val_center", 90)
        target_angle = div_cfg.get("val_left", 45) if item_lower == "plastic" else div_cfg.get("val_right", 135)
        push_angle = push_cfg.get("val_push", 150)
        push_retract = push_cfg.get("val_center", 90)

        div_dwell = max(0.2, div_cfg.get("duration_ms", 600) / 1000.0)
        push_dwell = max(0.4, push_cfg.get("duration_ms", 1200) / 1000.0)

        logger.info("[HAL-GPIO] [Stage 1] Tilt diverter (pin %d) -> %d deg (%s)", pin_div, target_angle, item_lower)
        self.set_servo_angle(pin_div, target_angle)
        time.sleep(div_dwell)

        logger.info("[HAL-GPIO] [Stage 2] Push bottle (pin %d) -> %d deg", pin_push, push_angle)
        self.set_servo_angle(pin_push, push_angle)
        time.sleep(push_dwell)

        logger.info("[HAL-GPIO] [Reset] Retract pusher -> %d deg, Center diverter -> %d deg", push_retract, angle_center)
        self.set_servo_angle(pin_push, push_retract)
        time.sleep(0.3)
        self.set_servo_angle(pin_div, angle_center)
        return True

    def _single_ultrasonic_pulse(self, trig_pin: int, echo_pin: int) -> float:
        """Measure distance with 10us trigger pulse and echo timeout (cm)."""
        if not GPIO or trig_pin <= 0:
            return 0.0

        is_single_pin = (echo_pin <= 0 or echo_pin == trig_pin)

        # 1. Setup Trigger pin
        GPIO.setup(trig_pin, GPIO.OUT)
        GPIO.output(trig_pin, GPIO.LOW)
        time.sleep(0.000002)

        # 2. Fire 10us pulse
        GPIO.output(trig_pin, GPIO.HIGH)
        time.sleep(0.000010)
        GPIO.output(trig_pin, GPIO.LOW)

        # 3. Setup Echo pin
        actual_echo = trig_pin if is_single_pin else echo_pin
        if is_single_pin:
            GPIO.setup(actual_echo, GPIO.IN)
        else:
            GPIO.setup(actual_echo, GPIO.IN)

        # 4. Measure Echo pulse duration with 30ms timeout (max ~5 meters)
        timeout = time.time() + 0.035
        pulse_start = time.time()
        while GPIO.input(actual_echo) == 0:
            pulse_start = time.time()
            if pulse_start > timeout:
                return -1.0  # Timeout / disconnected

        pulse_end = pulse_start
        timeout = time.time() + 0.035
        while GPIO.input(actual_echo) == 1:
            pulse_end = time.time()
            if pulse_end > timeout:
                return -1.0  # Timeout

        pulse_duration = pulse_end - pulse_start
        distance = (pulse_duration * 34300.0) / 2.0  # Speed of sound: 343 m/s = 34300 cm/s
        return round(distance, 2)

    def read_bin_distance(self, trig_pin: int, echo_pin: int = 0) -> float:
        """Take median / average of valid pulses to filter electrical noise."""
        with self._lock:
            readings: List[float] = []
            for _ in range(3):
                d = self._single_ultrasonic_pulse(trig_pin, echo_pin)
                if math.isfinite(d) and 1.0 <= d <= 450.0:
                    readings.append(d)
                time.sleep(0.02)

            if not readings:
                return 0.0  # Sensor unreachable
            return round(sum(readings) / len(readings), 2)

    def is_bin_full(self, trig_pin: int, echo_pin: int, threshold_cm: float) -> bool:
        """
        Check if bin is full. Default-unsafe: if sensor fails or is unreadable (0.0 cm),
        treat as full to prevent overflow.
        """
        dist = self.read_bin_distance(trig_pin, echo_pin)
        if dist <= 0.0 or not math.isfinite(dist):
            logger.warning("[HAL-GPIO] Ultrasonic unreadable on trig=%d, treating as FULL", trig_pin)
            return True
        return dist <= threshold_cm

    def trigger_led(self, status: str) -> None:
        if not GPIO:
            return
        with self._lock:
            if status == "success":
                GPIO.output(self.PIN_LED_GREEN, GPIO.HIGH)
                GPIO.output(self.PIN_LED_RED, GPIO.LOW)
            elif status in ("error", "full"):
                GPIO.output(self.PIN_LED_GREEN, GPIO.LOW)
                GPIO.output(self.PIN_LED_RED, GPIO.HIGH)
            elif status in ("scanning", "sorting"):
                GPIO.output(self.PIN_LED_GREEN, GPIO.HIGH)
                GPIO.output(self.PIN_LED_RED, GPIO.HIGH)
            else:  # idle
                GPIO.output(self.PIN_LED_GREEN, GPIO.LOW)
                GPIO.output(self.PIN_LED_RED, GPIO.LOW)
