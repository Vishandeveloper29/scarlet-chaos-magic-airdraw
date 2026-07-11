"""
recorder.py
===========
Minimal MP4 clip recorder built on cv2.VideoWriter, toggled with the V key.
Kept separate from main.py so the record/stop/file-naming logic has one
obvious home.
"""

from __future__ import annotations

import os
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from config import RecordingConfig


class Recorder:
    def __init__(self, cfg: RecordingConfig, fps: float, size: Tuple[int, int]):
        self.cfg = cfg
        self.fps = max(fps, 15.0)
        self.size = size
        self.writer: Optional[cv2.VideoWriter] = None
        self.path: Optional[str] = None
        os.makedirs(cfg.output_dir, exist_ok=True)

    @property
    def is_recording(self) -> bool:
        return self.writer is not None

    def toggle(self) -> None:
        self.stop() if self.is_recording else self.start()

    def start(self) -> None:
        self.path = os.path.join(self.cfg.output_dir, f'scarlet_{int(time.time())}.mp4')
        fourcc = cv2.VideoWriter_fourcc(*self.cfg.fourcc)
        self.writer = cv2.VideoWriter(self.path, fourcc, self.fps, self.size)
        print('Recording started:', self.path)

    def stop(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            print('Recording saved:', self.path)

    def write(self, frame: np.ndarray) -> None:
        if self.writer is not None:
            self.writer.write(frame)

    def close(self) -> None:
        self.stop()
