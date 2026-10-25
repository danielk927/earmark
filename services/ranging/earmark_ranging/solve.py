"""From the distances between the user's phone and the fixed phones, find where the user's phone is."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .chirp import SPEED_OF_SOUND_M_S as C

Z_RANGE = (0.2, 2.6)  # a held phone is never lower or higher than this, meters


def pair_distance(diff_a: float, diff_b: float, mic_to_speaker_m: float = 0.03) -> float:
    """Distance between phones A and B, with no shared clock.

    diff_a: on A's own recording, when B's chirp was heard minus when A's own chirp was heard (seconds).
    diff_b: the same on B's recording, for A's chirp minus B's own.
    The time B plays minus the time A plays cancels between the two, leaving twice the travel time.
    Each phone hears its own chirp a hair late (speaker to mic), which the last term puts back.
    """
    return 0.5 * C * (diff_a + diff_b) + mic_to_speaker_m


@dataclass(frozen=True)
class Fix:
    position: tuple[float, float, float]
    used: int  # how many fixed phones were used
    rms_m: float  # how badly the distances disagree with the answer
    dropped: tuple[str, ...] = ()


def _solve(anchors: np.ndarray, d: np.ndarray, x0: np.ndarray, z_prior: tuple[float, float] | None) -> tuple[np.ndarray, float]:
    def resid(p: np.ndarray) -> np.ndarray:
        r = np.linalg.norm(anchors - p, axis=1) - d
        if z_prior is not None:
            r = np.append(r, (p[2] - z_prior[0]) * (0.05 / z_prior[1]))
        return r

    sol = least_squares(resid, x0, method="lm" if len(d) + (z_prior is not None) >= 3 else "trf")
    rr = np.linalg.norm(anchors - sol.x, axis=1) - d
    return sol.x, float(np.sqrt(np.mean(rr**2)))


def locate(
    anchors: dict[str, tuple[float, float, float]],
    distances: dict[str, float],
    start: tuple[float, float, float] | None = None,
    z_prior: tuple[float, float] | None = (1.25, 0.25),
    max_rms_m: float = 0.25,
) -> Fix | None:
    """Best position for the phone given its distance to each fixed phone, or None if it cannot be trusted.

    With only three distances the height prior picks between the two mirror-image answers; with four or more it is
    only a light nudge. One bad distance (an echo heard instead of the direct sound) is dropped if that fixes the fit.
    """
    names = [n for n in distances if n in anchors]
    if len(names) < 3:
        return None
    a = np.array([anchors[n] for n in names], dtype=float)
    d = np.array([distances[n] for n in names], dtype=float)
    x0 = np.array(start if start is not None else a.mean(axis=0), dtype=float)
    p, rms = _solve(a, d, x0, z_prior)
    # The height guess only has to pick between the two mirror-image answers; once it has, let the distances
    # alone decide (starting from the guessed answer finds the right one). Keep the guess if that goes wild.
    p2, rms2 = _solve(a, d, p, None)
    if Z_RANGE[0] <= p2[2] <= Z_RANGE[1] and np.linalg.norm(p2 - p) < 1.0:
        p, rms = p2, rms2
    dropped: tuple[str, ...] = ()

    def plausible(q: np.ndarray) -> bool:
        return Z_RANGE[0] <= q[2] <= Z_RANGE[1]

    # With five or more distances, one wrong one (an echo heard instead of the direct sound) shows up as a
    # much better fit when it is left out. Four distances cannot tell, because leaving one out always fits.
    if len(names) >= 5 and (rms > 0.05 or not plausible(p)):
        best = None
        for k in range(len(names)):
            keep = [i for i in range(len(names)) if i != k]
            p2, r2 = _solve(a[keep], d[keep], x0, z_prior)
            if plausible(p2) and (best is None or r2 < best[0]):
                best = (r2, p2, names[k])
        if best is not None and best[0] <= 0.5 * rms:
            rms, p, dropped = best[0], best[1], (best[2],)
    if rms > max_rms_m or not plausible(p):
        return None
    return Fix(tuple(float(v) for v in p), len(names) - len(dropped), rms, dropped)
