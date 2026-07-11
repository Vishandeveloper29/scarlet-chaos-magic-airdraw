"""
storm.py
========
Atmospheric storm layer: drifting clouds, falling rain, occasional thunder
flashes, and camera screen-shake during strikes. All rendered with cheap
primitive shapes (ellipses / lines) so it stays fast on integrated GPUs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Tuple

import pygame

from config import StormConfig
from particles import ParticleSystem

Color = Tuple[int, int, int]


@dataclass
class Cloud:
    x: float
    y: float
    scale: float
    drift_speed: float
    puff_offsets: List[Tuple[float, float, float]] = field(default_factory=list)  # dx, dy, r

    def __post_init__(self) -> None:
        if not self.puff_offsets:
            for _ in range(6):
                self.puff_offsets.append(
                    (random.uniform(-60, 60), random.uniform(-15, 15), random.uniform(25, 55))
                )


@dataclass
class RainDrop:
    x: float
    y: float
    speed: float
    length: float


class StormSystem:
    def __init__(self, cfg: StormConfig, width: int, height: int):
        self.cfg = cfg
        self.width = width
        self.height = height
        self.active = False

        self.clouds: List[Cloud] = []
        self.rain: List[RainDrop] = []
        self._thunder_timer = random.uniform(cfg.thunder_min_interval, cfg.thunder_max_interval)
        self.flash_alpha = 0.0
        self.shake_magnitude = 0.0
        self._shake_offset = (0.0, 0.0)

        self._init_clouds()
        self._init_rain()

    def _init_clouds(self) -> None:
        self.clouds = [
            Cloud(
                x=random.uniform(0, self.width),
                y=random.uniform(20, self.height * 0.22),
                scale=random.uniform(0.8, 1.6),
                drift_speed=random.uniform(6, 18),
            )
            for _ in range(self.cfg.cloud_count)
        ]

    def _init_rain(self) -> None:
        self.rain = [
            RainDrop(
                x=random.uniform(0, self.width),
                y=random.uniform(-self.height, 0),
                speed=random.uniform(self.cfg.rain_speed_min, self.cfg.rain_speed_max),
                length=random.uniform(10, 22),
            )
            for _ in range(self.cfg.rain_drop_count)
        ]

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.active = False
        self.flash_alpha = 0.0

    def toggle(self) -> None:
        self.active = not self.active

    def trigger_thunder(self, strong: bool = False) -> None:
        self.flash_alpha = 220.0 if strong else 140.0
        self.shake_magnitude = 18.0 if strong else 9.0

    def update(self, dt: float, particles: ParticleSystem) -> None:
        if not self.active:
            self.flash_alpha = max(0.0, self.flash_alpha - dt * 400.0)
            self.shake_magnitude = max(0.0, self.shake_magnitude - dt * self.cfg.screen_shake_decay * 40)
            self._update_shake(dt)
            return

        for c in self.clouds:
            c.x += c.drift_speed * dt
            if c.x - 120 > self.width:
                c.x = -120

        for r in self.rain:
            r.y += r.speed * dt
            r.x -= 40 * dt  # slight wind slant
            if r.y > self.height:
                if random.random() < 0.15:
                    particles.emit_rain_splash(r.x, self.height - 2, (150, 190, 230))
                r.y = random.uniform(-40, -5)
                r.x = random.uniform(0, self.width)

        self._thunder_timer -= dt
        if self._thunder_timer <= 0:
            self.trigger_thunder(strong=random.random() < 0.3)
            self._thunder_timer = random.uniform(self.cfg.thunder_min_interval, self.cfg.thunder_max_interval)

        self.flash_alpha = max(0.0, self.flash_alpha - dt * 300.0)
        self.shake_magnitude = max(0.0, self.shake_magnitude - dt * self.cfg.screen_shake_decay)
        self._update_shake(dt)

    def _update_shake(self, dt: float) -> None:
        if self.shake_magnitude > 0.1:
            self._shake_offset = (
                random.uniform(-1, 1) * self.shake_magnitude,
                random.uniform(-1, 1) * self.shake_magnitude,
            )
        else:
            self._shake_offset = (0.0, 0.0)

    def get_shake_offset(self) -> Tuple[int, int]:
        return int(self._shake_offset[0]), int(self._shake_offset[1])

    def draw_clouds_and_rain(self, surface: pygame.Surface) -> None:
        if not self.active:
            return
        cloud_layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for c in self.clouds:
            for dx, dy, r in c.puff_offsets:
                rr = int(r * c.scale)
                pygame.draw.circle(
                    cloud_layer, (90, 100, 120, 120),
                    (int(c.x + dx * c.scale), int(c.y + dy * c.scale)), rr,
                )
        surface.blit(cloud_layer, (0, 0))

        for r in self.rain:
            col = (170, 200, 235, 160)
            end = (r.x - 4, r.y + r.length)
            pygame.draw.line(surface, col[:3], (r.x, r.y), end, 1)

    def draw_thunder_flash(self, surface: pygame.Surface) -> None:
        if self.flash_alpha > 1:
            flash = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            flash.fill((230, 240, 255, int(min(255, self.flash_alpha))))
            surface.blit(flash, (0, 0))
