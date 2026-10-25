# Phones as beacons: setup in plain words

Instead of buzzers and wires, six iPhones find each other by sound.
Five phones sit around the room (the beacons). The sixth is the one the user carries.
The Mac works out where the user is and tells the rest of Earmark.

## What you need
- 6 iPhones (old ones are fine; they must be iPhones) and the Mac.
- All of them on the same Wi-Fi. A phone hotspot works best, not the hall Wi-Fi.
- Xcode on the Mac (App Store, about 10 GB) to put the app on each phone. A free Apple ID is enough, but then each phone's copy lasts 7 days.
- Tape and a tape measure.

## One-time: put the app on each phone
1. `brew install xcodegen`
2. `cd locator/ios/EarmarkPhone && xcodegen` then open `EarmarkPhone.xcodeproj` in Xcode.
3. Click the project name, then "Signing", and pick your Apple ID team.
3b. If Xcode asks, sign in with your Apple ID under Xcode > Settings > Accounts. On the phone turn on Settings > Privacy & Security > Developer Mode (it restarts the phone).
4. Plug in a phone, choose it at the top, press Run. On the phone, if it asks, trust the developer in Settings > General > VPN and Device Management. Allow the microphone and local network when asked.
5. Repeat for every phone.

## Every time
1. On the Mac, start the usual app (`make demo-sim`), then in another tab run `make ranging`. It prints the address phones should use, like `ws://192.168.1.20:8766`.
2. Beacon phones: open the app, choose "A beacon", pick the number 1 to 5, type the Mac's address, press Start. Put it at its spot, screen on, volume all the way up, the bottom edge (speaker and microphone) pointing into the room.
3. The user's phone: choose "The user's phone", same address, Start. Hold it at chest height with the bottom edge uncovered.
4. The Mac tab shows lines like `fix x 0.32 y 0.51 z 1.55 ok 5 phones`. That is the user's position. Earmark uses it automatically.

## Measure where the beacons are

> The planned way, with no tape measure ("Set up the room"), is in `docs/project/ROOM_SETUP.md` and is not built yet. Until then, measure as below.
- Stand-in numbers are in `locator/config/beacons.json` (B1 to B5 are beacon phones 1 to 5).
- The origin is the floor under the middle of the mat. x is right, y is forward (the way the tape arrow points), z is up. Measure the height of each phone's bottom edge.
- Put the real numbers in that file.

## If something is off
- Run `make ranging` with `--verbose` (type `cd services/ranging && uv run earmark-ranging serve --verbose`). Every 2 seconds it shows, for each phone, how loud its own chirp was and which other phones it heard.
  - A phone that hears nobody: its volume is too low, or something covers its speaker.
  - A phone nobody hears: same, or it faces the wall.
- Too noisy in the hall? Add `--audible` to use a louder, lower pitch (you will hear faint ticks).
- Does the quiet high pitch work on these phones? Press "Play test sweep" on one phone while another phone records it in Voice Memos, then follow the band test in `locator/docs/BRINGUP.md` step B3.
- Add `--save-audio /tmp/heard` to keep what each phone heard as sound files.

## Settings that worked in the first real test (2 iPhones on a hotspot)
- Start the Mac side with: `cd services/ranging && uv run earmark-ranging serve --verbose --band 12000 16000 --volume 0.5`
- At about 1 m apart this got a distance in about 45% of rounds, steady to a few centimeters. Phones 1.75 m apart worked about 1 round in 4. Keep the beacons within about 1.5 m of where the judge stands.
- The quiet band (17000 to 20000) was too weak. Lower bands are stronger but you can hear them. `--volume` makes it quieter when phones are close.
- The measured gap was 1.05 m when the team had estimated 0.7 m; nobody measured it with a tape, so a fixed offset has not been ruled out. Measure once with a tape and compare.

## What it can and cannot do
- Works out the user's position about twice a second, to a few centimeters in simulation.
- Not yet tried with real phones. The first real test is what decides the pitch and how loud the speakers need to be.
