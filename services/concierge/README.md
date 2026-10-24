# Earmark concierge (voice agent)

The concierge turns speech into guidance.
It listens to the bus, transcribes `mic_audio` with Cartesia Ink, picks one tool with the Bitdeer LLM (raced against a keyword grammar), resolves the object with Moss, computes every direction and sentence in code, and speaks through Cartesia Sonic.
Spec: BUILD_BRIEF 5.D; contracts in `contracts/schemas/bus_message.schema.json` are authoritative.

## Run

```sh
cd services/concierge
uv sync                                         # Python 3.12 venv, deps, contracts by path
uv run earmark-concierge                        # connect to the hub bus and serve
uv run earmark-concierge --text "Where's the sugar?"   # inject one typed transcript after the snapshot, keep running
uv run earmark-concierge --repl                 # each stdin line is a typed transcript
uv run earmark-concierge --no-llm               # force the keyword grammar
uv run earmark-concierge synth-phrases          # pre-synthesize config/phrases/<phrase_id>.wav (needs a key)
python3 scripts/latency_report.py               # from the repo root: per-stage and end-to-end latency
```

It runs with no API keys at all: every vendor sits behind an interface whose fallback is chosen automatically when its env var is missing.
With `--text`, injection waits for the snapshot, then up to 6 s for any Mac app message, so the reply goes to the Mac app rather than local `say`.
`synth-phrases` exits with code 2 and a clear message when `CARTESIA_API_KEY` or `CARTESIA_VOICE_ID` is missing.

## Test

```sh
cd services/concierge
uv run pytest -q
```

- Unit: grammar, clock face and distance for every seed spot, relative spots, times, precision policy, ambiguity, labels, intent racing and validation, resolver fallbacks, STT and TTS fallbacks, phrase synthesis, latency report.
- Scenario acceptance (`tests/test_scenarios.py`): no keys and the LLM disabled; the hub's output for each scenario is fed as `state_update` / `pickup` / `unknown_tag`, with the typed transcripts read from `scenarios/*.jsonl`.
- Integration (`tests/test_integration.py`): the real `earmark-concierge --text` process against an in-test bus server (`hello` -> `snapshot`, subscribe-filtered broadcast), started before the bus to exercise reconnect, then restarted mid-run.
- Vendor fakes (`tests/fakes.py`): a fake Ink turns server (good, silent, mute, error), a fake Sonic server (good, error, slow, drop), and the bus.

## Configure

Env vars are read at start; a repo-root `.env` is loaded without overriding the real environment, and empty values count as unset.
Vendor defaults are the values verified in `docs/vendor-notes/` on 2026-10-24.

| Variable | Default | Verified in |
| - | - | - |
| `EARMARK_BUS_URL` | `ws://127.0.0.1:8765` | `contracts/README.md` |
| `CARTESIA_API_KEY` | unset: Apple Speech STT, system-voice speech | `cartesia.md` 2 |
| `CARTESIA_VERSION` | `2026-08-14` | `cartesia.md` 2 |
| `CARTESIA_STT_URL` | `wss://api.cartesia.ai/stt/turns/websocket` | `cartesia.md` 3.1 |
| `CARTESIA_STT_MODEL` | `ink-2` | `cartesia.md` 3.2 |
| `CARTESIA_STT_SAMPLE_RATE` | `16000` (the URL uses each burst's declared `sample_rate`) | `cartesia.md` 3.4 |
| `CARTESIA_TTS_URL` | `wss://api.cartesia.ai/tts/websocket` | `cartesia.md` 4.1 |
| `CARTESIA_TTS_BYTES_URL` | `https://api.cartesia.ai/tts/bytes` | `cartesia.md` 5 |
| `CARTESIA_TTS_MODEL` | `sonic-3.6-2026-08-27` (pinned snapshot, same for live and cached) | `cartesia.md` 4.1 |
| `CARTESIA_VOICE_ID` | unset: TTS off (`speak_text`) | `cartesia.md` 4.6 |
| `CARTESIA_TTS_ENCODING` | `pcm_f32le` | `cartesia.md` 4.5 |
| `CARTESIA_TTS_SAMPLE_RATE` | `48000` | `cartesia.md` 4.5 |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | unset: local fallback resolver | `moss.md` 2 |
| `MOSS_INDEX_NAME` | `earmark-objects` (no personal data: it is sent in telemetry) | `moss.md` 5 |
| `BITDEER_API_KEY` | unset: keyword grammar only | `bitdeer.md` 1 |
| `BITDEER_BASE_URL` | `https://api-inference.bitdeer.ai/v1` | `bitdeer.md` 1 |
| `BITDEER_CHAT_MODEL` | `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B` | `bitdeer.md` 3.1 |
| `LLM_TIMEOUT_S` | `1.5` | BUILD_BRIEF 5.D |

Concierge tuning knobs (defaults in `earmark_concierge/config.py`):

| Variable | Default | Meaning |
| - | - | - |
| `CONCIERGE_STT_CONNECT_TIMEOUT_S` | `1.0` | Ink must report `connected` this soon after a burst's first audio |
| `CONCIERGE_STT_FIRST_EVENT_TIMEOUT_S` | `1.5` | a `turn.*` event must arrive this soon while audio flows |
| `CONCIERGE_STT_IDLE_CLOSE_S` | `5.0` | close the Ink socket after this long without audio |
| `CONCIERGE_STT_PROBE_INTERVAL_S` | `60` | while on Apple Speech, probe Cartesia this often |
| `CONCIERGE_TTS_FIRST_CHUNK_TIMEOUT_S` | `1.0` | Sonic's first chunk deadline before `speak_text` |
| `CONCIERGE_GUIDE_TIMEOUT_S` | `60` | `guide_stop` reason `timeout` |
| `CONCIERGE_BEHIND_COOLDOWN_S` | `4` | at most one "It's behind you" per window |
| `CONCIERGE_STATUS_INTERVAL_S` | `5` | periodic `status` |
| `CONCIERGE_MAC_APP_TTL_S` | `15` | the Mac app counts as present this long after its last message |
| `CONCIERGE_LABEL_WINDOW_S` | `300` | an `unknown_tag` older than this is not used for "this is X" |
| `CONCIERGE_CLARIFY_WINDOW_S` | `30` | how long "Do you mean A or B?" waits for the answer |
| `CONCIERGE_STALE_S` | `600` | area/proximity states older than this are reported as "last seen" |
| `CONCIERGE_MOSS_MIN_SCORE` | `0.35` | Moss hit floor (UNVERIFIED: tune with a key) |
| `CONCIERGE_MOSS_MARGIN` | `0.08` | hits within this of the best Moss score are ambiguous |
| `CONCIERGE_TIMEZONE` | household timezone from `config/objects.cache.json` or `objects.seed.json` | spoken times |
| `CONCIERGE_SAY_CMD` | `say` | local speech when no Mac app is on the bus |
| `CONCIERGE_LATENCY_LOG` | `logs/latency.jsonl` | latency JSON lines |

Secrets are only sent as `Authorization` headers and are never logged.

## Pipeline

1. `mic_audio` -> Ink turns WebSocket (binary PCM).
   The socket opens on a burst's first chunk (audio is buffered while it connects) and is closed with `{"type":"close"}` after 5 s without audio, because Ink bills about 10,800 credits per hour even for silence.
   While a turn is open and the Mac app has stopped sending, the concierge pads 100 ms zero frames, because Ink waits for audio rather than hearing silence and `turn.end` would otherwise never fire (`cartesia.md` 3.8).
   Object names and aliases go in as `keyterm`s.
   `turn.update` and `turn.eager_end` -> `transcript` is_final=false; `turn.end` -> is_final=true (source `cartesia`).
   `turn.eager_end` starts the LLM call early; `turn.resume` cancels it; only `turn.end` acts.
2. Intent: the grammar result is computed at once, and the Bitdeer call (`tool_choice` required, `parallel_tool_calls` false, `reasoning_effort: "none"`, `timeout=1.5`, `max_retries=0`) wins if it returns exactly one valid tool call in time.
   Every decision is logged with the path, the LLM status, and the LLM latency attributed to Bitdeer.
3. Resolution: exact name or alias, then Moss (when ready), then fuzzy names (rapidfuzz), then a lexical scorer over notes and description.
   Ambiguity is decided in code; the answer to "Do you mean the salt or the pepper?" is resolved against just those candidates (names, typos, and "the first one").
4. Tools run deterministic code (`policy.py`, `phrasing.py`): clock face from `atan2(x, y)` against calibrated forward, distance bands, relative spots ordered by azimuth, household-local times.
5. Speech (below), with latency logged per stage.

## Fallback ladder

| Stage | Normal | Fallback, in order |
| - | - | - |
| Speech in | Cartesia Ink | no key, connect failure, no `connected` within 1 s, no `turn.*` within 1.5 s, or a server error -> `stt_mode apple` and "Switching to backup listening."; Apple and typed transcripts are always accepted; Cartesia is probed every 60 s (socket open plus `connected`, no audio) and restored with `stt_mode cartesia` |
| Intent | Bitdeer tool call | timeout, error, invalid or multiple calls, or "declined" (empty name) -> keyword grammar -> "Sorry, I didn't catch that." |
| Resolution | exact name, then Moss session index | Moss error or no key -> fuzzy names -> lexical notes/description -> "I don't know that item yet..." |
| Speech out | `speak` chunks from Sonic | static phrase text -> `speak_cached`; no TTS key, Sonic error, or first chunk later than 1 s -> `speak_text` (and skip Sonic for 30 s); no Mac app on the bus -> local `say` |

## Decisions

- One uv project, Python 3.12, contracts by editable path; every bus message goes through `earmark_contracts.parse_bus` / `dump`.
- Raw `websockets` for Ink and Sonic (per `cartesia.md` 6), `httpx` for the bytes endpoint, so the Cartesia SDK and its `websockets<16` pin are not needed.
- The household timezone is read from the registry files, since `snapshot` does not carry `household` (see the contract proposal in the handoff report).
- Mac app presence is inferred from its messages (`status` from `mac_app`, `head_pose`, `playback`, `guide_feedback`, `mic_audio`, Apple transcripts) within 15 s, since the bus has no presence message.
- `exact` precision starts guidance; `area` and `proximity` do not ping (a receiver's position is not the object's), and the fob chirp is the spatial cue instead.
- Objects with a fob are chirped whenever they are asked for and not exactly located, including "never seen" and stale states; the roaming-keys scenarios ask before the fob is first heard.
- Never-seen objects without a fob read back their family notes ("Its notes say: ... usually kept in the pantry").
- Asking about a different object while guiding stops the old guidance (`guide_stop cancelled`); a guided object's new exact position re-sends `guide_start`.
- A wrong pickup keeps guidance running and names the relative spot; if the target is not on a spot, the clock face; if unknown, says so.
- Medication answers report pickups and current spot only; advice-seeking wording adds "I can't give medical advice, but I can tell you what the sensors saw."
- The concierge only knows pickups since it started, and says so ("I haven't seen them picked up since I started at 7:03 AM").
- Lexical evidence can widen a single Moss answer into a question, never narrow it, so look-alikes produce a question rather than a guess.
- Spoken times use 12-hour clock with AM/PM ("at 8:12 PM"), "yesterday", a weekday within a week, or month and day; never a date for today.
- Distances are horizontal from the head: < 0.45 m "within easy reach", < 0.8 m "about an arm's length away", < 1.5 m "about a step away", else about N steps (0.75 m each).
- Clock hours round half away from zero, so the seed spots read 10, 11, 1, and 2 o'clock.
- Utterances are serialized so `speak` chunks never interleave; `guide_start` is sent before the speech that shares its `utterance_id`.

## What is mocked tonight

No Cartesia, Moss, or Bitdeer key exists, so none of the three has been exercised against the live service.
- Cartesia Ink and Sonic: tested against local fake servers that follow the event shapes in `cartesia.md`.
- Bitdeer: tested with fake choosers and an HTTP mock that checks the exact request body the `openai` SDK sends.
- Moss: tested with a fake index; the real SDK was run with bad credentials and fails fast with `MossError: UNAUTHORIZED`, which triggers the fallback.
- The hub: tested with an in-test bus server; scenario states are hand-written equivalents of the hub's output.
- `config/phrases/*.wav` are not generated yet (`synth-phrases` needs a key); until then the Mac app speaks `speak_cached` text with the system voice, per the contract.

## Open items

- Moss thresholds (`CONCIERGE_MOSS_MIN_SCORE`, `CONCIERGE_MOSS_MARGIN`) need tuning on the seed queries once a key exists.
- Benchmark Bitdeer p50/p95 for the tool call (`bitdeer.md` 3.1); if it is regularly above 1.5 s, the grammar answers most turns and the LLM only adds latency.
- UNVERIFIED: that an Ink socket opened for a probe without audio costs no credits.
