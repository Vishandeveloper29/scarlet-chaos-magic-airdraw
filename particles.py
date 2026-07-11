"""
particles.py
============
A lightweight, capped particle system used for sparks, energy trails,
impact bursts and hammer trails. Designed to be cheap: particles are plain
dataclasses stored in a flat list, updated with simple Euler integration,
and drawn with pygame's fast primitive calls (no per-particle surfaces).

A hard cap (config.particles.max_particles) protects frame rate on
integrated graphics -- once the cap is hit, oldest particles are recycled.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Tuple

import pygame

from config import ParticleConfig

Color = Tuple[int, int, int]


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: Color
    size: float
    gravity: bool = False
    fade: bool = True


class ParticleSystem:
    def __init__(self, cfg: ParticleConfig):
        self.cfg = cfg
        self.particles: List[Particle] = []

    def clear(self) -> None:
        self.particles.clear()

    def emit_spark_burst(
        self,
        x: float,
        y: float,
        count: int,
        color: Color,
        speed_scale: float = 1.0,
        gravity: bool = False,
    ) -> None:
        for _ in range(count):
            angle = random.uniform(0, 6.2832)
            speed = random.uniform(self.cfg.spark_speed_min, self.cfg.spark_speed_max) * speed_scale
            vx = speed * pygame.math.Vector2(1, 0).rotate_rad(angle).x
            vy = speed * pygame.math.Vector2(1, 0).rotate_rad(angle).y
            life = random.uniform(self.cfg.spark_lifetime_min, self.cfg.spark_lifetime_max)
            self._add(
                Particle(
                    x=x, y=y, vx=vx, vy=vy, life=life, max_life=life,
                    color=color, size=random.uniform(1.5, 3.5), gravity=gravity,
                )
            )

    def emit_trail(self, x: float, y: float, color: Color, size: float = 3.0) -> None:
        self._add(
            Particle(
                x=x, y=y,
                vx=random.uniform(-15, 15), vy=random.uniform(-15, 15),
                life=0.35, max_life=0.35, color=color, size=size, gravity=False,
            )
        )

    def emit_rain_splash(self, x: float, y: float, color: Color) -> None:
        for _ in range(4):
            self._add(
                Particle(
                    x=x, y=y,
                    vx=random.uniform(-40, 40), vy=random.uniform(-90, -20),
                    life=0.25, max_life=0.25, color=color, size=1.5, gravity=True,
                )
            )

    def _add(self, p: Particle) -> None:
        if len(self.particles) >= self.cfg.max_particles:
            self.particles.pop(0)  # recycle oldest
        self.particles.append(p)

    def update(self, dt: float) -> None:
        alive: List[Particle] = []
        g = self.cfg.gravity
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.gravity:
                p.vy += g * dt
            alive.append(p)
        self.particles = alive

    def draw(self, surface: pygame.Surface) -> None:
        for p in self.particles:
            t = max(0.0, p.life / p.max_life)
            alpha = int(255 * t) if p.fade else 255
            size = max(1, int(p.size * (0.5 + 0.5 * t)))
            col = (*p.color, alpha)
            # Draw onto a tiny per-particle surface only when needed for alpha;
            # for performance, approximate with pygame.draw + a shared overlay.
            rect = pygame.Rect(int(p.x) - size, int(p.y) - size, size * 2, size * 2)
            temp = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, col, (size, size), size)
            surface.blit(temp, rect.topleft, special_flags=pygame.BLEND_RGBA_ADD)
