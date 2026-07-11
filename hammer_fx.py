"""
hammer_fx.py
============
A pure-OpenCV "Mjolnir" summon/throw mechanic. No sprites, no pygame -- the
hammer is drawn with primitive shapes so it composites cleanly into the same
glow/sharp layers the rest of chaos_magic.py already uses.

State machine, per hand (tracked independently for Left/Right so you can
dual-wield):

    IDLE --(fist held above shoulder for `charge_time`)--> READY
    READY --(fist opens while the hand is moving fast)--> THROWN
    THROWN --(leaves frame OR max_lifetime elapses)--> IDLE  (+ impact event)
    READY --(fist opens slowly, no swing)--> IDLE  (fizzles, no impact)

`update()` returns an optional (x, y) impact position when a throw lands,
which the caller (ChaosMagicSystem) turns into a shockwave/nova.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from config import HammerConfig
from themes import Theme


class HammerState(Enum):
    IDLE = auto()
    CHARGING = auto()
    READY = auto()
    THROWN = auto()


@dataclass
class HammerInstance:
    state: HammerState = HammerState.IDLE
    charge_t: float = 0.0
    life_t: float = 0.0
    pos: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    angle: float = 0.0


class HammerSystem:
    def __init__(self, cfg: HammerConfig, width: int, height: int):
        self.cfg = cfg
        self.w, self.h = width, height
        self.hands: Dict[str, HammerInstance] = {}

    def update(
        self,
        label: str,
        is_fist: bool,
        is_raised: bool,
        hand_center: np.ndarray,
        hand_velocity: np.ndarray,
        dt: float,
    ) -> Optional[Tuple[int, int]]:
        """Advance the state machine for one hand. Returns an impact
        (x, y) position if a thrown hammer detonated this frame."""
        inst = self.hands.setdefault(label, HammerInstance())
        impact: Optional[Tuple[int, int]] = None

        if inst.state == HammerState.IDLE:
            if is_fist and is_raised:
                inst.state = HammerState.CHARGING
                inst.charge_t = 0.0

        elif inst.state == HammerState.CHARGING:
            if is_fist and is_raised:
                inst.charge_t += dt
                if inst.charge_t >= self.cfg.charge_time:
                    inst.state = HammerState.READY
            else:
                inst.state = HammerState.IDLE
                inst.charge_t = 0.0

        elif inst.state == HammerState.READY:
            inst.pos = hand_center.astype(np.float32)
            if not is_fist:
                speed = float(np.linalg.norm(hand_velocity))
                if speed > self.cfg.swing_velocity_threshold:
                    inst.state = HammerState.THROWN
                    inst.life_t = 0.0
                    direction = hand_velocity / max(speed, 1e-3)
                    inst.vel = direction * self.cfg.throw_speed
                else:
                    inst.state = HammerState.IDLE
                    inst.charge_t = 0.0

        elif inst.state == HammerState.THROWN:
            inst.pos = inst.pos + inst.vel * dt
            inst.angle += dt * self.cfg.spin_speed
            inst.vel *= 0.995
            inst.life_t += dt
            out_of_bounds = not (-80 < inst.pos[0] < self.w + 80 and -80 < inst.pos[1] < self.h + 80)
            if out_of_bounds or inst.life_t >= self.cfg.max_lifetime:
                impact = (int(inst.pos[0]), int(inst.pos[1]))
                inst.state = HammerState.IDLE
                inst.charge_t = 0.0

        return impact

    def is_active(self, label: str) -> bool:
        inst = self.hands.get(label)
        return inst is not None and inst.state != HammerState.IDLE

    def draw(self, glow: np.ndarray, sharp: np.ndarray, label: str, hand_center: np.ndarray, theme: Theme) -> None:
        inst = self.hands.get(label)
        if inst is None or inst.state == HammerState.IDLE:
            return

        if inst.state == HammerState.CHARGING:
            t = min(1.0, inst.charge_t / max(self.cfg.charge_time, 1e-3))
            r = int(18 + 46 * t)
            c = tuple(hand_center.astype(int))
            cv2.circle(glow, c, r, theme.primary, 4, cv2.LINE_AA)
            cv2.circle(sharp, c, max(2, int(r * 0.22)), theme.core, -1, cv2.LINE_AA)
            for i in range(int(6 * t) + 1):
                a = i * math.tau / 6
                p = (int(c[0] + math.cos(a) * r), int(c[1] + math.sin(a) * r))
                cv2.circle(sharp, p, 3, theme.secondary, -1, cv2.LINE_AA)
            return

        pos = hand_center if inst.state == HammerState.READY else inst.pos
        self._draw_mjolnir(glow, sharp, tuple(pos.astype(int)), inst.angle, theme)
        if inst.state == HammerState.THROWN:
            tail = tuple((pos - inst.vel * 0.04).astype(int))
            cv2.line(glow, tail, tuple(pos.astype(int)), theme.secondary, 10, cv2.LINE_AA)

    def _draw_mjolnir(self, glow: np.ndarray, sharp: np.ndarray, center: Tuple[int, int], angle: float, theme: Theme) -> None:
        cx, cy = center
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def rot(dx: float, dy: float) -> Tuple[int, int]:
            return (int(cx + dx * cos_a - dy * sin_a), int(cy + dx * sin_a + dy * cos_a))

        # Handle
        cv2.line(sharp, rot(0, -4), rot(0, 34), (35, 30, 40), 6, cv2.LINE_AA)
        cv2.line(sharp, rot(0, -4), rot(0, 34), theme.secondary, 2, cv2.LINE_AA)

        # Rectangular head
        head = np.array([rot(-24, -36), rot(24, -36), rot(24, -6), rot(-24, -6)], np.int32)
        cv2.fillConvexPoly(glow, head, theme.dark)
        cv2.polylines(sharp, [head], True, theme.primary, 3, cv2.LINE_AA)

        # Energy halo
        cv2.circle(glow, center, 50, theme.primary, 3, cv2.LINE_AA)
        cv2.circle(glow, center, 30, theme.secondary, 2, cv2.LINE_AA)
