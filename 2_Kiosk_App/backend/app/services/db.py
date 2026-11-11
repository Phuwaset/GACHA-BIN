"""Database connection, models, and session management using SQLAlchemy (Concept v2.0 schema)."""
import logging
import secrets
from datetime import datetime, timezone
from typing import Generator
from sqlalchemy import (
    create_engine,
    inspect,
    Boolean,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import (
    DATABASE_URL,
    SUPERADMIN_USERNAME,
    SUPERADMIN_PHONE,
    SUPERADMIN_DEFAULT_PIN,
)
from app.services.security import hash_pin

logger = logging.getLogger("gachabin.db")


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def new_key_id() -> str:
    return f"USR-{secrets.token_hex(4).upper()}"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

if "sqlite" in DATABASE_URL:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    key_id = Column(String(36), primary_key=True, default=new_key_id)
    username = Column(String(50), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    score = Column(Integer, default=0, nullable=False)
    total_score = Column(Integer, default=0, nullable=False)
    role = Column(String(20), default="user", nullable=False)  # user / superadmin
    pin_code = Column(String(128), default="", nullable=False)  # PBKDF2 'salt$hash', empty for users
    created_at = Column(DateTime, default=utc_now, nullable=False)


class History(Base):
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(36), ForeignKey("users.key_id"), nullable=False, index=True)
    item_type = Column(String(20), nullable=False)  # plastic / metal
    points_added = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=utc_now, nullable=False)


class GpioSetting(Base):
    __tablename__ = "gpio_settings"

    setting_key = Column(String(40), primary_key=True)  # servo_diverter / servo_pusher / us_plastic / us_metal / system
    gpio_pin = Column(Integer, default=0, nullable=False)  # PWM pin, or Trigger/SIG pin; 0 = disabled
    gpio_pin_secondary = Column(Integer, default=0, nullable=False)  # Echo pin; 0 = single-pin sensor
    val_center = Column(Integer, default=90, nullable=False)
    val_left = Column(Integer, default=45, nullable=False)
    val_right = Column(Integer, default=135, nullable=False)
    val_push = Column(Integer, default=180, nullable=False)
    duration_ms = Column(Integer, default=1200, nullable=False)
    threshold_cm = Column(Float, default=30.0, nullable=False)
    hold_timer_sec = Column(Integer, default=5, nullable=False)
    session_timeout_sec = Column(Integer, default=60, nullable=False)


class GachaReward(Base):
    __tablename__ = "gacha_rewards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    tier = Column(String(20), nullable=False)  # common / rare / special
    category = Column(String(50), default="", nullable=False)
    image_url = Column(String(255), default="", nullable=False)
    drop_rate = Column(Float, default=1.0, nullable=False)  # relative weight inside its tier
    stock = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # soft delete keeps gacha_spins history intact


class GachaSpin(Base):
    __tablename__ = "gacha_spins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(36), ForeignKey("users.key_id"), nullable=False, index=True)
    reward_id = Column(Integer, ForeignKey("gacha_rewards.id"), nullable=False)
    points_spent = Column(Integer, default=20, nullable=False)
    claim_code = Column(String(20), unique=True, nullable=False)
    claim_status = Column(String(20), default="pending", nullable=False)  # pending / waiting_restock / claimed
    timestamp = Column(DateTime, default=utc_now, nullable=False)


DEFAULT_GPIO_SETTINGS = [
    dict(setting_key="servo_diverter", gpio_pin=12, val_center=90, val_left=45, val_right=135, duration_ms=600),
    dict(setting_key="servo_pusher", gpio_pin=13, val_center=90, val_push=150, duration_ms=1200),
    dict(setting_key="us_plastic", gpio_pin=23, gpio_pin_secondary=24, threshold_cm=30.0),
    dict(setting_key="us_metal", gpio_pin=5, gpio_pin_secondary=6, threshold_cm=30.0),
    dict(setting_key="system", gpio_pin=0, hold_timer_sec=5, session_timeout_sec=60),
]

DEFAULT_REWARDS = [
    ("พวงกุญแจรีไซเคิล", "common", "กิ๊ฟช็อป", 10),
    ("สติกเกอร์ GACHA-BIN", "common", "กิ๊ฟช็อป", 10),
    ("ที่คั่นหนังสือ", "common", "อุปกรณ์การเรียน", 10),
    ("กระเป๋าสตางค์", "rare", "กระเป๋า", 3),
    ("กระเป๋าดินสอ", "rare", "อุปกรณ์การเรียน", 3),
    ("ชุดเครื่องเขียน", "rare", "อุปกรณ์การเรียน", 3),
    ("โมเดลลูฟี่ วันพีซ", "special", "อาร์ตทอย", 1),
    ("Art Toy Limited", "special", "อาร์ตทอย", 1),
    ("หมวกฟางลูฟี่", "special", "อาร์ตทอย", 1),
    ("ตุ๊กตา Miniso Rare", "special", "ของแรร์ห้าง", 1),
    ("กล่องสุ่ม Miniso", "special", "ของแรร์ห้าง", 1),
]


def _assert_not_legacy_schema() -> None:
    """Fail loudly instead of running v2 code against a v1 file (create_all never alters tables)."""
    insp = inspect(engine)
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "key_id" not in cols:
            raise RuntimeError(
                f"[DB] Legacy v1 database detected ({DATABASE_URL}). "
                "Back up and remove gachabin.db (plus -wal/-shm) so the v2 schema can be created."
            )


def init_db() -> None:
    """Create tables and seed superadmin, hardware defaults, and starter rewards when missing."""
    _assert_not_legacy_schema()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.query(User).filter(User.phone == SUPERADMIN_PHONE).first():
            db.add(User(
                username=SUPERADMIN_USERNAME,
                phone=SUPERADMIN_PHONE,
                role="superadmin",
                pin_code=hash_pin(SUPERADMIN_DEFAULT_PIN),
            ))
            logger.info("[DB] Seeded superadmin account %s", SUPERADMIN_USERNAME)
        existing = {s.setting_key for s in db.query(GpioSetting).all()}
        for row in DEFAULT_GPIO_SETTINGS:
            if row["setting_key"] not in existing:
                db.add(GpioSetting(**row))
        if db.query(GachaReward).count() == 0:
            db.add_all([
                GachaReward(name=n, tier=t, category=c, stock=s, drop_rate=1.0)
                for n, t, c, s in DEFAULT_REWARDS
            ])
        db.commit()


def get_db() -> Generator[Session, None, None]:
    """Dependency helper for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
