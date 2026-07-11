"""
hammer.py
=========
Procedural Mjolnir: a glowing rectangular hammer head + handle drawn purely
with pygame primitives (no texture assets required, though assets/hammer/
is reserved if the user wants to drop in a sprite later).

State machine:
    IDLE_IN_HAND -> THROWN -> RETURNING -> IDLE_IN_HAND

Also provides `MjolnirField`, the pulsing energy effect summoned between two
open hands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

import numpy as np
import pygame

from config import HammerConfig
from particles import ParticleSystem

Color = Tuple[int, int, int]


class HammerState(Enum):
    IDLE_IN_HAND = auto()
    THROWN = auto()
    RETURNING = auto()


class Hammer:
    def __init__(self, cfg: HammerConfig):
        self.cfg = cfg
        self.state = HammerState.IDLE_IN_HAND
        self.pos = np.array([0.0, 0.0])
        self.vel = np.array([0.0, 0.0])
        self.target_hand_pos = np.array([0.0, 0.0])
        self.throw_direction = np.array([0.0, -1.0])
        self.rotation = 0.0
        self.just_impacted = False

    def throw(self, origin: np.ndarray, direction: np.ndarray) -> None:
        if self.state != HammerState.IDLE_IN_HAND:
            return
        self.pos = origin.copy()
        norm = np.linalg.norm(direction)
        self.throw_direction = direction / norm if norm > 1e-3 else np.array([0.0, -1.0])
        self.vel = self.throw_direction * self.cfg.throw_speed
        self.state = HammerState.THROWN

    def recall(self) -> None:
        if self.state == HammerState.THROWN:
            self.state = HammerState.RETURNING

    def update(self, dt: float, hand_pos: np.ndarray, bounds: Tuple[int, int], particles: ParticleSystem) -> None:
        self.target_hand_pos = hand_pos.copy()
        self.rotation += self.cfg.spin_speed_deg * dt
        self.rotation %= 360

        if self.state == HammerState.IDLE_IN_HAND:
            self.pos = hand_pos.copy()
            self.just_impacted = False

        elif self.state == HammerState.THROWN:
            self.pos += self.vel * dt
            particles.emit_trail(self.pos[0], self.pos[1], self.cfg.glow_color, size=4.0)
            w, h = bounds
            hit_wall = self.pos[0] < 0 or self.pos[0] > w or self.pos[1] < 0 or self.pos[1] > h
            if hit_wall:
                self.pos[0] = float(np.clip(self.pos[0], 4, w - 4))
                self.pos[1] = float(np.clip(self.pos[1], 4, h - 4))
                self._impact(particles)
                self.state = HammerState.RETURNING

        elif self.state == HammerState.RETURNING:
            to_hand = self.target_hand_pos - self.pos
            dist = np.linalg.norm(to_hand)
            particles.emit_trail(self.pos[0], self.pos[1], self.cfg.glow_color, size=3.0)
            if dist < 24:
                self.state = HammerState.IDLE_IN_HAND
                self.pos = self.target_hand_pos.copy()
            else:
                direction = to_hand / dist
                self.pos += direction * self.cfg.return_speed * dt

    def _impact(self, particles: ParticleSystem) -> None:
        self.just_impacted = True
        particles.emit_spark_burst(self.pos[0], self.pos[1], count=40, color=self.cfg.glow_color, speed_scale=1.4)

    def draw(self, surface: pygame.Surface) -> None:
        w, h = 46, 60
        temp = pygame.Surface((w * 3, h * 3), pygame.SRCALPHA)
        cx, cy = temp.get_width() // 2, temp.get_height() // 2

        # Glow behind the hammer
        pygame.draw.circle(temp, (*self.cfg.glow_color, 60), (cx, cy), int(w * 1.1))

        # Build hammer shape on an unrotated surface, then rotate.
        shape = pygame.Surface((w, h), pygame.SRCALPHA)
        head_rect = pygame.Rect(0, 0, w, int(h * 0.42))
        pygame.draw.rect(shape, self.cfg.head_color, head_rect, border_radius=4)
        pygame.draw.rect(shape, (*self.cfg.glow_color, 180), head_rect, width=2, border_radius=4)
        handle_rect = pygame.Rect(w // 2 - 4, int(h * 0.42), 8, int(h * 0.58))
        pygame.draw.rect(shape, self.cfg.handle_color, handle_rect, border_radius=2)

        rotated = pygame.transform.rotate(shape, self.rotation)
        rrect = rotated.get_rect(center=(cx, cy))
        temp.blit(rotated, rrect.topleft)

        surface.blit(
            temp,
            (int(self.pos[0] - temp.get_width() / 2), int(self.pos[1] - temp.get_height() / 2)),
            special_flags=pygame.BLEND_RGBA_ADD,
        )


class MjolnirField:
    """The pulsing energy bridge summoned when both hands are open."""

    def __init__(self, cfg: HammerConfig):
        self.cfg = cfg
        self._t = 0.0

    def update(self, dt: float) -> None:
        self._t += dt

    def draw(self, surface: pygame.Surface, hand_a: np.ndarray, hand_b: np.ndarray) -> None:
        pulse = 0.6 + 0.4 * math.sin(self._t * 8.0)
        mid = (hand_a + hand_b) / 2.0
        dist = float(np.linalg.norm(hand_b - hand_a))

        temp = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        thickness = max(2, int(4 + 6 * pulse))
        pygame.draw.line(
            temp, (*self.cfg.glow_color, int(140 * pulse) + 40),
            (float(hand_a[0]), float(hand_a[1])), (float(hand_b[0]), float(hand_b[1])), thickness,
        )
        radius = int(14 + 10 * pulse)
        pygame.draw.circle(temp, (255, 255, 255, int(120 * pulse) + 40), (int(mid[0]), int(mid[1])), radius)
        surface.blit(temp, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
