# Earmark demo script (design v7: walking, 2 minutes + 2 minutes Q&A)

Roles: **Presenter** (talks), **Operator** (at the Mac), **Judge** (blindfolded, AirPods in, iPhone in hand).
Numbers in brackets come from real trials and latency runs; never say a number we did not measure.

## Setup at the table (about 15 minutes, once)

1. Mat in the center, tape arrow pointing forward; sugar in the cupboard (front), keys in the drawer (right), spice jar in the bag (left), pills in the box (behind).
2. Five buzzers mounted (two high about 1.8 m, two low about 0.3 m, one at about 1 m), pointing inward, wires taped along edges.
3. Phone app: enter each buzzer's tape-measured position, calibrate, then hold the phone at each item's spot and tap save (the Mac map updates as each `save_spot` arrives).
4. Phone joins nothing; the Mac joins the **phone's hotspot**. The hub logs the URL the phone uses.

## Before each judge (Operator, 60 seconds)

1. `make reset`.
2. AirPods connected to the Mac; menu-bar AirPods icon: Spatial Audio **Off**.
3. Earmark app status bar: Bus connected, Locator live (pose quality ok, 4-5 beacons), Head tracking "Tracking", Output = AirPods at **48 kHz**.
4. Judge on the mat facing the arrow: press **R** (Recenter).
5. Mac screen on the audience map (where the judge is, which way they face, where the sound comes from).

## Script

**0:00 - 0:15 Hook (Presenter)**
- "If you're blind, finding the sugar in a cupboard or the pills in a box means searching by touch, shelf by shelf."
- "Earmark finds things at home with just your AirPods and the phone you already carry. No cameras."

**0:15 - 1:10 Live demo (Judge)**
- Judge presses the AirPods stem: "Where's the sugar?"
- Earmark: "The sugar is in the cupboard, at your twelve o'clock, about two steps away." A click starts repeating from the cupboard.
- Presenter: "Turn your head. The sound stays on the cupboard." Then: "Walk toward it." The clicks get louder and faster; drifting off course moves them to one side.
- About half a meter away the clicks stop, a "you're here" tone plays, and Earmark says "Top shelf, front left." The judge finds the sugar by touch.
- Judge: "Where are my blood pressure pills?" The click comes from behind with the distinct behind sound, and Earmark says "Turn right." The judge turns and walks to the box.

**1:10 - 1:40 How it works (Presenter, pointing at the map)**
- Five buzzers chirp in turn every 300 ms; the phone hears each chirp and works out where it is from the arrival times, like GPS.
- The AirPods report head direction; the Mac renders the click in 3D from the item's saved spot.
- Cartesia transcribes and speaks; Moss matches vague requests; Convex is the live backend for the caregiver dashboard; Bitdeer models choose actions and reason for a Fetch.ai agent caregivers reach through ASI:One.

**1:40 - 2:00 Impact (Presenter)**
- Measurable: "[TRIAL RESULTS: n trials with m blindfolded testers; median time to find with Earmark vs touch only]." Say "pilot" for a handful of trials.
- Caregivers: the dashboard shows when the pills were found around each dose time (found, not taken).
- Responsible: no cameras, no medical advice, and Earmark asks instead of guessing.

## Q&A crib

- **Why not a camera app?** Cameras can't see into cupboards or bags, and a camera in the home is a privacy dealbreaker; Seeing AI's Find My Things is camera-based (`docs/CUSTOMER.md`).
- **Why five buzzers?** The phone needs four to fix a 3D position; the fifth covers one blocked by the body.
- **Front/back confusion?** A distinct behind sound past 100 degrees, plus "turn left/right".
- **Latency?** [LATENCY: median and p90 from `make latency`], target 1.2 s.
- **Offline?** Speech falls back to cached phrases and the system voice; intent falls back to a keyword grammar; no position falls back to the mat with spoken distances.

## If something fails (Operator)

| Failure | Do this | What the judge hears |
|---|---|---|
| Beacons unreliable | Nothing; the phone switches to step counting | Same, a little less precise |
| No position at all | Nothing; the system assumes the mat | Spoken distances ("about two steps ahead") |
| Phone not connected | `make demo-sim`, walk the listener with WASD to mirror the judge | Same experience, driven by the operator |
| Head tracking lost | Nothing; room-forward directions plus clock faces | "At your two o'clock" |
| Cartesia down | Nothing; cached phrases, system voice, Apple Speech | A different voice |
| Everything on fire | Play the backup demo video | - |
