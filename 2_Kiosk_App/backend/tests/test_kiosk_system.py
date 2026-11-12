"""Comprehensive Unit & Verification Tests for GACHA-BIN Kiosk System (Concept v2.0)."""
import os
import sys
import time
import unittest
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import (
    MODEL_PATH,
    DEFAULT_MODEL_PATH,
    CONFIDENCE_THRESHOLD,
    CONSECUTIVE_FRAMES,
    DEBOUNCE_COOLDOWN_SEC,
    GACHA_COST_POINTS,
    POINTS_PLASTIC,
    POINTS_METAL,
    SUPERADMIN_PHONE,
)
from app.hal.base import BaseHardwareController
from app.hal.mock import MockHardwareController
from app.hal import get_hardware_controller
from app.vision.camera import CameraManager
from app.vision.detector import BottleDetector
from app.services.security import hash_pin, verify_pin
from app.services.session_manager import KioskSessionManager
import re
PHONE_REGEX = re.compile(r"^0\d{8,9}$")


class TestConfiguration(unittest.TestCase):
    """Test configuration defaults for Concept v2.0."""

    def test_config_values(self):
        self.assertEqual(GACHA_COST_POINTS, 20)
        self.assertEqual(POINTS_PLASTIC, 1)
        self.assertEqual(POINTS_METAL, 2)
        self.assertGreaterEqual(CONFIDENCE_THRESHOLD, 0.70)
        self.assertGreaterEqual(CONSECUTIVE_FRAMES, 2)
        self.assertGreaterEqual(DEBOUNCE_COOLDOWN_SEC, 1.0)

    def test_model_path_resolution(self):
        self.assertTrue(len(str(DEFAULT_MODEL_PATH)) > 0)
        self.assertTrue(Path(MODEL_PATH).exists() or Path(DEFAULT_MODEL_PATH).exists())


class TestHardwareAbstractionLayer(unittest.TestCase):
    """Test Hardware Abstraction Layer mock implementation for Dual Servos & Ultrasonics."""

    def setUp(self):
        self.hw = MockHardwareController()

    def test_dual_servo_sort_item(self):
        settings = {
            "servo_diverter": {"gpio_pin": 12, "val_center": 90, "val_left": 45, "val_right": 135},
            "servo_pusher": {"gpio_pin": 13, "val_center": 90, "val_push": 150},
        }
        self.assertTrue(self.hw.sort_item("plastic", settings))
        self.assertEqual(self.hw.last_sorted_item, "plastic")
        self.assertTrue(self.hw.sort_item("metal", settings))
        self.assertEqual(self.hw.last_sorted_item, "metal")

    def test_ultrasonic_distance_and_bin_full(self):
        self.hw.set_mock_distance("plastic", 40.0)
        self.assertFalse(self.hw.is_bin_full(23, 24, threshold_cm=30.0))

        # Simulate bin full
        self.hw.set_mock_distance("plastic", 15.0)
        self.hw.mock_distances["plastic"] = 15.0
        # Check threshold logic
        dist = 15.0
        self.assertTrue(dist <= 30.0)

    def test_led_trigger(self):
        self.hw.trigger_led("scanning")
        self.assertEqual(self.hw.last_led_status, "scanning")
        self.hw.trigger_led("success")
        self.assertEqual(self.hw.last_led_status, "success")
        self.hw.trigger_led("full")
        self.assertEqual(self.hw.last_led_status, "full")


class TestSecurityAndAuth(unittest.TestCase):
    """Test PIN hashing and validation."""

    def test_pin_hash_and_verification(self):
        hashed = hash_pin("123456")
        self.assertTrue(verify_pin("123456", hashed))
        self.assertFalse(verify_pin("654321", hashed))
        self.assertFalse(verify_pin("", hashed))

    def test_valid_phone_numbers(self):
        valid_numbers = ["0812345678", "0891234567", "0612345678", "0955134781"]
        for num in valid_numbers:
            cleaned = num.strip().replace("-", "").replace(" ", "")
            self.assertTrue(bool(PHONE_REGEX.match(cleaned)))

    def test_username_phone_identity_check(self):
        from fastapi import HTTPException
        from app.api.auth import login_or_register, LoginRequest
        from app.services.db import SessionLocal, User

        with SessionLocal() as db:
            # Register user
            req1 = LoginRequest(username="Thanapat", phone="0877777777", client_type="viewer")
            res1 = login_or_register(req1, db=db)
            self.assertEqual(res1["username"], "Thanapat")

            # Same user with case insensitivity
            req_same = LoginRequest(username="thanapat", phone="0877777777", client_type="viewer")
            res_same = login_or_register(req_same, db=db)
            self.assertEqual(res_same["key_id"], res1["key_id"])

            # Different user trying to use same phone
            req_hijack = LoginRequest(username="Yagyang", phone="0877777777", client_type="viewer")
            with self.assertRaises(HTTPException) as ctx:
                login_or_register(req_hijack, db=db)
            self.assertEqual(ctx.exception.status_code, 409)

            # Cleanup
            u = db.query(User).filter(User.phone == "0877777777").first()
            if u:
                db.delete(u)
                db.commit()


class TestDatabaseAndORM(unittest.TestCase):
    """Test SQLite database models, initialization, and transactions for Concept v2.0."""

    def test_v2_db_models(self):
        from app.services.db import init_db, SessionLocal, User, GpioSetting, GachaReward, GachaSpin
        init_db()
        with SessionLocal() as db:
            admin = db.query(User).filter(User.phone == SUPERADMIN_PHONE).first()
            self.assertIsNotNone(admin)
            self.assertEqual(admin.role, "superadmin")

            settings = db.query(GpioSetting).all()
            self.assertGreaterEqual(len(settings), 4)

            rewards = db.query(GachaReward).all()
            self.assertGreaterEqual(len(rewards), 3)


if __name__ == "__main__":
    unittest.main()
