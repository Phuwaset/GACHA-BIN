"""YOLO Classification & Debounce Detection Engine."""
import logging
import os
import time
from typing import Optional, Dict, Any

logger = logging.getLogger("gachabin.vision.detector")



class BottleDetector:
    """Wraps YOLO classification model with presence gating, debounce, and item exit verification."""

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.88,
        consecutive_frames_required: int = 8,
        hold_duration_sec: float = 1.2,
        cooldown_seconds: float = 2.0,
        diff_threshold: float = 8.0,
        min_change_percent: float = 3.0,
    ) -> None:
        self.model_path = model_path
        self.conf_threshold = confidence_threshold
        self.frames_required = consecutive_frames_required
        self.hold_duration_sec = hold_duration_sec
        self.cooldown_sec = cooldown_seconds
        self.diff_threshold = diff_threshold
        self.min_change_percent = min_change_percent

        self.model = None
        self.names = {0: "metal", 1: "plastic"}

        # State tracking for debounce & verification
        self._current_candidate: Optional[str] = None
        self._candidate_start_time: float = 0.0
        self._consecutive_count: int = 0
        self._drop_count: int = 0
        self._last_counted_time: float = 0.0
        self._last_counted_class: Optional[str] = None

        # Presence & Background Differencing
        self._bg = None
        self._bg_warmup_frames: int = 0
        self._waiting_for_exit: bool = False

        self._load_model()

    def reset_session(self) -> None:
        """Reset detection states and background baseline when a new session starts."""
        self._bg = None
        self._bg_warmup_frames = 0
        self._waiting_for_exit = False
        self._last_counted_class = None
        self._reset_candidate()
        self._last_counted_time = 0.0
        logger.info("[Detector] Session state and background baseline reset")

    def _load_model(self) -> None:
        if not os.path.exists(self.model_path):
            logger.warning("[Detector] Model file not found at %s. Running in mock mode.", self.model_path)
            return

        try:
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            self.names = getattr(self.model, "names", None) or {0: "metal", 1: "plastic"}
            logger.info("[Detector] Loaded YOLO model from %s with classes: %s", self.model_path, self.names)
        except ImportError:
            logger.warning("[Detector] Ultralytics is not installed. Running in mock mode.")
            self.model = None
        except Exception as e:
            logger.error("[Detector] Failed to load YOLO model: %s", e)
            self.model = None

    def process_frame(self, frame) -> Dict[str, Any]:
        """
        Processes camera frame with:
        1. Presence detection (filters out empty chamber / background false positives)
        2. Exit gate (prevents duplicate counting until item is removed/dropped)
        3. YOLO classification + debounce confirmation
        """
        import cv2
        import numpy as np

        now = time.time()
        in_cooldown = (now - self._last_counted_time) < self.cooldown_sec

        if frame is None:
            return {"class": "empty", "conf": 0.0, "event": None, "in_cooldown": in_cooldown, "is_present": False}

        # 1. Grayscale & Blur for presence differencing
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (21, 21), 0)

        # Baseline background initialization
        if self._bg is None:
            self._bg = blurred.astype("float")
            self._bg_warmup_frames = 1
            return {
                "class": "empty",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": False,
                "diff_score": 0.0,
            }

        # Fast background calibration on first 5 frames
        if self._bg_warmup_frames < 5:
            cv2.accumulateWeighted(blurred, self._bg, 0.4)
            self._bg_warmup_frames += 1
            return {
                "class": "empty",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": False,
                "diff_score": 0.0,
            }

        # 2. Compute difference against baseline background
        frame_delta = cv2.absdiff(blurred, cv2.convertScaleAbs(self._bg))
        diff_score = float(np.mean(frame_delta))
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        percent_changed = float((np.count_nonzero(thresh) / thresh.size) * 100)

        is_present = (diff_score >= self.diff_threshold) or (percent_changed >= self.min_change_percent)

        # 3. Handle Empty Scene
        if not is_present:
            # Slowly adapt background to ambient lighting changes when chamber is empty
            cv2.accumulateWeighted(blurred, self._bg, 0.05)

            # If we were waiting for previous item to leave, it has now exited!
            if self._waiting_for_exit:
                logger.info("[Detector] Chamber cleared (item removed/dropped). Ready for next item.")
                self._waiting_for_exit = False

            self._reset_candidate()
            return {
                "class": "empty",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": False,
                "diff_score": round(diff_score, 2),
                "percent_changed": round(percent_changed, 2),
                "waiting_for_exit": False,
                "progress": 0.0,
            }

        # 4. Handle Item Present but Gate Locked (Waiting for exit)
        if self._waiting_for_exit:
            return {
                "class": self._last_counted_class or "waiting_exit",
                "conf": 1.0,
                "event": None,
                "in_cooldown": True,
                "is_present": True,
                "diff_score": round(diff_score, 2),
                "percent_changed": round(percent_changed, 2),
                "waiting_for_exit": True,
                "progress": 0.0,
            }

        if self.model is None:
            return {
                "class": "item_detected",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": True,
                "progress": 0.0,
            }

        # 5. Run YOLO Classification Inference on Present Item
        try:
            results = self.model(frame, imgsz=224, verbose=False)
            r = results[0]
            if r.probs is None:
                self._reset_candidate()
                return {
                    "class": "scanning",
                    "conf": 0.0,
                    "event": None,
                    "in_cooldown": in_cooldown,
                    "is_present": True,
                    "progress": 0.0,
                }

            idx = int(r.probs.top1)
            conf = float(r.probs.top1conf)
            label = self.names.get(idx, str(idx)).lower()

            # Debounce & consecutive hold time check
            detected_event = None
            progress = 0.0
            if not in_cooldown and conf >= self.conf_threshold and label in ("plastic", "metal"):
                self._drop_count = 0
                if self._current_candidate == label:
                    self._consecutive_count += 1
                else:
                    self._current_candidate = label
                    self._candidate_start_time = now
                    self._consecutive_count = 1

                elapsed = now - self._candidate_start_time
                progress = min(1.0, round(elapsed / self.hold_duration_sec, 2))

                # Item confirmed when held continuously for at least hold_duration_sec AND min frames
                if elapsed >= self.hold_duration_sec and self._consecutive_count >= self.frames_required:
                    points = 1 if label == "plastic" else 2
                    detected_event = {
                        "item_type": label,
                        "confidence": round(conf, 4),
                        "points": points,
                        "timestamp": now,
                    }
                    self._last_counted_time = now
                    self._last_counted_class = label
                    self._waiting_for_exit = True  # Lock exit gate until removed/dropped!
                    self._reset_candidate()
                    in_cooldown = True
                    progress = 1.0
                    logger.info(
                        "[Detector] Confirmed item: %s (+%d pts, conf=%.2f, held=%.2fs). Waiting for exit.",
                        label, points, conf, elapsed
                    )
            else:
                # Brief glitch tolerance (up to 2 frames) before discarding candidate
                if not in_cooldown and self._current_candidate is not None:
                    self._drop_count += 1
                    if self._drop_count > 2:
                        self._reset_candidate()
                        progress = 0.0
                    else:
                        elapsed = now - self._candidate_start_time
                        progress = min(1.0, round(elapsed / self.hold_duration_sec, 2))
                else:
                    if not in_cooldown:
                        self._reset_candidate()
                    progress = 0.0

            return {
                "class": label,
                "conf": round(conf, 4),
                "event": detected_event,
                "in_cooldown": in_cooldown,
                "is_present": True,
                "diff_score": round(diff_score, 2),
                "percent_changed": round(percent_changed, 2),
                "waiting_for_exit": self._waiting_for_exit,
                "progress": progress,
                "candidate": self._current_candidate,
            }
        except Exception as e:
            logger.error("[Detector] Inference error: %s", e)
            return {
                "class": None,
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": True,
                "progress": 0.0,
            }

    def _reset_candidate(self) -> None:
        self._current_candidate = None
        self._candidate_start_time = 0.0
        self._consecutive_count = 0
        self._drop_count = 0

