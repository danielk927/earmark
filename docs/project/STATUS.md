# Earmark status

Last updated: 2026-10-25 (venue Wi-Fi without hotspots: the judge phone through a tunnel; AirPods stem squeeze to talk).
Sponsor prizes, what each wants, and what we do: `docs/sponsors/TRACKS.md`. What is left to do and who does it: `docs/project/NEXT_STEPS.md`.

## What changed in the latest pass

- **No hotspot needed** (branch `phone-tunnel`). The venue forbids hotspots, and its Wi-Fi (like the school's) keeps phones from reaching the Mac; tested 2026-10-25: a phone could not open a page served by the Mac. `make session TUNNEL=1` starts a Cloudflare tunnel (ordinary outbound HTTPS from the Mac) and prints a name to type on the judge phone. Tested on that Wi-Fi with a phone-sized stream (1 Mbit/s) from Safari on the phone to the Mac for 60 s: nothing lost, typical extra delay 10 ms, 95% under 0.2 s, one 1.2 s hiccup. Timing comes from the phone's sample numbers, so delay never changes distances, only how fresh a position is. The judge's room audio passes through Cloudflare (TLS, not stored).
- **A Wi-Fi blip no longer forces a recalibration.** The phone keeps recording through a dropout, holds up to 6 s and resends it after rejoining under the same recording name; the Mac keeps its calibration. Tested with a fake microphone and a fake Mac that drops the link. **The phone app must be rebuilt and reinstalled** (Xcode) for this and for typing the tunnel name; not yet run on a real iPhone.

- **Squeeze an AirPod stem to talk** (Mac app, push-to-talk mode): squeeze once, hear a short rising sound, speak; it stops by itself 1.5 s after you stop talking (falling sound), or on a second squeeze, after 5 s with no speech, or at 20 s. A squeeze also cuts Earmark off mid-sentence. The squeeze reaches the app as a play/pause command, so Earmark claims Now Playing; music or a video playing on the Mac can take the squeeze instead. Taking an AirPod out sends the same command; that false start ends after 5 s. Tested with unit tests only: **not yet tried on real AirPods.**
- **"I'm leaving my keys here" is saved where you said it.** The concierge read the position after the language model answered, so a user already walking back was saved at the mat (this was the failing `test_put_here` end-to-end test).
- **The user's phone reconnecting no longer gives wrong positions.** Its sample counter skips the seconds it was offline, so the old calibration gave confident nonsense; the Mac now drops the calibration, sends a `lost` pose and asks for a recalibration. An error in the solver or a console hook no longer stops the position service.
- **Smaller Mac fixes:** speech or an earcon arriving while the audio engine is stopped (a route change) no longer crashes the app; holding Space across a listen-mode switch no longer leaves the mic open; the routing debounce test no longer fails on a busy machine.
- **Known, not changed:** with exactly three beacons at one height, a single wrong distance cannot be detected and the position is still marked `ok` (`services/ranging/README.md`, "Known limits").

## Earlier pass (2026-10-24 night)

- **Why calibration failed on real phones (found by analysing `services/ranging/runs/*.wav`):** the beacon phone was set to Beacon 2 (a down chirp, 125 ms into the cycle) while the Mac was told B1 (an up chirp), and the detector also reported weak opposite-sweep "ghost" chirps 32 ms after each real one. The Mac calibrated on the ghosts ("ragged", "phase off by +88 ms") and then gave random distances. Fed the right beacon, the same recordings calibrate to 0.028 ms (about 1 cm) and hold 1.00 m ±2 cm for 100 s.
  Fixed: ghost suppression in the detector; a plain-words warning when chirps arrive from a beacon number nobody configured (and no calibration start while a configured beacon is silent); replay now uses the recording's own temperature and calibration length.
- **Two beacons now give a position** (circle intersection at chest height, user stays on one side of the line; reported as "degraded"). Room setup works with two beacons. Use `make room-setup ONLY="B1 B2"` and `make room-recalibrate ONLY="B1 B2"`. Distances creep about 20 cm per 10 minutes (clock drift): the status line asks for a recalibration after 5 minutes. Simulated with two beacons: setup places both within centimeters and positions follow a walk. **Not yet run live with two real beacons.**
- **Bug sweep, by area** (each with tests): Mac app (head recenter no longer jumps when a device changes mid-guidance, relative target after renderer change, UI uses the locator, push-to-talk cap and release on focus loss, Apple Speech permission order, transcripts queued while the bus is down, PHASE lock); concierge (follow-up answers keep the place, Claude knows "it", free-text items in place_item, Moss timeout and background retry, TTS socket warmed at start, Ink watchdog ignores held-silence, height wording no longer says "down low" for counter spots, no double speech without the Mac app); hub (bus clients can no longer forge pickups into Convex, poller survives a bad reply, spoken place vs spot read and BLE ordering, reset reloads `space.json`); Convex (reset clears "stored" events, schedule edits no longer invent missed doses, photo action rate limit, registry `version` contract fixed); dashboard (`/room` item names can no longer inject HTML, wss on https, status text instead of colour only, medication form no longer overwrites others' edits); locator app default now speaks the current hub protocol.
- **Environment fixes:** macOS hides the venv `.pth` files, so Python skipped them. The Makefile and `scripts/run_stack.sh` now put the packages on `PYTHONPATH`, so every target works; `make fix-venvs` un-hides them. `make mac-test` had a shell syntax error and is fixed. 10 cached phrase WAVs were generated into `config/phrases/` (rebuild the Mac app with `make mac` so it bundles them). `services/ranging/runs/` and `out.csv` are now gitignored.
- **Tests now:** contracts 67 (Python) + TS + Swift, hub 158, concierge 202, ranging 43, Convex 114 + typecheck, memory agent 97, dashboard 151 + typecheck/lint/build, Mac Swift 80 (the Swift tests do run on this Mac), end-to-end 8.
- **Still open for the session:** item positions in `config/space.json` must be re-measured in the locator frame (z from the floor; the placeholder spots are at z = 0); the dashboard's Convex functions still have no login; the Mac app was not run against real AirPods after these changes; the spoken-place-versus-spot-read rule means an item still on its spot flips back to the spot on the next read.

## Earlier pass (kept for history)

- **AirPods test passed (reported by the team, 2026-10-24):** with real AirPods Pro the 3D ping works and follows head turns, head tracking runs at about 54 per second, output stays at 48 kHz, and the app correctly switches the mic to the Mac. The detailed pointing scores in the table below were not filled in.

- **Live room page built** (`/room` on the dashboard, `dashboard/src/room/`): a black-on-white 3D model of the room (three.js) that follows the user's position live, with guidance, conversation, memory and items beside it. Tested in a browser with virtual phones and the keyboard walking simulator; not yet with real phones. The setup now uses 3 beacon phones plus the user's phone (`config/beacons.json`, hiding places at real room size in `config/space.json`).
- **First real phone test (2026-10-24, two iPhones on a hotspot, 0.75 m apart):** the phone-to-phone distance works. In the audible band (`--audible`, 2000 to 4500 Hz) the Mac measured 0.73, 0.74 and 0.84 m, with a strong chirp (strength about 34). In the quiet band (17000 to 20000 Hz) the chirp was weak (about 8), heard only part of the time, and measured 0.62 m. Next: range test at 1, 2 and 3 m, then the position fix with the user's phone plus 3 beacons. The school Wi-Fi blocks phones from reaching the Mac; the iPhone hotspot works for testing, a travel router is the plan for the demo.
- **Phones as beacons built:** `services/ranging` (the Mac side: tells phones when to chirp, listens, works out the position, sends `listener_pose` to the bus) and `locator/ios/EarmarkPhone` (the iPhone app, plus a Mac stand-in). The 17 tests with six virtual phones (own clocks, noise, walking, lost data) pass. In simulation it stays accurate until the background hiss is about as loud as the chirp from the farthest phone. The iPhone app now builds for an iPhone with Xcode (BUILD SUCCEEDED), and with Xcode installed all 75 Swift tests pass, including the new walking, louder/faster and arrival tests. **Not verified:** no real phone has played or heard a chirp, and the app has not been installed on a phone. Setup guide: `locator/docs/PHONE_BEACONS.md`.
- **Merged in Aidan's hardware work** (his repo is retired): `locator/` (beacon firmware, mic-only iPhone app, Python positioning tools; its 188 tests pass), `firmware/` (NFC reader, ESP-NOW gateway and Bluetooth anchor sketches), and `docs/project/HARDWARE_NFC.md` (his wiring guide). His own hub, dashboard, Mac app and camera-based iPhone app were not brought over.
  **Now connected** (see "Walking: the locator" in `docs/project/ARCHITECTURE.md`): the bus accepts `listener_pose` and `ptt` (and the locator's `hello` with a token, `status`, and `mic_audio` without a timestamp). The Mac app places the ping relative to the user, speeds it up and makes it louder as they approach, and stops at 0.5 m with an arrival tone (`guide_feedback arrived`). The concierge gives directions from the user's position and heading, says "You're here..." on arrival, and saves "I'm leaving my keys here" at the user's position. Verified by Python tests, a new end-to-end scenario (`put_here`), and a throwaway Swift program that exercised the Mac app's new logic against the mock renderer; the new Swift tests are written in the repo but cannot run on this Mac.
  **Not built yet:** the AirPods stem as push-to-talk and phone-microphone speech input (the Mac app only announces `ptt`), and nothing here has run against the real locator app, beacons or AirPods. The locator's own hub notes (`locator/docs/CONTRACT_NOTES.md`) describe Aidan's old hub, not this one.

- **Memory by named places.** The user says "I put my keys in the drawer"; Earmark saves it (a new `place_item` bus message and `stored` event, using the `areas` in `config/space.json`: the counter, cupboard, drawer, bag, box).
  "Where are my keys?" then says where and when it was noted, and "Where did I put my keys before?" lists the earlier place with its time.
  The dashboard timeline and the memory agent show these moves too.
  "Leaving it here" is not saved because the app does not know where the user stands; Earmark asks for a place. Place positions in `space.json` are placeholders to measure on the real table.
- **Claude replaces Bitdeer** everywhere: concierge tool choice (`claude-haiku-5-5`), memory agent (`claude-sonnet-5-5`), and photo labeling in Convex (`claude-haiku-5-5`). No Anthropic key exists yet, so all of it is tested against mocked HTTP only.
- **Stale test fixed:** the wrong-jar end-to-end test expected "one o'clock", but the concierge intentionally says "one spot to your right".
- **Test results this pass:** contracts (Python 62, TypeScript check), hub 145, concierge 179, Convex 109 plus typecheck, memory agent 97, dashboard 134 plus typecheck, lint and build, end-to-end 6 passed and 1 skipped (needs a local Convex).
- **Test results after the locator work:** contracts (Python 65, TypeScript check), hub 149, concierge 184, ranging 17, Convex 110, dashboard 139, memory agent 97, end-to-end 8 passed.
- *(Superseded: the Swift tests do run on this Mac, 80 pass, and the hidden `.pth` problem is worked around by the Makefile; see the latest pass above.)*

## Toolchain (demo Mac)

| Tool | Found | Notes |
|---|---|---|
| macOS | 26.5.1 on MacBook Pro M5, 24 GB | Meets the macOS 14+ requirement for `CMHeadphoneMotionManager`. The system clock is set to Central time (CDT); the demo household uses America/Los_Angeles. |
| Xcode | Not installed | An `Xcode-beta.app` in `~/Downloads` disappeared during the check. Command Line Tools only: Swift 6.1.2, macOS 15.5 SDK, swift-testing works, XCTest does not. The Mac app is a SwiftPM package bundled and signed by `mac/build_app.sh` (verified feasible tonight). |
| Code signing | `Apple Development: daniel214940@icloud.com (PDF7CUACBD)` | Stable identity, so mic/motion/speech permissions survive rebuilds. |
| Python | 3.15 default, 3.12 via uv, 3.11 and 3.14 via Homebrew, uv 0.11.3 | Every service pins 3.12 (uAgents crashes on 3.14+). |
| Node | 26.10.0, npm 11.19.1, pnpm | Convex "use node" actions need Node 22/24, so Earmark uses none. |
| git / gh | 2.39.5, gh logged in as danielk927 | Repo: https://github.com/danielk927/earmark (private). |
| just | Not installed | `make` is the task runner. |
| az / swa CLIs | Not installed | Only needed for the optional Azure deployment. |
| Docker | Not installed | Only needed if Azure's source builds are blocked for student subscriptions. |
| AirPods | Several paired, none connected | Needed for the Phase 0.5 spatial gate. |

## Components

| Component | Status | Verified | Mocked |
|---|---|---|---|
| contracts | done | Python (62 tests), TS (generated + type-checked), Swift (swift-testing) validate every example, config file, and scenario line | - |
| scenarios | done | `scripts/gen_scenarios.py`; every line validates against the bus schema | - |
| Convex AI guidelines | done | `npx convex ai-files install` wrote `convex/_generated/ai/guidelines.md`, `AGENTS.md`, `CLAUDE.md`, and 33 skills | - |
| hub | done (Phase 1) | 145 tests: debounce, state engine, every scenario, bus routing, offline Convex queue, CLIs, trial CLI; smoke run over the real WebSocket | Convex (fake server), BLE (fake bleak), serial (fake port), camera (stub) |
| convex | done (Phase 1) | 109 tests (adherence incl. DST, every HTTP route validated against the schemas with ajv, client-function type contract, seed/reset keeps trials); live on the local anonymous backend; liveMap update 15 ms after /ingest | Claude photo labeling (mocked fetch; no key) |
| concierge | done (Phase 1) | 179 tests; every scenario with LLM off; STT/TTS fallbacks against fake Cartesia servers; real-process integration | Cartesia (fake servers), Claude (fake), Moss (fake; real SDK fails fast to fallback) |
| Mac app + spatial spike | done (Phase 1), gate pending | 70 Swift tests incl. offline-rendered ear checks for both Option A variants; both bundles signed (Apple Development, hardened runtime); against the real hub + concierge it plays every utterance (playback started 20-290 ms after speak_text), reports status every 5 s, and follows stt_mode | AirPods head tracking (mock head); mic and Apple Speech never started (no permission prompts while unattended) |
| dashboard | done (Phase 1), polish in progress | 134 vitest tests, axe 0 violations (light/dark/phone), lint, build; screenshots of every page against the live local Convex (`dashboard/e2e/live.mjs`) | photo labeling suggestion (no Anthropic key) |
| memory agent | done (Phase 1) | 97 tests; Chat Protocol handler + a real two-uAgent exchange offline; boots on 3.12 and publishes the AgentChatProtocol manifest; answers all example questions from the live local Convex ("Did Mom take her evening pills?" -> the seeded missed dose) | Claude (scripted and mock HTTP; keyword router answers without a key); Agentverse/ASI:One not exercised (needs the human's browser login) |

## Research findings that change the plan

1. **Cartesia STT cost:** Ink 2 bills about 10,800 credits per hour even for silence; the free plan covers under 2 hours of always-listening.
   The Mac app streams audio only while push-to-talk is held or its local voice detector fires (plus 1 s of trailing audio), and the concierge opens the STT socket lazily.
2. **Cartesia turn detection** exists only for `ink-2` on `wss://api.cartesia.ai/stt/turns/websocket`; audio goes as raw binary PCM frames, 16 kHz.
   TTS is `sonic-3.6-2026-08-27` (pinned so cached phrases match live speech), streamed as raw `pcm_f32le` at 48 kHz.
3. **Claude settings** (checked against the current API docs): the concierge's Haiku call forces one tool, turns thinking off and sets effort `low` for speed; the memory agent's Sonnet call uses `thinking: between_tools` (Sonnet 5.5 rejects `disabled`) with effort `low` and no forced tool choice (Sonnet 5.5 rejects it); no `temperature` is sent (rejected on newer models).
   Bitdeer was dropped and its notes were deleted.
4. **Moss cold start needs internet** (credential check and model download); queries are in-process (about 6 ms).
   The concierge must start online, and falls back to alias/fuzzy matching on any Moss error.
5. **uAgents crashes on Python 3.14+**; the memory agent pins 3.12.
   Fetch.ai prize eligibility requires the whole workflow inside ASI:One, an Agentverse registration, the Chat Protocol, a **public** GitHub repo with run instructions, `innovationlab` and `hackathon` README badges, and a 3-5 minute demo video.
   Judging rewards Payment Protocol, multi-agent work, and Interactive Cards as bonuses (not in scope unless approved).
6. **Convex without an account** runs only on this Mac (anonymous local deployment); phone-based family labeling, the memory agent's access, and Azure all need a cloud deployment, which needs `npx convex login`.
   Queries cannot read `Date.now()`, so doses are materialized by mutations and a cron.
7. **Apple spatial audio:** Option A (`AVAudioEnvironmentNode` + manual head tracking) needs no entitlements and its conventions were verified by offline rendering.
   PHASE's automatic head tracking and the Personalized Spatial Audio profile need paid-team entitlements and a provisioning profile, so Option B is tested as PHASE driven by the same manual head tracker.
   `AVAudioEngine` follows the system default devices on macOS, so the system default input must not be the AirPods (or playback drops to hands-free quality); the app switches the default input to the built-in mic and shows it.
   Under hardened runtime the mic needs the `com.apple.security.device.audio-input` entitlement (not in the brief).
8. **BLE fobs:** by the Immediate Alert spec a disconnect ends the alert, so the hub holds the connection for the chirp and writes 0x00 before disconnecting.
   macOS grants Bluetooth to the terminal app, so the hub must be launched once from Terminal.app to accept the prompt.
9. **Azure:** Static Web Apps (free) for the dashboard, Container Apps (min 1 replica) for the memory agent; `az containerapp up --source` may be blocked on student subscriptions (needs Docker locally then).

| e2e | started (Phase 2) | `make e2e-test`: real hub + concierge processes, scenarios replayed over the bus: wrong_jar, moved_item, roaming_keys, missed_dose (and the seeded missed dose read back from Convex), full_demo - 6 passed | vendor keys blanked (grammar, fallback resolver, system voice) |

Phase 2 findings fixed so far:
- The concierge sent `stt_mode` only at startup, so a Mac app that connected later stayed on Cartesia (streaming into nothing without a key or during an outage). It now re-sends `stt_mode` whenever the Mac app's status reports a different engine.
- The keys questions in `roaming_keys` and `full_demo` came before the fob was first heard; they now come after, so the answer is the proximity phrase (definition of done item 4).
- Lint is part of `make test` for every Python service, with rules pinned per project.

## Spatial gate (Phase 0.5)

Not run yet: needs the human wearing AirPods (procedure will be in `mac/README.md`).

| Test | A: HRTFHQ | A: auto | B: PHASE (manual tracking) |
|---|---|---|---|
| Sign check | - | - | - |
| Fixed-in-room | - | - | - |
| Pointing (front, pass >= 8/10 within 20 deg) | - | - | - |
| Behind (4 trials, front/back confusions) | - | - | - |

## Audio routing check

Not run yet: confirm the AirPods output stays at 48 kHz (no hands-free mode) with the built-in mic capturing.

## Contract changes

- 2026-10-24: added the `place_item` bus message (concierge to hub: object id, saved place id) and the `stored` Convex event kind, with examples in `contracts/examples/bus/place_item/`. Swift treats `place_item` as an unhandled type (`other`), so no Swift change.

- 2026-10-24: initial contracts.
  Bus messages added beyond the brief's table: `hello`, `snapshot`, `registry_update`, `unknown_tag`, `label`, `stt_mode`, `guide_feedback`, `speak_text`, `playback`, `reset`.
  Convex client-function contract added in `contracts/ts/convexFunctions.ts`.
- 2026-10-24: added `registry_response` to `convex_http.schema.json` (GET /api/registry with required `version`), proposed by hub-builder. Documented `roaming` as "tracked by any non-spot method" and the pickup debounce bias.

## Deferred contract proposals

- memory-agent-builder: add `window_minutes` to `dose`, and `near_label`/`area_label` to `object_summary.state` (the agent reads `config/space.json` for labels today).
- convex-builder: document that `untouched_7d` covers tagged objects only, that `date` defaults to today, the 500/500 ingest cap, and 404 for unknown objectIds.

## Decisions

- 2026-10-24 (evening): positioning uses self-timed beacon phones plus a listen-only target phone with a 10 s calibration on the mat (see "How the user's position is found" in `docs/project/NEXT_STEPS.md`). Beacons are told apart by time slot in one shared band. The UWB branch (`uwb-prd`) and the ESP32 buzzer firmware are fallbacks, not merged. The parked `spec-b-core` branch is the same idea in Swift with no app around it; its tracker may be borrowed later.

- 2026-10-24: the human authorized fully autonomous work overnight; Phase 0 and Phase 2 checkpoints are recorded here rather than blocking.
- 2026-10-24: one uv project per Python service (no shared workspace lockfile) so parallel builders never conflict; each depends on `contracts/python` by path.
- 2026-10-24: all wire and disk JSON is snake_case; Convex tables and Convex client functions are camelCase.
- 2026-10-24: pepper is seeded without a home spot (pantry), so "something for my eggs" has two candidates while the four demo spots stay salt, sugar, medication, and one free spot.
- 2026-10-24: the hub talks to Convex over plain HTTPS to HTTP actions (the Python `convex` client's `subscribe` blocks other threads).
- 2026-10-24: not installed: Convex's optional user-scope Claude plugin (it would change the human's global setup).
- 2026-10-24: the simulator gets an interactive Wizard-of-Oz mode (keys lift/place jars) so `make demo-sim` works live with no detection hardware.

## Keys and accounts (checked 2026-10-24)

| Service | State |
|---|---|
| Anthropic | Key in `.env`; real calls verified: tool choice with Haiku (0.9 to 1.4 s each), family questions with Sonnet (4 to 8 s), both against the real Convex data |
| Convex | Dev deployment `diligent-ptarmigan-12`: functions deployed, demo data seeded, `EARMARK_HUB_SECRET`, `EARMARK_READ_SECRET` and `ANTHROPIC_API_KEY` set. The photo-naming action has not been run against a real photo yet |
| Moss | Verified: finds the right items ("something for my eggs" gives pepper and salt). The very first start took 7 minutes (it downloads a model); after that 2 seconds. Start it once well before any demo |
| Cartesia | Key and voice in `.env`; real speech verified (first sound after about 2 seconds on a cold start). Listening (speech to text) not tried yet |
| Fetch.ai | Not started |

## Blockers needing the human (batched)

1. **AirPods spatial gate** (most important): wear the demo AirPods and run the spike per `mac/README.md`; set system Spatial Audio to Off for Earmark from the AirPods menu-bar icon.
2. **Keys** (put them in `.env`; see `.env.example`):
   - Cartesia API key plus a chosen voice ID.
   - Moss project ID and key (portal.usemoss.dev; redeem code CALHACKS on the billing page).
   - Anthropic API key (`ANTHROPIC_API_KEY`, also set on the Convex deployment for photo labeling); redeem the $50 credit link in `#cohost-anthropic`.
   - Fetch.ai: a seed phrase (`MEMORY_AGENT_SEED`), plus a browser login to agentverse.ai and asi1.ai for the mailbox step.
3. **Convex:** run `npx convex login` so the backend can move from this Mac to a cloud deployment (phones and the memory agent need it).
4. **Hardware facts:** NFC module model, microcontroller board, number of readers, BLE fob model.
5. **Repo visibility:** Fetch.ai requires a public repo; OK to make `danielk927/earmark` public before submission?
6. **Azure:** whether Azure for Students is activated and on which account.
7. **Customer research:** has anyone talked to a blind or low-vision person or an accessibility professional? (`docs/project/CUSTOMER.md` never invents interviews.)
8. **Timing:** the Convex workshop "Build Your Backend with Convex" is today, Saturday, 4:00-5:00 PM PDT at Gate 3.
9. **Product decisions:** whether to add Fetch.ai bonus items (Payment Protocol, multi-agent, Interactive Cards); stretch items (Creao, Visa + Apify) stay off unless approved.
10. **Bluetooth permission:** launch the hub once from Terminal.app and accept the Bluetooth prompt before using real fobs.
