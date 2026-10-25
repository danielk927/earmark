"""Where the fixed phones are: space.json's UWB anchors by default (the same phones are the sound beacons)."""
from __future__ import annotations

import json

from earmark_ranging.config import DEFAULT_BEACONS, REPO, load_anchors, load_labels


def test_default_is_the_uwb_anchors_in_space_json_anchor_n_is_beacon_n():
    space = json.loads((REPO / "config" / "space.json").read_text())
    assert DEFAULT_BEACONS.name == "space.json"
    assert load_anchors() == {int(a["anchor"].split("_")[-1]): tuple(a["position"]) for a in space["anchors"]}
    assert set(load_labels()) == set(load_anchors())


def test_a_bare_beacons_file_still_works(tmp_path):
    f = tmp_path / "beacons.json"
    f.write_text(json.dumps({"beacons": [{"id": "B2", "label": "right", "position": [1, 2, 0.75]}]}))
    assert load_anchors(f) == {2: (1.0, 2.0, 0.75)}
    assert load_labels(f) == {2: "right"}
    assert load_labels(tmp_path / "missing.json") == {}
