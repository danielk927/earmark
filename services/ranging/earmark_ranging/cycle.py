"""One round of chirps: which chirp is whose, and what distances that gives."""
from __future__ import annotations

import math

from .chirp import direction_for_slot
from .detect import Event
from .solve import pair_distance

N_SLOTS = 6  # slot 0 is the user's phone, slots 1 to 5 are the fixed phones


def assign_slots(
    events: list[Event], own_slot: int, gap_s: float, near_s: float | None = None, own_pool: list[Event] | None = None
) -> dict[int, float]:
    """Who chirped when, on one phone's own recording.

    The phone's own chirp is the loudest by far, so it is the reference. Every other chirp is a whole number of
    gaps away from it, and rising/falling shapes alternate by slot, which settles any doubt between neighbours.
    `own_pool` limits which chirps may be the phone's own (the ones near when it was told to play).
    Returns slot -> time (seconds on this phone's recording).
    """
    if not events:
        return {}
    own_dir = direction_for_slot(own_slot)
    pool = [e for e in (own_pool if own_pool is not None else events) if e.shape == own_dir]
    if not pool:
        return {}
    own = max(pool, key=lambda e: e.score)
    out: dict[int, tuple[float, float]] = {own_slot: (own.t, own.score)}
    reach = near_s if near_s is not None else (N_SLOTS + 0.5) * gap_s
    for e in events:
        if e is own or abs(e.t - own.t) > reach:
            continue
        rel = (e.t - own.t) / gap_s
        best = None
        for off in range(math.floor(rel) - 1, math.ceil(rel) + 2):
            slot = own_slot + off
            if slot == own_slot or not 0 <= slot < N_SLOTS or direction_for_slot(slot) != e.shape:
                continue
            err = abs(off - rel)
            if err < 0.5 and (best is None or err < best[0]):
                best = (err, slot)
        if best is None:
            continue
        slot = best[1]
        if slot not in out or e.score > out[slot][1]:
            out[slot] = (e.t, e.score)
    return {s: t for s, (t, _) in out.items()}


def pair_distances(
    heard: dict[int, dict[int, float]], listener: int = 0, mic_to_speaker_m: float = 0.03
) -> dict[int, float]:
    """Distance from the listener's phone to every fixed phone that both heard each other this round."""
    me = heard.get(listener)
    if not me or listener not in me:
        return {}
    out: dict[int, float] = {}
    for slot, theirs in heard.items():
        if slot == listener or slot not in me or slot not in theirs or listener not in theirs:
            continue
        diff_me = me[slot] - me[listener]
        diff_them = theirs[listener] - theirs[slot]
        d = pair_distance(diff_me, diff_them, mic_to_speaker_m)
        if 0.05 < d < 15.0:
            out[slot] = d
    return out


def all_pair_distances(heard: dict[int, dict[int, float]], mic_to_speaker_m: float = 0.03) -> dict[tuple[int, int], float]:
    """Every pair, for checking the fixed phones against the tape measure."""
    out: dict[tuple[int, int], float] = {}
    slots = sorted(heard)
    for i, a in enumerate(slots):
        for b in slots[i + 1 :]:
            ha, hb = heard[a], heard[b]
            if a in ha and b in ha and a in hb and b in hb:
                d = pair_distance(ha[b] - ha[a], hb[a] - hb[b], mic_to_speaker_m)
                if 0.05 < d < 15.0:
                    out[(a, b)] = d
    return out
