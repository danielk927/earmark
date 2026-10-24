# EARMARK — Build Brief for Claude Code

> **For the human:** Put this file in the root of an empty git repo as `BUILD_BRIEF.md`, start Claude Code there, and send:
> `Read BUILD_BRIEF.md in full. Then execute Phase 0 and stop at its checkpoint.`
> Fill in the `[BRACKETED]` fields in section 10 as you learn them.

---

## 0. Your role and mission

You are the lead engineer and orchestrator for **Earmark**, a Cal Hacks 13.0 project. The hackathon ends **Sunday morning**, so treat time as the scarcest resource. Your job:

1. Build a working, demo-ready system that is independent of which detection hardware the team ends up using.
2. Parallelize the work with subagents wherever the work is genuinely independent (see section 7), and do the work yourself wherever it isn't.
3. Keep the human in the loop only for things you cannot do: API keys, physical hardware facts, tape-measure measurements, Apple code signing, and final judgment calls.

A small system that works live beats an ambitious one that doesn't. When in doubt, cut scope, not quality.

---

## 1. The product

Earmark is an assistive system that helps blind and low-vision people find everyday objects by sound. Each household object is tracked by some detection method (NFC "home spots," Bluetooth fobs, or others later). When the user asks, "Where's the sugar?", Earmark plays a spatial-audio ping through their AirPods from the exact direction of the object, using AirPods head tracking so the sound stays fixed in the room as they turn their head.

When an object is picked up, Earmark confirms it ("Got it, that's the sugar") or corrects the user if they grabbed a look-alike ("That's the salt. The sugar is one spot to your right"). Roaming items like keys carry Bluetooth fobs that chirp on command. Caregivers get a live dashboard and medication-adherence tracking. There are no cameras in the home, and the user never needs to touch a phone.

**The hero demo moment:** two identical jars, salt and sugar. A judge wearing AirPods asks for the sugar, follows the sound, and gets corrected out loud if they pick the wrong jar.

**Judging criteria:** real-world application, functionality, creativity, and technical complexity. The pitch is 2 minutes plus 2 minutes of Q&A.

---

## 2. Non-negotiable rules

1. **The contracts are law.** Every component communicates only through the schemas in `contracts/` (section 4). If a component needs a contract change, it stops and proposes the change to the orchestrator. Components never edit contracts unilaterally.
2. **Detection-agnostic by design.** Nothing downstream of the hub may know or care which detection method produced an event. Detection methods are adapters.
3. **Math lives in code, never in an LLM.** Directions, distances, angles, debouncing, and medication-adherence rules are deterministic code with tests. LLMs only (a) choose which tool to call and (b) phrase responses.
4. **Verify every third-party API against its current official docs before writing integration code.** Do not invent endpoints, package names, parameter names, or model IDs. Put every URL, model ID, and voice ID in config or environment variables, never hard-coded. Record what you verified in `docs/vendor-notes/<vendor>.md` with the doc URLs.
5. **Demo safety over cleverness:**
   - The local loop (detection → hub → concierge → Mac app → AirPods) must work with no internet except the speech API, and must degrade gracefully when that fails (cached phrases, then macOS `say`).
   - Every external call has a timeout and a fallback.
   - A keyword-grammar fallback handles the top voice commands if the LLM is slow or unreachable.
6. **Secrets** go in `.env` (gitignored). Commit `.env.example` with every variable documented. Never print secrets in logs.
7. **Accessibility is a feature, not a polish item.** The dashboard must be fully usable with a screen reader and keyboard: semantic HTML, ARIA where needed, visible focus, high contrast, no information conveyed by color alone, and both light and dark modes.
8. **No medical advice, anywhere.** Agents report what the events show and nothing more.
9. **Always runnable.** Every step ends with something that runs. Commit small, often, with clear messages. Keep `docs/STATUS.md` current.
10. **Ask the human only when blocked** on keys, hardware facts, measurements, signing, or a product decision. Batch your questions.
11. **AirPods spatial guidance is the core of the product, and it must work through Earmark's own app.**
    - The app itself renders the spatial audio and applies head tracking. It never depends on the system's Spatial Audio menu, which only applies to supported media content.
    - It is the first thing built and the first thing verified on real AirPods (see the Phase 0.5 spatial gate).
    - If it isn't working, nothing else matters. Escalate to the human immediately.

---

## 2.5 Official sponsor resources (read these before writing integration code)

These are the sponsors' own Cal Hacks materials. They override anything in this brief that conflicts with them. Save a copy or summary of each to `docs/sponsor-packs/<sponsor>.md`. If a link can't be fetched (for example, a Google Doc that requires sign-in), ask the human to export it as PDF or Markdown into `docs/sponsor-packs/`.

| Sponsor | Resources | What to extract |
|---|---|---|
| **Convex** | Home-page agent prompt: https://www.convex.dev (copy the prompt shown there and follow it) · Hackathon resources: https://www.convex.dev/hackathons/resources · Docs: https://docs.convex.dev · AI code-generation guidelines: https://docs.convex.dev/ai · ESP32 client (alpha): https://github.com/convex/convex-esp32 | Apply Convex's AI code-generation guidelines to this repo **before** convex-builder starts (install whatever rules or guideline files they provide). The prize is "Best Use of Convex." There's a workshop on building agentic apps on Saturday at 4 pm; tell the human if it's still upcoming. |
| **Fetch.ai** | Hack pack: https://docs.google.com/document/d/1pbsW7tH946iooPZxhn2FOuWZ1UjlEfJu4Hi9CQQPBpo/edit?tab=t.0 | Exact judging requirements, required protocols, registration steps, and any README or badge requirements. |
| **Moss** | Hack pack: https://docs.google.com/document/d/1V6M4Mone7edq5bNJk6e4f7TFri1FSQEIFbVTRJXSBVU/edit?tab=t.0 | SDK install, auth, index and query API, latency guidance, judging criteria. |
| **Cartesia** | https://docs.cartesia.ai/calhacks · Main docs: https://docs.cartesia.ai | Credits, judging criteria, current TTS model (Sonic) and STT model (Ink) names, streaming and WebSocket APIs, output formats. Cartesia's docs describe Ink 2 as real-time transcription with built-in turn detection, so use it as Earmark's primary speech-to-text (see 5.D and 5.E). |
| **Bitdeer AI** | Starter pack (the human has a PDF): create an account at bitdeer.ai, submit the credit request form, then open **Model Studio** in the left sidebar to create an API key, test models, and monitor credits. The pack links a Getting Started guide, a Model Catalog, an Integrations guide, and Python workshop demo code; find these from bitdeer.ai or ask the human for the links. | Available models: **chat** (text-only and multimodal text + image), **embeddings** (`BAAI/bge-m3`), **reranker** (`BAAI/bge-reranker-v2-m3`), and **image generation** (`byteplus/Seedream-5.0-Lite`). Confirm the base URL, the chat model IDs, and whether the chosen chat model supports tool or function calling. |
| **Microsoft** | Challenge brief (below) · Azure for Students credits: https://azure.microsoft.com/en-us/free/students | See the criteria below and section 6.1. |

**Microsoft challenge, verbatim intent:** build a production-minded AI agent that solves a meaningful problem in finance, productivity, healthcare, or another high-impact domain. Judges look for:
1. Customer understanding
2. Measurable usefulness
3. A path from prototype to production
4. Responsible design
5. End-to-end functionality

The prizes are **Grand Prize: Built for the Real World** and the **Microsoft Customer Impact Award**.

---

## 3. Architecture

```
            ┌─────────────── Detection adapters (pluggable) ───────────────┐
            │ simulator (always) │ nfc_serial │ ble_fobs │ camera (stub)   │
            └──────────────────────────┬───────────────────────────────────┘
                                       │ DetectionEvent
                                       ▼
                     ┌──────────────── hub (Python) ────────────────┐
                     │ debounce · state engine · pickup detection   │
                     │ registry cache · local WebSocket bus :8765   │
                     └───────┬──────────────────────┬───────────────┘
            bus messages     │                      │ HTTPS (secret header)
        ┌────────────────────┼───────────┐          ▼
        ▼                    ▼           │   ┌────────────── Convex ──────────────┐
 concierge (Python)   Mac app (Swift)    │   │ objects · spots · areas · events  │
 voice agent:         head tracking      │   │ objectState · medications · doses │
 Moss + LLM tools     spatial ping       │   │ HTTP actions · crons              │
 + Cartesia TTS ────▶ speech playback    │   └──────┬──────────────────┬─────────┘
                      mic → STT ─────────┘          │                  │
                         │                          ▼                  ▼
                         ▼                  dashboard (React)   memory_agent (Fetch.ai
                      AirPods               caregiver + family  uAgent, Bitdeer LLM)
                                            labeling                ◀── ASI:One
```

### Repo layout

```
earmark/
  BUILD_BRIEF.md
  contracts/            # JSON Schemas + example messages (source of truth)
  config/               # space.json (spots/areas/listener), objects.seed.json, phrases.json
  convex/               # Convex backend (TypeScript)
  dashboard/            # React + Vite caregiver dashboard (Convex client)
  services/
    hub/                # Python: adapters, state engine, bus, Convex sync
      adapters/         # simulator.py, nfc_serial.py, ble_fobs.py, camera_stub.py
    concierge/          # Python: voice agent
    memory_agent/       # Python: Fetch.ai uAgent + Bitdeer
  mac/EarmarkApp/       # Swift macOS app (Xcode project)
  scenarios/            # JSONL event scenarios for the simulator
  scripts/              # dev/demo runners, calibration, latency report
  docs/                 # STATUS.md, vendor-notes/, DEVPOST.md, ARCHITECTURE.md
  .claude/agents/       # subagent definitions (section 7.2)
```

### Tech choices

- **Python 3.11+** with `uv` (or `pip` + venv) for `services/`. Suggested libraries, to be verified before use: `websockets`, `pyserial`, `bleak` (Bluetooth on macOS via CoreBluetooth), the `openai` client (Bitdeer exposes an OpenAI-compatible endpoint), the Moss Python SDK, the Cartesia Python SDK, `uagents` for Fetch.ai, and Convex's Python client (or plain HTTPS to Convex HTTP actions if simpler).
- **TypeScript** for Convex and the dashboard (React + Vite).
- **Swift + SwiftUI** for the macOS app, targeting macOS 14+ (required for AirPods head tracking via `CMHeadphoneMotionManager` on Mac).
- **Local bus:** a single WebSocket server inside the hub at `ws://127.0.0.1:8765`. Every local component connects as a client. JSON messages only, each with a `type` field.
- **Speech:**
  - **Speech-to-text:** Cartesia Ink (streaming, with built-in turn detection) is primary. Apple's on-device Speech framework is the fallback.
  - **Text-to-speech:** Cartesia Sonic.
  - Model names come from env vars, verified against Cartesia's docs.
- **Bitdeer usage:**
  - **Chat model:** concierge tool selection and the memory agent's reasoning.
  - **Multimodal chat model:** photo-assisted labeling in the dashboard (5.F).
  - **Embeddings, reranker, and image generation are deliberately not used in the voice loop.** Moss owns retrieval there. Don't build a second retrieval system that competes with it.
- **Cloud hosting for the production path (Microsoft):** Azure, using Azure for Students credits, for the dashboard and the memory agent (6.1). Convex stays the database. Treat this as optional until the human confirms the Azure account works.

---

## 4. Contracts (build these first, in Phase 0)

Write each as a JSON Schema in `contracts/`, with at least two valid example messages each in `contracts/examples/`. Generate or hand-write matching types for Python (dataclasses or pydantic), TypeScript, and Swift (`Codable`), and add a test that validates every example against its schema.

### 4.1 Coordinate system (used everywhere)

- Units are **meters**.
- The origin is the **calibrated listening position**: the center of the user's head while seated in the demo chair, or standing at the counter.
- **+x = right, +y = forward, +z = up**, from the user's perspective at calibration time.
- Head yaw is measured in degrees from the calibrated forward direction, positive turning right. Recentering sets the current head pose as yaw 0.

### 4.2 `DetectionEvent` (adapter → hub)

```json
{
  "type": "detection",
  "source": "simulator | nfc | ble | camera | ultrasonic",
  "tag": "04A2B3C4D5E6F7",
  "kind": "seen | placed | removed | lost",
  "where": { "spot": 3 },
  "precision": "exact | area | proximity | none",
  "rssi": null,
  "t": 1761350400.12
}
```

`where` is one of `{ "spot": int }`, `{ "position": [x, y, z] }`, `{ "area": "kitchen_counter" }`, or `{ "near": "receiver_id", "distance_class": "near | mid | far" }`.

### 4.3 `ObjectState` (hub → bus and Convex)

```json
{
  "type": "state_update",
  "object_id": "sugar",
  "location": { "spot": 3, "position": [0.15, 0.60, 0.0] },
  "precision": "exact",
  "status": "on_spot | held | missing | roaming",
  "home_spot": 3,
  "last_seen_t": 1761350400.12,
  "source": "nfc"
}
```

### 4.4 Bus messages

| `type` | Direction | Key fields |
|---|---|---|
| `mic_audio` | Mac app → concierge | `seq`, `sample_rate`, `encoding`, `chunk_b64` (streamed mic audio for Cartesia STT) |
| `transcript` | concierge → bus (from Cartesia STT), or Mac app → concierge (Apple Speech fallback) | `text`, `is_final`, `source` (`cartesia` / `apple` / `typed`), `t` |
| `trial_start` / `trial_end` | dashboard or CLI → bus | `trial_id`, `mode` (`earmark` / `baseline`), `target_object_id`; `trial_end` adds `outcome` |
| `guide_start` | concierge → Mac app | `object_id`, `target_position` [x,y,z], `precision`, `utterance_id` |
| `guide_stop` | concierge → Mac app | `reason` (`found` / `cancelled` / `timeout`) |
| `speak` | concierge → Mac app | `utterance_id`, `format`, `sample_rate`, `chunk_b64`, `final` (streamed PCM chunks) |
| `speak_cached` | concierge → Mac app | `phrase_id` (pre-synthesized audio bundled with the app) |
| `chirp` | concierge → hub | `fob_id`, `action` (`start` / `stop`) |
| `pickup` | hub → bus | `object_id`, `from_spot`, `t` |
| `pickup_result` | concierge → bus | `expected`, `actual`, `correct` |
| `head_pose` | Mac app → bus (debug only, ≤10 Hz) | `yaw`, `pitch` |
| `status` | any → bus | `component`, `ok`, `detail` |

### 4.5 `config/space.json`

```json
{
  "listener": { "label": "demo chair", "origin_note": "center of head, seated" },
  "spots": [
    { "spot": 1, "label": "far left",     "position": [-0.42, 0.42, 0.0] },
    { "spot": 2, "label": "center left",  "position": [-0.16, 0.58, 0.0] },
    { "spot": 3, "label": "center right", "position": [ 0.16, 0.58, 0.0] },
    { "spot": 4, "label": "far right",    "position": [ 0.42, 0.42, 0.0] }
  ],
  "areas": [ { "area": "kitchen_counter", "position": [0, 0.6, 0] } ],
  "receivers": []
}
```

These are placeholder positions: 4 spots in an arc about 60 cm from the listener, roughly 30° apart. Real values come from `scripts/calibrate.py` in Phase 4.

---

## 5. Component specifications

Each component gets a `README.md` covering how to run, test, and configure it. "Acceptance" lists what must be demonstrably true before the component counts as done.

### 5.A Simulator and scenarios (`services/hub/adapters/simulator.py`, `scenarios/`)

- Replays a JSONL file of `DetectionEvent`s with original relative timing, with flags for speed, looping, and a step mode (Enter advances one event).
- Write these scenarios:
  - `normal_pickup`: sugar lifted from spot 3, put back.
  - `wrong_jar`: target is sugar, but salt (spot 2) is lifted.
  - `moved_item`: sugar removed from spot 3, placed on spot 1.
  - `flicker`: rapid EMPTY/TAG alternation on one spot, which must not produce events after debouncing.
  - `missed_dose`: the medication on spot 4 untouched past its scheduled window.
  - `roaming_keys`: a BLE fob moving from far to near.
  - `full_demo`: the exact live demo sequence, in order.
- **Acceptance:** every scenario runs end to end through the hub, and the resulting state updates match the expected outcomes in a test.

### 5.B Hub (`services/hub/`)

- **Adapter interface:** `class Adapter: async def events(self) -> AsyncIterator[DetectionEvent]`. Adapters are enabled via config, and several can run at once.
- **`nfc_serial` adapter:**
  - Auto-detects the serial port, at 115200 baud by default.
  - Parses `SPOT <n> TAG <uid_hex>`, `SPOT <n> EMPTY`, and `SPOT <n> ERROR <reason>` lines.
  - Raw lines are logged to `logs/serial.log`.
  - The firmware itself is out of scope until the human confirms the board and module (section 10). When they do, write it in `firmware/` for the confirmed hardware: all readers on one shared SPI bus with a separate chip-select pin each, avoiding the board's boot-strapping pins, and emitting the line format above.
- **`ble_fobs` adapter (`bleak`):**
  - Scans continuously and smooths RSSI with an exponential moving average.
  - Maps RSSI to `distance_class` with configurable thresholds.
  - Handles `chirp` by connecting on demand and writing alert level `0x01` (start) or `0x00` (stop) to the Alert Level characteristic `0x2A06` of the Immediate Alert service `0x1802`. Then disconnect, because cheap fobs beep when a held connection drops.
  - Auto-stops after a configurable timeout.
  - Cheap fobs vary, so log the discovered services and characteristics for each fob and make the UUIDs configurable.
- **`camera_stub` adapter:** the interface only, plus a docstring describing how a future vision adapter would emit `position` events.
- **State engine:**
  - A placement requires 2 consecutive matching reads. A removal requires about 1.5 s of continuous absence (configurable).
  - Emits a `pickup` event when an object leaves its spot.
  - Tracks `status` for every object and resolves spot numbers to positions using `space.json`.
- **Registry:** maps tags to objects. Convex is the source of truth, cached locally in `config/objects.cache.json` so the hub works offline.
- **Convex sync:** sends events and state to a Convex HTTP action with a shared-secret header, with retry and an offline queue.
- **Acceptance:** unit tests for debounce and state transitions; all scenarios pass; the hub survives Convex being unreachable and catches up when it returns.

### 5.C Convex (`convex/`)

- **Tables:**
  - `objects`: `objectId`, `name`, `aliases[]`, `notes`, `tag`, `homeSpot`, `isMedication`, `fobId?`
  - `spots`: `spot`, `label`, `position`
  - `areas`
  - `events`: append-only
  - `objectState`: one row per object
  - `medications`: `objectId`, `scheduleTimes[]` (local times), `windowMinutes` (default 60)
  - `doses`: computed results: `objectId`, `scheduledFor`, `status` (`taken` / `late` / `missed` / `pending`), `evidenceEventId?`
  - `trials`: `trialId`, `mode` (`earmark` / `baseline`), `targetObjectId`, `startedAt`, `endedAt`, `secondsToFind`, `wrongPicks`, `outcome`, `tester` (a pseudonym only). See 5.I.
- **Follow Convex's AI code-generation guidelines** from https://docs.convex.dev/ai, applied in Phase 0. Use Convex's idioms (queries, mutations, actions, HTTP actions, scheduled functions, crons, and validators on every argument) rather than general-purpose backend patterns. The goal is "Best Use of Convex," so real-time reactivity should be visible in the demo.
- **Functions:**
  - An HTTP action `POST /ingest` (shared secret) that accepts events and state.
  - Queries for the dashboard, and mutations for registry editing.
  - **A deterministic adherence function:** a dose is `taken` if the medication object has a `pickup` within ±`windowMinutes` of the scheduled time, `late` if within twice the window, and `missed` after that. Unit-test it.
  - A cron that recomputes doses periodically and builds a `dailySummary`.
- **Read endpoints (HTTP actions, shared secret)** for agents: `GET /api/object?name=`, `GET /api/history?objectId=&since=`, `GET /api/adherence?date=`, and `GET /api/daily-summary?date=`.
- **Seed data:** salt and sugar in identical jars on spots 2 and 3, a blood-pressure medication on spot 4 scheduled at 08:00 and 20:00, keys on a fob, and two days of history including one missed dose.
- **Acceptance:** the schema deploys to a Convex dev deployment, the adherence tests pass, and the seed data loads with one command.

### 5.D Concierge, the voice agent (`services/concierge/`)

- **Pipeline:** `mic_audio` → Cartesia Ink streaming STT (with its built-in turn detection deciding when the user has finished speaking) → `transcript` → intent → Moss resolves the object → tool execution → response text → Cartesia Sonic TTS → `speak` chunks to the Mac app.
- **STT fallback:** if Cartesia STT is unreachable or slow (no partial transcript within 1 s of speech starting), tell the Mac app to switch to Apple Speech and accept its `transcript` messages instead. The `--text` CLI flag injects typed transcripts for testing.
- **Bitdeer tool calling:** verify in Phase 0 that the chosen chat model supports OpenAI-style tool or function calling on Bitdeer's endpoint. If it doesn't, use a JSON-only response format with a strict schema, and validate it before acting.
- **Moss index:** one document per object, built from name, aliases, notes, and description. Rebuild it on every registry change. Log the query latency.
- **LLM tool calling (Bitdeer, via the OpenAI-compatible endpoint):**
  - Tools: `locate_object(name)`, `guide_to_object(object_id)`, `chirp_fob(object_id)`, `label_object(tag, name, aliases?)`, `last_seen(object_id)`, `stop_guidance()`, `list_objects()`.
  - The model picks exactly one tool per turn. Tool results come from deterministic code.
  - Model ID and base URL come from env vars.
- **Keyword fallback grammar** for when the LLM times out (more than 1.5 s) or is unreachable:
  - "where is / where's / where are / find (my) X"
  - "stop" / "cancel"
  - "this is X" (labeling)
  - "make X beep / chirp"
- **Response policy by precision:**
  - `exact`: start guidance and say a short directional phrase computed in code. Use clock-face directions ("at your two o'clock") plus a rough distance ("about an arm's length").
  - `area` or `proximity`: "It's near the counter. I'll make it chirp." Then send `chirp` if it has a fob.
  - `none` or stale: "I last saw it on the far-left spot at 8:12."
  - Unknown object: "I don't know that item yet. Put it on the setup spot and say, 'This is…'"
- **Pickup confirmation:** while guiding, watch `pickup` events.
  - Target picked up: `guide_stop(found)`, then "Got it, that's the sugar."
  - Different object picked up: name it, and say where the target is relative to it ("The sugar is one spot to your right").
- **Cartesia TTS:** stream audio for low latency. Pre-synthesize common phrases into `config/phrases/` at build time so the Mac app can play them with `speak_cached`. The last-resort fallback is macOS `say`.
- **Latency budget:** final transcript to first audible audio in 1.2 s or less (target), 2.0 s maximum. Log per-stage timings, and generate a report with `scripts/latency_report.py`.
- **Acceptance:** with the simulator and a typed transcript (a `--text` CLI flag), every scenario produces the correct guidance and speech, and the fallback grammar works with the LLM disabled.

### 5.E Mac app (`mac/EarmarkApp/`, Swift + SwiftUI)

- **WebSocket client** to the hub bus, with auto-reconnect.
- **Spatial audio is the heart of this app (rule 11).** Build it behind two protocols so the implementation can be swapped without touching anything else, and so the same code can be ported to an iPhone app later:
  - `HeadTracking`: connection status, calibrate or recenter, yaw and pitch relative to the calibration.
  - `SpatialRenderer`: start, stop, set the target position, set the ping rate, play the "locked" tone, and duck the volume.

  Include a mock for each, so the rest of the app runs without AirPods.

- **Head tracking:**
  - Use `CMHeadphoneMotionManager` (available on macOS 14+ with supported AirPods). Handle connect and disconnect callbacks, "not available," and "not authorized" with a clear on-screen message.
  - Add a large **Recenter** button, plus a keyboard shortcut (R), that sets the current head pose as yaw 0.
  - Smooth the readings lightly, without adding noticeable lag.
  - **Verify the sign conventions on a real device.** Turning your head left must move a sound that's straight ahead into your right ear. Put `yawSign` and `pitchSign` constants in one file so they can be flipped in seconds.

- **Renderer options:** build the spike for both, then pick one using the spatial gate test.
  - **Option A: `AVAudioEngine` + `AVAudioEnvironmentNode`** with the high-quality HRTF rendering algorithm, plus manual head tracking. Each audio frame, rotate the listener (or the source) using the latest yaw and pitch from `CMHeadphoneMotionManager`. This is the most explicit and predictable path.
  - **Option B: Apple's PHASE framework.** Apple documents how PHASE can track head movement and apply the user's Personalized Spatial Audio profile. Check in Phase 0 what's available on the demo Mac's macOS version. If PHASE can use the AirPods' head tracking and the personal profile directly, it may localize better, especially front versus back. Use it only if it passes the gate test as well as Option A or better.

- **Cue design:**
  - Use a **mono** source for anything spatialized; environment-node spatialization expects mono input. Synthesize the ping procedurally: a short, bright blip around 880–1,200 Hz with a soft attack and short decay. Keep it short so Bluetooth latency doesn't smear it.
  - **Ping rate** follows the angle between the head direction and the target: about 900 ms between pings when the error is 90° or more, down to about 150 ms when it's under 10°. Play a distinct "locked" tone when the error stays under 8° for more than 300 ms.
  - **Front versus back confusion is the most common failure** with generic head-related audio filters. When the target is more than 100° away from the head direction, switch to a distinct "behind" sound (lower and muffled), and have the concierge say "It's behind you, turn right" (or left, whichever is the shorter turn).
  - Keep spatialized cues and speech in separate layers. The cue is spatial; speech is centered. Speech ducks the cue.

- **Robustness:**
  - Restart the audio engine automatically on route changes (AirPods removed or reconnected) and interruptions.
  - Re-check head tracking status after each restart.
  - Show the active renderer, the head-tracking status, and the current yaw on screen.

- **Fallback ladder:** each step applies automatically, and the UI says which mode is active.
  1. Spatial audio with head tracking (normal).
  2. Spatial audio without head tracking. Directions are relative to the calibrated forward direction, and the concierge adds clock-face directions.
  3. Exaggerated stereo panning plus spoken clock-face directions.
  4. Speech only.
- **Speech playback:** a separate, non-spatial player node for Cartesia audio and cached phrases. Duck the ping volume while speech plays.
- **Speech input:**
  - **Primary:** capture mic audio (16-bit PCM at the sample rate Cartesia STT expects; verify in Phase 0) and stream it to the concierge as `mic_audio`.
  - **Fallback:** Apple's Speech framework (`SFSpeechRecognizer`, preferring on-device recognition) sending `transcript` messages, used when the concierge requests it or the bus is down.
  - **Modes:** always-listening, and push-to-talk (hold Space) for the noisy judging hall. Show which speech engine is active in the status bar.
- **CRITICAL audio-routing rule:** using the AirPods microphone on a Mac can switch the AirPods to a low-quality hands-free audio mode, which can destroy the stereo cues spatial audio depends on.
  - Default the **input to the Mac's built-in microphone** (or a configured USB mic) and keep the **AirPods output-only**.
  - Verify this early on real hardware and record the result in `docs/STATUS.md`.
  - Show the current input and output devices in the UI.
  - Also note in the README: turn off the system's own Spatial Audio setting for AirPods during the demo, so it doesn't process the app's audio a second time.
- **Judge-facing UI:**
  - A large live top-down map: listener at the origin, spots, object chips, the current target highlighted, and a head-direction cone.
  - A status bar showing bus, head tracking, mic, and output device.
  - A collapsible debug panel.
- **Permissions:** microphone, speech recognition, and motion usage descriptions, as required on macOS. Verify which keys are needed for macOS 14+.
- **Acceptance:** all three spatial gate tests pass on real AirPods (see Phase 0.5). With the simulator running, a teammate wearing AirPods, eyes closed, can be guided to each spot by sound alone.

### 5.F Dashboard (`dashboard/`, React + Vite + Convex)

- **Pages:**
  - **Live map:** mirrors the Mac app's map, read-only, with real-time updates.
  - **Items:** add or edit names, aliases, and notes, and assign a home spot or fob. This is remote family labeling, and it's the Meta "bringing people closer" angle.
  - **Medications:** schedules plus a day view of taken / late / missed / pending.
  - **Timeline:** recent pickups and placements.
  - **Trials:** results from trial mode (5.I), comparing Earmark with the baseline: median time to find, wrong-pick rate, and the number of trials. Show the raw counts, never only percentages.
- **Photo-assisted labeling (Bitdeer multimodal):**
  - During setup, a family member can upload one photo of an item from their own phone or laptop.
  - A Convex action sends it to a Bitdeer multimodal chat model, which suggests a name, aliases, and a short description. The human confirms or edits before anything is saved.
  - Delete the photo once the suggestion comes back; store only the text. Earmark still has no cameras in the home. This is a one-time photo taken by a caregiver, and the deletion is part of the responsible-design story.
- **Accessibility:** follow rule 7 strictly. Every status has a text label, and the map has a text-list equivalent.
- **Acceptance:** editing a label updates what the concierge recognizes within seconds, with no restart. A photo produces a sensible suggestion in under 5 seconds.

### 5.G Memory agent (`services/memory_agent/`, Fetch.ai + Bitdeer)

- A uAgent implementing the **Chat Protocol**, registered on **Agentverse** (via mailbox) so it can be discovered through **ASI:One**. Verify the current requirements in Fetch.ai's official docs and the Cal Hacks hack pack, and record them in `docs/vendor-notes/fetchai.md`.
- Reasoning uses a **Bitdeer-hosted model** through the OpenAI-compatible endpoint. The agent's tools call Convex's read endpoints only.
- **Example questions:** "Where did Dad leave his keys?", "Did Mom take her evening pills?", "What hasn't been touched in a week?"
- Answers come strictly from the data, with the data's timestamps. No medical advice.
- The README includes the agent address and steps to reproduce.
- **Acceptance:** a question sent through the chat interface returns a correct answer drawn from seed data.

### 5.I Trial mode: measurable usefulness (`scripts/trial.py`, Convex `trials`, dashboard Trials page)

This produces real evidence for Microsoft's "measurable usefulness" criterion and gives the pitch an honest number.

- **Protocol:**
  1. A blindfolded teammate sits in the demo chair. The operator picks a target among look-alike items (for example, salt versus sugar, or two identical pill bottles).
  2. **Baseline mode:** the tester is told only "it's on the counter" and searches by touch.
  3. **Earmark mode:** the tester uses the full system.
  4. Alternate the modes, and randomize targets and spot positions between trials.
- **Recording:** `trial_start` starts the timer. The trial ends automatically when the target's `pickup` arrives with confirmation, or manually by the operator. Every wrong `pickup` counts as a wrong pick.
- **Rules:** never fabricate, edit, or extrapolate trial data. Report the number of trials, testers, and conditions exactly. If there are only a handful of trials, say so and call it a pilot.
- **Acceptance:** at least one full trial of each mode recorded end to end, with results visible on the dashboard.

### 5.H Stretch (only after section 8's core acceptance passes, and only if the human approves)

- **Creao:** a scheduled caregiver agent that reads `GET /api/daily-summary` and messages a caregiver. Document the exact endpoint contract in `docs/creao.md`.
- **Visa + Apify Restock Agent:** "I'm almost out of salt" → product lookup → spoken approval → checkout. Do not start without explicit approval.

---

## 6. Sponsor integration map

Every integration must be load-bearing and visible in the demo or the Devpost.

| Sponsor | Where | What judges should see |
|---|---|---|
| Cartesia | concierge, Mac app | Both directions of the voice loop: Ink speech-to-text with turn detection, and Sonic speech. The wrong-jar correction spoken live |
| Moss | concierge | Fuzzy requests resolved instantly ("something for my eggs"), with latency shown in the debug panel |
| Convex | hub sync, dashboard, agents, trials | The live map updating the instant a jar is lifted; remote labeling taking effect in seconds; adherence and trial results computed in Convex functions |
| Microsoft (Built for the Real World / Customer Impact) | the whole product, plus Azure hosting | All five challenge criteria addressed explicitly (6.1) |
| Fetch.ai | memory_agent | A remote question answered through ASI:One |
| Bitdeer | concierge tool calling, memory_agent reasoning, photo-assisted labeling | Three distinct uses (text chat, tool calling, multimodal), each attributed in the logs and the Devpost |
| Creao (stretch) | `/api/daily-summary` | A caregiver message about a missed dose |
| Meta (optional) | dashboard | A family member labeling items remotely |

### 6.1 Microsoft challenge: one deliverable per criterion

| Criterion | Deliverable |
|---|---|
| **Customer understanding** | `docs/CUSTOMER.md`: who the users are (blind and low-vision people, plus caregivers), the specific jobs Earmark does, and why existing tools fall short (camera apps describe a scene but don't remember where things are or tell identical containers apart). If the team talks to any blind or low-vision person or an accessibility professional this weekend, record what they said with permission. **Never invent interviews or quotes.** |
| **Measurable usefulness** | Trial mode (5.I) with real results on the dashboard, plus live metrics: guidance latency, time to find, and medication adherence. |
| **Path from prototype to production** | `docs/PRODUCTION.md` covering: hardware cost per home, the iPhone port (same Apple frameworks), Azure hosting for the cloud parts, multi-household support, security and data retention, battery life for fobs, and a step-by-step rollout plan. If Azure credits are available, actually deploy the dashboard (for example, Azure Static Web Apps) and the memory agent (for example, Azure Container Apps) and link them. |
| **Responsible design** | `docs/RESPONSIBLE_DESIGN.md` covering: no cameras in the home; one-time caregiver photos deleted after labeling; data minimization (object names, spots, and timestamps only); caregiver access controls; no medical advice; honest uncertainty (the system says when it isn't sure and never guesses which bottle is which); and safe failure modes (fallbacks, and what happens when detection is wrong). |
| **End-to-end functionality** | The definition of done in section 8, demonstrated live. |

---

## 7. Parallel agent workflow

### 7.1 When to parallelize

Parallelize only work that is independent and owns separate files. Shared interfaces are dependencies: they must exist **before** any fan-out. Subagents start with a fresh context and only see what you put in their task prompt, so every delegation must include the relevant brief sections, contract file paths, owned directories, and acceptance criteria. Use read-only subagents for research and review, and worktree-isolated subagents for anything that writes code.

Verify the current subagent mechanics in your installed Claude Code version before relying on them (run `/agents` and check the official Claude Code docs on subagents and parallel work). If a frontmatter field below isn't supported, drop it and enforce the same constraint through the agent's instructions. Do not use experimental "agent teams."

### 7.2 Subagent definitions to create in `.claude/agents/`

**`implementer.md`** (template; create one specialized copy per component, or pass the component spec in the task prompt):

```markdown
---
name: implementer
description: Implements one Earmark component inside its owned directories. Use for Phase 1 component builds.
tools: Read, Write, Edit, Bash, Grep, Glob, WebFetch
isolation: worktree
---
You implement exactly one component of Earmark. Before editing, list the files you will own. Never edit files outside your owned directories, and never edit anything in contracts/ or config/space.json. If you need a contract change, stop and return a written proposal instead.
Verify any third-party API against its official docs before using it, and write what you verified to docs/vendor-notes/<vendor>.md (append only).
Build against the simulator and mocks, not real hardware or keys. If a key is missing, implement behind an interface with a mock and say so.
Before returning, run your component's tests and its acceptance check. Return: files changed, how to run, what is verified, what is mocked, and open issues.
```

**`reviewer.md`** (read-only):

```markdown
---
name: reviewer
description: Read-only reviewer for Earmark. Use in Phase 3 for demo-risk, accessibility, security, and sponsor-fit reviews.
tools: Read, Grep, Glob, Bash
---
You review; you never edit files. Produce a prioritized list of findings (P0 = would break the live demo, P1 = judges would notice, P2 = nice to fix), each with file paths and a concrete fix.
```

**`researcher.md`** (read-only, for Phase 0 documentation checks):

```markdown
---
name: researcher
description: Fetches and summarizes current official docs for one vendor SDK. Use in Phase 0.
tools: Read, Write, WebFetch, WebSearch
---
Find the official documentation for the assigned vendor. Summarize only what Earmark needs: install command, auth, the exact calls we will make, request and response shapes, rate limits, and gotchas. Include doc URLs for every claim. Write to docs/vendor-notes/<vendor>.md and return a 10-line summary. If you cannot verify something, say so explicitly rather than guessing.
```

### 7.3 Phases

**Phase 0: Foundation (you, sequential, with parallel researchers)**

1. Check the toolchain: Xcode and Swift versions, macOS version (must be 14 or later), Python 3.11+, Node 20+, git. Report anything missing.
2. Launch **researcher** subagents **in parallel**. Start each one from its sponsor's official Cal Hacks materials in section 2.5, then the main docs:
   - Cartesia: the Cal Hacks page, Ink STT streaming, and Sonic TTS streaming
   - Moss: its hack pack
   - Convex: the hackathon resources, the AI guidelines, the Python client, and HTTP actions
   - Fetch.ai: its hack pack, uAgents, the Chat Protocol, Agentverse, and ASI:One
   - Bitdeer Model Studio: the model catalog, tool-calling support, and multimodal input format
   - Microsoft: the Azure for Students setup, plus the simplest hosting for a static React app and a small Python service
   - Apple: head tracking plus `AVAudioEnvironmentNode`
   - `bleak` on macOS, and Apple's Speech framework on macOS

   Each one writes `docs/vendor-notes/<vendor>.md` and flags anything in this brief that contradicts the official materials.
2b. Before any Convex code is written, apply Convex's AI code-generation guidelines to the repo.
3. While they run, create the repo skeleton, `.gitignore`, `.env.example`, a task runner (`Makefile` or `justfile` with `dev`, `test`, `demo-sim`, `demo-live`, `seed`, and `reset`), `contracts/` with schemas, examples, and types, the placeholder `config/space.json`, `config/objects.seed.json`, `convex/schema.ts`, and all of `scenarios/`.
4. Write `docs/ARCHITECTURE.md` and `docs/STATUS.md`. Commit.
5. **Checkpoint:** report a status table, list the env vars the human must fill in, list the research findings that change the plan, and **stop for human confirmation**.

**Phase 0.5: Spatial audio spike and gate (you, with the human, sequential; do this before or alongside the start of Phase 1)**

The riskiest, most important piece gets proven first, on real hardware.

1. Build `mac/SpatialSpike/`, a minimal standalone macOS app with no bus, no backend, and no network. It has:
   - The head-tracking status and live yaw and pitch readout
   - A Recenter button
   - A renderer toggle (Option A or Option B)
   - Buttons that place the ping at preset angles (−90°, −45°, 0°, 45°, 90°, and 180°)
   - A "random position" button for blind tests
   - A results logger
2. Have the human connect real AirPods to the demo Mac, set the system Spatial Audio setting for the app to **Off**, and run the three gate tests:
   - **Sign check:** with the ping straight ahead, turning the head left moves it into the right ear, and looking up moves it down. If not, flip `yawSign` or `pitchSign` and re-run.
   - **Fixed-in-room test:** place the ping at 0°, then have the tester turn their head slowly 90° left and right. The ping must sound like it stays put in the room rather than following the head.
   - **Pointing test:** with eyes closed, the tester points at the perceived source for 10 random positions in the front half of the room. **Pass: at least 8 of 10 within ±20°.** Also run 4 trials from behind and log any front/back confusions.
3. Record the results for each renderer in `docs/STATUS.md`. Pick the renderer that passes with the best pointing accuracy.
4. **If neither passes,** stop and report to the human with the measured numbers and the specific failure (sign, drift, front/back confusion, latency, or audio-routing degradation). Propose fixes in order: recheck the routing rule, adjust the cue sound, exaggerate the cues, or fall back as in the 5.E fallback ladder. **Do not proceed with the full Mac app until the spatial gate passes or the human accepts a fallback.**
5. mac-app-builder (Phase 1) builds the production `SpatialRenderer` from the winning spike code.

**Phase 1: Parallel component build (6 implementer subagents, worktree-isolated)**

Launch all six in one batch, each with its component spec from section 5 pasted into its task prompt:

| Subagent | Owns | Spec |
|---|---|---|
| hub-builder | `services/hub/**`, `scripts/trial.py` | 5.A, 5.B, 5.I (trial CLI) |
| convex-builder | `convex/**` (except `schema.ts`, which needs orchestrator approval to change) | 5.C |
| concierge-builder | `services/concierge/**`, `config/phrases/**` | 5.D |
| mac-app-builder | `mac/**` | 5.E |
| dashboard-builder | `dashboard/**` | 5.F |
| memory-agent-builder | `services/memory_agent/**` | 5.G |

While they work, you handle contract-change proposals as they come in. Approve or reject each quickly, and broadcast approved changes to the affected subagents.

**Phase 2: Integration (you, sequential)**

1. Merge the worktrees one at a time, running tests after each merge.
2. Build `scripts/demo_sim.sh`: it starts the hub with the simulator, the concierge, and the Convex dev deployment, then prints how to launch the Mac app and dashboard.
3. Run every scenario end to end. Write `tests/e2e/` scripted checks for `wrong_jar`, `moved_item`, `missed_dose`, and `roaming_keys`.
4. Run the latency report. If it exceeds budget, fix the largest stage first.
5. **Checkpoint:** report the results and stop for human confirmation.

**Phase 3: Parallel review (4 reviewer subagents, read-only)**

- **demo-risk:** offline behavior, timeouts, fallbacks, restart and reset, what happens when each external service is down.
- **accessibility:** the dashboard and Mac app UI against rule 7.
- **security:** secrets handling, endpoint authentication, logging of sensitive data.
- **sponsor-fit:** whether each integration is meaningful and visible, plus a draft Devpost paragraph per sponsor written to `docs/DEVPOST.md`.

Fix all P0 and P1 findings yourself, or by dispatching implementers to the affected directories.

**Phase 4: Hardware bring-up (you, human-in-the-loop, sequential)**

1. When the human confirms the hardware (section 10), write and test the firmware in `firmware/` and validate `nfc_serial` against real output. Ask for the serial monitor output when debugging, and diagnose before changing code.
2. Validate `ble_fobs` with the real fobs and record their UUIDs in config.
3. Run `scripts/calibrate.py`, which asks the human for tape-measure readings for each spot and writes `config/space.json`.
4. Do an eyes-closed guidance test with a teammate and tune the ping-rate curve and "locked" threshold.
5. Verify the audio-routing rule (5.E) on real AirPods.

**Phase 5: Demo hardening (you)**

- `make reset` returns everything to the demo starting state in under 10 seconds.
- `make demo-live` runs the full stack with real adapters. `make demo-sim` is the fallback, if hardware fails, with no code changes.
- Polish the seed data. Write the README quick start, `docs/DEVPOST.md`, an architecture diagram, and a 2-minute demo script, and keep everything in `docs/STATUS.md` up to date.
- Write `docs/CUSTOMER.md`, `docs/PRODUCTION.md`, and `docs/RESPONSIBLE_DESIGN.md` (6.1). Draft them early, in Phase 2, and finish them here.
- Run trial mode with at least two teammates, in both modes, and put the real results into the Devpost and the pitch.
- If the human has Azure credits working, deploy the dashboard and the memory agent to Azure and verify both from a phone on cellular data.
- Help the human record a local demo video as a backup.

---

## 8. Definition of done (core)

All of these must pass with the simulator. The first five must also pass with at least one real detection source.

0. The Phase 0.5 spatial gate passes on the demo Mac with the demo AirPods: the sign check, the fixed-in-room test, and at least 8 of 10 pointing trials within ±20°.
1. "Where's the sugar?" → a clock-direction phrase within about 1.2 s, and a ping from spot 3 that stays fixed in the room as the listener turns their head. If the target is behind the listener, they get the "behind" sound and a spoken turn direction.
2. The user lifts the salt instead → an immediate correction naming the salt and giving the sugar's relative position.
3. The sugar moves to spot 1 → the next query guides to spot 1.
4. "Where are my keys?" → a proximity phrase, then the fob chirps.
5. "Something for my eggs" → Moss resolves to salt (and, if seeded, pepper), and Earmark asks which one.
6. With the LLM disabled, steps 1–4 still work through the fallback grammar.
7. The dashboard shows live state and medication adherence including the seeded missed dose, and editing a label takes effect in the voice loop within seconds.
8. The Fetch.ai agent answers "Did Mom take her evening pills?" correctly from seed data.
9. `make reset` and `make demo-sim` work from a clean terminal.
10. Spoken requests work through Cartesia STT, and still work through Apple Speech when Cartesia is blocked.
11. At least one real trial of each mode (Earmark and baseline) is recorded and shown on the dashboard.
12. A photo uploaded in the dashboard produces a confirmed label through Bitdeer's multimodal model, and the photo is deleted afterward.

---

## 9. Cut list (if behind schedule, cut from the top down)

1. Visa + Apify Restock Agent
2. Creao summary
3. Azure deployment (keep `docs/PRODUCTION.md` either way)
4. Dashboard Timeline page
5. Photo-assisted labeling
6. Fetch.ai agent polish (keep a minimal working version)
7. Ping-curve fine-tuning

**Never cut:** AirPods spatial guidance with head tracking in Earmark's own app, the voice → guide → pickup confirmation loop, the wrong-jar correction, the keyword fallback, `make reset`, and `make demo-sim`.

---

## 10. Facts the human must provide (ask in one batch)

- Detection hardware actually in hand: `[NFC module model]`, `[microcontroller board model]`, `[number of readers]`, `[BLE fob model]`
- API keys and IDs:
  - Cartesia: key and voice ID
  - Moss
  - Bitdeer: key, base URL, chat model ID, and multimodal model ID. The credit request form must be submitted at bitdeer.ai first.
  - Convex: login and deployment
  - Fetch.ai / Agentverse
- Whether the team has activated Azure for Students credits, and which account to use
- Access to the Fetch.ai and Moss Google Docs. If they can't be fetched, the human exports them into `docs/sponsor-packs/`.
- The links inside the Bitdeer starter pack PDF (Getting Started, Model Catalog, Integrations, workshop demo code), if they can't be found from bitdeer.ai
- Whether anyone on the team has spoken with, or can quickly speak with, a blind or low-vision person or an accessibility professional, for `docs/CUSTOMER.md`
- The Apple ID or team to use for Xcode signing on the demo Mac
- Tape-measure positions for each spot, relative to the listening position (Phase 4)
- Approval for any stretch item

---

## 11. Reporting format

At every checkpoint, and whenever you finish a phase, report:

1. A table of components with status (done / partial / blocked), what's verified, and what's mocked.
2. Decisions made, and any contract changes.
3. Blockers needing the human, as a numbered list.
4. The next three actions.

Keep it short. Then continue, unless the phase says to stop.
