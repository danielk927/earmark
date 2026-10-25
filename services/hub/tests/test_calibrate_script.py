"""scripts/calibrate.py: floor-frame prompts, stored tracking values, geometry check."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "calibrate.py"


def _load():
    spec = importlib.util.spec_from_file_location("calibrate_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cal = _load()


def make_space() -> dict:
    return {
        "listener": {"label": "table", "origin_note": "floor mark"},
        "spots": [{"spot": 1, "label": "left", "position": [-0.2, 0.3, 0.9]}],
        "anchors": [
            {"anchor": "uwb_1", "label": "UWB Reader/Emitter 1", "position": [-1.5, 0.0, 1.3]},
            {"anchor": "uwb_2", "label": "UWB Reader/Emitter 2", "position": [1.5, 0.0, 1.3]},
            {"anchor": "uwb_3", "label": "UWB Reader/Emitter 3", "position": [0.0, -3.0, 1.3]},
        ],
        "tracking": {"phone_z": -0.35, "head_offset_m": 0.2, "ear_z_m": 1.55, "mark_z_m": 0.9},
    }


def feed(monkeypatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def anchors_at(*pts):
    return [{"anchor": f"uwb_{i + 1}", "label": f"a{i + 1}", "position": [x, y, 1.3]} for i, (x, y) in enumerate(pts)]


def test_interactive_writes_floor_heights(monkeypatch):
    answers = [
        "", "",                      # listener label, note
        "", "", "", "95",            # spot: label, forward (keep 30), side (keep), height 95
        "y",                         # update UWB
        "0", "-150", "190",          # anchor 1: forward, side, height above floor
        "0", "150", "190",
        "-300", "0", "175",
        "160",                       # ear height
        "120",                       # phone above the floor
        "",                          # head offset (keep)
        "75",                        # table top
    ]
    feed(monkeypatch, answers)
    out = cal.calibrate(make_space())
    assert out["spots"][0]["position"] == [-0.2, 0.3, 0.95]
    assert [a["position"][2] for a in out["anchors"]] == [1.9, 1.9, 1.75]
    assert out["anchors"][2]["position"][:2] == [0.0, -3.0]
    t = out["tracking"]
    assert t["ear_z_m"] == 1.6
    assert t["phone_z"] == pytest.approx(-0.4)  # relative to the ears
    assert t["head_offset_m"] == 0.2
    assert t["mark_z_m"] == 0.75


def test_enter_keeps_current_values(monkeypatch):
    feed(monkeypatch, [""] * 6 + ["y"] + [""] * 9 + [""] * 4)
    out = cal.calibrate(make_space())
    assert out == make_space()


def test_main_writes_with_backup(monkeypatch, tmp_path):
    space_file = tmp_path / "space.json"
    space_file.write_text(json.dumps(make_space()))
    monkeypatch.setattr(cal, "SPACE", space_file)
    monkeypatch.setattr("sys.argv", ["calibrate.py", "--out", str(space_file)])
    feed(monkeypatch, [""] * 6 + ["y"] + [""] * 9 + ["170", "", "", ""] + ["y"])
    cal.main()
    assert (tmp_path / "space.json.bak").exists()
    new = json.loads(space_file.read_text())
    assert new["tracking"]["ear_z_m"] == 1.7
    assert new["tracking"]["phone_z"] == pytest.approx(-0.5)  # phone kept at 1.20 m


def test_good_triangle_has_low_hdop_and_no_warnings():
    anchors = anchors_at((-3.0, -2.0), (3.0, -2.0), (0.0, 3.5))
    area = (-0.5, 0.5, -0.5, 0.5)
    rep = cal.geometry_report(anchors, area, 1.2)
    assert rep["trio"]["max"] < 2.0
    assert all(p["bad_frac"] <= 0.2 for p in rep["pairs"].values())
    assert cal.anchor_warnings(anchors, area, 1.2) == []


def test_surrounding_triangle_crossing_pair_lines_has_no_warnings():
    # The area crosses the lines through anchor pairs (pair DOP max is large there),
    # but only a sliver of the area is affected, so nothing fires.
    anchors = anchors_at((-2.0, 1.0), (2.0, 1.0), (0.0, -3.0))
    area = (-0.5, 0.5, -1.5, 0.0)
    rep = cal.geometry_report(anchors, area, 1.2)
    assert max(p["max"] for p in rep["pairs"].values()) > 4.0
    assert all(p["bad_frac"] <= 0.2 for p in rep["pairs"].values())
    assert cal.anchor_warnings(anchors, area, 1.2) == []


def test_collinear_anchors_warn():
    # anchors strung along the y axis, walking area on the same side of all of them
    anchors = anchors_at((0.0, 1.0), (0.05, 2.0), (0.0, 3.0))
    warnings = cal.anchor_warnings(anchors, (-0.5, 0.5, -2.0, 0.0), 1.2)
    assert any(w.startswith("poor geometry near") for w in warnings)


def test_pair_nearly_in_line_warns():
    # uwb_1 and uwb_2 sit on the y axis and the area is on that axis, so without
    # uwb_3 they point the same way. uwb_3 keeps the trio fine.
    anchors = anchors_at((0.0, 2.0), (0.0, 4.0), (3.0, -0.5))
    area = (-0.1, 0.1, -1.0, 0.0)
    warnings = cal.anchor_warnings(anchors, area, 1.2)
    assert any("if uwb_3 is blocked, uwb_1 and uwb_2 are nearly in line over" in w
               and "of the walking area (worst near (" in w for w in warnings)
    assert not any(w.startswith("poor geometry") for w in warnings)


def test_trio_warning_needs_p90_above_limit():
    anchors = anchors_at((0.0, 1.0), (0.05, 2.0), (0.0, 3.0))
    rep = cal.geometry_report(anchors, (-0.5, 0.5, -2.0, 0.0), 1.2)
    assert rep["trio"]["p90"] > 2.0
    # a good layout has p90 under the limit, so no trio warning even though max >= p90
    good = cal.geometry_report(anchors_at((-3.0, -2.0), (3.0, -2.0), (0.0, 3.5)), (-0.5, 0.5, -0.5, 0.5), 1.2)
    assert good["trio"]["p90"] <= good["trio"]["max"] < 2.0


def test_missing_anchor_warning():
    assert cal.anchor_warnings(anchors_at((0, 0), (1, 1))) == ["the hub expects three anchors: uwb_1, uwb_2, uwb_3"]
    assert cal.anchor_warnings([]) == []


def test_default_area_is_shrunk_bounding_box():
    anchors = anchors_at((-2.0, 1.0), (2.0, 1.0), (0.0, -3.0))
    assert cal.default_area(anchors) == pytest.approx((-1.7, 1.7, -2.7, 0.7))
    # tiny layouts collapse to the center instead of inverting
    assert cal.default_area(anchors_at((0, 0), (0.2, 0.2), (0.1, 0.1))) == pytest.approx((0.1, 0.1, 0.1, 0.1))


def test_parse_area():
    assert cal.parse_area("-1,1,-2,0") == (-1.0, 1.0, -2.0, 0.0)
    with pytest.raises(argparse.ArgumentTypeError):
        cal.parse_area("1,-1,0,1")


def test_describe_mentions_floor_heights():
    text = cal.describe(make_space())
    assert "above the floor" in text
    assert "z=1.30 m above the floor" in text
    assert "ears 155 cm above the floor" in text
    assert "phone 120 cm above the floor (-35 cm vs the ears)" in text
    assert "table top 90 cm above the floor" in text
    assert "Walking area" in text


def test_current_space_json_describes():
    space = json.loads((ROOT / "config" / "space.json").read_text())
    assert "above the floor" in cal.describe(space)
    assert cal.describe(space, (-1.0, 1.0, -2.0, 0.0))
