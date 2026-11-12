"""WebSocket stream handler for real-time camera preview, bottle detection, sorting, and scoring."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import (
    MODEL_PATH,
    CAMERA_INDEX,
    CONFIDENCE_THRESHOLD,
    CONSECUTIVE_FRAMES,
    HOLD_DURATION_SEC,
    DEBOUNCE_COOLDOWN_SEC,
    POINTS_PLASTIC,
    POINTS_METAL,
    ADMIN_PHONE,
    CARTOON_HOLD_SEC,
)
from app.hal import get_hardware_controller
from app.hal.mock import MockHardwareController
from app.services.db import SessionLocal, User, History
from app.services.session_manager import session_manager
from app.services.hardware import check_bin_status, execute_sorting
from app.vision.camera import CameraManager
from app.vision.detector import BottleDetector

logger = logging.getLogger("gachabin.websocket")
router = APIRouter()

camera_mgr = CameraManager(camera_index=CAMERA_INDEX)
hw = get_hardware_controller()
_detector = None


def get_detector() -> BottleDetector:
    """Lazy-load YOLO BottleDetector when recycling session begins."""
    global _detector
    if _detector is None:
        logger.info("[Detector] Lazy-loading YOLO model from %s...", MODEL_PATH)
        _detector = BottleDetector(
            model_path=MODEL_PATH,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            consecutive_frames_required=CONSECUTIVE_FRAMES,
            hold_duration_sec=HOLD_DURATION_SEC,
            cooldown_seconds=DEBOUNCE_COOLDOWN_SEC,
        )
    return _detector


@router.websocket("/ws/recycle/{key_id}")
async def recycle_session_endpoint(websocket: WebSocket, key_id: str):
    """
    WebSocket endpoint for active recycling session:
    - Streams live preview frames with detection overlay.
    - Runs 4-stage vision pipeline (presence -> 1.2s dwell -> YOLO -> exit gate).
    - Checks ultrasonic bin level sensor before sorting.
    - Executes 2-stage servo sorting (Diverter tilt -> Pusher sweep -> Reset).
    - Enforces 60-second inactivity timeout with real-time countdown.
    """
    await websocket.accept()
    logger.info("[WS] Client connected for key_id=%s", key_id)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.key_id == key_id).first()
        if not user:
            await websocket.send_text(json.dumps({"type": "ERROR", "message": "User not found"}))
            await websocket.close()
            return

        cam_connected = camera_mgr.start_session()
        hw.trigger_led("scanning")
        detector_task = asyncio.create_task(asyncio.to_thread(get_detector))

        session_plastic = 0
        session_metal = 0
        session_points = 0

        # Initial handshake
        await websocket.send_text(json.dumps({
            "type": "SESSION_STARTED",
            "key_id": user.key_id,
            "username": user.username,
            "current_score": user.score,
            "camera_connected": cam_connected,
        }))

        incoming_queue: asyncio.Queue = asyncio.Queue()

        async def client_reader():
            try:
                while True:
                    text = await websocket.receive_text()
                    await incoming_queue.put(text)
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            except Exception as ex:
                logger.debug("[WS] Reader error: %s", ex)

        reader_task = asyncio.create_task(client_reader())
        detector = None

        while True:
            # Check if reader task disconnected
            if reader_task.done() and incoming_queue.empty():
                logger.info("[WS] Client disconnected")
                break

            # Inactivity timeout check (60s default)
            status_info = session_manager.get_status()
            time_remaining = status_info["time_remaining_sec"]
            if not status_info["has_active_session"] or status_info["active_key_id"] != user.key_id:
                logger.info("[WS] Session timed out or overtaken for key_id=%s", user.key_id)
                try:
                    await websocket.send_text(json.dumps({"type": "TIMEOUT", "message": "หมดเวลาการใช้งาน"}))
                except Exception:
                    pass
                break

            # Handle incoming messages from queue
            event = None
            should_finish = False
            while not incoming_queue.empty():
                try:
                    msg = incoming_queue.get_nowait()
                    data = json.loads(msg)
                    session_manager.touch_activity()

                    action = data.get("action")
                    if action == "FINISH":
                        logger.info("[WS] User requested FINISH")
                        should_finish = True
                        break
                    elif action == "SIMULATE_DETECT":
                        if not isinstance(hw, MockHardwareController) and user.role != "superadmin":
                            continue
                        sim_type = data.get("item_type", "plastic").lower()
                        pts = POINTS_PLASTIC if sim_type == "plastic" else POINTS_METAL
                        event = {"item_type": sim_type, "confidence": 0.99, "points": pts}
                except Exception as ex:
                    logger.debug("[WS] Client message parse error: %s", ex)

            if should_finish:
                break

            # Prepare detector
            if detector is None and detector_task.done():
                try:
                    detector = detector_task.result()
                    detector.reset_session()
                    logger.info("[WS] YOLO Detector initialized and ready")
                except Exception as ex:
                    logger.error("[WS] Detector initialization failed: %s", ex)

            # Frame capture
            ok, frame = await asyncio.to_thread(camera_mgr.read_frame)
            result = {}

            if not event:
                if not ok or frame is None:
                    await asyncio.sleep(0.05)
                    continue

                if detector is not None:
                    result = await asyncio.to_thread(detector.process_frame, frame)
                    event = result.get("event")
                else:
                    result = {"class": "Initializing AI...", "conf": 0.0, "is_present": False}

            # Handle confirmed item detection
            if event:
                session_manager.touch_activity()
                item_type = event["item_type"]
                conf = float(event["confidence"])
                pts = POINTS_PLASTIC if item_type == "plastic" else POINTS_METAL

                # Check ultrasonic sensor for target bin
                bin_status = check_bin_status()
                target_bin = bin_status.get(item_type, {})

                if target_bin.get("is_full", False):
                    # Safety interlock: target bin is full!
                    hw.trigger_led("full")
                    await websocket.send_text(json.dumps({
                        "type": "BIN_FULL_WARNING",
                        "item_type": item_type,
                        "message": f"ถังขยะ {item_type.upper()} เต็มแล้ว! ไม่สามารถเปิดช่องรับได้",
                    }))
                else:
                    # Execute 2-stage sorting asynchronously in thread to avoid blocking loop
                    sort_ok, sort_msg = await asyncio.to_thread(execute_sorting, item_type)

                    if sort_ok:
                        # Record in history table
                        hist = History(
                            key_id=user.key_id,
                            item_type=item_type,
                            points_added=pts,
                            confidence=conf,
                        )
                        db.add(hist)
                        user.score += pts
                        user.total_score += pts
                        db.commit()

                        if item_type == "plastic":
                            session_plastic += 1
                        else:
                            session_metal += 1
                        session_points += pts

                        if detector is not None:
                            detector.notify_sorting_completed()

                        await websocket.send_text(json.dumps({
                            "type": "ITEM_DETECTED",
                            "item_type": item_type,
                            "points_awarded": pts,
                            "session_plastic": session_plastic,
                            "session_metal": session_metal,
                            "session_points": session_points,
                            "user_score": user.score,
                            "cartoon_hold_sec": CARTOON_HOLD_SEC,
                        }))

            # Stream preview frame
            if frame is not None:
                preview_b64 = await asyncio.to_thread(camera_mgr.get_preview_jpeg_base64, frame, 320, 240)
                if preview_b64:
                    await websocket.send_text(json.dumps({
                        "type": "PREVIEW_FRAME",
                        "image": preview_b64,
                        "candidate_class": result.get("class"),
                        "confidence": result.get("conf"),
                        "is_present": result.get("is_present", False),
                        "waiting_for_exit": result.get("waiting_for_exit", False),
                        "progress": result.get("progress", 0.0),
                        "time_remaining_sec": time_remaining,
                    }))

            await asyncio.sleep(0.06)

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error("[WS] Session error: %s", e)
    finally:
        if "reader_task" in locals() and not reader_task.done():
            reader_task.cancel()
        hw.trigger_led("idle")
        camera_mgr.stop_session()
        db.close()
        logger.info("[WS] Session cleaned up for key_id=%s", key_id)
