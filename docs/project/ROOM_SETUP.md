# Room setup

**Status:** built. Proven end to end in the simulator (virtual phones, with the timing wobble real phones show): beacons placed within about 5 to 15 cm, and the room page draws them where they were found. With real phones, only one beacon and one listening phone have been tried so far (live distance, about ±10 cm). The full walk with three real beacons has not been tried.

There is no tape measure on the beacons. You tape four marks on the floor once, and the phone stands on each of them in turn; the Mac works out where the beacons are from what it hears at each mark.

## Before the event (once)

Tape four small marks on the floor, measured from the middle of the mat (x right, y forward the way the tape arrow points, in meters). The defaults, in `config/beacons.json` under `setup_marks`:

| Mark | Where |
|---|---|
| 1. The mat | the middle of the mat (0, 0) |
| 2. A step forward | 0.8 m forward (0, 0.8) |
| 3. Back right | 0.7 m right, 0.5 m back (0.7, -0.5) |
| 4. Back left | 0.7 m left, 0.5 m back (-0.7, -0.5) |

If your room needs other spots, change the numbers there. Keep them spread out (a triangle around the mat, not a line).

## The flow, start to finish

1. **Put the beacons down anywhere sensible.** Three beacon phones around the mat, about 1 to 1.5 m away, all at about the same height (on a table or chair, roughly 0.75 m), bottom edge (the speaker) toward the mat. Roughly: beacon 1 ahead, beacon 2 on the right, beacon 3 on the left. Nothing to measure.
2. **Start the beacons.** On each beacon phone: Earmark Phone, "Beacon (no Mac)", its number (1, 2, 3), band 12 to 16 kHz, Start. Volume all the way up. They need no network.
3. **Start the Mac.** Three terminals: `make demo-sim` (hub and voice), `cd dashboard && npm run dev` (the room page), and `make room-setup` (the phones). Open `http://localhost:5173/room`. **The map starts empty**: no beacons yet.
4. **Connect the judge's phone.** "The user's phone" mode, the Mac's address (the `make room-setup` terminal prints it), Start.
5. **Walk the marks.** A teammate holds the judge's phone at chest height (about 1.25 m), bottom edge out, and:
   - stands on mark 1 (the mat), presses Enter in the `make room-setup` terminal, and stands still for 10 s;
   - walks to mark 2 when it says so, presses Enter, stands still for 10 s;
   - the same for marks 3 and 4.

   After the last mark it prints where it found each beacon (`room setup ok`), saves them into `config/beacons.json`, and starts tracking. The beacons appear on the map and the Phones light turns on.
6. **Recenter the AirPods.** Back on the mat, facing forward, press R in the Mac app, so "forward" for the AirPods matches "forward" in the room.
7. **Place the objects.** The teammate walks to where an item will go and says "I'm leaving my keys here". The spot is saved and the item appears on the map. An item Earmark has never heard of ("I'm leaving my glasses here") is added on the spot.
8. **The judge comes.** They take the phone, stand on the mat facing forward and ask "Where are my keys?". The ping leads them there, getting louder and faster as they walk, and says "You're here" at half a meter.

## If something goes wrong

- **"room setup FAILED"**: it says why, per beacon. "heard clearly at 2 marks" means that beacon is too far, too quiet or blocked from some marks: move it closer or turn it up. "chirps are ragged" means the phone moved during a stop. Go back to the mat and press Enter to walk the marks again.
- **A beacon is moved or knocked over**: walk the marks again (`make room-setup`, Enter on each mark).
- **The Mac was restarted but nothing moved**: `make room-recalibrate` and stand on the mat for 30 s. It uses the beacon positions saved last time.
- **Practice without phones**: `make room-setup-sim` runs the whole walk with a virtual phone and virtual beacons; with the hub and room page running, the map fills in.

## Honest limits

- Placement is only as good as the marks: a mark taped 5 cm off moves the beacons by about that much.
- Phones hear each other best within about 1.5 m. Keep beacons and marks close.
- Every stop must be at about the same phone height (chest, 1.25 m), and beacons at about the same height as each other.
- Hold the phone still, not touching anything else, during each 10 s stop.
- The school Wi-Fi blocks phones from reaching the Mac. Use a travel router or an iPhone hotspot (the hotspot phone can be a beacon; it cannot be the judge's phone).
- If a beacon could be in two places that fit equally well, the Mac picks the one nearer its rough spot (ahead, right, left) and says so.
