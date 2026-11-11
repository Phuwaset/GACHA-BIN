"""Single-Session Lock, Inactivity Countdown, and Kiosk Network Manager."""
import logging
import socket
import subprocess
import sys
import threading
import time
from typing import Optional, Dict, Any, Tuple
from app.services.hardware import get_all_gpio_settings
from app.services.db import SessionLocal, User

logger = logging.getLogger("gachabin.session")


class KioskSessionManager:
    """Manages single-session kiosk lock and queue status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active_user_key_id: Optional[str] = None
        self.active_user_name: str = ""
        self.active_user_phone: str = ""
        self.active_user_role: str = "user"
        self.session_start_time: float = 0.0
        self.last_activity_time: float = 0.0
        self.session_timeout_sec: int = 60
        self.waiting_queue: list[str] = []

    def get_timeout_setting(self) -> int:
        try:
            settings = get_all_gpio_settings()
            return int(settings.get("system", {}).get("session_timeout_sec", 60))
        except Exception:
            return 60

    def start_session(self, user: User) -> Tuple[bool, bool, str]:
        """
        Attempt to acquire active session for user.
        Returns (is_active, is_queued, message).
        """
        with self._lock:
            now = time.time()
            self.session_timeout_sec = self.get_timeout_setting()

            # Check if existing session expired
            if self.active_user_key_id is not None:
                if (now - self.last_activity_time) >= self.session_timeout_sec:
                    logger.info("[Session] Previous session for %s timed out", self.active_user_name)
                    self._clear_session_locked()

            # If slot is free or same user reconnecting
            if self.active_user_key_id is None or self.active_user_key_id == user.key_id:
                self.active_user_key_id = user.key_id
                self.active_user_name = user.username
                self.active_user_phone = user.phone
                self.active_user_role = user.role
                self.session_start_time = now
                self.last_activity_time = now
                if user.key_id in self.waiting_queue:
                    self.waiting_queue.remove(user.key_id)
                logger.info("[Session] User %s (%s) acquired active session", user.username, user.key_id)
                return True, False, "Session acquired"

            # Slot is occupied by another user -> Put in queue
            if user.key_id not in self.waiting_queue:
                self.waiting_queue.append(user.key_id)
            queue_pos = self.waiting_queue.index(user.key_id) + 1
            remaining = max(0, int(self.session_timeout_sec - (now - self.last_activity_time)))
            logger.info("[Session] User %s queued at position %d", user.username, queue_pos)
            return False, True, f"กำลังมีผู้ใช้งานอยู่ (คิวที่ {queue_pos}, เหลือเวลาประมาณ {remaining} วินาที)"

    def touch_activity(self) -> None:
        """Reset inactivity timeout countdown on any interaction or bottle detection."""
        with self._lock:
            if self.active_user_key_id is not None:
                self.last_activity_time = time.time()

    def end_session(self, key_id: Optional[str] = None) -> bool:
        """End session if authorized and promote next user in queue."""
        with self._lock:
            if self.active_user_key_id is None:
                return True
            if key_id is not None and self.active_user_key_id != key_id:
                return False  # Cannot end someone else's session
            logger.info("[Session] User %s logged out", self.active_user_name)
            self._clear_session_locked()
            return True

    def _clear_session_locked(self) -> None:
        self.active_user_key_id = None
        self.active_user_name = ""
        self.active_user_phone = ""
        self.active_user_role = "user"
        self.session_start_time = 0.0
        self.last_activity_time = 0.0

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            self.session_timeout_sec = self.get_timeout_setting()

            # Auto-timeout check
            if self.active_user_key_id is not None:
                elapsed = now - self.last_activity_time
                if elapsed >= self.session_timeout_sec:
                    self._clear_session_locked()

            time_remaining = 0
            if self.active_user_key_id is not None:
                time_remaining = max(0, int(self.session_timeout_sec - (now - self.last_activity_time)))

            return {
                "has_active_session": self.active_user_key_id is not None,
                "active_key_id": self.active_user_key_id,
                "active_username": self.active_user_name,
                "active_phone": self.active_user_phone,
                "active_role": self.active_user_role,
                "time_remaining_sec": time_remaining,
                "queue_length": len(self.waiting_queue),
            }


session_manager = KioskSessionManager()


def get_local_ip() -> str:
    """Determine the LAN IP address of this device."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not send actual packets; connects to arbitrary LAN/external IP to inspect routing
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_wifi_ssid() -> str:
    """Get connected Wi-Fi SSID name."""
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["iwgetid", "-r"], timeout=1).decode("utf-8").strip()
            if out:
                return out
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], timeout=1).decode("utf-8", errors="ignore")
            for line in out.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        ssid = parts[1].strip()
                        if ssid:
                            return ssid
        except Exception:
            pass
    return "GACHA-BIN-WIFI"
