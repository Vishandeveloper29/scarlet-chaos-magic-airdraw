"""
lightning.py
============
The heart of the visual style: procedurally generated branching lightning
bolts, finger-to-finger arcs, palm auras, and directional blasts.

Algorithm (midpoint displacement, a.k.a. the "Fast Fourier" lightning trick):
  1. Start with a straight line from point A to point B.
  2. Find the midpoint and displace it perpendicular to the A->B direction
     by a random amount proportional to the segment length.
  3. Recurse on the two new sub-segments, shrinking the displacement each
     level (like a 1D fractal / midpoint displacement terrain).
  4. Optionally spawn a shorter "branch" bolt at some vertices.

This is cheap (no per-pixel shaders needed) and looks convincingly electric
when rendered with a multi-pass glow (thick, low-alpha outer strokes plus a
thin, bright core stroke).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pygame

from config import LightningConfig
from hand_tracker import HandData, FINGER_TIPS

Color = Tuple[int, int, int]


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------
def _generate_bolt_points(
    start: np.ndarray,
    end: np.ndarray,
    displacement: float,
    depth: int,
    min_segment: float = 8.0,
) -> List[np.ndarray]:
    """Recursive midpoint-displacement fractal line."""
    if depth <= 0 or np.linalg.norm(end - start) < min_segment:
        return [start, end]

    mid = (start + end) / 2.0
    direction = end - start
    length = np.linalg.norm(direction)
    if length < 1e-3:
        return [start, end]
    normal = np.array([-direction[1], direction[0]]) / length
    offset = normal * random.uniform(-displacement, displacement)
    mid = mid + offset

    left = _generate_bolt_points(start, mid, displacement * 0.55, depth - 1, min_segment)
    right = _generate_bolt_points(mid, end, displacement * 0.55, depth - 1, min_segment)
    return left[:-1] + right


@dataclass
class Bolt:
    points: List[np.ndarray]
    life: float
    max_life: float
    color_core: Color
    color_glow: Color
    width: float = 2.0


class LightningSystem:
    """Owns all active bolts / arcs / auras and renders them each frame."""

    def __init__(self, cfg: LightningConfig):
        self.cfg = cfg
        self.bolts: List[Bolt] = []
        self._aura_pulse_t = 0.0

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.bolts.clear()

    def update(self, dt: float) -> None:
        self._aura_pulse_t += dt
        alive = []
        for b in self.bolts:
            b.life -= dt
            if b.life > 0:
                alive.append(b)
        self.bolts = alive

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------
    def spawn_bolt(
        self,
        start: np.ndarray,
        end: np.ndarray,
        intensity: float = 1.0,
        lifetime: Optional[float] = None,
    ) -> None:
        if len(self.bolts) >= self.cfg.max_bolts:
            self.bolts.pop(0)

        displacement = 14.0 * (0.5 + intensity)
        depth = min(self.cfg.max_branch_depth, 5)
        points = _generate_bolt_points(start.astype(float), end.astype(float), displacement, depth)

        bolt = Bolt(
            points=points,
            life=lifetime if lifetime is not None else self.cfg.bolt_lifetime,
            max_life=lifetime if lifetime is not None else self.cfg.bolt_lifetime,
            color_core=self.cfg.palette_core,
            color_glow=self.cfg.palette_mid,
            width=1.5 + intensity * 2.5,
        )
        self.bolts.append(bolt)

        # Random branching off intermediate vertices
        if len(points) > 2:
            for i in range(1, len(points) - 1):
                if random.random() < self.cfg.branch_probability * intensity:
                    branch_end = points[i] + (points[i] - points[0]) * random.uniform(0.15, 0.4)
                    branch_end += np.array(
                        [random.uniform(-30, 30), random.uniform(-30, 30)]
                    )
                    branch_points = _generate_bolt_points(
                        points[i], branch_end, displacement * 0.6, max(1, depth - 2)
                    )
                    self.bolts.append(
                        Bolt(
                            points=branch_points,
                            life=bolt.life * 0.6,
                            max_life=bolt.life * 0.6,
                            color_core=self.cfg.palette_core,
                            color_glow=self.cfg.palette_edge,
                            width=max(1.0, bolt.width * 0.5),
                        )
                    )

    def spawn_finger_arcs(self, hand: HandData, intensity: float) -> None:
        """Arcs jumping between adjacent fingertips -- the classic 'crackling hand' look."""
        tips = [hand.landmarks_px[i] for i in FINGER_TIPS]
        for i in range(len(tips) - 1):
            if random.random() < 0.5 + 0.4 * intensity:
                self.spawn_bolt(tips[i], tips[i + 1], intensity=intensity, lifetime=self.cfg.finger_arc_lifetime)

    def spawn_blast(self, origin: np.ndarray, direction: np.ndarray, length: float, intensity: float) -> np.ndarray:
        """Directional blast: a chain of bolts marching outward from the hand. Returns impact point."""
        direction = direction / (np.linalg.norm(direction) + 1e-6)
        end = origin + direction * length
        segments = 3
        prev = origin
        for s in range(1, segments + 1):
            t = s / segments
            jitter = np.array([random.uniform(-20, 20), random.uniform(-20, 20)]) * (1 - t)
            point = origin + direction * length * t + jitter
            self.spawn_bolt(prev, point, intensity=intensity, lifetime=0.22)
            prev = point
        return prev

    def spawn_arc_between(self, a: np.ndarray, b: np.ndarray, intensity: float) -> None:
        self.spawn_bolt(a, b, intensity=intensity, lifetime=0.15)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        for b in self.bolts:
            t = max(0.0, b.life / b.max_life)
            self._draw_bolt(surface, b, t)

    def _draw_bolt(self, surface: pygame.Surface, bolt: Bolt, t: float) -> None:
        pts = [(float(p[0]), float(p[1])) for p in bolt.points]
        if len(pts) < 2:
            return
        alpha_outer = int(90 * t)
        alpha_mid = int(160 * t)
        alpha_core = int(255 * t)

        # Outer glow (wide, low alpha) -- drawn on a temp SRCALPHA surface then
        # additively blended so overlapping bolts brighten instead of muddying.
        bbox = self._bolt_bbox(pts, pad=int(bolt.width * 6) + 12)
        w = max(1, bbox[2] - bbox[0])
        h = max(1, bbox[3] - bbox[1])
        temp = pygame.Surface((w, h), pygame.SRCALPHA)
        offset = (-bbox[0], -bbox[1])
        local_pts = [(p[0] + offset[0], p[1] + offset[1]) for p in pts]

        try:
            pygame.draw.lines(temp, (*bolt.color_glow, alpha_outer), False, local_pts, max(2, int(bolt.width * 4)))
            pygame.draw.lines(temp, (*bolt.color_glow, alpha_mid), False, local_pts, max(2, int(bolt.width * 2)))
            pygame.draw.lines(temp, (*bolt.color_core, alpha_core), False, local_pts, max(1, int(bolt.width)))
        except ValueError:
            return

        surface.blit(temp, bbox[:2], special_flags=pygame.BLEND_RGBA_ADD)

    @staticmethod
    def _bolt_bbox(pts: List[Tuple[float, float]], pad: int) -> Tuple[int, int, int, int]:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = int(min(xs)) - pad, int(max(xs)) + pad
        y0, y1 = int(min(ys)) - pad, int(max(ys)) + pad
        return x0, y0, x1, y1

    # ------------------------------------------------------------------
    # Palm aura (radial glow that pulses & grows with movement speed)
    # ------------------------------------------------------------------
    def draw_palm_aura(self, surface: pygame.Surface, center: np.ndarray, intensity: float) -> None:
        pulse = 0.85 + 0.15 * math.sin(self._aura_pulse_t * 10.0)
        radius = int((self.cfg.aura_base_radius + intensity * (self.cfg.aura_max_radius - self.cfg.aura_base_radius)) * pulse)
        radius = max(10, radius)

        temp = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        for i, (col, frac, alpha) in enumerate(
            [
                (self.cfg.palette_core, 0.25, 130),
                (self.cfg.palette_mid, 0.55, 80),
                (self.cfg.palette_edge, 1.0, 40),
            ]
        ):
            r = max(2, int(radius * frac))
            pygame.draw.circle(temp, (*col, int(alpha * intensity + 20)), (radius, radius), r)
        surface.blit(
            temp,
            (int(center[0] - radius), int(center[1] - radius)),
            special_flags=pygame.BLEND_RGBA_ADD,
        )
