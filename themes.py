"""
themes.py
=========
Named color palettes for the chaos-magic renderer. All colors are BGR
tuples (OpenCV's convention, not RGB). Cycle through themes at runtime
with the [ and ] keys.

Adding your own theme is a one-line addition to THEMES + THEME_ORDER.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

Color = Tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    label: str        # human-readable name shown in the HUD
    primary: Color     # main energy ring / bolt color
    secondary: Color   # inner ring / accent color
    core: Color         # hottest, brightest center color
    dark: Color         # shadow / fist / storm cloud color
    flash: Color        # full-screen flash tint on big events


THEMES: Dict[str, Theme] = {
    "scarlet": Theme("Scarlet Witch",  (20, 25, 255),  (90, 35, 255),  (235, 235, 255), (5, 0, 55),   (35, 25, 110)),
    "void":    Theme("Void Purple",    (255, 40, 140), (255, 90, 190), (255, 235, 250), (60, 0, 55),  (110, 25, 60)),
    "emerald": Theme("Emerald Chaos",  (60, 220, 70),  (100, 255, 140),(235, 255, 235), (0, 45, 10),  (25, 90, 35)),
    "gold":    Theme("Infinity Gold",  (30, 180, 255), (60, 210, 255), (245, 250, 255), (0, 35, 60),  (25, 80, 120)),
    "ice":     Theme("Frost Rune",     (255, 180, 60), (255, 220, 140),(255, 250, 245), (60, 25, 0),  (110, 70, 20)),
}

THEME_ORDER: List[str] = ["scarlet", "void", "emerald", "gold", "ice"]


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["scarlet"])


def next_theme(name: str) -> str:
    i = THEME_ORDER.index(name) if name in THEME_ORDER else 0
    return THEME_ORDER[(i + 1) % len(THEME_ORDER)]


def prev_theme(name: str) -> str:
    i = THEME_ORDER.index(name) if name in THEME_ORDER else 0
    return THEME_ORDER[(i - 1) % len(THEME_ORDER)]
