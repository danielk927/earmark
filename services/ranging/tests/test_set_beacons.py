"""scripts/set_beacons.py: typing in tape measurements and saving them."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("set_beacons", ROOT / "scripts" / "set_beacons.py")
set_beacons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(set_beacons)


def test_numbers_and_enter_are_read_correctly():
    assert set_beacons.parse_meters("", 0.4) == 0.4
    assert set_beacons.parse_meters(" -1.25 ", 0.4) == -1.25
    assert set_beacons.parse_meters("1.2m", 0.4) == 1.2
    with pytest.raises(ValueError):
        set_beacons.parse_meters("a lot", 0.4)


def test_typed_positions_are_saved_and_the_rest_of_the_file_is_kept(tmp_path):
    path = tmp_path / "beacons.json"
    shutil.copy(ROOT / "config" / "beacons.json", path)
    before = json.loads(path.read_text())
    answers = iter(["1.2", "", "", "-1", "", "bad", "0.8", "0.6", "-0.5", "0.9"])
    # B1: x 1.2, y kept, height kept; B2: x -1, y kept, height "bad" then 0.8 ... then B3 x 0.6, y -0.5, z 0.9
    positions = set_beacons.ask_all({1: (0.0, 0.8, 0.75), 2: (0.5, -0.6, 0.75), 3: (-0.5, -0.6, 0.75)}, lambda _: next(answers))
    assert positions == {1: (1.2, 0.8, 0.75), 2: (-1.0, -0.6, 0.8), 3: (0.6, -0.5, 0.9)}
    set_beacons.save_beacons(path, positions, "2026-01-01T00:00:00")
    after = json.loads(path.read_text())
    assert [b["position"] for b in after["beacons"]] == [[1.2, 0.8, 0.75], [-1.0, -0.6, 0.8], [0.6, -0.5, 0.9]]
    assert after["room"] == before["room"] and after["setup_marks"] == before["setup_marks"]
    assert [b["label"] for b in after["beacons"]] == [b["label"] for b in before["beacons"]]
