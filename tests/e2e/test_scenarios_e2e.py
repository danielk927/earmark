"""Brief Phase 2.3: scripted end-to-end checks across real processes."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import of, spoken

ROOT = Path(__file__).resolve().parents[2]
PINNED_SPACE = ROOT / "services" / "hub" / "tests" / "fixtures" / "space.json"  # not config/space.json: re-measured
SPOTS = {s["spot"]: s["position"] for s in json.loads(PINNED_SPACE.read_text())["spots"]}


def run(stack, scenario, speed=3.0):
    return asyncio.run(stack.run_scenario(scenario, speed))


def test_wrong_jar(stack):
    msgs = run(stack, "wrong_jar")
    guides = of(msgs, "guide_start")
    assert guides and guides[0]["object_id"] == "sugar"
    assert guides[0]["target_position"] == SPOTS[3]
    assert [m["object_id"] for m in of(msgs, "pickup")] == ["salt"]
    results = of(msgs, "pickup_result")
    assert results and results[0] == {**results[0], "expected": "sugar", "actual": "salt", "correct": False}
    text = " ".join(spoken(msgs))
    assert "one spot to your right" in text
    assert "That's the salt. The sugar is one spot to your right." in text
    assert not of(msgs, "guide_stop"), "a wrong pick must not end guidance"


def test_moved_item(stack):
    msgs = run(stack, "moved_item")
    assert [(m["object_id"], m["from_spot"]) for m in of(msgs, "pickup")] == [("sugar", 3)]
    sugar = [m for m in of(msgs, "state_update") if m["object_id"] == "sugar"][-1]
    assert sugar["status"] == "on_spot" and sugar["location"]["spot"] == 1 and sugar["home_spot"] == 3
    guides = of(msgs, "guide_start")
    assert guides and guides[-1]["target_position"] == SPOTS[1]
    assert any("ten o'clock" in t for t in spoken(msgs))


def test_roaming_keys(stack):
    msgs = run(stack, "roaming_keys")
    chirps = of(msgs, "chirp")
    assert chirps and chirps[0]["fob_id"] == "fob_keys" and chirps[0]["action"] == "start"
    keys = [m for m in of(msgs, "state_update") if m["object_id"] == "keys"]
    classes = [m["location"]["distance_class"] for m in keys if m["status"] == "roaming"]
    assert classes[0] == "far" and classes[-1] == "near"
    assert any("keys" in t and "beep" in t for t in spoken(msgs))
    assert not of(msgs, "guide_start"), "proximity items get a chirp, not a spatial ping"


def test_missed_dose(stack):
    msgs = run(stack, "missed_dose")
    assert not [m for m in of(msgs, "pickup") if m["object_id"] == "bp_meds"]
    meds = [m for m in of(msgs, "state_update") if m["object_id"] == "bp_meds"]
    assert meds and meds[-1]["status"] == "on_spot" and meds[-1]["location"]["spot"] == 4


def test_missed_dose_in_convex():
    """The seeded missed dose is reported by Convex (skipped when no local deployment is running)."""
    site = os.environ.get("CONVEX_SITE_URL") or _dotenv("CONVEX_SITE_URL")
    secret = os.environ.get("EARMARK_READ_SECRET") or _dotenv("EARMARK_READ_SECRET")
    if not site or not secret:
        pytest.skip("no Convex deployment configured")
    statuses = []
    for back in range(0, 3):
        day = (date.today() - timedelta(days=back)).isoformat()
        req = urllib.request.Request(f"{site}/api/adherence?date={day}", headers={"X-Earmark-Secret": secret})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                statuses += [d["status"] for d in json.load(r)["doses"]]
        except OSError:
            pytest.skip("Convex deployment not reachable")
    assert statuses.count("missed") == 1


def test_full_demo(stack):
    msgs = run(stack, "full_demo", speed=4.0)
    assert [(m["object_id"], m["from_spot"]) for m in of(msgs, "pickup")] == [("salt", 2), ("sugar", 3), ("sugar", 1)]
    assert [m["target_position"] for m in of(msgs, "guide_start")][:2] == [SPOTS[3], SPOTS[1]]
    assert [m["correct"] for m in of(msgs, "pickup_result")] == [False, True, True]
    text = spoken(msgs)
    assert "That's the salt. The sugar is one spot to your right." in text
    assert text.count("Got it, that's the sugar.") == 2
    assert any("salt" in t and "pepper" in t and t.endswith("?") for t in text)
    assert of(msgs, "chirp")


def _collapse(items: list) -> list:
    return [x for i, x in enumerate(items) if i == 0 or x != items[i - 1]]


def test_uwb_walk(uwb_stack):
    """UWB-PRD 12.1 e2e: walk from the start mark (tracked, meters phrasing), freeze at the counter
    ("You're at the counter."), then the unchanged wrong-jar correction and "Got it" confirmation.
    Replayed at 1x: the hub's still/freshness/speed-gate timing is wall-clock."""
    msgs = run(uwb_stack, "uwb_walk", speed=1.0)
    uwb = uwb_stack.cfg["uwb"]

    poses = of(msgs, "listener_pose")
    modes = _collapse([p["mode"] for p in poses])
    assert modes in (["tracked", "frozen"], ["fixed", "tracked", "frozen"]), modes
    tracked = [p for p in poses if p["mode"] == "tracked"]
    frozen = [p for p in poses if p["mode"] == "frozen"]
    assert {p["source"] for p in tracked + frozen} == {"sim"}
    assert tracked[0]["position"][1] < -2.5, "tracking starts on the start mark, ~3 m back"
    span = tracked[-1]["t"] - tracked[0]["t"]
    assert len(tracked) / span >= 5.0, "listener_pose rate while tracked must be >= 5 Hz"
    landing = frozen[0]["position"]
    assert math.dist(landing[:2], uwb["counter_ref"]) <= 0.35, f"froze away from the origin: {landing}"

    # The answer to "Where's the sugar?" is given on the start mark: plain words and meters.
    text = spoken(msgs)
    answer = next(t for t in text if t.startswith("The sugar is"))
    assert answer == "The sugar is ahead of you, about 3 and a half meters.", answer
    # Freezing during guidance announces itself once, then the clock face.
    at_counter = [t for t in text if t.startswith("You're at the counter.")]
    assert len(at_counter) == 1, at_counter
    assert re.fullmatch(r"You're at the counter\. The sugar is at your (twelve|one) o'clock, [a-z' ]+\.",
                        at_counter[0]), at_counter[0]
    idx = {id(m): i for i, m in enumerate(msgs)}
    first_frozen = idx[id(frozen[0])]
    said = [(i, m.get("text", "")) for i, m in enumerate(msgs) if m["type"] in ("speak_text", "speak_cached", "speak")]
    assert max(i for i, t in said if t == answer) < first_frozen, "meters answer must precede the freeze"
    assert min(i for i, t in said if t == at_counter[0]) > first_frozen

    # The existing wrong-jar flow, unchanged by UWB.
    guides = of(msgs, "guide_start")
    assert guides and guides[0]["object_id"] == "sugar" and guides[0]["target_position"] == SPOTS[3]
    pickups = of(msgs, "pickup")
    assert [(m["object_id"], m["from_spot"]) for m in pickups] == [("salt", 2), ("sugar", 3)]
    assert [m["correct"] for m in of(msgs, "pickup_result")] == [False, True]
    assert "That's the salt. The sugar is one spot to your right." in text
    assert "Got it, that's the sugar." in text
    assert [m["reason"] for m in of(msgs, "guide_stop")] == ["found"]

    # NFC re-anchor: from the salt pickup on, the frozen listener is within reach of spot 2.
    after = [p for p in frozen if idx[id(p)] > idx[id(pickups[0])]]
    assert after and all(math.dist(p["position"][:2], SPOTS[2][:2]) <= uwb["reach_max_m"] + 1e-3 for p in after)


def _dotenv(name: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or None
    return None


def test_put_in_place(stack):
    msgs = run(stack, "put_in_place", speed=1.0)
    assert [(m["object_id"], m["area"]) for m in of(msgs, "place_item")] == [("keys", "drawer"), ("keys", "bag")]
    keys = [m for m in of(msgs, "state_update") if m["object_id"] == "keys"]
    assert [m["location"]["area"] for m in keys] == ["drawer", "bag"]
    text = spoken(msgs)
    assert "Got it, the keys are in the drawer." in text
    assert any(t.startswith("The keys are in the drawer, at your") for t in text)
    assert any(t.startswith("The keys are near the bag, noted at") and "Before that, they were near the drawer" in t
               for t in text)


def test_put_here(stack):
    msgs = run(stack, "put_here", speed=1.0)
    [placed] = of(msgs, "place_item")
    assert placed["object_id"] == "keys" and placed["position"] == [0.8, -0.4, 1.0]
    keys = [m for m in of(msgs, "state_update") if m["object_id"] == "keys"]
    assert keys[-1]["precision"] == "exact" and keys[-1]["location"]["position"] == [0.8, -0.4, 1.0]
    [guide] = of(msgs, "guide_start")
    assert guide["object_id"] == "keys" and guide["target_position"] == [0.8, -0.4, 1.0]
    assert "Got it, I'll remember where you left the keys." in spoken(msgs)
    assert any(t.startswith("The keys are at your four o'clock") for t in spoken(msgs))
