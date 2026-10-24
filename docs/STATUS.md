# Earmark status

Last updated: 2026-10-24 03:50 PDT (Phase 0 done; Phase 0.5 and Phase 1 building in parallel).
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
| hub | building | - | - |
| convex | building | - | - |
| concierge | building | - | - |
| Mac app + spatial spike | building | - | - |
| dashboard | building | - | - |
| memory agent | building | - | - |

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

- 2026-10-24: initial contracts.
  Bus messages added beyond the brief's table: `hello`, `snapshot`, `registry_update`, `unknown_tag`, `label`, `stt_mode`, `guide_feedback`, `speak_text`, `playback`, `reset`.
  Convex client-function contract added in `contracts/ts/convexFunctions.ts`.

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
