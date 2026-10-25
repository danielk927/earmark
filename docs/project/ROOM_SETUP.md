# Room setup (the plan we agreed on)

**Status: planned, not built yet.** Today the beacon positions are typed by hand into `config/beacons.json` (see the bottom of this page). The three parts marked "to build" are what we will build next, after the UI changes are pulled.

## The flow, start to finish

1. **The map starts empty.** No beacons, no items. The room screen (`/room`) shows an empty room and a "Set up the room" panel.
2. **Place the beacons.** A teammate stands on the middle of the mat, facing forward (the way the tape arrow points), holding the "user's phone". The three beacon phones are stood up around them, about 1 to 1.5 m away, all at about the same height (on a table or chair, roughly 0.75 m).
   - Beacon 1 goes straight ahead of the mat.
   - Beacon 2 goes on the right.
   - Beacon 3 goes on the left.
3. **Press "Set up the room".** The phones chirp for a few seconds and measure the distance between every pair of phones. The Mac works out where each beacon is, and they appear on the map. No tape measure needed.
4. **Recenter the AirPods.** The teammate faces forward and presses R in the Mac app, so "forward" for the AirPods matches "forward" in the room.
5. **Place the objects.** The teammate walks to where an item will go and says "I'm leaving my keys here". The position under the phone is saved and the item appears on the map. An item Earmark has never heard of (for example "glasses") is created on the spot.
6. **The judge comes.** They stand on the middle of the mat facing forward. They ask "Where are my keys?". The ping leads them there, getting louder and faster as they walk, and says "You're here" at half a meter.

## To build

1. **"Set up the room" (calibration).** The Mac collects the pair distances between the judge's phone and beacons 1 to 3 for a few seconds, takes the middle value for each pair, then solves the layout. It assumes the judge's phone is held at about 1.25 m and the beacons are all at about the same height (0.75 m), and uses the conventions in step 2 to fix left, right and forward. It checks the fit and says so if the numbers do not agree (a beacon was moved, or not heard). Needs the user's phone and beacons 1 to 3 connected.
2. **Empty map.** The ranging service starts with no beacons, and the room page draws only what exists: the beacons after setup and items that have a position. The named places from `config/space.json` (cupboard, drawer, bag, box) are not drawn, because their numbers are placeholders.
3. **Items created by voice.** If the item in "I'm leaving X here" is not in the list, the voice service creates it (the hub already creates items from a label; this would give it a made-up tag), then saves its position.

## Honest limits

- The position fix from the judge's phone plus 3 beacons is proven in the simulator, but not yet with four real phones. Two real iPhones measured their distance to a few centimeters (0.97 m true against 1.04 to 1.06 m measured).
- A phone held at a very different height from the assumed 1.25 m, or beacons at very different heights, will shift positions. Keep them close to the numbers above.
- Phones hear each other best within about 1.5 m. Keep the play area small.
- The school Wi-Fi blocks phones from reaching the Mac. Use a travel router or the iPhone hotspot.

## The current way (works today, used until the above is built)

Measure each beacon with a tape from the middle of the mat (x right, y forward, z height in meters) and type it into `config/beacons.json`. The hiding places in `config/space.json` work the same way. Then start the app. This is the only way to place beacons right now.
