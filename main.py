"""
main.py
=======
Application entry point and the frame loop. Wires together:

    HandTracker        -> raw webcam frame  -> smoothed hand landmarks
    GestureRecognizer   -> hand landmarks    -> high-level gestures/charge
    ChaosMagicSystem    -> gestures          -> particles/orbs/hammer/nova
    Tutorial            -> gestures          -> onboarding overlay
    Recorder            -> final frame       -> optional .mp4 clip

Run with `python main.py` (or double-click run_windows.bat on Windows).
"""

from __future__ import annotations

import os
import time

import cv2

from config import CONFIG
from hand_tracker import HandTracker
from gestures import GestureRecognizer
from chaos_magic import ChaosMagicSystem
from tutorial import Tutorial
from recorder import Recorder
from spell_painter import SpellPainter
from themes import next_theme, prev_theme

CAPTURE_DIR = "captures"
os.makedirs(CAPTURE_DIR, exist_ok=True)


def draw_hud(frame, fps, magic: ChaosMagicSystem, recorder: Recorder, painter: SpellPainter) -> None:
    cv2.rectangle(frame, (18, 18), (560, 202), (10, 0, 25), -1)
    cv2.rectangle(frame, (18, 18), (560, 202), (40, 20, 170), 2)
    cv2.putText(frame, "SCARLET CHAOS MAGIC", (34, 49), cv2.FONT_HERSHEY_DUPLEX, 0.78,
                (225, 210, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"FPS {fps:4.1f}   THEME: {magic.theme.label.upper()}   DRAW: {painter.current_mode_label}", (34, 76),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (180, 170, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, "Open palm: aura | Pinch + release: blast | Swipe up: quick blast",
                (34, 99), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 190, 235), 1, cv2.LINE_AA)
    cv2.putText(frame, "Fist raised: summon hammer, swing to throw | Two palms: shield / NOVA",
                (34, 121), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 190, 235), 1, cv2.LINE_AA)
    cv2.putText(frame, "Two fingers together: AIR DRAW spell trail | Bring both draw-hands together: sigil burst",
                (34, 143), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (210, 200, 240), 1, cv2.LINE_AA)
    cv2.putText(frame, "[ ] theme  M mode  D draw on/off  U undo  X clear  S shield  R runes",
                (34, 167), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (170, 160, 220), 1, cv2.LINE_AA)
    cv2.putText(frame, "T storm  C shot  V record  H help  Q quit",
                (34, 188), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (170, 160, 220), 1, cv2.LINE_AA)
    if recorder.is_recording:
        cv2.circle(frame, (frame.shape[1] - 38, 38), 10, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(frame, "REC", (frame.shape[1] - 84, 46), cv2.FONT_HERSHEY_DUPLEX, 0.6,
                    (0, 0, 255), 1, cv2.LINE_AA)


def open_camera(cfg):
    """Try multiple backends and warm up the camera for a few frames."""
    backend_candidates = []
    if hasattr(cv2, "CAP_DSHOW"):
        backend_candidates.append(cv2.CAP_DSHOW)
    backend_candidates.append(cv2.CAP_ANY)

    last_cap = None
    for backend in backend_candidates:
        cap = cv2.VideoCapture(cfg.camera.device_index, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(cfg.camera.device_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.camera.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.camera.height)
        cap.set(cv2.CAP_PROP_FPS, cfg.camera.fps)
        if not cap.isOpened():
            cap.release()
            continue
        frame = None
        ok = False
        for _ in range(18):
            ok, frame = cap.read()
            if ok and frame is not None:
                break
            time.sleep(0.03)
        if ok and frame is not None:
            return cap, frame
        last_cap = cap
        cap.release()

    raise RuntimeError(
        "Could not open webcam or receive frames. Close Camera/OBS/DroidCam/Virtual Camera or change device_index in config.py."
    )


def main() -> None:
    cfg = CONFIG
    cap, frame = open_camera(cfg)

    h, w = frame.shape[:2]
    tracker = HandTracker(cfg.hands, w, h)
    recognizer = GestureRecognizer(cfg.gestures, w, h)
    magic = ChaosMagicSystem(w, h, cfg.max_particles, cfg.theme.default, cfg.hammer)
    painter = SpellPainter(w, h, cfg.spell_draw, cfg.theme.default)
    tutorial = Tutorial(cfg.tutorial)
    recorder = Recorder(cfg.recording, cfg.camera.fps, (w, h))

    theme_name = cfg.theme.default
    last_nova_time = -999.0
    prev = time.perf_counter()
    fps = 0.0

    print("Scarlet Chaos Magic started. Press Q or ESC to exit.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if cfg.camera.flip_horizontal:
                frame = cv2.flip(frame, 1)
            frame = cv2.convertScaleAbs(frame, alpha=cfg.background_dim, beta=-4)

            now = time.perf_counter()
            dt = min(0.05, now - prev)
            prev = now
            inst = 1 / max(dt, 1e-4)
            fps = fps * 0.9 + inst * 0.1

            hands = tracker.process(frame)
            state = recognizer.update(hands, dt)
            tutorial.update(state, dt)

            for hand in hands:
                hs = state.hands.get(hand.handedness)
                if hs and hs.pinch_just_released and hs.charge > 8:
                    charge = recognizer.consume_charge(hand.handedness)
                    magic.cast_orb(hand.palm_center, hs.pointing_direction, charge)
                elif hs and hs.swipe_forward:
                    magic.cast_orb(hand.palm_center, hs.pointing_direction, 45)

            # Two-hand ultimate: both hands charged and brought together.
            if (
                "Left" in state.hands and "Right" in state.hands
                and state.hands_together
                and state.hands["Left"].charge >= cfg.ultimate.charge_threshold
                and state.hands["Right"].charge >= cfg.ultimate.charge_threshold
                and (magic.time - last_nova_time) >= cfg.ultimate.cooldown_seconds
            ):
                left_hand = next(hd for hd in hands if hd.handedness == "Left")
                right_hand = next(hd for hd in hands if hd.handedness == "Right")
                midpoint = (left_hand.palm_center + right_hand.palm_center) / 2
                magic.cast_nova(midpoint, big=True)
                recognizer.consume_charge("Left")
                recognizer.consume_charge("Right")
                last_nova_time = magic.time

            magic.update(dt, hands, state)
            painter.update(dt, hands, state)
            out = magic.draw(frame, hands, state)
            out = painter.draw(out, hands, state)
            tutorial.draw(out)
            draw_hud(out, fps, magic, recorder, painter)
            recorder.write(out)

            cv2.imshow("Scarlet Chaos Magic - Webcam VFX", out)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("s"):
                magic.shield_enabled = not magic.shield_enabled
            if key == ord("r"):
                magic.runes_enabled = not magic.runes_enabled
            if key == ord("t"):
                magic.storm_enabled = not magic.storm_enabled
            if key == ord("h"):
                tutorial.reopen()
            if key == ord("v"):
                recorder.toggle()
            if key == ord("m"):
                print("Draw mode:", painter.cycle_mode())
            if key == ord("x"):
                painter.clear()
                print("Air-draw strokes cleared.")
            if key == ord("u"):
                painter.undo()
                print("Removed last air-draw stroke.")
            if key == ord("d"):
                enabled = painter.toggle_enabled()
                print("Air-draw", "enabled" if enabled else "disabled")
            if key == ord("]"):
                theme_name = next_theme(theme_name)
                magic.set_theme(theme_name)
                painter.set_theme(theme_name)
            if key == ord("["):
                theme_name = prev_theme(theme_name)
                magic.set_theme(theme_name)
                painter.set_theme(theme_name)
            if key == ord("c"):
                path = os.path.join(CAPTURE_DIR, f"scarlet_{int(time.time())}.png")
                cv2.imwrite(path, out)
                print("Saved:", path)
    finally:
        tracker.close()
        recorder.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
