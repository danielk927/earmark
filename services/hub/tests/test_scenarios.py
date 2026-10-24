"""Every scenario through the simulator + state engine on a virtual clock (brief 5.A acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest
from earmark_contracts import ObjectState, Pickup, Transcript, UnknownTag

from conftest import ROOT, run_scenario


def pickups(outputs):
    return [(o.object_id, o.from_spot) for o in outputs if isinstance(o, Pickup)]


def states_of(outputs, oid):
    return [o for o in outputs if isinstance(o, ObjectState) and o.object_id == oid]


def unknowns(outputs):
    return [o for o in outputs if isinstance(o, UnknownTag)]


async def test_normal_pickup(space, objects):
    eng, out, _ = await run_scenario("normal_pickup", space, objects)
    assert pickups(out) == [("sugar", 3)]
    sugar = states_of(out, "sugar")
    assert [s.status for s in sugar] == ["on_spot", "held", "on_spot"]
    final = eng.state("sugar")
    assert final.status == "on_spot" and final.location.spot == 3 and final.precision == "exact"
    assert final.location.position == [0.16, 0.58, 0.0]


async def test_wrong_jar(space, objects):
    eng, out, others = await run_scenario("wrong_jar", space, objects)
    assert pickups(out) == [("salt", 2)]
    assert eng.state("salt").status == "on_spot" and eng.state("salt").location.spot == 2
    assert [m.text for m in others if isinstance(m, Transcript)] == ["Where's the sugar?"]


async def test_moved_item(space, objects):
    eng, out, _ = await run_scenario("moved_item", space, objects)
    assert pickups(out) == [("sugar", 3)]
    sugar = eng.state("sugar")
    assert sugar.status == "on_spot" and sugar.location.spot == 1 and sugar.home_spot == 3
    assert sugar.location.position == [-0.42, 0.42, 0.0]
    held = [s for s in states_of(out, "sugar") if s.status == "held"][0]
    assert held.location.spot is None and held.location.position is None and held.precision == "none"


async def test_flicker(space, objects):
    eng, out, _ = await run_scenario("flicker", space, objects)
    assert pickups(out) == []
    assert unknowns(out) == []
    states = [o for o in out if isinstance(o, ObjectState)]
    # Only the initial placements of salt, sugar and bp_meds; nothing after.
    assert sorted(s.object_id for s in states) == ["bp_meds", "salt", "sugar"]
    assert all(s.status == "on_spot" for s in states)
    assert max(s.t for s in states) == min(s.t for s in states)


async def test_missed_dose(space, objects):
    eng, out, _ = await run_scenario("missed_dose", space, objects)
    assert ("bp_meds", 4) not in pickups(out)
    assert pickups(out) == []
    assert eng.state("bp_meds").status == "on_spot" and eng.state("bp_meds").location.spot == 4


async def test_roaming_keys(space, objects):
    eng, out, _ = await run_scenario("roaming_keys", space, objects)
    keys = states_of(out, "keys")
    assert [(s.status, s.location.distance_class) for s in keys] == [
        ("roaming", "far"), ("roaming", "mid"), ("roaming", "near")]
    assert all(s.precision == "proximity" and s.location.near == "hub" for s in keys)
    assert keys[0].location.position == [0, 0.6, 0]
    assert pickups(out) == []


async def test_roaming_keys_start_missing(space, objects):
    from earmark_hub.state import StateEngine

    assert StateEngine(space, objects).state("keys").status == "missing"


async def test_label_new_item(space, objects):
    eng, out, others = await run_scenario("label_new_item", space, objects)
    u = unknowns(out)
    assert len(u) == 1 and u[0].spot == 1 and u[0].tag == "04A1B2C3D4E5FF"
    assert pickups(out) == []
    assert [m.text for m in others] == ["This is honey."]


async def test_full_demo(space, objects):
    eng, out, others = await run_scenario("full_demo", space, objects)
    assert pickups(out) == [("salt", 2), ("sugar", 3), ("sugar", 1)]
    assert unknowns(out) == []
    assert eng.state("sugar").location.spot == 3
    assert eng.state("keys").location.distance_class == "near"
    assert len([m for m in others if isinstance(m, Transcript)]) == 4


@pytest.mark.parametrize("path", sorted((ROOT / "scenarios").glob("*.jsonl")), ids=lambda p: p.stem)
async def test_every_scenario_runs(path: Path, space, objects):
    eng, out, _ = await run_scenario(path.stem, space, objects)
    assert len(eng.states()) == len(objects)
