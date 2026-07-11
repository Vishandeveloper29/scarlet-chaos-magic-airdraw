from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import cv2
import numpy as np

from config import SpellDrawConfig
from themes import Theme, get_theme

Color = Tuple[int, int, int]


@dataclass
class SpellStroke:
    hand: str
    mode: str
    width: int
    color_a: Color
    color_b: Color
    color_core: Color
    points: List[np.ndarray] = field(default_factory=list)


@dataclass
class SpellSpark:
    pos: np.ndarray
    vel: np.ndarray
    life: float
    max_life: float
    color: Color
    size: float


@dataclass
class SpellSigil:
    pos: np.ndarray
    radius: float
    life: float
    max_life: float
    mode: str


class SpellPainter:
    """Persistent two-finger air drawing system with multiple fantasy brush modes."""

    MODES = [
        ("arcane", "ARCANE"),
        ("lightning", "LIGHTNING"),
        ("phoenix", "PHOENIX"),
        ("cosmic", "COSMIC"),
    ]

    def __init__(self, width: int, height: int, cfg: SpellDrawConfig, theme_name: str = "scarlet"):
        self.w = width
        self.h = height
        self.cfg = cfg
        self.mode_index = 0
        self.theme_name = theme_name
        self.theme = get_theme(theme_name)
        self.enabled = cfg.enabled
        self.strokes: List[SpellStroke] = []
        self.active_strokes: Dict[str, SpellStroke] = {}
        self.sparks: List[SpellSpark] = []
        self.sigils: List[SpellSigil] = []
        self._time = 0.0
        self._last_dual_sigil = -999.0

    @property
    def current_mode(self) -> str:
        return self.MODES[self.mode_index][0]

    @property
    def current_mode_label(self) -> str:
        return self.MODES[self.mode_index][1]

    def set_theme(self, theme_name: str) -> None:
        self.theme_name = theme_name
        self.theme = get_theme(theme_name)

    def cycle_mode(self) -> str:
        self.mode_index = (self.mode_index + 1) % len(self.MODES)
        return self.current_mode_label

    def toggle_enabled(self) -> bool:
        self.enabled = not self.enabled
        if not self.enabled:
            self.active_strokes.clear()
        return self.enabled

    def clear(self) -> None:
        self.strokes.clear()
        self.active_strokes.clear()
        self.sparks.clear()
        self.sigils.clear()

    def undo(self) -> None:
        if self.strokes:
            self.strokes.pop()

    def update(self, dt: float, hands, gesture_state) -> None:
        self._time += dt
        self._update_particles(dt)
        self._update_sigils(dt)

        if not self.enabled:
            self.active_strokes.clear()
            return

        active_now = set()
        draw_hands = []
        for hand in hands:
            hs = gesture_state.hands.get(hand.handedness)
            if hs is None or not getattr(hs, "is_two_finger_pose", False):
                continue
            if hs.draw_point is None:
                continue
            active_now.add(hand.handedness)
            draw_hands.append((hand, hs))
            point = np.array(hs.draw_point, dtype=np.float32)
            stroke = self.active_strokes.get(hand.handedness)
            if stroke is None:
                stroke = self._new_stroke(hand.handedness)
                stroke.points.append(point.copy())
                self.active_strokes[hand.handedness] = stroke
                self.strokes.append(stroke)
                if len(self.strokes) > self.cfg.max_strokes:
                    self.strokes = self.strokes[-self.cfg.max_strokes:]
                self._spawn_sigils(point, hand.handedness)
            else:
                if np.linalg.norm(point - stroke.points[-1]) >= self.cfg.min_point_distance:
                    self._append_interpolated(stroke, stroke.points[-1], point)
                    self._spawn_motion_sparks(point, hs.speed)

        for hand_label in list(self.active_strokes):
            if hand_label not in active_now:
                self.active_strokes.pop(hand_label, None)

        # Dual-hand sigil: if both hands are drawing and brought together, spawn a large rune pulse.
        if len(draw_hands) == 2 and gesture_state.hands_together and (self._time - self._last_dual_sigil) > self.cfg.dual_hand_sigil_cooldown:
            p = (draw_hands[0][1].draw_point + draw_hands[1][1].draw_point) / 2.0
            self.sigils.append(SpellSigil(np.array(p, dtype=np.float32), 55.0, 1.15, 1.15, self.current_mode))
            self._last_dual_sigil = self._time
            self._spawn_radial_burst(np.array(p, dtype=np.float32), 18)

    def draw(self, frame, hands=None, gesture_state=None):
        if not self.enabled and not self.strokes and not self.sparks and not self.sigils:
            return frame

        glow = np.zeros_like(frame, dtype=np.uint8)
        sharp = np.zeros_like(frame, dtype=np.uint8)

        for stroke in self.strokes:
            self._draw_stroke(glow, sharp, stroke)

        self._draw_sigils(glow, sharp)
        self._draw_sparks(glow)

        # Active drawing cursor / portal indicators.
        if hands and gesture_state and self.enabled:
            for hand in hands:
                hs = gesture_state.hands.get(hand.handedness)
                if hs is None or not getattr(hs, "is_two_finger_pose", False) or hs.draw_point is None:
                    continue
                center = tuple(np.array(hs.draw_point, dtype=int))
                rr = int(14 + 4 * math.sin(self._time * 8.0))
                cv2.circle(glow, center, rr + 12, self.theme.primary, 2, cv2.LINE_AA)
                cv2.circle(glow, center, rr, self.theme.secondary, 2, cv2.LINE_AA)
                cv2.circle(sharp, center, 3, self.theme.core, -1, cv2.LINE_AA)

        bloom = cv2.GaussianBlur(glow, (0, 0), 10)
        bloom2 = cv2.GaussianBlur(glow, (0, 0), 22)
        out = cv2.addWeighted(frame, 1.0, bloom2, 0.58, 0)
        out = cv2.addWeighted(out, 1.0, bloom, 0.95, 0)
        out = cv2.addWeighted(out, 1.0, glow, 0.85, 0)
        out = cv2.addWeighted(out, 1.0, sharp, 1.0, 0)
        self._draw_mode_badge(out)
        return out

    def _new_stroke(self, hand: str) -> SpellStroke:
        width = self.cfg.brush_base_size + random.randint(-2, 3)
        return SpellStroke(
            hand=hand,
            mode=self.current_mode,
            width=width,
            color_a=self.theme.primary,
            color_b=self.theme.secondary,
            color_core=self.theme.core,
        )

    def _append_interpolated(self, stroke: SpellStroke, p0: np.ndarray, p1: np.ndarray) -> None:
        dist = float(np.linalg.norm(p1 - p0))
        steps = max(1, int(dist / 6.0))
        for i in range(1, steps + 1):
            t = i / steps
            p = p0 * (1.0 - t) + p1 * t
            stroke.points.append(np.array(p, dtype=np.float32))
        if len(stroke.points) > self.cfg.max_points_per_stroke:
            del stroke.points[: len(stroke.points) - self.cfg.max_points_per_stroke]

    def _draw_stroke(self, glow, sharp, stroke: SpellStroke) -> None:
        pts = stroke.points
        if len(pts) < 2:
            return
        for i in range(1, len(pts)):
            p0 = tuple(pts[i - 1].astype(int))
            p1 = tuple(pts[i].astype(int))
            if stroke.mode == "arcane":
                self._draw_arcane_segment(glow, sharp, p0, p1, stroke, i)
            elif stroke.mode == "lightning":
                self._draw_lightning_segment(glow, sharp, p0, p1, stroke, i)
            elif stroke.mode == "phoenix":
                self._draw_phoenix_segment(glow, sharp, p0, p1, stroke, i)
            else:
                self._draw_cosmic_segment(glow, sharp, p0, p1, stroke, i)

    def _draw_arcane_segment(self, glow, sharp, p0, p1, stroke, i):
        cv2.line(glow, p0, p1, stroke.color_a, stroke.width + 10, cv2.LINE_AA)
        cv2.line(glow, p0, p1, stroke.color_b, stroke.width + 4, cv2.LINE_AA)
        cv2.line(sharp, p0, p1, stroke.color_core, max(2, stroke.width // 3), cv2.LINE_AA)
        if i % 8 == 0:
            mid = ((p0[0] + p1[0]) // 2, (p0[1] + p1[1]) // 2)
            cv2.circle(sharp, mid, max(3, stroke.width // 3), stroke.color_core, 1, cv2.LINE_AA)
            for k in range(6):
                a = self._time * 1.7 + k * math.tau / 6
                p = (int(mid[0] + math.cos(a) * stroke.width), int(mid[1] + math.sin(a) * stroke.width))
                cv2.line(sharp, mid, p, stroke.color_b, 1, cv2.LINE_AA)

    def _draw_lightning_segment(self, glow, sharp, p0, p1, stroke, i):
        mx = int((p0[0] + p1[0]) / 2 + random.randint(-10, 10))
        my = int((p0[1] + p1[1]) / 2 + random.randint(-10, 10))
        mid = (mx, my)
        cv2.line(glow, p0, mid, stroke.color_b, stroke.width + 8, cv2.LINE_AA)
        cv2.line(glow, mid, p1, stroke.color_a, stroke.width + 8, cv2.LINE_AA)
        cv2.line(sharp, p0, mid, stroke.color_core, max(2, stroke.width // 3), cv2.LINE_AA)
        cv2.line(sharp, mid, p1, stroke.color_core, max(2, stroke.width // 3), cv2.LINE_AA)
        if i % 4 == 0:
            bx = int(mid[0] + random.randint(-22, 22))
            by = int(mid[1] + random.randint(-22, 22))
            cv2.line(glow, mid, (bx, by), stroke.color_b, max(1, stroke.width // 4), cv2.LINE_AA)

    def _draw_phoenix_segment(self, glow, sharp, p0, p1, stroke, i):
        warm = (max(0, stroke.color_b[0] - 20), min(255, stroke.color_b[1] + 20), 255)
        cv2.line(glow, p0, p1, warm, stroke.width + 12, cv2.LINE_AA)
        cv2.line(glow, p0, p1, stroke.color_a, stroke.width + 5, cv2.LINE_AA)
        cv2.line(sharp, p0, p1, stroke.color_core, max(2, stroke.width // 3), cv2.LINE_AA)
        if i % 3 == 0:
            ex = int((p0[0] + p1[0]) / 2 + random.randint(-14, 14))
            ey = int((p0[1] + p1[1]) / 2 - random.randint(4, 18))
            cv2.circle(glow, (ex, ey), random.randint(2, 4), warm, -1, cv2.LINE_AA)

    def _draw_cosmic_segment(self, glow, sharp, p0, p1, stroke, i):
        teal = (255, 180, 120)
        purple = stroke.color_a
        cv2.line(glow, p0, p1, purple, stroke.width + 11, cv2.LINE_AA)
        cv2.line(glow, p0, p1, teal, stroke.width + 4, cv2.LINE_AA)
        cv2.line(sharp, p0, p1, stroke.color_core, max(2, stroke.width // 3), cv2.LINE_AA)
        if i % 6 == 0:
            star = ((p0[0] + p1[0]) // 2, (p0[1] + p1[1]) // 2)
            cv2.drawMarker(sharp, star, stroke.color_core, markerType=cv2.MARKER_STAR, markerSize=10, thickness=1)

    def _spawn_motion_sparks(self, point: np.ndarray, speed: float) -> None:
        burst = 1 + int(min(4, speed / 650.0))
        for _ in range(burst):
            a = random.random() * math.tau
            velocity = np.array([math.cos(a), math.sin(a)], dtype=np.float32) * random.uniform(25, 120)
            life = random.uniform(0.22, 0.75)
            color = random.choice([self.theme.primary, self.theme.secondary, self.theme.core])
            self.sparks.append(SpellSpark(point.copy(), velocity, life, life, color, random.uniform(1.4, 4.4)))
        if len(self.sparks) > self.cfg.max_sparks:
            self.sparks = self.sparks[-self.cfg.max_sparks:]

    def _spawn_radial_burst(self, point: np.ndarray, count: int) -> None:
        for _ in range(count):
            a = random.random() * math.tau
            velocity = np.array([math.cos(a), math.sin(a)], dtype=np.float32) * random.uniform(60, 180)
            life = random.uniform(0.35, 0.95)
            color = random.choice([self.theme.primary, self.theme.secondary, self.theme.core])
            self.sparks.append(SpellSpark(point.copy(), velocity, life, life, color, random.uniform(2.0, 5.0)))

    def _spawn_sigils(self, point: np.ndarray, hand: str) -> None:
        radius = random.uniform(18.0, 30.0)
        self.sigils.append(SpellSigil(point.copy(), radius, 0.75, 0.75, self.current_mode))
        self._spawn_radial_burst(point.copy(), 8)
        if len(self.sigils) > 24:
            self.sigils = self.sigils[-24:]

    def _update_particles(self, dt: float) -> None:
        for spark in self.sparks:
            spark.pos += spark.vel * dt
            spark.vel *= 0.95
            spark.life -= dt
        self.sparks = [s for s in self.sparks if s.life > 0]

    def _update_sigils(self, dt: float) -> None:
        for sigil in self.sigils:
            sigil.life -= dt
        self.sigils = [s for s in self.sigils if s.life > 0]

    def _draw_sparks(self, glow) -> None:
        for spark in self.sparks:
            alpha = max(0.0, spark.life / spark.max_life)
            col = tuple(int(c * alpha) for c in spark.color)
            cv2.circle(glow, tuple(spark.pos.astype(int)), max(1, int(spark.size * alpha)), col, -1, cv2.LINE_AA)

    def _draw_sigils(self, glow, sharp) -> None:
        for sigil in self.sigils:
            alpha = max(0.0, sigil.life / sigil.max_life)
            center = tuple(sigil.pos.astype(int))
            r = int(sigil.radius * (1.0 + 0.45 * (1.0 - alpha)))
            primary = tuple(int(c * alpha) for c in self.theme.primary)
            secondary = tuple(int(c * alpha) for c in self.theme.secondary)
            core = tuple(int(c * alpha) for c in self.theme.core)
            cv2.circle(glow, center, r, primary, 2, cv2.LINE_AA)
            cv2.circle(glow, center, int(r * 0.65), secondary, 1, cv2.LINE_AA)
            for i in range(6):
                a = self._time * 1.6 + i * math.tau / 6
                p = (int(center[0] + math.cos(a) * r), int(center[1] + math.sin(a) * r))
                cv2.line(sharp, center, p, core, 1, cv2.LINE_AA)
            cv2.drawMarker(sharp, center, core, markerType=cv2.MARKER_CROSS, markerSize=max(8, int(r * 0.65)), thickness=1)

    def _draw_mode_badge(self, frame) -> None:
        panel_w = 360
        x0, y0 = 18, frame.shape[0] - 70
        cv2.rectangle(frame, (x0, y0), (x0 + panel_w, y0 + 42), (18, 12, 28), -1)
        cv2.rectangle(frame, (x0, y0), (x0 + panel_w, y0 + 42), self.theme.secondary, 1)
        txt = f"AIR DRAW: TWO FINGERS | MODE: {self.current_mode_label}"
        cv2.putText(frame, txt, (x0 + 12, y0 + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (240, 235, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "M mode  X clear  U undo  D toggle draw", (x0 + 12, y0 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 190, 230), 1, cv2.LINE_AA)
