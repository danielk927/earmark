# Phones as beacons: setup in plain words

Instead of buzzers and wires, iPhones find each other by sound.
Two to four phones sit around the room (the beacons; the plan uses 2 or 3, and self-timed mode supports up to 4). One more is the one the user carries.
The Mac works out where the user is and tells the rest of Earmark.

## What you need
- 3 to 5 iPhones (2 or 3 beacons plus the user's phone; old ones are fine; they must be iPhones) and the Mac.
- All of them on the same Wi-Fi. A phone hotspot works best, not the hall Wi-Fi.
- Xcode on the Mac (App Store, about 10 GB) to put the app on each phone. A free Apple ID is enough, but then each phone's copy lasts 7 days.
- Tape and a tape measure.

## One-time: put the app on each phone
1. `brew install xcodegen`
2. `cd locator/ios/EarmarkPhone && xcodegen` then open `EarmarkPhone.xcodeproj` in Xcode.
3. Click the project name, then "Signing", and pick your Apple ID team.
3b. If Xcode asks, sign in with your Apple ID under Xcode > Settings > Accounts. On the phone turn on Settings > Privacy & Security > Developer Mode (it restarts the phone).
4. Plug in a phone, choose it at the top, press Run. On the phone, if it asks, trust the developer in Settings > General > VPN and Device Management. Allow the microphone and local network when asked.
5. Repeat for every phone you use.

## Every time
1. On the Mac, start the usual app (`make demo-sim`), then in another tab run `make ranging`. It prints the address phones should use, like `ws://192.168.1.20:8766`.
2. Beacon phones: open the app, choose "A beacon", pick the number (1 to 4 in self-timed mode), type the Mac's address, press Start. Put it at its spot, screen on, volume all the way up, the bottom edge (speaker and microphone) pointing into the room.
3. The user's phone: choose "The user's phone", same address, Start. Hold it at chest height with the bottom edge uncovered.
4. The Mac tab shows lines like `fix x 0.32 y 0.51 z 1.55 ok 5 phones`. That is the user's position. Earmark uses it automatically.

## Measure where the beacons are

> The way with no tape measure is built: run `make room-setup` and stand on the floor marks, and the Mac places the beacons. See `docs/project/ROOM_SETUP.md`. With only some beacons out, add `ONLY`, for example `make room-setup ONLY="B1 B2"`. If the beacons are already placed (by room-setup or a tape), `make room-recalibrate ONLY="B1 B2"` calibrates once while you stand on the mat. The tape measure way is below.
- The numbers live in the repo-root `config/beacons.json` (the ranging service reads that file; B1 to B4 are beacon phones 1 to 4). `locator/config/beacons.json` is only for the old buzzer plan.
- The origin is the floor under the middle of the mat. x is right, y is forward (the way the tape arrow points), z is up. Measure the height of each phone's bottom edge.
- Put the real numbers in the repo-root file.

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
- Tried with 2 real iPhones (see the first real test above); that test decided the pitch and volume. More than 2 phones in a room have not been tried.

## Beacon with no Mac (self-timed)

A third role in the phone app. A phone in this role chirps on its own clock: every 0.5 s, exactly, with no Wi-Fi, no Mac address and no microphone. Beacon 1 chirps at the start of each half second, beacon 2 at 0.125 s, beacon 3 at 0.250 s, beacon 4 at 0.375 s. Odd-numbered beacons sweep up in pitch, even-numbered ones sweep down. Because the chirps are written straight into the speaker's audio stream (not fired by a timer), the gap between two chirps is the same to the sample. That is what lets the Mac turn each chirp the user's phone hears into a distance: Wi-Fi delays cannot shift a chirp by even a millisecond (1 ms would be 34 cm).

The user's phone is unchanged: "The user's phone", the Mac's address, Start. It records and streams to the Mac as before. The Mac calibrates once (it needs to see one chirp at a known distance) and then turns every later chirp into a distance.

### Before every session: check the beacon numbers
The beacon phone REMEMBERS its beacon number (it is a stored setting). Before every session, open each beacon phone and confirm its number matches what the Mac was told (for example `--only B1 B2`). If it does not match, the Mac says "heard Beacon N, but only B.. is configured". Fix the number on the phone (or start the Mac with the right `--only`).

### Two beacons
With two beacons the Mac gets two distances, which give two mirror-image points on either side of the line between the beacons. It assumes the user's phone is at chest height (about 1.25 m) and that the user stays on one side of that line (the mat side). If the user walks across the line, the position flips to the wrong side. The position is marked "degraded" because nothing cross-checks it. Set up with `make room-setup ONLY="B1 B2"` and recalibrate with `make room-recalibrate ONLY="B1 B2"`.

### On the beacon phone
1. Open Earmark Phone and choose "Beacon (no Mac)".
2. Set the beacon number (1 to 4). Leave the band at 12 to 16 kHz unless the Mac side is started with another band; the other presets are 14 to 18 and 17 to 20 kHz.
3. Volume slider: 0.8 is the default. Turn it down if the phones are very close; up to 1.0 for a big room.
4. Press Start. The screen shows "Beacon N, chirping every 0.5 s, slot ... s", the number of chirps so far and the band.
5. Turn the phone's volume buttons all the way up, leave the screen on (the app keeps it awake), and point the bottom edge (the speaker) toward the room. Put it in airplane mode if you like; it does not need the network.
6. If headphones are plugged in or the audio output changes, the app says so: press Stop, then Start again.

### The one-beacon test (tonight)
- Lay a tape measure on the floor or a table. Put the beacon phone at 0 with its bottom edge facing along the tape.
- Start the Mac side in self-timed listening mode (the ranging service's instructions say how), then the user's phone as "The user's phone" with the Mac's address.
- Hold the user's phone at exactly 1.00 m on the tape, bottom edge facing the beacon, and keep it still while the Mac calibrates (it says when it is done).
- Then walk the phone along the tape and compare the Mac's distance with the tape: 0.50, 1.50, 2.00 m. Each chirp is 0.5 s apart, so you get two distances a second.
- If the Mac hears nothing: volume on the beacon, the band (both sides must use the same one), something covering the speaker or the microphone.

### Mac as the beacon (one iPhone only)
The Mac's own speaker can play the beacon so a one-phone test works: in `locator/ios/EarmarkPhone` run `swift run phone-cli --beacon 1` (add `--band 14000 18000` or `--volume 0.5` to match the Mac side). It prints the first chirp time and a count every 10 chirps. Turn the Mac's volume all the way up. The iPhone is then "The user's phone" as usual. Mac speakers are weaker above 16 kHz than a phone's, so stay within about 1.5 m.
