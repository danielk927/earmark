# Next steps

Plain list of what is left, who can do it, and in what order. Updated 2026-10-24.

## Where we are

| Part | State |
|---|---|
| Software (voice, memory, dashboard, backend, Mac app, locator tools) | Built and tested on a laptop |
| Claude | Works with the real key |
| Convex | Live on the cloud dev deployment with demo data |
| Moss | Works (warm it up once before any demo: the first start takes minutes) |
| Cartesia (voice) | Key set; speech works |
| AirPods 3D sound and head tracking | Tested on real AirPods and works |
| Beacons, phone position | Phones-as-beacons app and Mac service built. Real test: two iPhones measured their distance to a few centimeters at about 1 m in the 12 to 16 kHz band. Calibrate-then-listen mode added 2026-10-24 evening; not yet run on real phones |

## A real test you can do today (no hardware)

1. `make demo-sim` starts everything with the simulator (see `docs/project/DEMO_SCRIPT.md`).
2. Say or type "Where's the sugar?", "I put my keys in the drawer", "Where did I put my keys before?".
3. Check the dashboard (live map and timeline) updates.
4. The AirPods spatial test has passed. Needs the app built once with `make mac`, then `make mac-open` (ad-hoc signing means macOS asks for permissions again after each rebuild).

## Room setup: the agreed plan

The setup we agreed on (empty map, a teammate stands on the mat, the Mac works out where the beacons are, then place objects by walking and speaking) is written up in `docs/project/ROOM_SETUP.md`. It is planned, not built. We are waiting for the UI changes to be pulled first.

## How the user's position is found (decided 2026-10-24 evening)

Spare iPhones around the room are the beacons; the judge carries one more iPhone. Sound does the measuring. Rules:

- **Beacons chirp on their own, with no network.** Each beacon plays a 40 ms sweep every 0.5 s on its own clock, in its own time slot (beacon 1 at 0 ms, beacon 2 at 125 ms, beacon 3 at 250 ms, beacon 4 at 375 ms). Odd beacons sweep up, even beacons sweep down. Wi-Fi never touches the timing, so Wi-Fi jitter cannot cause distance error.
- **The judge's phone only listens.** It streams its microphone to the Mac. The Mac finds each chirp in the recording to a fraction of a sample.
- **Calibration replaces clock sync.** Before the blindfold goes on, the judge's phone sits still for 10 s at a known spot (the mat). From the chirps heard there, the Mac fits each beacon's schedule on the phone's timeline: a start offset and the exact period. After that, every chirp heard gives a distance directly: distance = speed of sound x (heard time - scheduled time).
- **Beacons are told apart by time slot, not by pitch.** All beacons use the same band (12 to 16 kHz, the band real phones could produce and hear). Splitting the band per beacon would blunt the timing.
- **Position updates after every chirp**, 8 times a second with four beacons, using the newest distance plus the latest one from each other beacon. Height is not tracked; the judge's head height is a fixed number. Items keep their own 3D positions in `config/space.json`.
- The older two-way mode (Mac tells phones when to chirp, every phone records) stays in the code as a fallback; it was the first thing to measure a real distance between two iPhones.

### Test plan, in order (each step must pass before the next)

1. **Live distance, one beacon and one target phone.** Beacon at 0 on a tape measure (an iPhone in "Beacon (no Mac)" mode, or the Mac's own speaker via `phone-cli --beacon 1`). Target held at exactly 1.00 m during the 10 s calibration, bottom edges facing each other. Then hold at 0.5, 1, 2, 3 m for 20 s each and walk slowly between them. Pass: a printed distance after nearly every chirp (about 2 per second), within 5 cm standing still, following smoothly while walking. Commands: `services/ranging/README.md`, section "Calibrate-then-listen mode".
2. **Position, four beacons.** Four beacon phones at taped positions in `config/beacons.json`, all at about the same height on tables or chairs. Calibrate standing on the mat. Stand on five taped floor marks. Pass: within 30 cm on every mark, a position at least once a second.
3. **Walking.** Walk slowly between the marks; the dashboard `/room` page should follow without jumps.
4. **AirPods end to end.** Blindfold, AirPods on, ask for the salt, walk to it. Its audio half can be rehearsed any time with the keyboard walking simulator on the `/room` page.

## Fallback only: buzzer hardware, how to start (in this order, each step must pass before the next)

You need three tools first: `brew install arduino-cli` (to put the program on the ESP32), Xcode from the App Store (for the iPhone app), and `brew install xcodegen`.

1. **Answer four questions** (read the metal can on the ESP32 and the buzzer packaging): WROOM or WROVER? Magnetic or piezo buzzers? Can we solder? Can we cut the Ethernet cables? Details: `locator/docs/WIRING.md` sections 2 and 3.
2. **Hearing test (the biggest risk).** Build the simple one-buzzer circuit (`WIRING.md` section 6a), put the program on the board (`cd locator && make flash`, add `--wrover` if it is a WROVER), record it with the iPhone from 1, 2, 3 and 4 meters in the loud hall, then run `make bandtest FILE=recording.wav`. This tells us which pitch to use and whether the plan can work at all. If it fails, use the fallback in `LOCATOR_BRIEF.md` section 11 (user stays on the mat, named places still work).
3. **One beacon** with the full circuit (`locator/docs/BRINGUP.md`, Phase B).
4. **Five beacons**, then mount them (two high at about 1.8 m, two low at about 0.3 m, one in the middle at about 1 m) and tape-measure each position from the mat. Put the numbers in `locator/config/beacons.json`.
5. **iPhone app:** `cd locator/ios/EarmarkLocator && xcodegen`, open the project in Xcode, pick your team under Signing, run it on the phone. Set it to the "hello" connection mode and the Mac's address (phone hotspot works best).
6. **Check the fix:** walk with the phone; the Mac status shows `listener_pose` arriving. Then try "Where are my keys?" and walk to them.

`BRINGUP.md` has the pass/fail check for every step. Do not skip ahead.

## Who does what

| Person | Job |
|---|---|
| Hardware (one or two people) | Steps 1 to 4 above |
| Phone (one person with the Mac and Xcode) | Tools, step 5, AirPods spatial test |
| Accounts and story (one person) | Cartesia key, Fetch.ai accounts, Devpost, talk to a blind or low-vision person, record the demo video |
| Software (Claude sessions) | Wire in whatever the tests find; stem-button push-to-talk and phone-microphone speech are not built yet |

## Keys: do teammates share them?

Yes, one set is fine for the hackathon.

- Everyone puts the same keys in their own `.env` (the file git ignores). Share them privately, never in git or a public channel.
- Anthropic, Cartesia and Moss: one shared key each. Costs and rate limits are shared.
- Convex: teammates do not need to log in just to use it. They need `CONVEX_URL`, `CONVEX_SITE_URL` and the two secrets from `.env`. To change backend code they must be invited to the Convex team.
- Each Claude Code session reads the `.env` in its own folder, so copy the file to each machine.
