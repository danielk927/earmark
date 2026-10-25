# Room setup

**Status:** built. Proven end to end in the simulator (virtual phones, with the timing wobble real phones show): beacons placed within about 5 to 15 cm, and the room page draws them where they were found. With real phones, only one beacon and one listening phone have been tried so far. The recordings of that test (`services/ranging/runs/`) show the distance is steady to about ±2 cm once the beacon is identified correctly; the earlier failures were a beacon phone set to the wrong number (see below). The full walk with real beacons has not been tried.

The main path: put the three beacons in the fixed triangle from `setup.md` (1.2 m from the mat, B2 and B3 1.5 m apart; the numbers are already in `config/beacons.json`), then stand on the mat for 30 s so the Mac learns each beacon's timing. A floor-mark walk that finds the beacons by itself is still there as an option (`make session MODE=setup`, see the end), but it needs well-spread marks and was not accurate enough on real runs.

## The flow, start to finish

1. **Put the beacons down.** Three beacon phones around the mat, about 1 to 1.5 m away, all at about the same height (on a table or chair, roughly 0.75 m), bottom edge (the speaker) toward the mat. Roughly: beacon 1 ahead, beacon 2 on the right, beacon 3 on the left.
2. **Check them (only if you place them differently).** With a tape, from the floor under the middle of the mat: how far **right** each beacon is, and how far **forward** (the way the tape arrow points). Left and behind are negative. Then run `make beacons` and type the numbers; Enter keeps the number shown in brackets. Height defaults to 0.75 m. It saves them into `config/beacons.json`. Do this again only if a beacon moves.
3. **Start the beacons.** On each beacon phone: Earmark Phone, "Beacon (no Mac)", its number (1, 2, 3), band 12 to 16 kHz, Start. Volume all the way up. They need no network.
4. **Start the Mac.** `make session` starts the hub, voice, room page and Mac app, then runs the phone step in that terminal. Open `http://localhost:5173/room`.
5. **Connect the judge's phone.** "The user's phone" mode, the Mac's address (the terminal prints it), Start.
6. **Stand on the mat for 30 s.** Hold the phone at chest height (about 1.25 m), bottom edge out, still, on the middle of the mat. After 30 s it prints `calibration ok` and starts tracking. The beacons appear on the map and the Phones light turns on. Everything the phone hears is saved to `logs/session-<time>.wav`, so a bad run can be replayed.
7. **Recenter the AirPods.** Back on the mat, facing forward, press R in the Mac app, so "forward" for the AirPods matches "forward" in the room.
8. **Place the objects.** A teammate walks to where an item will go and says "I'm leaving my keys here". The spot is saved and the item appears on the map. An item Earmark has never heard of ("I'm leaving my glasses here") is added on the spot.
9. **The judge comes.** They take the phone, stand on the mat facing forward and ask "Where are my keys?". The ping leads them there, getting louder and faster as they walk, and says "You're here" at half a meter.

With three beacons, a position is only given when all three were heard in the last moment (two would flip between two answers), a position that would mean moving faster than about 1.5 m/s is ignored, and the result is lightly smoothed.

## With only two beacons

Two beacons are enough for a position. Use beacons 1 and 2, and start the Mac side with the beacons you really have:

```
make beacons                          # type in B1 and B2 (Enter keeps B3 as it is; it is ignored with ONLY)
make session ONLY="B1 B2"             # stand on the mat for 30 s
```

Place them about 2 m apart, side by side along a wall or the far side of the area, and keep the user on one side of the line between them (the mat side). The Mac assumes the phone is at chest height and picks the mirror-image point on the user's side; if the user walks across the line, the position flips to the wrong side. A position from two beacons is reported as "degraded" because nothing cross-checks it.

## Before every session: check the beacon numbers

Each beacon phone **remembers its number** from the last time. Open each one and confirm it matches what the Mac was told (`B1` is Beacon 1, which sweeps up; `B2` is Beacon 2, which sweeps down). If they differ the Mac now says `clear chirps from Beacon 2 are arriving, but only B1 is configured`, and refuses to start calibrating while a configured beacon has not been heard. (In the first real test the phone was on Beacon 2 while the Mac was told B1, which made calibration look like an echo problem.)

Distances can creep by about 20 cm over 10 minutes because two phone clocks run slightly differently; the Mac's status line says when to stand on the mat and press Enter to recalibrate (after 5 minutes).

## If something goes wrong

- **"calibration FAILED"**: it says why, per beacon. "chirps are ragged" means the phone moved while calibrating. Stand still on the mat and run `make session` again.
- **A beacon is moved or knocked over**: measure it again (`make beacons`), then `make session`.
- **The Mac was restarted but nothing moved**: `make session` and stand on the mat for 30 s. It uses the beacon positions saved last time.
- **The position jumped around**: the run was saved as `logs/session-<time>.wav`; replay it with `earmark-ranging replay <file>` (in `services/ranging`).
- **Practice without phones**: `make session MODE=sim` runs with a virtual phone and virtual beacons; with the room page open, the map fills in.

## Optional: let the Mac find the beacons (floor-mark walk)

If you cannot measure with a tape, the Mac can work out the beacon positions from what the phone hears while it stands on four floor marks. It is less exact than a tape, because it depends on how well spread out the marks are.

Tape four small marks on the floor, measured from the middle of the mat (x right, y forward, in meters). The defaults are in `config/beacons.json` under `setup_marks`: the mat (0, 0), a step forward (0, 0.8), back right (0.7, -0.5), back left (-0.7, -0.5). Keep them spread out (a triangle around the mat, not a line).

Run `make session MODE=setup`. Stand on mark 1 (the mat), press Enter, and stand still for 10 s; do the same on marks 2, 3 and 4. After the last mark it prints where it found each beacon (`room setup ok`), saves them into `config/beacons.json`, and starts tracking. "heard clearly at 2 marks" means that beacon is too far, too quiet or blocked from some marks.

## Honest limits

- Positions are only as good as the tape: a beacon measured 5 cm off puts every fix off by about that much.
- Phones hear each other best within about 1.5 m. Keep the beacons close to the mat.
- Hold the phone at about chest height (1.25 m), and keep the beacons at about the same height as each other.
- Hold the phone still, not touching anything else, during the 30 s calibration.
- The school and venue Wi-Fi block phones from reaching the Mac, and hotspots are not allowed at the venue. Run `make session TUNNEL=1`: the judge phone connects through a Cloudflare tunnel over the Wi-Fi (setup.md).
- With the floor-mark walk, if a beacon could be in two places that fit equally well, the Mac picks the one nearer its rough spot (ahead, right, left) and says so.
