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

    def notify_sorting_completed(self) -> None:
        """Called when hardware servo sorting completes (item swept into bin)."""
        logger.info("[Detector] Sorting completed. Unlocking gate and preparing for next item.")
        self._waiting_for_exit = False
        self._last_counted_class = None
        self._reset_candidate()
        self._last_counted_time = time.time()
        self._bg = None
        self._bg_warmup_frames = 0

    def _load_model(self) -> None:
        if not os.path.exists(self.model_path):
            logger.warning("[Detector] Model file not found at %s. Running in mock mode.", self.model_path)
            return

        try:
            from ultralytics import YOLO
            import numpy as np
            self.model = YOLO(self.model_path)
            self.names = getattr(self.model, "names", None) or {0: "metal", 1: "plastic"}
            # Warm-up inference so first active scan has 0ms latency
            dummy = np.zeros((224, 224, 3), dtype=np.uint8)
            self.model(dummy, imgsz=224, verbose=False)
            logger.info("[Detector] Loaded and warmed up YOLO model from %s with classes: %s", self.model_path, self.names)
        except ImportError:
            logger.warning("[Detector] Ultralytics is not installed. Running in mock mode.")
            self.model = None
        except Exception as e:
            logger.error("[Detector] Failed to load YOLO model: %s", e)
            self.model = None

    def process_frame(self, frame) -> Dict[str, Any]:
        """
        Processes camera frame with:
        1. Center ROI extraction (focuses on bottle, eliminates background clutter)
        2. Presence detection & Optical gating
        3. Exit gate (prevents duplicate counting until item is removed/dropped)
        4. YOLO classification + temporal dwell debounce
        5. Live on-frame HUD overlay (corners, label, confidence, progress bar)
        """
        import cv2
        import numpy as np

        now = time.time()
        cooldown_elapsed = now - self._last_counted_time
        in_cooldown = cooldown_elapsed < self.cooldown_sec

        if frame is None:
            return {"class": "empty", "conf": 0.0, "event": None, "in_cooldown": in_cooldown, "is_present": False}

        h, w = frame.shape[:2]
        # Define Center Target ROI (65% width, 75% height)
        rw = int(w * 0.65)
        rh = int(h * 0.75)
        rx1 = max(0, (w - rw) // 2)
        ry1 = max(0, (h - rh) // 2)
        rx2 = min(w, rx1 + rw)
        ry2 = min(h, ry1 + rh)
        roi = frame[ry1:ry2, rx1:rx2]

        # 1. Grayscale & Blur for presence differencing on ROI
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blurred_roi = cv2.GaussianBlur(gray_roi, (21, 21), 0)

        # Baseline background initialization
        if self._bg is None:
            self._bg = blurred_roi.astype("float")
            self._bg_warmup_frames = 1
            self._draw_overlay(frame, rx1, ry1, rx2, ry2, "Calibrating Camera...", (180, 180, 180), 0.0)
            return {
                "class": "calibrating",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": False,
                "diff_score": 0.0,
            }

        if self._bg_warmup_frames < 5:
            cv2.accumulateWeighted(blurred_roi, self._bg, 0.4)
            self._bg_warmup_frames += 1
            self._draw_overlay(frame, rx1, ry1, rx2, ry2, "Calibrating Camera...", (180, 180, 180), 0.0)
            return {
                "class": "calibrating",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": False,
                "diff_score": 0.0,
            }

        # 2. Compute difference against baseline background
        frame_delta = cv2.absdiff(blurred_roi, cv2.convertScaleAbs(self._bg))
        diff_score = float(np.mean(frame_delta))
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        percent_changed = float((np.count_nonzero(thresh) / thresh.size) * 100)

        # 3. Handle Item Present but Gate Locked (Waiting for exit / Cooldown)
        if self._waiting_for_exit:
            is_cleared = (diff_score < (self.diff_threshold * 0.7)) and (percent_changed < (self.min_change_percent * 0.7))
            if is_cleared or (cooldown_elapsed >= self.cooldown_sec):
                logger.info("[Detector] Exit gate cleared / cooldown expired. Ready for next item.")
                self._waiting_for_exit = False
                self._reset_candidate()
                self._bg = None
                self._bg_warmup_frames = 0
            else:
                remaining_cd = max(0.0, self.cooldown_sec - cooldown_elapsed)
                self._draw_overlay(
                    frame, rx1, ry1, rx2, ry2,
                    f"SORTED: {str(self._last_counted_class).upper()} (NEXT IN {remaining_cd:.1f}s)",
                    (0, 215, 255), 1.0 - (remaining_cd / self.cooldown_sec)
                )
                return {
                    "class": "cooldown",
                    "conf": 1.0,
                    "event": None,
                    "in_cooldown": True,
                    "is_present": True,
                    "diff_score": round(diff_score, 2),
                    "percent_changed": round(percent_changed, 2),
                    "waiting_for_exit": True,
                    "progress": 0.0,
                }

        # Handle active cooldown right after sorting
        if in_cooldown:
            remaining_cd = max(0.0, self.cooldown_sec - cooldown_elapsed)
            self._draw_overlay(
                frame, rx1, ry1, rx2, ry2,
                f"READY IN {remaining_cd:.1f}s",
                (0, 215, 255), 1.0 - (remaining_cd / self.cooldown_sec)
            )
            return {
                "class": "cooldown",
                "conf": 0.0,
                "event": None,
                "in_cooldown": True,
                "is_present": True,
                "progress": 0.0,
            }

        if self.model is None:
            self._draw_overlay(frame, rx1, ry1, rx2, ry2, "AI MODEL OFFLINE (MOCK)", (200, 200, 200), 0.0)
            return {
                "class": "item_detected",
                "conf": 0.0,
                "event": None,
                "in_cooldown": in_cooldown,
                "is_present": True,
                "progress": 0.0,
            }

        # 4. Run YOLO Classification Inference on Center ROI
        try:
            results = self.model(roi, imgsz=224, verbose=False)
            r = results[0]
            if r.probs is None:
                self._reset_candidate()
                self._draw_overlay(frame, rx1, ry1, rx2, ry2, "Place bottle inside frame", (120, 120, 120), 0.0)
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

            # Dynamic presence check: motion diff OR confident classification in ROI
            motion_present = (diff_score >= self.diff_threshold) or (percent_changed >= self.min_change_percent)
            vision_confident = conf >= self.conf_threshold and label in ("plastic", "metal")
            is_present = motion_present or vision_confident

            if not is_present:
                # Slowly adapt background to ambient lighting changes when chamber is empty
                cv2.accumulateWeighted(blurred_roi, self._bg, 0.05)
                self._reset_candidate()
                self._draw_overlay(frame, rx1, ry1, rx2, ry2, "Align bottle in center", (150, 150, 150), 0.0)
                return {
                    "class": "empty",
                    "conf": round(conf, 4),
                    "event": None,
                    "in_cooldown": in_cooldown,
                    "is_present": False,
                    "diff_score": round(diff_score, 2),
                    "percent_changed": round(percent_changed, 2),
                    "waiting_for_exit": False,
                    "progress": 0.0,
                }

            # 5. Debounce & consecutive hold time check
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
                    self._waiting_for_exit = True
                    self._reset_candidate()
                    in_cooldown = True
                    progress = 1.0
                    logger.info(
                        "[Detector] Confirmed item: %s (+%d pts, conf=%.2f, held=%.2fs). Waiting for exit.",
                        label, points, conf, elapsed
                    )
            else:
                # Brief glitch tolerance (up to 3 frames) before discarding candidate
                if not in_cooldown and self._current_candidate is not None:
                    self._drop_count += 1
                    if self._drop_count > 3:
                        self._reset_candidate()
                        progress = 0.0
                    else:
                        elapsed = now - self._candidate_start_time
                        progress = min(1.0, round(elapsed / self.hold_duration_sec, 2))
                else:
                    if not in_cooldown:
                        self._reset_candidate()
                    progress = 0.0

            # Draw HUD Overlay with real-time detection & progress
            hud_color = (0, 230, 118) if label == "plastic" else (0, 140, 255)
            if in_cooldown:
                hud_color = (0, 215, 255)
            hud_text = f"{label.upper()} {int(conf * 100)}%"
            if progress > 0 and not in_cooldown:
                hud_text += f" [HOLDING {int(progress * 100)}%]"

            self._draw_overlay(frame, rx1, ry1, rx2, ry2, hud_text, hud_color, progress)

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

    def _draw_overlay(self, frame, x1: int, y1: int, x2: int, y2: int, text: str, color: tuple, progress: float) -> None:
        """Draw tactical smart vision bounding reticle, status badge, and progress bar onto preview frame."""
        import cv2

        # 1. Corner brackets
        line_len = 24
        thickness = 2
        # Top-left
        cv2.line(frame, (x1, y1), (x1 + line_len, y1), color, thickness)
        cv2.line(frame, (x1, y1), (x1, y1 + line_len), color, thickness)
        # Top-right
        cv2.line(frame, (x2, y1), (x2 - line_len, y1), color, thickness)
        cv2.line(frame, (x2, y1), (x2, y1 + line_len), color, thickness)
        # Bottom-left
        cv2.line(frame, (x1, y2), (x1 + line_len, y2), color, thickness)
        cv2.line(frame, (x1, y2), (x1, y2 - line_len), color, thickness)
        # Bottom-right
        cv2.line(frame, (x2, y2), (x2 - line_len, y2), color, thickness)
        cv2.line(frame, (x2, y2), (x2, y2 - line_len), color, thickness)

        # 2. Status Label Pill above reticle
        cv2.rectangle(frame, (x1, max(0, y1 - 28)), (x1 + 220, y1), (15, 23, 42), -1)
        cv2.putText(
            frame, text, (x1 + 6, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA
        )

        # 3. Progress bar at bottom of reticle
        if progress > 0.0:
            bar_w = int((x2 - x1) * min(1.0, progress))
            cv2.rectangle(frame, (x1, y2 - 4), (x2, y2), (40, 40, 40), -1)
            cv2.rectangle(frame, (x1, y2 - 4), (x1 + bar_w, y2), color, -1)

    def _reset_candidate(self) -> None:
        self._current_candidate = None
        self._candidate_start_time = 0.0
        self._consecutive_count = 0
        self._drop_count = 0

