"""State engine: debounce, transitions, position resolution, unknown tags, registry changes."""
from __future__ import annotations

from earmark_contracts import DetectionEvent, ObjectState, Pickup, RegistryObject, UnknownTag

from conftest import SALT, SUGAR, T0, UNKNOWN, fob, read
from earmark_hub.state import Placed, Removed, StateEngine, Stored


def feed(engine: StateEngine, *events):
    out = []
    for ev in events:
        out.extend(engine.handle(ev))
    return out


def of(out, cls):
    return [o for o in out if isinstance(o, cls)]


def place_sugar(engine, spot=3, t=0.0):
    return feed(engine, read(spot, SUGAR, t), read(spot, SUGAR, t + 0.5))


# ---------------------------------------------------------------- debounce


def test_placement_needs_two_consecutive_reads(engine):
    out = feed(engine, read(3, SUGAR, 0.0))
    assert out == [] and engine.state("sugar").status == "missing"
    out = feed(engine, read(3, SUGAR, 0.5))
    assert [o.status for o in of(out, ObjectState)] == ["on_spot"]
    assert of(out, Placed)[0].spot == 3


def test_reads_must_be_consecutive(engine):
    out = feed(engine, read(3, SUGAR, 0.0), read(3, None, 0.5), read(3, SUGAR, 1.0))
    assert of(out, ObjectState) == []
    out = feed(engine, read(3, SUGAR, 1.5))
    assert engine.state("sugar").status == "on_spot"


def test_one_stray_read_does_nothing(engine):
    place_sugar(engine)
    out = feed(engine, read(1, SALT, 1.0), read(1, None, 1.5), read(3, SALT, 2.0), read(3, SUGAR, 2.5),
               read(3, SUGAR, 3.0))
    assert out == []
    assert engine.state("sugar").location.spot == 3
    assert engine.state("salt").status == "missing"


def test_removal_needs_continuous_absence(engine):
    place_sugar(engine)
    out = feed(engine, read(3, None, 1.0), read(3, None, 1.5), read(3, None, 2.0))
    assert of(out, Pickup) == []
    out = feed(engine, read(3, None, 2.5))  # 1.5 s after the first absent read
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("sugar", 3)]
    st = engine.state("sugar")
    assert st.status == "held" and st.precision == "none" and st.location.spot is None
    assert st.location.position is None and st.last_seen_t == T0 + 1.0  # lift time


def test_flicker_never_removes(engine):
    place_sugar(engine)
    events = []
    for k in range(2, 40):
        events.append(read(3, None if k % 2 else SUGAR, k * 0.5))
    out = feed(engine, *events)
    assert of(out, Pickup) == [] and of(out, ObjectState) == []


def test_tick_removes_when_reads_stop(engine):
    place_sugar(engine)
    feed(engine, read(3, None, 1.0))  # one EMPTY, then the reader goes quiet
    assert of(engine.tick(T0 + 2.4), Pickup) == []
    out = engine.tick(T0 + 2.5)
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("sugar", 3)]


def test_silence_alone_is_not_a_removal(engine):
    place_sugar(engine)
    assert engine.tick(T0 + 60) == []
    assert engine.state("sugar").status == "on_spot"


def test_removal_s_is_configurable(space, objects):
    eng = StateEngine(space, objects, removal_s=0.5)
    place_sugar(eng)
    out = feed(eng, read(3, None, 1.0), read(3, None, 1.5))
    assert len(of(out, Pickup)) == 1


def test_kind_removed_with_last_tag_counts_as_empty(engine):
    place_sugar(engine)
    gone = DetectionEvent(source="nfc", tag=SUGAR, kind="removed", where={"spot": 3}, precision="exact",
                          rssi=None, t=T0 + 1.0)
    feed(engine, gone)
    assert len(of(engine.tick(T0 + 2.5), Pickup)) == 1


def test_placed_kind_confirms_immediately(engine):
    ev = DetectionEvent(source="camera", tag=SUGAR, kind="placed", where={"spot": 1}, precision="exact",
                        rssi=None, t=T0)
    feed(engine, ev)
    assert engine.state("sugar").location.spot == 1


def test_lowercase_tag_matches_registry(engine):
    feed(engine, read(3, SUGAR.lower(), 0.0), read(3, SUGAR.lower(), 0.5))
    assert engine.state("sugar").status == "on_spot"


# ---------------------------------------------------------------- transitions


def test_put_back_after_pickup(engine):
    place_sugar(engine)
    feed(engine, *[read(3, None, 1.0 + k * 0.5) for k in range(4)])
    out = feed(engine, read(3, SUGAR, 5.0), read(3, SUGAR, 5.5))
    assert [o.status for o in of(out, ObjectState)] == ["on_spot"]
    assert engine.state("sugar").last_seen_t == T0 + 5.5


def test_move_to_new_spot_implies_removal_from_old(engine):
    place_sugar(engine)
    # Moved faster than the removal window: spot 1 confirms while spot 3 still records it.
    out = feed(engine, read(3, None, 1.0), read(1, SUGAR, 1.0), read(1, SUGAR, 1.5))
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("sugar", 3)]
    assert [type(o).__name__ for o in out if not isinstance(o, ObjectState)] == ["Removed", "Pickup", "Placed"]
    st = engine.state("sugar")
    assert st.status == "on_spot" and st.location.spot == 1 and st.home_spot == 3
    # The old spot no longer claims the sugar, so later EMPTY reads there do nothing.
    assert of(feed(engine, *[read(3, None, 2.0 + k * 0.5) for k in range(6)]), Pickup) == []


def test_swap_on_same_spot_removes_the_old_tag_first(engine):
    place_sugar(engine)
    out = feed(engine, read(3, SALT, 1.0), read(3, SALT, 1.5))
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("sugar", 3)]
    assert engine.state("salt").location.spot == 3


def test_pickup_from_any_spot(engine):
    place_sugar(engine, spot=1)
    out = feed(engine, *[read(1, None, 1.0 + k * 0.5) for k in range(4)])
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("sugar", 1)]


def test_state_update_only_on_change(engine):
    out = place_sugar(engine) + feed(engine, *[read(3, SUGAR, 1.0 + k * 0.5) for k in range(10)])
    assert len(of(out, ObjectState)) == 1


def test_engine_time_never_goes_backwards(engine):
    place_sugar(engine, t=10.0)
    feed(engine, read(3, None, 11.0))
    out = feed(engine, read(2, SALT, 5.0))  # stale timestamp: processed at the engine's current time
    assert out == [] and engine.now == T0 + 11.0


# ---------------------------------------------------------------- positions


def test_spot_resolves_to_space_position(engine):
    place_sugar(engine, spot=4)
    st = engine.state("sugar")
    assert st.location.position == [0.42, 0.42, 0.0] and st.precision == "exact"


def test_unknown_spot_number_has_no_position(engine):
    place_sugar(engine, spot=9)
    st = engine.state("sugar")
    assert st.status == "on_spot" and st.location.spot == 9 and st.location.position is None


def test_area_and_position_events(engine):
    area = DetectionEvent(source="camera", tag=SUGAR, kind="seen", where={"area": "kitchen_counter"},
                          precision="area", rssi=None, t=T0)
    feed(engine, area)
    st = engine.state("sugar")
    assert st.status == "roaming" and st.location.area == "kitchen_counter" and st.location.position == [0, 0.6, 0]
    pos = DetectionEvent(source="camera", tag=SUGAR, kind="seen", where={"position": [0.1, 0.2, 0.3]},
                         precision="exact", rssi=None, t=T0 + 1)
    feed(engine, pos)
    assert engine.state("sugar").location.position == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------- BLE states


def test_ble_roaming_then_lost_keeps_location(engine):
    out = feed(engine, fob("far", 0.0), fob("far", 1.0), fob("mid", 2.0))
    assert [o.location.distance_class for o in of(out, ObjectState)] == ["far", "mid"]
    assert engine.state("keys").last_seen_t == T0 + 2.0
    feed(engine, fob(None, 5.0))
    st = engine.state("keys")
    assert st.status == "missing" and st.precision == "none"
    assert st.location.near == "hub" and st.location.distance_class == "mid" and st.location.position == [0, 0.6, 0]
    assert st.last_seen_t == T0 + 2.0


def test_never_seen_is_missing(engine):
    st = engine.state("keys")
    assert st.status == "missing" and st.last_seen_t is None and st.location.position is None


def test_proximity_does_not_override_a_spot(space, objects):
    objs = [o.model_copy(update={"fob_id": "fob_sugar"}) if o.object_id == "sugar" else o for o in objects]
    eng = StateEngine(space, objs)
    place_sugar(eng)
    feed(eng, fob("far", 1.0, tag="fob_sugar"), fob(None, 2.0, tag="fob_sugar"))
    assert eng.state("sugar").status == "on_spot"


def test_unregistered_fob_is_ignored(engine):
    assert feed(engine, fob("near", 0.0, tag="fob_unknown")) == []


# ---------------------------------------------------------------- unknown tags


def test_unknown_tag_once_per_placement(engine):
    out = feed(engine, *[read(1, UNKNOWN, k * 0.5) for k in range(10)])
    assert [(u.tag, u.spot) for u in of(out, UnknownTag)] == [(UNKNOWN, 1)]
    assert of(out, Pickup) == []
    out = feed(engine, *[read(1, None, 5.0 + k * 0.5) for k in range(4)])
    assert of(out, Pickup) == [] and of(out, Removed)[0].object_id is None
    out = feed(engine, read(1, UNKNOWN, 8.0), read(1, UNKNOWN, 8.5))
    assert len(of(out, UnknownTag)) == 1


def test_empty_is_never_a_tag(engine):
    seen_empty = DetectionEvent(source="nfc", tag="EMPTY", kind="seen", where={"spot": 1}, precision="exact",
                                rssi=None, t=T0)
    out = feed(engine, seen_empty, seen_empty.model_copy(update={"t": T0 + 0.5}), read(1, None, 1.0))
    assert of(out, UnknownTag) == [] and of(out, Placed) == []


# ---------------------------------------------------------------- registry changes / reset


def test_label_resolves_tag_already_on_a_spot(engine, objects):
    feed(engine, read(1, UNKNOWN, 0.0), read(1, UNKNOWN, 0.5))
    honey = RegistryObject(object_id="honey", name="honey", aliases=[], notes="", description="", tag=UNKNOWN,
                           home_spot=1, is_medication=False, fob_id=None)
    out = engine.set_objects([*objects, honey])
    st = [o for o in of(out, ObjectState) if o.object_id == "honey"]
    assert len(st) == 1 and st[0].status == "on_spot" and st[0].location.spot == 1 and st[0].home_spot == 1
    out = feed(engine, *[read(1, None, 2.0 + k * 0.5) for k in range(4)])
    assert [(p.object_id, p.from_spot) for p in of(out, Pickup)] == [("honey", 1)]


def test_registry_change_updates_home_spot_and_drops_removed_objects(engine, objects):
    changed = [o.model_copy(update={"home_spot": 1}) if o.object_id == "sugar" else o
               for o in objects if o.object_id != "pepper"]
    out = engine.set_objects(changed)
    assert [(o.object_id, o.home_spot) for o in of(out, ObjectState)] == [("sugar", 1)]
    assert "pepper" not in {s.object_id for s in engine.states()}


def test_reset_returns_to_startup_state(engine):
    place_sugar(engine)
    out = engine.reset(now=T0 + 3.0)
    assert [(o.object_id, o.status, o.t) for o in of(out, ObjectState)] == [("sugar", "missing", T0 + 3.0)]
    assert all(s.status == "missing" for s in engine.states())
    out = place_sugar(engine, t=5.0)
    assert engine.state("sugar").status == "on_spot" and of(out, Pickup) == []


# ---------------------------------------------------------------- named places (said by the user)


def test_place_in_area_moves_the_item_there(engine):
    place_sugar(engine)
    out = engine.place_in_area("sugar", "drawer", T0 + 5)
    assert [(s.object_id, s.area) for s in of(out, Stored)] == [("sugar", "drawer")]
    st = engine.state("sugar")
    assert (st.status, st.precision, st.location.area, st.location.spot) == ("roaming", "area", "drawer", None)
    assert st.location.position == engine.space.area_position("drawer")


def test_place_in_area_twice_still_logs_both(engine):
    engine.place_in_area("salt", "bag", T0 + 1)
    out = engine.place_in_area("salt", "bag", T0 + 2)
    assert len(of(out, Stored)) == 1 and of(out, ObjectState) == []


def test_place_in_area_ignores_unknown_item_or_place(engine):
    assert engine.place_in_area("nope", "drawer", T0) == []
    assert engine.place_in_area("sugar", "attic", T0) == []
    assert engine.state("sugar").status == "missing"


def test_place_at_position_keeps_the_exact_spot(engine):
    out = engine.place_at_position("keys", [0.8, -0.4, 1.0], T0 + 3)
    assert [(s.object_id, s.area, s.position) for s in of(out, Stored)] == [("keys", None, [0.8, -0.4, 1.0])]
    st = engine.state("keys")
    assert (st.status, st.precision, st.location.area) == ("roaming", "exact", None)
    assert st.location.position == [0.8, -0.4, 1.0]
    assert engine.place_at_position("nope", [0, 0, 0], T0) == []
