#!/bin/bash
# ==============================================================================
# GACHA-BIN Kiosk Launcher Script for Raspberry Pi OS
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[GACHA-BIN] Starting from: $DIR"

# 1. Activate Python virtual environment if present
if [ -d "$DIR/backend/venv" ]; then
    source "$DIR/backend/venv/bin/activate"
elif [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
elif [ -d "$DIR/../1_AI_Training/.venv" ]; then
    source "$DIR/../1_AI_Training/.venv/bin/activate"
fi

# 2. Clear lingering zombie process on port 8000 and start FastAPI Backend
echo "[GACHA-BIN] Checking and clearing port 8000..."
if command -v fuser > /dev/null 2>&1; then
    fuser -k 8000/tcp 2>/dev/null || true
fi
sleep 0.5

echo "[GACHA-BIN] Starting FastAPI Backend on port 8000..."
python3 -m uvicorn app.main:app --app-dir "$DIR/backend" --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Trap signals to ensure backend process is terminated on script exit
cleanup() {
    echo "[GACHA-BIN] Shutting down Backend (PID $BACKEND_PID)..."
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    echo "[GACHA-BIN] Goodbye!"
}
trap cleanup EXIT INT TERM

# 3. Wait for Backend Health Check
echo "[GACHA-BIN] Waiting for Backend to be ready..."
BACKEND_OK=0
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health > /dev/null; then
        echo "[GACHA-BIN] Backend is online!"
        BACKEND_OK=1
        break
    fi
    sleep 0.5
done
if [ "$BACKEND_OK" -eq 0 ]; then
    echo "[WARNING] Backend health check timed out. Browser will attempt to connect anyway."
fi

# 4. Launch Chromium Kiosk (Native, lightweight, no Electron)
echo "[GACHA-BIN] Launching Chromium Kiosk..."
if command -v chromium-browser > /dev/null 2>&1; then
    chromium-browser --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://127.0.0.1:8000
elif command -v chromium > /dev/null 2>&1; then
    chromium --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://127.0.0.1:8000
elif command -v google-chrome > /dev/null 2>&1; then
    google-chrome --kiosk --noerrdialogs --disable-infobars http://127.0.0.1:8000
else
    echo "[INFO] No Chromium/Chrome found. Access Kiosk UI via browser at http://localhost:8000"
    wait "$BACKEND_PID"
fi

