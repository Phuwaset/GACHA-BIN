"""Application settings and configuration."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
_candidate_model = BASE_DIR.parent / "models" / "best.pt"
if not _candidate_model.exists():
    _candidate_model = BASE_DIR / "model" / "best.pt"
if not _candidate_model.exists():
    _alt = BASE_DIR.parent.parent / "1_AI_Training" / "models" / "best.pt"
    if _alt.exists():
        _candidate_model = _alt
DEFAULT_MODEL_PATH = _candidate_model
STATIC_DIR = Path(__file__).resolve().parent / "static"
REWARD_IMAGE_DIR = STATIC_DIR / "rewards"

# Server Settings
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# Database
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'gachabin.db'}")

# Vision & AI
MODEL_PATH: str = os.getenv("MODEL_PATH", str(DEFAULT_MODEL_PATH))
CAMERA_INDEX: int = int(os.getenv("CAMERA_INDEX", "0"))
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONF_THRESHOLD", "0.65"))
HOLD_DURATION_SEC: float = float(os.getenv("HOLD_DURATION_SEC", "0.8"))
CONSECUTIVE_FRAMES: int = int(os.getenv("CONSECUTIVE_FRAMES", "5"))
DEBOUNCE_COOLDOWN_SEC: float = float(os.getenv("COOLDOWN_SEC", "2.0"))

# Hardware Mode ('mock' or 'gpio')
HARDWARE_MODE: str = os.getenv("HARDWARE_MODE", "mock")
BIN_POLL_INTERVAL_SEC: float = float(os.getenv("BIN_POLL_INTERVAL_SEC", "3.0"))

# Super Admin seed (PIN is stored hashed; change it after first login)
SUPERADMIN_USERNAME: str = os.getenv("SUPERADMIN_USERNAME", "phuwaset")
SUPERADMIN_PHONE: str = os.getenv("SUPERADMIN_PHONE", "0955134781")
ADMIN_PHONE: str = SUPERADMIN_PHONE
SUPERADMIN_DEFAULT_PIN: str = os.getenv("SUPERADMIN_DEFAULT_PIN", "123456")

# Business Logic
GACHA_COST_POINTS: int = int(os.getenv("GACHA_COST_POINTS", "20"))
POINTS_PLASTIC: int = int(os.getenv("POINTS_PLASTIC", "1"))
POINTS_METAL: int = int(os.getenv("POINTS_METAL", "2"))
# Ordered low-to-high cumulative thresholds for the tier roll; must sum to 1.0.
TIER_RATES: tuple = (("special", 0.05), ("rare", 0.25), ("common", 0.70))
