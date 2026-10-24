"""Config fixture tests: LOCATOR_BRIEF.md sections 2.2, 4.6 and 8.6.

These pin the placeholder defaults exactly as written in the brief so a
later edit that drifts from the shared ground truth fails CI instead of
silently desynchronizing the firmware, the app, and the tools.
"""

import json
from pathlib import Path

import pytest

LOCATOR_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = LOCATOR_ROOT / "config"


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def beacons() -> dict:
    return load_json(CONFIG_DIR / "beacons.json")


@pytest.fixture
def chirp() -> dict:
    return load_json(CONFIG_DIR / "chirp.json")


@pytest.fixture
def params() -> dict:
    return load_json(CONFIG_DIR / "locator_params.json")


# Brief section 2.2 placeholder geometry.

BEACON_PLACEHOLDERS = [
    ("B1", [-1.5, 1.5, 1.8], 0),
    ("B2", [1.5, 1.5, 0.3], 1),
    ("B3", [1.5, -1.5, 1.8], 2),
    ("B4", [-1.5, -1.5, 0.3], 3),
    ("B5", [-1.8, 0.0, 1.0], 4),
]


def test_beacon_config_is_the_bare_form_accepted_by_the_import_rule(beacons):
    # Section 2.2: the app and tools accept a bare {"beacons": [...]} file or
    # the other repo's full space.json. The committed fixture is the bare form.
    assert set(beacons.keys()) == {"beacons"}


def test_placeholder_beacons_match_the_brief(beacons):
    entries = beacons["beacons"]
    assert len(entries) == 5
    for entry, (beacon_id, position, slot) in zip(entries, BEACON_PLACEHOLDERS):
        assert entry["id"] == beacon_id
        assert entry["position"] == position
        assert entry["slot"] == slot


def test_beacon_slots_are_unique_and_cover_0_to_4(beacons):
    slots = sorted(entry["slot"] for entry in beacons["beacons"])
    assert slots == [0, 1, 2, 3, 4]


def test_beacon_positions_are_xyz_numbers(beacons):
    for entry in beacons["beacons"]:
        assert len(entry["position"]) == 3
        assert all(isinstance(v, (int, float)) for v in entry["position"])


# Brief section 4.6 chirp config: the single source of truth shared with the
# firmware, the app, and the tools.

CHIRP_DEFAULTS = {
    "f_lo": 2000,
    "f_hi": 4500,
    "length_ms": 12,
    "slot_ms": 50,
    "n_slots": 6,
    "marker": {"beacon": "B1", "direction": "down"},
    "others_direction": "up",
    "version": 1,
}


def test_chirp_config_matches_the_brief(chirp):
    assert chirp == CHIRP_DEFAULTS


def test_params_chirp_block_matches_chirp_json(params, chirp):
    # Section 4.6: chirp.json is the single source of truth. The embedded copy
    # inside locator_params.json must never drift from it.
    assert params["chirp"] == chirp


# Brief section 8.6 defaults.


def test_params_fs(params):
    assert params["fs"] == 48000


def test_params_solver_gates(params):
    assert params["gate_ms"] == 3.0
    assert params["lookback_ms"] == 2.0
    assert params["snr_min"] == 8.0
    assert params["snr_acquire"] == 10.0
    assert params["resid_max_ms"] == 0.30
    assert params["resid_ok_ms"] == 0.15


def test_params_height_priors(params):
    assert params["height_prior"]["hand"] == {"mean_m": 1.25, "sigma_m": 0.25}
    assert params["height_prior"]["pocket"] == {"mean_m": 1.30, "sigma_m": 0.20}


def test_params_ear_offsets(params):
    assert params["ear_offset_m"]["hand"] == [0.0, 0.0, 0.35]
    assert params["ear_offset_m"]["pocket"] == [0.0, 0.0, 0.30]


def test_params_kalman(params):
    assert params["kalman"]["accel_sigma_mps2"] == 1.5
    assert params["kalman"]["meas_sigma_ok_m"] == 0.05
    assert params["kalman"]["meas_sigma_degraded_m"] == 0.15


def test_params_lost_timeout_and_temperature(params):
    assert params["lost_timeout_s"] == 1.5
    assert params["air_temperature_c"] == 22.0


def test_params_mic_audio_defaults(params):
    assert params["mic_audio"] == {"sample_rate": 16000, "chunk_ms": 40}


def test_params_hub_defaults(params):
    # Section 8.6: empty URL/token, auth mode query. Today's real hub has no
    # token auth at all — see contracts/README.md.
    assert params["hub"] == {"url": "", "token": "", "auth_mode": "query"}
