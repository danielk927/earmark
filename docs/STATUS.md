# Earmark status

Last updated: 2026-10-24 08:20 PDT (Phase 1 complete and merged; Phase 2 integration verified across real processes; Phase 3 reviews starting).
The orchestrator is working autonomously overnight while the human sleeps; checkpoints that ask for human confirmation are recorded here instead of blocking.

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
| contracts | done | Python (59 tests), TS (generated + type-checked), Swift (swift-testing) validate every example, config file, and scenario line | - |
| scenarios | done | `scripts/gen_scenarios.py`; every line validates against the bus schema | - |
| Convex AI guidelines | done | `npx convex ai-files install` wrote `convex/_generated/ai/guidelines.md`, `AGENTS.md`, `CLAUDE.md`, and 33 skills | - |
| hub | done (Phase 1) | 140 tests: debounce, state engine, every scenario, bus routing, offline Convex queue, CLIs, trial CLI; smoke run over the real WebSocket | Convex (fake server), BLE (fake bleak), serial (fake port), camera (stub) |
| convex | done (Phase 1) | 108 tests (adherence incl. DST, every HTTP route validated against the schemas with ajv, client-function type contract, seed/reset keeps trials); live on the local anonymous backend; liveMap update 15 ms after /ingest | Bitdeer photo labeling (mocked fetch; no key) |
| concierge | done (Phase 1) | 167 tests; every scenario with LLM off; STT/TTS fallbacks against fake Cartesia servers; real-process integration | Cartesia (fake servers), Bitdeer (fake), Moss (fake; real SDK fails fast to fallback) |
| Mac app + spatial spike | done (Phase 1), gate pending | 70 Swift tests incl. offline-rendered ear checks for both Option A variants; both bundles signed (Apple Development, hardened runtime); against the real hub + concierge it plays every utterance (playback started 20-290 ms after speak_text), reports status every 5 s, and follows stt_mode | AirPods head tracking (mock head); mic and Apple Speech never started (no permission prompts while unattended) |
| dashboard | done (Phase 1), polish in progress | 134 vitest tests, axe 0 violations (light/dark/phone), lint, build; screenshots of every page against the live local Convex (`dashboard/e2e/live.mjs`) | photo labeling suggestion (no Bitdeer key) |
| memory agent | done (Phase 1) | 94 tests; Chat Protocol handler + a real two-uAgent exchange offline; boots on 3.12 and publishes the AgentChatProtocol manifest; answers all example questions from the live local Convex ("Did Mom take her evening pills?" -> the seeded missed dose) | Bitdeer (scripted; keyword router answers without a key); Agentverse/ASI:One not exercised (needs the human's browser login) |

## Research findings that change the plan

1. **Cartesia STT cost:** Ink 2 bills about 10,800 credits per hour even for silence; the free plan covers under 2 hours of always-listening.
   The Mac app streams audio only while push-to-talk is held or its local voice detector fires (plus 1 s of trailing audio), and the concierge opens the STT socket lazily.
2. **Cartesia turn detection** exists only for `ink-2` on `wss://api.cartesia.ai/stt/turns/websocket`; audio goes as raw binary PCM frames, 16 kHz.
   TTS is `sonic-3.6-2026-08-27` (pinned so cached phrases match live speech), streamed as raw `pcm_f32le` at 48 kHz.
3. **Bitdeer reasoning is on by default** on every chat model (12-17 s responses); every latency-sensitive call sends `reasoning_effort: "none"`.
   Tool calling and strict JSON schema output are supported.
   Model IDs change weekly (7-day notice, no redirects); the workshop code's model is removed on 2026-10-26.
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

## UWB track: what's verified in software vs pending on device

As of 2026-10-25, branch `uwb-prd`.
Nothing UWB has run on a phone yet.
The Mac and iOS code was written without a Swift toolchain and has **not been compiled** (not locally, not in CI); expect small fixes on the first Xcode build (`ios/README.md`, `mac/README.md`).

| Piece | Verified in software | Pending |
|---|---|---|
| contracts | Python suite passes (68 tests), including `config/space.json` with `anchors` and `tracking` and every `uwb_walk` line; TS check passes | Swift suite not run (no toolchain here) |
| hub | 219 tests pass, 78 of them UWB unit tests (PRD 12.1): solver (exact, σ 0.07 m median < 0.10 m, +0.4 m block flagged, 2-anchor choice, speed gate, slant), freeze, voice freeze, NFC re-anchor, lost to fixed, token relay, bus secret, `uwb_sim` at 5 Hz or more. They found and fixed a speed gate that stalled fast walks, a mirror-point lock-on, freeze overshoot after a stop, and a repeating re-anchor. `make demo-uwb-sim` runs the scripted walk | Tuning on device. Near the counter the uwb_2-uwb_3 line passes 17 cm from the origin, so a block on uwb_1 there can go undetected; move uwb_3 off that line when placing anchors |
| scenarios, e2e | `scenarios/uwb_walk.jsonl` (start mark, walk, freeze, wrong jar). `test_uwb_walk` runs it through the real hub and concierge: tracked to frozen, meters phrasing then "You're at the counter", wrong-jar correction, "Got it". The full e2e suite passes | Runs at 1x speed because the tracker timers use wall-clock time |
| concierge | 232 tests pass, including the listener-aware phrasing tests | - |
| convex, dashboard | Convex 132 tests and typecheck pass (the seed now accepts `tracking`); dashboard 146 tests pass, including axe in both themes | - |
| `scripts/calibrate.py` | Anchor and wearer prompts dry-run with piped input to a temp file; the output validates against `space.schema.json` and `earmark_contracts.Space`, and the hub's tracker loads it | - |
| Mac app (listener position, map, Calibrate screen) | - | Not compiled; `make mac-test` not run |
| iOS app `ios/EarmarkUWB` | - | Not compiled; needs Xcode; every gate below |

The hub logs listener mode changes and NFC re-anchor correction sizes, but never positions, so `logs/hub.jsonl` holds no pose history (`docs/RESPONSIBLE_DESIGN.md` 4.1).

## On-device gates (UWB)

From `docs/UWB-PRD.md` 12.2. Run in order; procedure in `ios/README.md`.
For each gate also note the phone models and iOS versions, the anchor positions used (`python3 scripts/calibrate.py --show`), and anything odd (session restarts, rates, round-robin needed or not).

| # | Gate | Pass | Date/time | Phones (model, iOS) | Result | Pass/fail | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Ranging: one anchor + wearer, tape at 0.5 / 1 / 2 / 3 m | Each within ±0.10 m, averaged over 2 s | | | | | |
| 2 | Concurrency: wearer with three sessions for 2 minutes | At least 5 Hz per anchor the whole time | | | | | |
| 3 | Position: stand on 5 floor marks | Median error ≤ 0.20 m, max ≤ 0.35 m | | | | | |
| 4 | Freeze: walk to the counter 10 times, stop naturally | Frozen point ≤ 0.15 m from the mark in 8 of 10 | | | | | |
| 5 | Body block: body between the phone and one anchor | Outlier flagged in `blocked`; pose jumps no more than 0.3 m | | | | | |
| 6 | Walk: eyes closed, start mark to the sugar, 5 attempts, with a spotter | 4 of 5 lift the correct jar (NFC-confirmed) | | | | | |

Gate 1 readings:

| True distance | Mean reading | Spread | Error |
|---|---|---|---|
| 0.5 m | | | |
| 1 m | | | |
| 2 m | | | |
| 3 m | | | |

Gate 3 readings (the Mac app's Verify marks):

| Mark | Expected (x, y) | Solved (x, y) | Error |
|---|---|---|---|
| Origin | (0, 0) | | |
| 1 m back | (0, -1) | | |
| 2 m back | (0, -2) | | |
| 1 m left | (-1, 0) | | |
| 1 m right | (1, 0) | | |

Bake-off with the sound track (PRD 13.10, gates 3, 4 and 6): decision: -

## Contract changes

- 2026-10-24: initial contracts.
  Bus messages added beyond the brief's table: `hello`, `snapshot`, `registry_update`, `unknown_tag`, `label`, `stt_mode`, `guide_feedback`, `speak_text`, `playback`, `reset`.
  Convex client-function contract added in `contracts/ts/convexFunctions.ts`.
- 2026-10-24: added `registry_response` to `convex_http.schema.json` (GET /api/registry with required `version`), proposed by hub-builder. Documented `roaming` as "tracked by any non-spot method" and the pickup debounce bias.

- 2026-10-24 (uwb-leo): UWB walking guidance (docs/UWB-PRD.md section 9).
  - Bus: `component` gains `ios_anchor` and `ios_wearer`. `hello` gains optional `device_id`, `role` and `secret`.
  - Bus: new `uwb_token`, `uwb_range`, `motion_state`, `listener_pose` and `listener_command`.
  - `listener_pose` carries optional per-anchor health.
  - `listener_command` (`freeze` | `recenter`) is new beyond the PRD. It lets the concierge's "I'm here" reach the hub, and "recenter" reach the Mac app.
  - `space.json` gains optional `anchors[]` and `tracking {phone_z, head_offset_m}`.
  - `/ingest` gains optional `anchors[]` (`ingest_anchor`) and `pose` (`ingest_pose`).
  - `LiveMap` gains `anchors` and `wearer`.
  - The Swift package now also targets iOS 17.

## Deferred contract proposals

- memory-agent-builder: add `window_minutes` to `dose`, and `near_label`/`area_label` to `object_summary.state` (the agent reads `config/space.json` for labels today).
- convex-builder: document that `untouched_7d` covers tagged objects only, that `date` defaults to today, the 500/500 ingest cap, and 404 for unknown objectIds.

## Decisions

- 2026-10-24: the human authorized fully autonomous work overnight; Phase 0 and Phase 2 checkpoints are recorded here rather than blocking.
- 2026-10-24: one uv project per Python service (no shared workspace lockfile) so parallel builders never conflict; each depends on `contracts/python` by path.
- 2026-10-24: all wire and disk JSON is snake_case; Convex tables and Convex client functions are camelCase.
- 2026-10-24: pepper is seeded without a home spot (pantry), so "something for my eggs" has two candidates while the four demo spots stay salt, sugar, medication, and one free spot.
- 2026-10-24: the hub talks to Convex over plain HTTPS to HTTP actions (the Python `convex` client's `subscribe` blocks other threads).
- 2026-10-24: not installed: Convex's optional user-scope Claude plugin (it would change the human's global setup).
- 2026-10-24: the simulator gets an interactive Wizard-of-Oz mode (keys lift/place jars) so `make demo-sim` works live with no detection hardware.

## Blockers needing the human (batched)

1. **AirPods spatial gate** (most important): wear the demo AirPods and run the spike per `mac/README.md`; set system Spatial Audio to Off for Earmark from the AirPods menu-bar icon.
2. **Keys** (put them in `.env`; see `.env.example`):
   - Cartesia API key plus a chosen voice ID.
   - Moss project ID and key (portal.usemoss.dev; redeem code CALHACKS on the billing page).
   - Bitdeer API key; also tell me how many credits the form granted.
   - Fetch.ai: a seed phrase (`MEMORY_AGENT_SEED`), plus a browser login to agentverse.ai and asi1.ai for the mailbox step.
3. **Convex:** run `npx convex login` so the backend can move from this Mac to a cloud deployment (phones and the memory agent need it).
4. **Hardware facts:** NFC module model, microcontroller board, number of readers, BLE fob model.
5. **Repo visibility:** Fetch.ai requires a public repo; OK to make `danielk927/earmark` public before submission?
6. **Azure:** whether Azure for Students is activated and on which account.
7. **Customer research:** has anyone talked to a blind or low-vision person or an accessibility professional? (`docs/CUSTOMER.md` never invents interviews.)
8. **Timing:** the Convex workshop "Build Your Backend with Convex" is today, Saturday, 4:00-5:00 PM PDT at Gate 3.
9. **Product decisions:** whether to add Fetch.ai bonus items (Payment Protocol, multi-agent, Interactive Cards); stretch items (Creao, Visa + Apify) stay off unless approved.
10. **Bluetooth permission:** launch the hub once from Terminal.app and accept the Bluetooth prompt before using real fobs.
11. **UWB walking demo:** install Xcode (large; gates the iOS app), four UWB iPhones (iPhone 11 or later, not SE), a travel router or a fifth phone's hotspot, and about 3 x 3 m of clear floor in front of the counter (`docs/UWB-PRD.md` 13).
