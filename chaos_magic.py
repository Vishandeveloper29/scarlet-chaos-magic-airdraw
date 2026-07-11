"""
chaos_magic.py
==============
The visual heart of the app. Owns every particle/orb/nova/hammer on screen
and composites them onto the webcam frame with a cheap multi-pass bloom
(three Gaussian blurs of different radii, additively blended) so glowing
energy actually looks like it's glowing instead of just being a flat color.

Render order each frame:
    1. draw storm clouds / lightning into `glow`
    2. draw each hand's aura / hammer into `glow` + `sharp`
    3. draw the two-hand shield (if active) into `glow` + `sharp`
    4. draw particles, orbs, and nova shockwaves into `glow`
    5. blur `glow` twice (small + large radius) and additively blend both
       plus the un-blurred `glow`/`sharp` layers back onto the camera frame
    6. apply a full-screen flash tint if a blast/nova just fired
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config import HammerConfig
from hammer_fx import HammerSystem
from themes import Theme, get_theme

Color = Tuple[int, int, int]


@dataclass
class Particle:
    pos: np.ndarray
    vel: np.ndarray
    life: float
    max_life: float
    size: float


@dataclass
class Orb:
    pos: np.ndarray
    vel: np.ndarray
    life: float
    radius: float


@dataclass
class Nova:
    pos: np.ndarray
    life: float
    max_life: float


class ChaosMagicSystem:
    def __init__(self, width: int, height: int, max_particles: int = 700,
                 theme_name: str = "scarlet", hammer_cfg: Optional[HammerConfig] = None):
        self.w, self.h = width, height
        self.max_particles = max_particles
        self.particles: List[Particle] = []
        self.orbs: List[Orb] = []
        self.novas: List[Nova] = []
        self.time = 0.0
        self.shield_enabled = True
        self.runes_enabled = True
        self.storm_enabled = True
        self.flash = 0.0

        self.theme: Theme = get_theme(theme_name)
        self.hammer = HammerSystem(hammer_cfg or HammerConfig(), width, height)

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------
    def set_theme(self, theme_name: str) -> None:
        self.theme = get_theme(theme_name)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, dt: float, hands=None, gesture_state=None) -> None:
        self.time += dt
        self.flash = max(0.0, self.flash - dt * 2.4)

        for p in self.particles:
            p.pos += p.vel * dt
            p.vel *= 0.985
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0
                           and -100 < p.pos[0] < self.w + 100 and -100 < p.pos[1] < self.h + 100]

        for o in self.orbs:
            o.pos += o.vel * dt
            o.vel *= 0.998
            o.life -= dt
        self.orbs = [o for o in self.orbs if o.life > 0
                     and -200 < o.pos[0] < self.w + 200 and -200 < o.pos[1] < self.h + 200]

        for n in self.novas:
            n.life -= dt
        self.novas = [n for n in self.novas if n.life > 0]

        if hands and gesture_state:
            for hand in hands:
                hs = gesture_state.hands.get(hand.handedness)
                if hs is None:
                    continue
                impact = self.hammer.update(hand.handedness, hs.is_fist, hs.is_raised,
                                             hand.palm_center, hand.velocity, dt)
                if impact is not None:
                    self.cast_nova(impact, big=False)

    # ------------------------------------------------------------------
    # Effect spawners
    # ------------------------------------------------------------------
    def emit_hand_aura(self, center, intensity: float = 1.0) -> None:
        count = max(2, int(7 * intensity))
        c = np.array(center, dtype=np.float32)
        for _ in range(count):
            a = random.random() * math.tau
            speed = random.uniform(25, 180) * intensity
            pos = c + np.array([math.cos(a), math.sin(a)], dtype=np.float32) * random.uniform(5, 45)
            vel = np.array([math.cos(a), math.sin(a)], dtype=np.float32) * speed + np.array([0, -45], dtype=np.float32)
            life = random.uniform(0.35, 1.0)
            self.particles.append(Particle(pos, vel, life, life, random.uniform(1.2, 4.2)))
        if len(self.particles) > self.max_particles:
            self.particles = self.particles[-self.max_particles:]

    def cast_orb(self, center, direction, charge: float = 60.0) -> None:
        d = np.array(direction, dtype=np.float32)
        n = np.linalg.norm(d)
        d = d / n if n > 1e-3 else np.array([0, -1], dtype=np.float32)
        speed = 480 + min(charge, 100) * 6
        self.orbs.append(Orb(np.array(center, dtype=np.float32), d * speed, 1.35, 22 + charge * 0.18))
        self.flash = 0.75
        for _ in range(60):
            self.emit_hand_aura(center, 1.8)

    def cast_nova(self, center, big: bool = True) -> None:
        """A radial shockwave: expanding ring + particle burst. `big=True`
        is used for the two-hand ultimate; `big=False` for hammer impacts."""
        c = np.array(center, dtype=np.float32)
        self.novas.append(Nova(c.copy(), 0.9 if big else 0.55, 0.9 if big else 0.55))
        self.flash = 1.0 if big else 0.6
        burst = 90 if big else 45
        for _ in range(burst):
            a = random.random() * math.tau
            speed = random.uniform(220, 620) * (1.3 if big else 1.0)
            vel = np.array([math.cos(a), math.sin(a)], dtype=np.float32) * speed
            life = random.uniform(0.4, 0.95)
            self.particles.append(Particle(c.copy(), vel, life, life, random.uniform(2.0, 5.0)))
        if len(self.particles) > self.max_particles:
            self.particles = self.particles[-self.max_particles:]

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    def draw(self, frame, hands, gesture_state):
        theme = self.theme
        glow = np.zeros_like(frame, dtype=np.uint8)
        sharp = np.zeros_like(frame, dtype=np.uint8)

        if self.storm_enabled:
            self._draw_storm(glow, theme)

        for hand in hands:
            state = gesture_state.hands.get(hand.handedness)
            center = tuple(hand.palm_center.astype(int))
            if state and (state.is_open_palm or state.is_pinching):
                intensity = 1.0 + state.charge / 100.0
                self.emit_hand_aura(center, intensity)
                self._draw_hand_magic(glow, sharp, center, state.charge, hand.landmarks_px, theme)
            if state and state.is_fist and not self.hammer.is_active(hand.handedness):
                cv2.circle(glow, center, 18, theme.dark, -1, cv2.LINE_AA)
            self.hammer.draw(glow, sharp, hand.handedness, hand.palm_center, theme)

        if self.shield_enabled and gesture_state.two_hands_open and len(hands) == 2:
            a, b = hands[0].palm_center, hands[1].palm_center
            center = tuple(((a + b) / 2).astype(int))
            radius = int(max(90, np.linalg.norm(a - b) * 0.55))
            self._draw_shield(glow, sharp, center, radius, theme)

        self._draw_particles(glow, theme)
        self._draw_orbs(glow, sharp, theme)
        self._draw_novas(glow, sharp, theme)

        bloom = cv2.GaussianBlur(glow, (0, 0), 9)
        bloom2 = cv2.GaussianBlur(glow, (0, 0), 22)
        out = cv2.addWeighted(frame, 1.0, bloom2, 0.65, 0)
        out = cv2.addWeighted(out, 1.0, bloom, 0.95, 0)
        out = cv2.addWeighted(out, 1.0, glow, 0.9, 0)
        out = cv2.addWeighted(out, 1.0, sharp, 1.0, 0)

        if self.flash > 0:
            overlay = np.full_like(out, theme.flash)
            out = cv2.addWeighted(out, 1.0, overlay, min(0.30, self.flash * 0.25), 0)
        return out

    def _draw_hand_magic(self, glow, sharp, center, charge, landmarks, theme: Theme) -> None:
        pulse = 1 + 0.08 * math.sin(self.time * 8)
        radius = int((48 + charge * 0.50) * pulse)
        cv2.circle(glow, center, radius, theme.primary, 7, cv2.LINE_AA)
        cv2.circle(glow, center, int(radius * 0.72), theme.secondary, 3, cv2.LINE_AA)
        cv2.circle(glow, center, int(radius * 0.25), theme.core, -1, cv2.LINE_AA)
        for i in range(8):
            a = self.time * 1.4 + i * math.tau / 8
            p1 = (int(center[0] + math.cos(a) * radius * 0.72), int(center[1] + math.sin(a) * radius * 0.72))
            p2 = (int(center[0] + math.cos(a) * radius), int(center[1] + math.sin(a) * radius))
            cv2.line(sharp, p1, p2, theme.core, 2, cv2.LINE_AA)
        if self.runes_enabled:
            for i in range(12):
                a = -self.time + i * math.tau / 12
                p = (int(center[0] + math.cos(a) * radius * 0.88), int(center[1] + math.sin(a) * radius * 0.88))
                cv2.circle(sharp, p, 3, theme.core, -1, cv2.LINE_AA)
        for tip in [4, 8, 12, 16, 20]:
            p = tuple(np.array(landmarks[tip], dtype=int))
            cv2.line(glow, center, p, theme.secondary, 2, cv2.LINE_AA)
            cv2.circle(glow, p, 7, theme.primary, -1, cv2.LINE_AA)

    def _draw_shield(self, glow, sharp, center, r, theme: Theme) -> None:
        for k in range(4):
            rr = int(r * (1 - k * 0.15))
            cv2.ellipse(glow, center, (rr, int(rr * 0.72)), 0, 0, 360,
                        theme.primary if k % 2 == 0 else theme.secondary, 3, cv2.LINE_AA)
        for i in range(10):
            a = self.time * 0.8 + i * math.tau / 10
            p = (int(center[0] + math.cos(a) * r), int(center[1] + math.sin(a) * r * 0.72))
            cv2.circle(sharp, p, 5, theme.core, -1, cv2.LINE_AA)

    def _draw_particles(self, glow, theme: Theme) -> None:
        for p in self.particles:
            alpha = max(0.0, p.life / p.max_life)
            col = tuple(int(c * alpha) for c in theme.primary)
            cv2.circle(glow, tuple(p.pos.astype(int)), max(1, int(p.size * alpha)), col, -1, cv2.LINE_AA)

    def _draw_orbs(self, glow, sharp, theme: Theme) -> None:
        for o in self.orbs:
            c = tuple(o.pos.astype(int))
            r = int(o.radius * (0.9 + 0.15 * math.sin(self.time * 15)))
            cv2.circle(glow, c, r * 2, theme.dark, -1, cv2.LINE_AA)
            cv2.circle(glow, c, r, theme.primary, -1, cv2.LINE_AA)
            cv2.circle(sharp, c, max(3, r // 3), theme.core, -1, cv2.LINE_AA)
            tail = tuple((o.pos - o.vel * 0.06).astype(int))
            cv2.line(glow, tail, c, theme.secondary, max(4, r // 2), cv2.LINE_AA)

    def _draw_novas(self, glow, sharp, theme: Theme) -> None:
        for n in self.novas:
            t = 1.0 - max(0.0, n.life / n.max_life)
            radius = int(40 + t * 420)
            alpha = max(0.0, 1.0 - t)
            outer = tuple(int(c * alpha) for c in theme.primary)
            inner = tuple(int(c * alpha) for c in theme.secondary)
            cv2.circle(glow, tuple(n.pos.astype(int)), radius, outer, 6, cv2.LINE_AA)
            cv2.circle(glow, tuple(n.pos.astype(int)), max(0, radius - 18), inner, 3, cv2.LINE_AA)

    def _draw_storm(self, glow, theme: Theme) -> None:
        for i in range(7):
            x = int((i * 211 + self.time * 35) % self.w)
            y = int(35 + 18 * math.sin(self.time + i))
            cv2.ellipse(glow, (x, y), (180, 55), 0, 0, 360, theme.dark, -1, cv2.LINE_AA)
        if random.random() < 0.025:
            x = random.randint(0, self.w - 1)
            pts = [(x, 0)]
            y = 0
            while y < self.h:
                y += random.randint(35, 70)
                x += random.randint(-35, 35)
                pts.append((x, y))
            cv2.polylines(glow, [np.array(pts, np.int32)], False, theme.secondary, 2, cv2.LINE_AA)
