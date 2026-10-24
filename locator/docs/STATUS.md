# STATUS.md — Earmark locator component status

Living status file (brief §9.1); format follows the brief's reporting format (§12).
Update it whenever a phase checkpoint is reported or a PR changes the state below.

**Last updated:** 2026-10-24 · **Phase:** A (no hardware) · **This PR:**
`feat/locator-hardware-docs` (hardware documentation).

---

## 1. Component table

| Component | Status | What's verified | What's simulated / not yet |
|---|---|---|---|
| Contracts, configs, Makefile, CI | **done** — merged (GitHub PR #2, `8895e0e`) | 48 pytest tests pass locally (2026-10-24) and on CI (`locator-tests` green on main); schemas validate every example and reject extra fields, bad enums, missing fields; configs match the brief's §2.2/§4.6/§8.6 defaults | — |
| Hub integration facts + bridge design | **done (documented)** | Verified against the hub's live source (`hub/earmark/hub.py`, `brain.py`, `server.py`, 2026-10-24): endpoint `ws://<mac-ip>:8765/ws`, no token auth (hello role = any string), unknown types silently ignored, native `pose` merges pos/yaw independently, **no** `listener_pose`/`mic_audio`/`ptt`/`status` handlers yet. Recorded in [CONTRACT_NOTES.md](CONTRACT_NOTES.md) and [contracts/README.md](../contracts/README.md) | The bridge itself ships in the iOS PR's network layer — wire-verified behavior vs. the live hub not yet exercised end-to-end |
| Python tools (`sim_beacons.py`, `pipeline.py`, `band_test.py`, `analyze_log.py`, `fake_hub.py`) | **not on main** — tools PR pending | — | All of §7, including the §7.7 acceptance criteria; `make sim` / `bandtest` / `fakehub` are scaffolded targets until then |
| Beacon firmware (`firmware/beacons/beacons.ino`) | **partial** — firmware PR (GitHub #3, draft) | Compiles for ESP32 (WROOM map default, WROVER alternative) with arduino-esp32 core 3.x per PR #3; native/host-side tests per that PR | Slot-start jitter ≤ 20 µs RMS (§4.4), upload, NVS persistence, acoustics — unverified until Phase B |
| iOS app (`ios/EarmarkLocator/`) | **partial** — iOS PR (GitHub #1, draft) | Swift core builds in CI (macOS) per PR #1 | On-device audio capture, detection, solving, screens, PTT streaming, and the Swift↔Python parity check (§9.4) — unverified |
| Hardware documentation (this PR) | **done** | Every Phase B/C pass criterion traceable to a BRINGUP checklist item; every part in WIRING.md traceable to a §3/§5 hardware fact; contract notes consistent with `contracts/` | Photos optional (§5) — none yet; WROVER pin map untested on real hardware |
| Vendor notes (`ios/vendor-notes/apple.md`) | **owned by the iOS PR** | — | Out of scope here by rule: this docs PR does not create Apple notes; cross-links are added when the iOS PR lands |
| Parity check (`scripts/parity_check.sh`, §9.4) | **blocked** | — | Needs tools PR + iOS PR; not run |
| Phases B–E | **not started** | — | Need the human-in-the-loop hardware steps ([BRINGUP.md](BRINGUP.md)) |

## 2. Measured numbers

- **48/48** locator tests pass locally (2026-10-24, Python 3.11); CI `locator-tests`
  green on merged main.
- No hardware measurements yet (Phase A): SNR, fix rate, error, latency are all
  Phase B/C deliverables (§12) — none exist, and none are claimed.

## 3. Blockers needing the human (batched §3 facts — ask once, together)

1. **ESP32 module:** WROOM or WROVER? Read the metal can. (WROVER: GPIO 16/17 are
   taken by PSRAM — pin map switches; [WIRING.md](WIRING.md) §2.)
2. **Bare buzzers:** magnetic or piezo? (Usually marked +/− with a coil inside; §3.)
3. **Buzzer module:** 2 or 3 pins? On-board transistor (active-low)? Pin labels?
4. **Transistor markings:** S8050, PN2222, or other (affects the datasheet pinout
   check in [WIRING.md](WIRING.md) §3).
5. **Desk permissions:** soldering station and hookup wire available? May the Ethernet
   cables be cut? ([WIRING.md](WIRING.md) §8.)

## 4. Next three actions

1. **Land the Python tools PR** — unblocks the §7.7 simulator acceptance criteria and
   the `make sim` / `bandtest` / `fakehub` targets BRINGUP relies on.
2. **Merge the firmware PR (#3) and iOS PR (#1)** once their CIs are green — Phase B
   step B1 (`make flash`) is the exact first hardware step after that.
3. **Phase A checkpoint:** report status to the human, hand over the §3 fact batch
   above in one message, and tell them the first hardware step is B1 in
   [BRINGUP.md](BRINGUP.md). Stop there (§10 Phase A.6).
