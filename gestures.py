"""
gestures.py
===========
Turns raw HandData (from hand_tracker.py) into meaningful, high-level
gesture events: open palm, fist, pinch/charge/release, hand raised,
two-hands-open, swipe forward, pull back, hands apart/together.

The recognizer is deliberately heuristic (distance/angle thresholds) rather
than ML-based, which keeps it fast enough for integrated graphics and easy
to tune via config.py.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from config import GestureConfig
from hand_tracker import (
    HandData,
    WRIST,
    THUMB_TIP,
    INDEX_TIP,
    MIDDLE_TIP,
    RING_TIP,
    PINKY_TIP,
    FINGER_TIPS,
    FINGER_MCPS,
    INDEX_MCP,
    MIDDLE_MCP,
    RING_MCP,
    PINKY_MCP,
)


class GestureType(Enum):
    NONE = auto()
    OPEN_PALM = auto()
    FIST = auto()
    PINCH_CHARGING = auto()
    PINCH_RELEASED = auto()
    HAND_RAISED = auto()
    TWO_HANDS_OPEN = auto()
    SWIPE_FORWARD = auto()
    PULL_BACK = auto()
    HANDS_APART = auto()
    HANDS_TOGETHER = auto()


@dataclass
class HandGestureState:
    handedness: str
    is_open_palm: bool = False
    is_fist: bool = False
    is_pinching: bool = False
    pinch_just_released: bool = False
    is_raised: bool = False
    is_two_finger_pose: bool = False
    charge: float = 0.0
    pointing_direction: np.ndarray = field(default_factory=lambda: np.array([0.0, -1.0]))
    draw_point: Optional[np.ndarray] = None
    draw_span: float = 0.0
    swipe_forward: bool = False
    pull_back: bool = False
    speed: float = 0.0


@dataclass
class GestureState:
    hands: Dict[str, HandGestureState] = field(default_factory=dict)
    two_hands_open: bool = False
    hands_apart: bool = False
    hands_together: bool = False
    active_gestures: List[GestureType] = field(default_factory=list)


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


class GestureRecognizer:
    def __init__(self, cfg: GestureConfig, frame_w: int, frame_h: int):
        self.cfg = cfg
        self.frame_w = frame_w
        self.frame_h = frame_h

        self._pinch_state: Dict[str, bool] = {}
        self._charge: Dict[str, float] = {}
        self._velocity_history: Dict[str, Deque[np.ndarray]] = {}
        self._two_hand_dist_history: Deque[float] = deque(maxlen=cfg.history_length)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update(self, hands: List[HandData], dt: float) -> GestureState:
        state = GestureState()

        for hand in hands:
            hgs = self._analyze_single_hand(hand, dt)
            state.hands[hand.handedness] = hgs
            state.active_gestures.extend(self._gesture_types_for(hgs))

        if len(hands) == 2:
            self._analyze_two_hands(hands, state)

        return state

    # ------------------------------------------------------------------
    # Single-hand analysis
    # ------------------------------------------------------------------
    def _analyze_single_hand(self, hand: HandData, dt: float) -> HandGestureState:
        label = hand.handedness
        lm = hand.landmarks_norm  # normalized 0..1, better for scale-independent thresholds
        lm_px = hand.landmarks_px

        extended = self._fingers_extended(lm)
        num_extended = sum(extended)

        is_open_palm = num_extended >= 4
        is_fist = num_extended <= 1

        # Two-finger draw pose: index + middle extended, ring + pinky tucked.
        index_extended = extended[1]
        middle_extended = extended[2]
        ring_extended = extended[3]
        pinky_extended = extended[4]
        draw_span = _dist(lm[INDEX_TIP][:2], lm[MIDDLE_TIP][:2])
        is_two_finger_pose = (
            index_extended and middle_extended
            and not ring_extended and not pinky_extended
            and draw_span > 0.020
        )
        draw_point = (lm_px[INDEX_TIP] + lm_px[MIDDLE_TIP]) / 2.0 if is_two_finger_pose else None

        # Pinch: distance between thumb tip and index tip (normalized space)
        pinch_dist = _dist(lm[THUMB_TIP][:2], lm[INDEX_TIP][:2])
        was_pinching = self._pinch_state.get(label, False)

        if was_pinching:
            is_pinching = pinch_dist < (
                self.cfg.pinch_distance_threshold + self.cfg.pinch_release_hysteresis
            )
        else:
            is_pinching = pinch_dist < self.cfg.pinch_distance_threshold

        pinch_just_released = was_pinching and not is_pinching
        self._pinch_state[label] = is_pinching

        # Charge accumulates while pinching, decays otherwise.
        charge = self._charge.get(label, 0.0)
        if is_pinching:
            charge = min(100.0, charge + self.cfg.pinch_release_hysteresis * 0 + dt * 90.0)
        elif pinch_just_released:
            pass  # leave charge as-is for one frame so caller can read it, then decay
        else:
            charge = max(0.0, charge - dt * 40.0)
        self._charge[label] = charge if not pinch_just_released else charge

        # Hand raised: wrist normalized y above threshold (small y = near top)
        is_raised = lm[WRIST][1] < self.cfg.hand_raised_y_threshold

        # Pointing direction: from wrist to middle-finger MCP -> tip, in pixel space
        direction = lm_px[MIDDLE_TIP] - lm_px[WRIST]
        norm = np.linalg.norm(direction)
        pointing_direction = direction / norm if norm > 1e-3 else np.array([0.0, -1.0])

        # Swipe / pull-back detection via velocity history
        hist = self._velocity_history.setdefault(label, deque(maxlen=self.cfg.history_length))
        hist.append(hand.velocity.copy())
        avg_vel = np.mean(hist, axis=0) if hist else np.zeros(2)

        # "Forward" swipe = fast upward/outward motion; "pull back" = fast
        # motion back toward the body (downward in screen space here, since
        # we don't have real depth without a stereo camera).
        speed = hand.speed
        swipe_forward = speed > self.cfg.swipe_velocity_threshold and avg_vel[1] < 0
        pull_back = speed > self.cfg.pull_back_velocity_threshold and avg_vel[1] > 0 and is_fist is False

        return HandGestureState(
            handedness=label,
            is_open_palm=is_open_palm,
            is_fist=is_fist,
            is_pinching=is_pinching,
            pinch_just_released=pinch_just_released,
            is_raised=is_raised,
            is_two_finger_pose=is_two_finger_pose and not is_pinching,
            charge=self._charge[label],
            pointing_direction=pointing_direction,
            draw_point=draw_point,
            draw_span=draw_span,
            swipe_forward=swipe_forward,
            pull_back=pull_back,
            speed=speed,
        )

    def consume_charge(self, handedness: str) -> float:
        """Called when a blast fires; resets charge to 0 and returns the amount used."""
        used = self._charge.get(handedness, 0.0)
        self._charge[handedness] = 0.0
        return used

    def _fingers_extended(self, lm: List[np.ndarray]) -> List[bool]:
        """
        Heuristic: a finger is 'extended' if its tip is farther from the wrist
        than its MCP joint by a healthy margin. Thumb uses a sideways check
        since it doesn't fold the same way as the other four fingers.
        """
        wrist = lm[WRIST][:2]
        results = []
        for tip_idx, mcp_idx in zip(FINGER_TIPS, FINGER_MCPS):
            tip = lm[tip_idx][:2]
            mcp = lm[mcp_idx][:2]
            tip_dist = np.linalg.norm(tip - wrist)
            mcp_dist = np.linalg.norm(mcp - wrist)
            results.append(tip_dist > mcp_dist * 1.15)
        return results

    # ------------------------------------------------------------------
    # Two-hand analysis
    # ------------------------------------------------------------------
    def _analyze_two_hands(self, hands: List[HandData], state: GestureState) -> None:
        h1, h2 = hands[0], hands[1]
        dist = _dist(h1.palm_center, h2.palm_center)
        self._two_hand_dist_history.append(dist)

        both_open = all(
            state.hands[h.handedness].is_open_palm for h in hands if h.handedness in state.hands
        )
        state.two_hands_open = both_open

        if len(self._two_hand_dist_history) >= 3:
            delta = self._two_hand_dist_history[-1] - self._two_hand_dist_history[0]
            if delta > self.cfg.two_hand_distance_delta:
                state.hands_apart = True
                state.active_gestures.append(GestureType.HANDS_APART)
            elif delta < -self.cfg.two_hand_distance_delta:
                state.hands_together = True
                state.active_gestures.append(GestureType.HANDS_TOGETHER)

        if both_open:
            state.active_gestures.append(GestureType.TWO_HANDS_OPEN)

    def _gesture_types_for(self, hgs: HandGestureState) -> List[GestureType]:
        types = []
        if hgs.is_open_palm:
            types.append(GestureType.OPEN_PALM)
        if hgs.is_fist:
            types.append(GestureType.FIST)
        if hgs.is_pinching:
            types.append(GestureType.PINCH_CHARGING)
        if hgs.pinch_just_released:
            types.append(GestureType.PINCH_RELEASED)
        if hgs.is_raised:
            types.append(GestureType.HAND_RAISED)
        if hgs.swipe_forward:
            types.append(GestureType.SWIPE_FORWARD)
        if hgs.pull_back:
            types.append(GestureType.PULL_BACK)
        return types
