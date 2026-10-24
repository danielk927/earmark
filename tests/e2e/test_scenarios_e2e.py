"""Brief Phase 2.3: scripted end-to-end checks across real processes."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import of, spoken

ROOT = Path(__file__).resolve().parents[2]
SPOTS = {s["spot"]: s["position"] for s in json.loads((ROOT / "config" / "space.json").read_text())["spots"]}


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


def _dotenv(name: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or None
    return None


def test_put_in_place(stack):
    msgs = run(stack, "put_in_place")
    assert [(m["object_id"], m["area"]) for m in of(msgs, "place_item")] == [("keys", "drawer"), ("keys", "bag")]
    keys = [m for m in of(msgs, "state_update") if m["object_id"] == "keys"]
    assert [m["location"]["area"] for m in keys] == ["drawer", "bag"]
    text = spoken(msgs)
    assert "Got it, the keys are in the drawer." in text
    assert any(t.startswith("The keys are near the drawer.") for t in text)
    assert any(t.startswith("The keys are near the bag, noted at") and "Before that, they were near the drawer" in t
               for t in text)
