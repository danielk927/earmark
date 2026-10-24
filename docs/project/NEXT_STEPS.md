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
| AirPods head tracking | Never tested on real AirPods |
| Beacons, phone locator app | Not built or tested; no hardware yet |

## A real test you can do today (no hardware)

1. `make demo-sim` starts everything with the simulator (see `docs/project/DEMO_SCRIPT.md`).
2. Say or type "Where's the sugar?", "I put my keys in the drawer", "Where did I put my keys before?".
3. Check the dashboard (live map and timeline) updates.
4. With the AirPods on: run the spatial test in `mac/README.md` and fill in the table in `docs/project/STATUS.md`. This is the most important test that has not been done.

## Hardware: how to start (in this order, each step must pass before the next)

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
