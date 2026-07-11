from dataclasses import dataclass, field

@dataclass
class CameraConfig:
    device_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    flip_horizontal: bool = True

@dataclass
class HandTrackingConfig:
    max_num_hands: int = 2
    min_detection_confidence: float = 0.60
    min_tracking_confidence: float = 0.55
    model_complexity: int = 0
    smoothing_alpha: float = 0.55
    process_every_n_frames: int = 1

@dataclass
class GestureConfig:
    pinch_distance_threshold: float = 0.045
    pinch_release_hysteresis: float = 0.015
    fist_curl_threshold: float = 0.55
    open_palm_extension_threshold: float = 0.65
    swipe_velocity_threshold: float = 1200.0
    pull_back_velocity_threshold: float = 850.0
    hand_raised_y_threshold: float = 0.34
    two_hand_distance_delta: float = 18.0
    history_length: int = 8

@dataclass
class HammerConfig:
    # Fist held above the raise threshold for this long summons Mjolnir.
    charge_time: float = 0.6
    # Pixels/sec the hand must be moving when the fist opens to count as a throw.
    swing_velocity_threshold: float = 380.0
    throw_speed: float = 1500.0
    # Thrown hammer despawns (and detonates) after this many seconds even
    # if it never leaves the frame.
    max_lifetime: float = 2.2
    spin_speed: float = 22.0

@dataclass
class UltimateConfig:
    # Both hands must be charged at least this much (0-100)...
    charge_threshold: float = 90.0
    # ...and brought together, to trigger the two-hand nova blast.
    cooldown_seconds: float = 1.5

@dataclass
class RecordingConfig:
    output_dir: str = "captures"
    fourcc: str = "mp4v"

@dataclass
class TutorialConfig:
    enabled_on_launch: bool = True
    step_hold_seconds: float = 0.35


@dataclass
class SpellDrawConfig:
    enabled: bool = True
    brush_base_size: int = 14
    min_point_distance: float = 4.0
    max_points_per_stroke: int = 1600
    max_strokes: int = 28
    max_sparks: int = 280
    dual_hand_sigil_cooldown: float = 1.1

@dataclass
class ThemeConfig:
    # One of: scarlet, void, emerald, gold, ice  (see themes.py)
    default: str = "scarlet"

@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    hands: HandTrackingConfig = field(default_factory=HandTrackingConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    hammer: HammerConfig = field(default_factory=HammerConfig)
    ultimate: UltimateConfig = field(default_factory=UltimateConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    tutorial: TutorialConfig = field(default_factory=TutorialConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    spell_draw: SpellDrawConfig = field(default_factory=SpellDrawConfig)
    bloom_strength: float = 1.35
    max_particles: int = 700
    background_dim: float = 0.72

CONFIG = AppConfig()
