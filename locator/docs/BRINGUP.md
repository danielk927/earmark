# BRINGUP.md — beacon bring-up, Phase B and Phase C

Phase B proves the hardware works with **one** beacon; Phase C proves the system
locates the phone with **five**. Steps are numbered checklists. Each step ends with
its **PASS** criterion, quoted from the phase list in
[LOCATOR_BRIEF.md](../LOCATOR_BRIEF.md) §10 — do not move to the next step until the
current one passes. Wiring itself lives in [WIRING.md](WIRING.md); this file assumes
you can follow it.

Rule of thumb from the brief (§10): when a step fails, fix it on the spot using its
"On fail" note — and if you exhaust those, follow the fallback ladder (brief §11)
before moving on.

---

## Prerequisites (what must exist before Phase B starts)

Phase B happens after Phase A — all software exists and no hardware is needed until
here. Map of who provides what:

| Prerequisite | Provided by | Notes |
|---|---|---|
| `locator/firmware/beacons/beacons.ino` + `locator/scripts/flash.sh` | firmware PR (GitHub #3) | `make flash` needs these. |
| iOS app with Run / Debug / Calibrate screens, Record toggle | iOS PR (GitHub #1) | Used to read SNR, record WAVs, capture templates. |
| `tools/band_test.py`, `tools/analyze_log.py`, `tools/fake_hub.py` | Python tools PR | `make bandtest`, `make fakehub`. |
| Contracts, configs, Makefile | merged (PR #2) | `make test` green. |

Check: `ls locator/firmware/beacons/beacons.ino locator/tools/band_test.py` finds both,
and the iOS app builds on the demo phone. If any piece is missing, that PR is the
blocker — do not improvise hardware steps around missing software.

**The phone side:** demo iPhone 17, app installed (free personal-team signing is
fine, §8.1), connected to the same network as the Mac (prefer the iPhone's Personal
Hotspot or a travel router, not the venue Wi-Fi — §1).

---

## How to open a serial monitor

You will type firmware commands and read replies throughout. Either:

- **Arduino IDE:** Tools → Serial Monitor; baud **115200**; line ending **Newline**. Or
- **arduino-cli:** `arduino-cli monitor -p <port> -b 115200` (port is the one
  `flash.sh` printed).

Every command is case-insensitive and answers `OK` or `ERR <reason>` (§4.5). If the
serial monitor is open while an upload runs, close it first — an open monitor can hold
the port and make the upload hang; that is why `flash.sh` prints "hold **BOOT** if the
upload hangs" (§4.1): hold the BOOT button during "Connecting…".

---

## Phase B — one beacon (human-in-the-loop)

### B1. Upload the firmware

1. [ ] Connect the ESP32 by USB to the Mac.
2. [ ] From `locator/`, run `make flash` (it prints beginner instructions; hold **BOOT**
       if the upload hangs, §4.1).
3. [ ] Open the serial monitor. Press the board's **EN/RST** button.
4. [ ] Expect: a banner with version, pin map and config JSON (§4.5 boot), then ~2 s
       later `RUNNING` and the cycle length (300 ms at defaults).
5. [ ] Expect: the on-board LED blinks **once per cycle** (~3.3 blinks/s) (§4.2).

**PASS:** *"RUNNING is printed and the LED blinks."* (§10 Phase B)

**On fail:** `ERR` on a command → read the reason. Upload hangs → hold BOOT and retry.
No LED → run `status`; if `status` says running, the board is fine and the LED claim
goes to the firmware owner. Still dead → [WIRING.md](WIRING.md) has nothing to fix
here; it is a board/USB fault — try another ESP32 (six are on the desk, §3).

### B2. Wire one direct-drive beacon and hear it

1. [ ] `stop` in the serial monitor (all pins inactive, §4.5).
2. [ ] Wire **B1 direct drive** on the WROOM map: GPIO 16 ─[100 Ω]→ buzzer (+),
       buzzer (−) → GND ([WIRING.md](WIRING.md) §6a). (WROVER: GPIO 25.)
3. [ ] Run `test`. It prints `>> B1 chirp` then chirps B1, B2, …, B5 once each,
       1 s apart (§4.5) — only B1 has a buzzer wired, so expect exactly one audible
       chirp per pass of the five.
4. [ ] Then run `beep 1` (chirps B1 every 300 ms until stopped, §4.5) and `stop`.

**PASS:** *"an audible chirp."* (§10 Phase B)

**On fail:** follow the [WIRING.md](WIRING.md) "if no sound" checklist from the top —
in order: running → `test` prints → 5 V present → transistor/legs (n/a here) → diode
(n/a here) → `invert 1 1` → swap the buzzer's two legs. If the direct-drive buzzer is
audible but faint, that is expected at this stage; range is judged in B4.

### B3. Band test

1. [ ] `stop`, then start the app's **Record** (iOS PR) with the phone **1 m** from
       the buzzer.
2. [ ] In the serial monitor run `sweep 1` (§4.5): expect `SWEEP START`, 2 s of
       silence first, a 10 s sweep from 1→20 kHz, then `SWEEP END`. Record through
       the whole sweep plus a second of margin on both sides.
3. [ ] Stop the recording, share the WAV (AirDrop per §8.7), and run
       `make bandtest FILE=<recording.wav>` (§7.3). It prints the recommended band as
       an exact firmware command, e.g. `band 2100 4600`, plus the matching chirp
       config JSON.
4. [ ] Send that `band <lo> <hi>` command on serial, then `save`, then `config` —
       the printed JSON must match the band test's recommended config.
5. [ ] Paste the same config JSON into the app: Settings → "Paste chirp config" (§4.6).

**PASS:** *"Run sweep 1, recording with the app's Record function from 1 m, then
band_test.py. Set the recommended band and paste the chirp config into the app."*
(§10 Phase B) — mechanically: `config` output == band-test output == pasted app config.

**On fail:** if `band_test.py` cannot find the sweep onset (§7.3), the recording is
too quiet — re-record at 0.5 m, or move to the transistor circuit ([WIRING.md](WIRING.md)
§5) and repeat.

### B4. Detection range, in the actual hall

Do this in the demo hall itself — the venue's noise and echoes are the real
adversary (§1, §10).

1. [ ] Run `beep 1`.
2. [ ] With the phone at **1 m**: read B1's SNR on the app's Debug screen (per-beacon
       SNR readout, §8.2). Note the number. Repeat at **2 m**, **3 m**, **4 m**.
3. [ ] Put the beacon inside a closed cardboard box (the demo cupboard) at 1 m and
       read the SNR once more.
4. [ ] `stop` when done.

**PASS:** *"SNR ≥ 10 at 4 m."* (§10 Phase B)

**On fail** (in order, §10 B4 + §11.1): switch to the **transistor circuit**
([WIRING.md](WIRING.md) §5) and retest → if still failing, **remove the 10 Ω
resistors** → aim the buzzer at the center → `len 20` (lengthen the chirp to 20 ms,
§4.3/§4.5) → lower the band → report. If the closed-box SNR collapses but open-air
passes, expect trouble at the cupboard in Phase C — say so in the report.

### B5. Timing (two beacons, side by side)

1. [ ] Wire the **second** beacon on B2's pin (WROOM: GPIO 17; WROVER: GPIO 26).
2. [ ] Place both beacons **side by side, ~30 cm from the phone** — equal distance,
       so the only difference in arrival times is the schedule itself.
3. [ ] Run the schedule (`run`) for **60 s** (§10 Phase B).
4. [ ] Measure B2−B1 arrival differences over that minute: read the arrival offsets
       on the app's Debug screen (§8.2), or Record the minute and compute from the
       exported log with `tools/analyze_log.py`.
5. [ ] `stop`.

**PASS:** *"B2 − B1 arrival differences = 50.000 ms ± 0.03 ms (std ≤ 0.02 ms)."*
(§10 Phase B)

**On fail:** this is the firmware's slot-start jitter requirement (≤ 20 µs RMS, §4.4)
showing up as phone-visible timing error. Save the recording/log and hand it to the
firmware owner — do not start Phase C on a schedule that drifts: every downstream
detection window is keyed to it (§6.5, §6.6).

---

## Phase C — five beacons, live positioning

### C1. Wire and mount all five beacons

1. [ ] Wire all five beacons per [WIRING.md](WIRING.md) (Ethernet harness or taped
       Dupont runs; B5 on its own run if one cable covers B1–B4).
2. [ ] Mount per the §2.2 height table: B1 front-left **1.8 m**, B2 front-right
       **0.3 m**, B3 back-right **1.8 m**, B4 back-left **0.3 m**, B5 left
       **1.0 m** — sound openings facing the mat.
3. [ ] Every wire off the floor and out of the walking area; both ends of every run
       labeled B1…B5.

**PASS:** *"Wire and mount all 5 beacons per section 2.2, with different heights,
wires off the floor and labels on."* (§10 Phase C) — mechanically: five mounted
buzzers at five distinct heights, no wire reachable by a walking person, labels on
both ends.

### C2. Tape-measure the beacon positions

1. [ ] With a tape measure, measure each buzzer's position relative to the **mat
       origin**: **x** right, **y** forward (the tape-arrow direction), **z** up, in
       meters (§2.1, §2.2). Measure to the buzzer itself, not its wire.
2. [ ] Enter the positions in the app: Calibrate screen → beacon positions (edit in
       place, or import a `beacons.json` / full `space.json` file — the app accepts
       either, §2.2, §8.3).
3. [ ] If the Calibrate screen warns that all heights are within 0.5 m of each other
       (§8.3), fix the mounting — the 3D solve needs the height spread.

**PASS** (mechanical, from C2's definition in §10): the five positions entered in the
app match the tape measure to within 2 cm, and no height warning is showing.

**On fail / rule:** never move a beacon after this step without re-measuring — tape
firmly ([WIRING.md](WIRING.md) §9). A moved beacon silently invalidates C4–C6.

### C3. Template capture

Per the Calibrate screen's guided flow (§8.3), for each beacon B1…B5:

1. [ ] Hold the phone ~10 cm from beacon Bn, bottom edge facing it. Tap **Capture**;
       the app records 3 s (10 cycles), aligns and averages the copies coherently.
2. [ ] Read the per-template SNR the app shows.

**PASS** (per §8.3): each beacon's template SNR **≥ 20**, and **≥ 8 of 10** copies
detected. The app reports fail otherwise.

**On fail:** distance the phone 10 cm *exactly* (closer can overload the mic),
re-check the band config (B3), and check that beacon's SNR at 1 m (B4 numbers).

### C4. Verify on the mat

1. [ ] Stand on the mat, phone at chest, upright, bottom edge uncovered (§1).
2. [ ] The Calibrate verify step shows the solved mic position and its distance from
       [0, 0, 1.25] (§8.3).

**PASS:** *"horizontal error < 10 cm"*, and the height is plausible (§8.3, §10 C4).

**On fail:** re-check C2 numbers (a 10 cm wiring-label error is a 10 cm solve error),
then the height spread, then re-run C3 for any beacon the Debug screen shows with
low SNR.

### C5. Taped floor marks

1. [ ] Tape **4 marks** at **1–1.5 m** from the origin, in different directions.
2. [ ] Measure and enter each mark's coordinates where the human is asked for them
       (Calibrate check-marks step, §8.3).
3. [ ] Stand on each mark in turn; the app shows the error per mark.

**PASS:** *"median error < 10 cm, max < 20 cm, quality ok at ≥ 90% of fixes."*
(§10 Phase C)

### C6. Walking test

1. [ ] Start `make fakehub` (from `locator/`) on the Mac — it validates every message
       against `contracts/` and records `listener_pose` to JSONL (§7.6).
2. [ ] **Hand mode:** walk a normal loop around the space (mat → cupboard → around),
       phone at chest.
3. [ ] **Pocket mode:** switch mode in Settings and repeat with the phone upside-down
       in a shirt pocket (§1) — pants pockets are not supported (§1).
4. [ ] Run `tools/analyze_log.py` on the fake_hub recording for each mode (§7.5).

**PASS:** *"a continuous track with no lost periods during a normal walk around the
space. Run analyze_log.py on the recording and report."* (§10 Phase C) — mechanically:
zero `quality: "lost"` stretches in either mode's JSONL, and the analyze_log plot
shows a closed loop, not jumps.

**On fail:** echo-shaped errors → the brief's echo fallbacks: `gate_ms` 2.0,
`slot_ms` 70, then inspect the first-arrival parameters on the log (§11.2) →
body-shadowing (worst behind you) → more high-mounted beacons / the 3-beacon
height-prior path (§11.3).

---

## After Phase C

Phase D is integration with the real Mac hub — the other repo's session is the
counterparty. Before plugging in, hand them
[CONTRACT_NOTES.md](CONTRACT_NOTES.md) (and its Appendix B block): it records what
today's hub actually speaks and what the locator will send. Phase D's own gate —
run CONTRACT_NOTES against the other repo's actual schemas and report any mismatch
immediately (§10 Phase D) — lives there too.
