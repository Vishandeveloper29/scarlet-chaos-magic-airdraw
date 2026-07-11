"""
effects.py
==========
Shared, generic visual-effect utilities that don't belong to a single
gameplay system: cheap bloom approximation, full-screen flash, and small UI
drawing helpers (FPS counter, energy bar, gesture/status text).

Bloom approach (cheap, integrated-GPU friendly):
  1. Downscale the rendered frame to a small surface (e.g. 1/4 size).
  2. Upscale it back with smoothscale (this blurs it, free anti-aliasing).
  3. Additively blend the blurred result back onto the full-size frame.
This approximates a glow/bloom pass without any shader code, at a fraction
of the cost of a real Gaussian blur.
"""

from __future__ import annotations

from typing import Optional, Tuple

import pygame

Color = Tuple[int, int, int]


def apply_bloom(surface: pygame.Surface, downscale: int = 4, intensity: float = 1.0) -> None:
    """In-place cheap bloom: blurs a downsampled copy and additively re-blends it."""
    w, h = surface.get_size()
    small_size = (max(1, w // downscale), max(1, h // downscale))
    small = pygame.transform.smoothscale(surface, small_size)
    # A second smoothscale pass (down then up) approximates a blur kernel.
    blurred = pygame.transform.smoothscale(small, (w, h))
    if intensity < 1.0:
        blurred.set_alpha(int(255 * intensity))
    surface.blit(blurred, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)


class ScreenFlash:
    """Simple full-screen additive flash used for blasts/thunder."""

    def __init__(self) -> None:
        self.alpha = 0.0

    def trigger(self, amount: float = 200.0) -> None:
        self.alpha = max(self.alpha, amount)

    def update(self, dt: float, decay: float = 500.0) -> None:
        self.alpha = max(0.0, self.alpha - decay * dt)

    def draw(self, surface: pygame.Surface, color: Color = (200, 220, 255)) -> None:
        if self.alpha > 1:
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((*color, int(min(255, self.alpha))))
            surface.blit(overlay, (0, 0))


class UIRenderer:
    """Draws the HUD: FPS, gesture status, energy bar, active power."""

    def __init__(self, ui_cfg) -> None:
        self.cfg = ui_cfg
        pygame.font.init()
        self.font_small = pygame.font.SysFont(ui_cfg.font_name, ui_cfg.font_size_small)
        self.font_medium = pygame.font.SysFont(ui_cfg.font_name, ui_cfg.font_size_medium)
        self.font_large = pygame.font.SysFont(ui_cfg.font_name, ui_cfg.font_size_large)

    def draw_text_glow(
        self, surface: pygame.Surface, text: str, pos: Tuple[int, int],
        font: pygame.font.Font, color: Color, glow_color: Optional[Color] = None,
    ) -> None:
        glow_color = glow_color or self.cfg.accent_color
        glow_surf = font.render(text, True, glow_color)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            surface.blit(glow_surf, (pos[0] + dx, pos[1] + dy), special_flags=pygame.BLEND_RGBA_ADD)
        main_surf = font.render(text, True, color)
        surface.blit(main_surf, pos)

    def draw_fps(self, surface: pygame.Surface, fps: float, pos: Tuple[int, int] = (16, 12)) -> None:
        self.draw_text_glow(surface, f"FPS: {fps:0.0f}", pos, self.font_small, self.cfg.text_color)

    def draw_gesture_status(self, surface: pygame.Surface, gesture_text: str, pos: Tuple[int, int]) -> None:
        self.draw_text_glow(surface, gesture_text, pos, self.font_small, self.cfg.accent_color)

    def draw_energy_bar(
        self, surface: pygame.Surface, charge: float, max_charge: float,
        pos: Tuple[int, int], size: Tuple[int, int] = (220, 18),
    ) -> None:
        x, y = pos
        w, h = size
        pct = max(0.0, min(1.0, charge / max_charge if max_charge else 0.0))
        pygame.draw.rect(surface, (40, 50, 70), (x, y, w, h), border_radius=6)
        fill_w = int(w * pct)
        if fill_w > 0:
            fill_color = (120, 190, 255) if pct < 1.0 else (255, 255, 255)
            pygame.draw.rect(surface, fill_color, (x, y, fill_w, h), border_radius=6)
        pygame.draw.rect(surface, self.cfg.text_color, (x, y, w, h), width=1, border_radius=6)
        label = self.font_small.render("ENERGY", True, self.cfg.text_color)
        surface.blit(label, (x, y - 20))

    def draw_active_power(self, surface: pygame.Surface, power_name: str, pos: Tuple[int, int]) -> None:
        self.draw_text_glow(surface, f"POWER: {power_name}", pos, self.font_medium, (255, 255, 255), self.cfg.accent_color)
