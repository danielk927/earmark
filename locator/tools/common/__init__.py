"""Shared DSP constants and definitions (LOCATOR_BRIEF.md section 7.1).

Single source of truth for the chirp waveform, config loading, and room
physics. The iOS app and the firmware consume the identical definitions
(brief sections 4.3 and 9.4).
"""

from .chirp import (
    ChirpConfig,
    chirp_edge_ticks,
    chirp_edge_times_s,
    square_wave_samples,
)
from .config import (
    DEFAULT_BEACONS,
    Beacon,
    ConfigError,
    beacons_from_dict,
    chirp_from_dict,
    load_beacon_config,
    load_chirp_config,
)
from .constants import (
    DEFAULT_TEMPERATURE_C,
    TICK_S,
    speed_of_sound,
)

__all__ = [
    "ChirpConfig",
    "chirp_edge_ticks",
    "chirp_edge_times_s",
    "square_wave_samples",
    "DEFAULT_BEACONS",
    "Beacon",
    "ConfigError",
    "beacons_from_dict",
    "chirp_from_dict",
    "load_beacon_config",
    "load_chirp_config",
    "DEFAULT_TEMPERATURE_C",
    "TICK_S",
    "speed_of_sound",
]
