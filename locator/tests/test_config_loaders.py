"""Config loader tests: the import rule and chirp config (brief 2.2, 4.6)."""

import json
from pathlib import Path

import pytest

from tools.common.config import (
    DEFAULT_BEACONS,
    ConfigError,
    beacons_from_dict,
    load_beacon_config,
    load_chirp_config,
)
from tools.common.constants import speed_of_sound

BARE_BEACONS = {
    "beacons": [
        {"id": "B1", "position": [-1.5, 1.5, 1.8], "slot": 0},
        {"id": "B2", "position": [1.5, 1.5, 0.3], "slot": 1},
    ]
}

SPACE_JSON = {
    "version": 2,
    "note": "the other repo owns the rest of this file",
    "spots": {
        "cupboard_salt": [-0.08, 1.5, 1.0],
        "pill_box": [0.0, -1.5, 0.8],
    },
    "beacons": BARE_BEACONS["beacons"],
}


def write_json(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_default_beacons_match_brief_2_2() -> None:
    assert [(b.id, b.position, b.slot) for b in DEFAULT_BEACONS] == [
        ("B1", (-1.5, 1.5, 1.8), 0),
        ("B2", (1.5, 1.5, 0.3), 1),
        ("B3", (1.5, -1.5, 1.8), 2),
        ("B4", (-1.5, -1.5, 0.3), 3),
        ("B5", (-1.8, 0.0, 1.0), 4),
    ]


def test_bare_beacon_file_loads(tmp_path: Path) -> None:
    path = write_json(tmp_path, "beacons.json", BARE_BEACONS)
    beacons = load_beacon_config(path)
    assert [b.id for b in beacons] == ["B1", "B2"]
    assert beacons[0].position == (-1.5, 1.5, 1.8)


def test_full_space_json_imports_only_beacons(tmp_path: Path) -> None:
    """The import rule: read only the beacons key, ignore everything else."""
    path = write_json(tmp_path, "space.json", SPACE_JSON)
    from_space = load_beacon_config(path)
    from_bare = load_beacon_config(write_json(tmp_path, "bare.json", BARE_BEACONS))
    assert from_space == from_bare


def test_space_json_without_beacons_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path, "space.json", {"version": 2, "spots": {}})
    with pytest.raises(ConfigError, match="beacons"):
        load_beacon_config(path)


@pytest.mark.parametrize(
    "entry",
    [
        {"position": [0, 0, 0], "slot": 0},  # missing id
        {"id": "B1", "position": [0, 0], "slot": 0},  # position too short
        {"id": "B1", "position": [0, 0, "x"], "slot": 0},  # non-numeric
        {"id": "B1", "position": [0, 0, 0]},  # missing slot
        {"id": "B1", "position": [0, 0, 0], "slot": -1},
        {"id": "B1", "position": [0, 0, 0], "slot": True},  # bool is not a slot
    ],
)
def test_invalid_beacon_entries_rejected(entry: dict) -> None:
    with pytest.raises(ConfigError):
        beacons_from_dict({"beacons": [entry]})


def test_duplicate_ids_and_slots_rejected() -> None:
    dup_id = {"beacons": [
        {"id": "B1", "position": [0, 0, 0], "slot": 0},
        {"id": "B1", "position": [1, 0, 0], "slot": 1},
    ]}
    with pytest.raises(ConfigError, match="duplicate beacon id"):
        beacons_from_dict(dup_id)
    dup_slot = {"beacons": [
        {"id": "B1", "position": [0, 0, 0], "slot": 0},
        {"id": "B2", "position": [1, 0, 0], "slot": 0},
    ]}
    with pytest.raises(ConfigError, match="duplicate slot"):
        beacons_from_dict(dup_slot)


def test_empty_beacons_rejected() -> None:
    with pytest.raises(ConfigError):
        beacons_from_dict({"beacons": []})


def test_beacons_sorted_by_slot(tmp_path: Path) -> None:
    path = write_json(tmp_path, "beacons.json", {"beacons": [
        {"id": "B9", "position": [0, 0, 0], "slot": 2},
        {"id": "B7", "position": [1, 0, 0], "slot": 0},
    ]})
    assert [b.id for b in load_beacon_config(path)] == ["B7", "B9"]


def test_default_chirp_config_matches_brief_4_6() -> None:
    cfg = load_chirp_config(None)
    assert cfg.to_dict() == {
        "f_lo": 2000.0,
        "f_hi": 4500.0,
        "length_ms": 12.0,
        "slot_ms": 50.0,
        "n_slots": 6,
        "marker": {"beacon": "B1", "direction": "down"},
        "others_direction": "up",
        "version": 1,
    }


def test_repo_chirp_json_matches_defaults() -> None:
    repo_chirp = Path(__file__).resolve().parents[1] / "config" / "chirp.json"
    assert load_chirp_config(repo_chirp).to_dict() == load_chirp_config(None).to_dict()


def test_chirp_config_wrapped_under_chirp_key(tmp_path: Path) -> None:
    path = write_json(tmp_path, "params.json", {
        "version": 1,
        "fs": 48000,
        "chirp": {"f_lo": 2100.0, "f_hi": 4600.0},
        "gate_ms": 3.0,
    })
    cfg = load_chirp_config(path)
    assert (cfg.f_lo, cfg.f_hi) == (2100.0, 4600.0)
    assert cfg.slot_ms == 50.0  # unspecified keys keep the defaults


def test_chirp_config_unknown_key_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path, "chirp.json", {"f_lo": 2000.0, "f_low": 2000.0})
    with pytest.raises(ConfigError, match="unknown chirp config key"):
        load_chirp_config(path)


def test_chirp_config_invalid_range_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path, "chirp.json", {"f_lo": 2000.0, "f_hi": 2500.0})
    with pytest.raises(ConfigError, match="below minimum"):
        load_chirp_config(path)


def test_invalid_json_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_chirp_config(path)


def test_speed_of_sound_formula() -> None:
    assert speed_of_sound(22.0) == pytest.approx(344.632)
    assert speed_of_sound(0.0) == pytest.approx(331.3)
    assert speed_of_sound(30.0) == pytest.approx(331.3 + 0.606 * 30.0)
