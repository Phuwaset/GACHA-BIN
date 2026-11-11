"""FastAPI Application Entry Point for GACHA-BIN Kiosk & Mobile Web Remote."""
import os
import io
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.api.auth import router as auth_router
from app.api.gacha import router as gacha_router
from app.api.admin import router as admin_router
from app.websocket.stream import router as ws_router
from app.services.db import init_db
from app.services.session_manager import get_local_ip

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(LOG_DIR, "gachabin.log")

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(), file_handler],
)
logger = logging.getLogger("gachabin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle events."""
    logger.info("Initializing GACHA-BIN Database (Concept v2.0)...")
    init_db()
    ip = get_local_ip()
    logger.info("GACHA-BIN Server ready.")
    logger.info("Kiosk Display Screen: http://%s:8000/", ip)
    logger.info("Mobile Web Remote:    http://%s:8000/m", ip)
    logger.info("Super Admin Portal:   http://%s:8000/admin", ip)
    yield
    logger.info("GACHA-BIN Server shutting down.")


app = FastAPI(
    title="GACHA-BIN Smart Vision Kiosk Backend",
    version="2.0.0",
    description="Unified backend server for Non-Touch Kiosk Display, Mobile Remote, and Dual-Servo sorting.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth_router)
app.include_router(gacha_router)
app.include_router(admin_router)
app.include_router(ws_router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATIC_INDEX = os.path.join(STATIC_DIR, "index.html")


@app.get("/api/qr")
def generate_qr_code():
    """Dynamically generate QR Code PNG pointing to mobile web remote."""
    import cv2
    ip = get_local_ip()
    target_url = f"http://{ip}:8000/m"
    try:
        encoder = cv2.QRCodeEncoder.create()
        qr_matrix = encoder.encode(target_url)
        # Resize to crisp 256x256 with 16px quiet zone
        scaled = cv2.resize(qr_matrix, (256, 256), interpolation=cv2.INTER_NEAREST)
        padded = cv2.copyMakeBorder(scaled, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=255)
        ok, buf = cv2.imencode(".png", padded)
        if ok:
            return Response(content=buf.tobytes(), media_type="image/png")
    except Exception as e:
        logger.error("[QR] Failed to generate QR code: %s", e)
    return Response(status_code=500)


@app.get("/")
def get_kiosk_display():
    """Serve standalone non-touch Kiosk Display UI (Standby & Active Dashboard)."""
    if os.path.exists(STATIC_INDEX):
        return FileResponse(STATIC_INDEX)
    return {"status": "ok", "message": "GACHA-BIN Backend running."}


@app.get("/m")
def get_mobile_ui():
    """Serve Mobile Web Remote UI for smartphone QR scan."""
    mobile_file = os.path.join(STATIC_DIR, "mobile.html")
    if os.path.exists(mobile_file):
        return FileResponse(mobile_file)
    return FileResponse(STATIC_INDEX)


@app.get("/admin")
def get_admin_ui():
    """Serve Super Admin Management Portal."""
    admin_file = os.path.join(STATIC_DIR, "admin.html")
    if os.path.exists(admin_file):
        return FileResponse(admin_file)
    return FileResponse(STATIC_INDEX)


@app.get("/health")
def health_check():
    return {"status": "ok", "app": "gachabin-v2", "ip": get_local_ip()}


if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
