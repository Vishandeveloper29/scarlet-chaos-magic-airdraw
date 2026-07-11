"""
tutorial.py
===========
An in-app, interactive onboarding overlay. Instead of a wall of text, each
step tells you a gesture to perform and auto-advances the moment the
GestureRecognizer actually detects it -- so "learning the controls" and
"testing that your webcam/lighting works" happen at the same time.

Runs automatically on first launch (see TutorialConfig.enabled_on_launch)
and can be reopened anytime with the H key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import cv2
import numpy as np

from config import TutorialConfig
from gestures import GestureState


@dataclass
class TutorialStep:
    title: str
    instruction: str
    check: Callable[[GestureState], bool]


def _default_steps() -> List[TutorialStep]:
    return [
        TutorialStep(
            "Awaken Your Aura",
            "Hold up ONE OPEN PALM to the camera.",
            lambda gs: any(h.is_open_palm for h in gs.hands.values()),
        ),
        TutorialStep(
            "Charge a Blast",
            "PINCH your thumb and index finger together to charge energy.",
            lambda gs: any(h.is_pinching for h in gs.hands.values()),
        ),
        TutorialStep(
            "Release the Blast",
            "RELEASE the pinch to fire a charged orb.",
            lambda gs: any(h.pinch_just_released for h in gs.hands.values()),
        ),
        TutorialStep(
            "Quick Strike",
            "Make a fast UPWARD SWIPE for an instant blast.",
            lambda gs: any(h.swipe_forward for h in gs.hands.values()),
        ),
        TutorialStep(
            "Summon Mjolnir",
            "Make a FIST and raise it above your shoulder to summon the hammer.",
            lambda gs: any(h.is_fist and h.is_raised for h in gs.hands.values()),
        ),
        TutorialStep(
            "Air Rune Drawing",
            "Raise INDEX + MIDDLE fingers together to draw in the air.",
            lambda gs: any(getattr(h, "is_two_finger_pose", False) for h in gs.hands.values()),
        ),
        TutorialStep(
            "Chaos Shield",
            "Show TWO OPEN PALMS to the camera to raise a shield.",
            lambda gs: gs.two_hands_open,
        ),
        TutorialStep(
            "Unleash the Nova",
            "Charge BOTH hands (pinch+hold) then bring them TOGETHER for the ultimate.",
            lambda gs: gs.hands_together,
        ),
    ]


class Tutorial:
    def __init__(self, cfg: TutorialConfig):
        self.cfg = cfg
        self.steps = _default_steps()
        self.index = 0
        self.active = cfg.enabled_on_launch
        self.completed = False
        self._hold_t = 0.0

    def reopen(self) -> None:
        self.index = 0
        self.active = True
        self.completed = False
        self._hold_t = 0.0

    def update(self, gesture_state: GestureState, dt: float) -> None:
        if not self.active or self.completed:
            return
        step = self.steps[self.index]
        if step.check(gesture_state):
            self._hold_t += dt
            if self._hold_t >= self.cfg.step_hold_seconds:
                self._hold_t = 0.0
                self.index += 1
                if self.index >= len(self.steps):
                    self.completed = True
                    self.active = False
        else:
            self._hold_t = 0.0

    def draw(self, frame: np.ndarray) -> np.ndarray:
        if not self.active or self.completed:
            return frame
        h, w = frame.shape[:2]
        step = self.steps[self.index]
        panel_w = min(680, w - 40)
        x0, y0 = (w - panel_w) // 2, h - 148
        panel_h = 112

        overlay = frame.copy()
        cv2.rectangle(overlay, (x0, y0), (x0 + panel_w, y0 + panel_h), (25, 10, 45), -1)
        frame[:] = cv2.addWeighted(overlay, 0.80, frame, 0.20, 0)
        cv2.rectangle(frame, (x0, y0), (x0 + panel_w, y0 + panel_h), (120, 65, 225), 2)

        progress_w = int((panel_w - 24) * (self.index / len(self.steps)))
        cv2.rectangle(frame, (x0 + 12, y0 + panel_h - 10), (x0 + 12 + progress_w, y0 + panel_h - 6), (120, 65, 225), -1)

        cv2.putText(frame, f'TUTORIAL {self.index + 1}/{len(self.steps)}: {step.title}',
                    (x0 + 18, y0 + 34), cv2.FONT_HERSHEY_DUPLEX, 0.64, (235, 225, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, step.instruction, (x0 + 18, y0 + 66),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (205, 198, 235), 1, cv2.LINE_AA)
        cv2.putText(frame, "Press H to hide  |  auto-advances when detected",
                    (x0 + 18, y0 + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 145, 180), 1, cv2.LINE_AA)
        return frame
