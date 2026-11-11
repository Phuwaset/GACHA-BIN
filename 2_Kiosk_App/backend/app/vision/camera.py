"""Camera Lifecycle Manager for On-Demand Video Capture."""
import base64
import logging
import sys
import threading
from typing import Optional, Tuple
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

logger = logging.getLogger("gachabin.vision.camera")


class CameraManager:
    """Manages camera lifecycle: opens during active recycling session, releases when session ends."""

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._active_sessions: int = 0

    def start_session(self) -> bool:
        """Increment session count and open camera if not already open."""
        with self._lock:
            self._active_sessions += 1
            if self._cap is None or not self._cap.isOpened():
                return self._open_camera()
            return True

    def stop_session(self) -> None:
        """Decrement session count and release camera when no sessions remain."""
        with self._lock:
            if self._active_sessions > 0:
                self._active_sessions -= 1
            if self._active_sessions == 0:
                self._release_camera()

    def _open_camera(self) -> bool:
        if not CV2_AVAILABLE or cv2 is None:
            logger.warning("[Camera] OpenCV is not available on this platform")
            return False

        indices_to_try = [self.camera_index]
        for candidate in (0, 1):
            if candidate not in indices_to_try:
                indices_to_try.append(candidate)

        for idx in indices_to_try:
            try:
                cap = None
                if sys.platform.startswith("linux") and hasattr(cv2, "CAP_V4L2"):
                    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                elif sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
                    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap = cv2.VideoCapture(idx)
                else:
                    cap = cv2.VideoCapture(idx)

                if cap and cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    # Warm-up reads to let sensor auto-exposure settle and verify device
                    ret = False
                    for _ in range(4):
                        ret, _ = cap.read()
                    if ret:
                        self._cap = cap
                        self.camera_index = idx
                        logger.info("[Camera] Camera index %d successfully opened and verified", idx)
                        return True
                    cap.release()
            except Exception as e:
                logger.debug("[Camera] Probing camera index %d failed: %s", idx, e)

        logger.error("[Camera] Failed to open any camera from indices: %s", indices_to_try)
        self._cap = None
        return False

    def _release_camera(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
                logger.info("[Camera] Camera index %d released (sleep mode)", self.camera_index)
            except Exception as e:
                logger.error("[Camera] Error releasing camera: %s", e)
            finally:
                self._cap = None

    def read_frame(self) -> Tuple[bool, Optional[any]]:
        """Read a single frame from the camera."""
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                return False, None
            ret, frame = self._cap.read()
            return ret, frame

    def get_preview_jpeg_base64(self, frame, width: int = 320, height: int = 240) -> Optional[str]:
        """Resize frame to lightweight thumbnail and encode to JPEG base64."""
        if frame is None or not CV2_AVAILABLE or cv2 is None:
            return None
        try:
            resized = cv2.resize(frame, (width, height))
            ret, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                return None
            return base64.b64encode(buf).decode("utf-8")
        except Exception as e:
            logger.debug("[Camera] Error encoding preview: %s", e)
            return None

