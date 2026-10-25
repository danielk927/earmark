# Room setup

**Status:** the tape-measure version below is built and works end to end in the simulator. With real phones, one beacon and one listening phone have been tested (live distance, about ±10 cm). Three real beacons at once have not been tried yet.

The beacon phones only chirp; they never listen (see "How the user's position is found" in `docs/project/NEXT_STEPS.md`). So the Mac cannot measure where the beacons are by itself. Their positions come from a tape measure, and the judge's phone is calibrated once on the mat.

## The flow, start to finish

1. **Place the beacons and measure them.** Three beacon phones stand around the mat, about 1.2 m away, all at about the same height (on a table or chair, roughly 0.75 m), bottom edge (the speaker) toward the mat:
   - Beacon 1 straight ahead of the mat (the way the tape arrow points).
   - Beacon 2 on the right.
   - Beacon 3 on the left.

   Measure each one from the floor under the middle of the mat (x right, y forward, z height, in meters) and type it into `config/beacons.json`. The file already holds these three spots at 1.2 m; if you put the phones exactly there, nothing needs changing.
2. **Start the beacons.** On each beacon phone: Earmark Phone, "Beacon (no Mac)", its number (1, 2, 3), band 12 to 16 kHz, Start. Volume all the way up. They need no network.
3. **Start the Mac.** Three terminals: `make demo-sim` (hub and voice), `cd dashboard && npm run dev` (the room page), and `make room-setup` (the phones). Open `http://localhost:5173/room`. **The map starts empty**: no beacons until the phones are calibrated.
4. **Calibrate on the mat.** A teammate stands on the middle of the mat, facing forward, holding the judge's phone at chest height (about 1.25 m), in "The user's phone" mode connected to the Mac's address. Press Enter in the `make room-setup` terminal and stand still for 30 s. When it says `calibration ok`, the beacons appear on the map and the Phones light turns on.
5. **Recenter the AirPods.** Still facing forward, press R in the Mac app, so "forward" for the AirPods matches "forward" in the room.
6. **Place the objects.** The teammate walks to where an item will go and says "I'm leaving my keys here". The spot is saved and the item appears on the map. **An item Earmark has never heard of (for example "I'm leaving my glasses here") is added on the spot.**
7. **The judge comes.** They take the phone, stand on the mat facing forward and ask "Where are my keys?". The ping leads them there, getting louder and faster as they walk, and says "You're here" at half a meter.

If a beacon is moved or knocked over, measure it again, fix `config/beacons.json`, restart `make room-setup` and calibrate again.

## Later, if there is time: no tape measure

The teammate stands on the mat, then on two or three taped marks on the floor, a few seconds each. From those, the Mac works out both where the beacons are and their timing. Not built.

## Honest limits

- Distances from one real beacon wobble by about ±10 cm, with an occasional bad reading (a filter now ignores sudden jumps). A position from three beacons will wobble more.
- Phones hear each other best within about 1.5 m. Keep the play area small.
- The judge's phone must stay at about the height used in calibration (1.25 m). Beacons at very different heights shift positions.
- Hold the phone still, not touching anything, during calibration; a moving hand makes it fail ("chirps are ragged").
- The school Wi-Fi blocks phones from reaching the Mac. Use a travel router or an iPhone hotspot (the hotspot phone can be a beacon; it cannot be the judge's phone).
