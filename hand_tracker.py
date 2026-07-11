"""
hand_tracker.py
================
Wraps MediaPipe Hands to give the rest of the app a clean, smoothed,
velocity-aware stream of hand landmark data in pixel coordinates.

Why smoothing matters: raw MediaPipe landmarks jitter frame to frame, which
makes lightning arcs and gesture thresholds flicker. We apply a simple
Exponential Moving Average (EMA) per landmark, keyed by handedness, so that
motion stays responsive but visually stable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import mediapipe as mp
import numpy as np

from config import HandTrackingConfig

# MediaPipe landmark indices we care about by name, for readability elsewhere.
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_MCP = 13
RING_TIP = 16
PINKY_MCP = 17
PINKY_TIP = 20

FINGER_TIPS = [THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP]
FINGER_MCPS = [INDEX_MCP, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]


@dataclass
class HandData:
    """A single tracked hand, fully resolved to pixel space."""
    handedness: str  # "Left" or "Right" (as reported by MediaPipe, mirror-corrected)
    landmarks_px: List[np.ndarray] = field(default_factory=list)   # 21 x (x, y) pixel coords
    landmarks_norm: List[np.ndarray] = field(default_factory=list)  # 21 x (x, y, z) normalized
    palm_center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))  # px/sec
    speed: float = 0.0
    timestamp: float = 0.0

    def tip(self, idx: int) -> np.ndarray:
        return self.landmarks_px[idx]


class HandTracker:
    """High-level wrapper around mediapipe.solutions.hands."""

    def __init__(self, cfg: HandTrackingConfig, frame_width: int, frame_height: int):
        self.cfg = cfg
        self.frame_w = frame_width
        self.frame_h = frame_height

        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.max_num_hands,
            model_complexity=cfg.model_complexity,
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )

        # Smoothed landmark state, keyed by handedness label so a hand keeps
        # its identity (and therefore smoothing continuity) across frames.
        self._smoothed: Dict[str, List[np.ndarray]] = {}
        self._prev_center: Dict[str, np.ndarray] = {}
        self._prev_time: Dict[str, float] = {}

        self._frame_counter = 0
        self._last_result_cache: List[HandData] = []

    def close(self) -> None:
        self._hands.close()

    def process(self, bgr_frame: np.ndarray) -> List[HandData]:
        """
        Run detection on a BGR frame (as returned by cv2.VideoCapture) and
        return smoothed HandData for each detected hand.
        """
        self._frame_counter += 1
        if self.cfg.process_every_n_frames > 1 and (
            self._frame_counter % self.cfg.process_every_n_frames != 0
        ):
            # Skip MediaPipe this frame to save CPU; reuse last result so
            # gestures/effects don't freeze, just update slightly less often.
            return self._last_result_cache

        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self._hands.process(rgb)
        rgb.flags.writeable = True

        hands_out: List[HandData] = []
        now = time.time()

        if result.multi_hand_landmarks and result.multi_handedness:
            for hand_landmarks, handedness in zip(
                result.multi_hand_landmarks, result.multi_handedness
            ):
                label = handedness.classification[0].label  # "Left"/"Right"
                raw_norm = [
                    np.array([lm.x, lm.y, lm.z], dtype=np.float32)
                    for lm in hand_landmarks.landmark
                ]
                raw_px = [
                    np.array([lm.x * self.frame_w, lm.y * self.frame_h], dtype=np.float32)
                    for lm in hand_landmarks.landmark
                ]

                smoothed_px = self._smooth(label, raw_px)

                palm_center = (
                    smoothed_px[WRIST]
                    + smoothed_px[INDEX_MCP]
                    + smoothed_px[MIDDLE_MCP]
                    + smoothed_px[RING_MCP]
                    + smoothed_px[PINKY_MCP]
                ) / 5.0

                velocity = np.zeros(2, dtype=np.float32)
                speed = 0.0
                if label in self._prev_center and label in self._prev_time:
                    dt = max(now - self._prev_time[label], 1e-3)
                    velocity = (palm_center - self._prev_center[label]) / dt
                    speed = float(np.linalg.norm(velocity))
                self._prev_center[label] = palm_center
                self._prev_time[label] = now

                hands_out.append(
                    HandData(
                        handedness=label,
                        landmarks_px=smoothed_px,
                        landmarks_norm=raw_norm,
                        palm_center=palm_center,
                        velocity=velocity,
                        speed=speed,
                        timestamp=now,
                    )
                )

        self._last_result_cache = hands_out
        return hands_out

    def _smooth(self, label: str, raw_px: List[np.ndarray]) -> List[np.ndarray]:
        """Exponential moving average smoothing, per landmark, per hand."""
        alpha = self.cfg.smoothing_alpha
        if label not in self._smoothed:
            self._smoothed[label] = [p.copy() for p in raw_px]
        else:
            prev = self._smoothed[label]
            for i in range(len(raw_px)):
                prev[i] = alpha * raw_px[i] + (1.0 - alpha) * prev[i]
        return [p.copy() for p in self._smoothed[label]]
