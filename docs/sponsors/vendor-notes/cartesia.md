# Cartesia vendor notes (Ink 2 STT, Sonic 3.6 TTS)

Verified 2026-10-24 against docs.cartesia.ai (index: https://docs.cartesia.ai/llms.txt), the current AsyncAPI/OpenAPI specs, PyPI, and the `cartesia-python` v4.2.0 source.
Nothing here was exercised against the live API, because no API key was available during research.
Items marked UNVERIFIED are inferences or gaps in the docs.
Sponsor and prize details are in `docs/sponsors/sponsor-packs/cartesia.md`.

## Quick reference for Earmark

| Item | Value | Source |
| - | - | - |
| REST base | `https://api.cartesia.ai` | https://docs.cartesia.ai/use-the-api/api-conventions |
| WebSocket base | `wss://api.cartesia.ai` | same |
| Version header | `Cartesia-Version: 2026-08-14` (only enum value in the current specs) | https://docs.cartesia.ai/api-reference/stt/turns/websocket |
| Auth (server) | `Authorization: Bearer <key>` or `X-API-Key: <key>` | https://docs.cartesia.ai/get-started/authenticate-your-client-applications |
| STT endpoint | `wss://api.cartesia.ai/stt/turns/websocket?model=ink-2&encoding=pcm_s16le&sample_rate=16000` | https://docs.cartesia.ai/api-reference/stt/turns/websocket |
| STT model | `ink-2` (stable), `ink-preview` (preview) | https://docs.cartesia.ai/build-with-cartesia/stt/latest |
| STT audio | raw mono `pcm_s16le` at 16000 Hz, binary frames of about 100 ms (3200 bytes), paced in real time | https://docs.cartesia.ai/build-with-cartesia/stt/audio-input |
| TTS endpoint | `wss://api.cartesia.ai/tts/websocket` | https://docs.cartesia.ai/api-reference/tts/websocket |
| TTS model | `sonic-3.6`; pinned snapshot `sonic-3.6-2026-08-27` | https://docs.cartesia.ai/build-with-cartesia/tts-models/latest |
| TTS output | `{"container":"raw","encoding":"pcm_f32le","sample_rate":48000}` (see section 4.5 for why) | https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format |
| Phrase pre-synthesis | `POST https://api.cartesia.ai/tts/bytes` with `container: "wav"` | https://docs.cartesia.ai/api-reference/tts/bytes |
| Python SDK | `cartesia` 4.2.0 (2026-09-02), Python >= 3.9, install `cartesia[websockets]` | https://pypi.org/project/cartesia/ |

## 1. Cal Hacks

- Prize, judging criteria, and submission requirements are summarized in `docs/sponsors/sponsor-packs/cartesia.md` (source: https://docs.cartesia.ai/calhacks).
- The Cal Hacks page does not mention credits or a claim process.
- Free plan: 20K credits/month; Pro: $5/month for 100K credits (https://cartesia.ai/pricing).

## 2. Auth, versioning, base URLs

- All requests use HTTPS or WSS; HTTP is not supported, and keys used over HTTP may be rotated automatically (https://docs.cartesia.ai/use-the-api/api-conventions).
- Send `Cartesia-Version` on every request; on WebSockets the `?cartesia_version=` query parameter is an alternative and takes precedence over the header.
- The current AsyncAPI marks `cartesia_version` as a required query parameter for both STT WebSockets, with `2026-08-14` as the only allowed value (https://docs.cartesia.ai/api-reference/stt/turns/websocket).
- The official SDK sends it as a `cartesia-version: 2026-08-14` header instead (observed in `src/cartesia/_client.py`, v4.2.0), so the header alone evidently works.
- For raw WebSocket clients, send both the header and the query parameter to be safe.
- Server-side auth accepts either `X-API-Key: <key>` or `Authorization: Bearer <key>`; header names are case-insensitive (https://docs.cartesia.ai/get-started/authenticate-your-client-applications).
- Browser or mobile clients must use a short-lived access token from `POST /access-token`, passed as `?access_token=` on WebSockets; Earmark's concierge is server-side Python, so it uses the API key directly.
- Standard keys are `sk_car_...`; admin keys (`sk_car_admin_...`) are rejected on TTS/STT endpoints.
- With version 2026-03-01 and newer, errors are structured JSON with `error_code`, `title`, `message`, `request_id`, and optional `doc_url` (https://docs.cartesia.ai/use-the-api/api-errors).
- WebSocket error events add `"type": "error"`, `"done": true`, and `status_code`.
- Common `error_code` values: `quota_exceeded`, `concurrency_limited`, `voice_not_found`, `model_not_found`, `voice_model_mismatch`, `unsupported_audio_format`, `plan_upgrade_required`.
- `GET /models?capability=tts|stt` lists the callable model IDs and can be used at startup to check the env-configured model names (https://docs.cartesia.ai/api-reference/models/list).

## 3. Ink streaming STT

### 3.1 Endpoints

There are two realtime endpoints (https://docs.cartesia.ai/use-the-api/stt/compare-endpoints):

| | Realtime STT (Auto) | Realtime STT (Manual) |
| - | - | - |
| URL | `wss://api.cartesia.ai/stt/turns/websocket` | `wss://api.cartesia.ai/stt/websocket` |
| Models | `ink-2`, `ink-preview` only | `ink-2`, `ink-preview`, `ink-whisper` |
| Turn detection | Built in, semantic (no separate VAD) | None; client sends `finalize` |
| Output | Turn events with cumulative transcripts | `transcript` deltas with `is_final` |
| Recommended for | Voice agents (always-listening) | Push-to-talk, or when the app already knows speech ended |

Batch `POST /stt` exists for files but supports `ink-whisper` only.

### 3.2 Models

- `ink-2`: stable, languages `en`, `fr`, `hi`, `ja`, `es`, with automatic language detection (https://docs.cartesia.ai/build-with-cartesia/stt/latest).
- `ink-preview`: preview channel, same languages.
- `ink-whisper` is now listed under "Older Models" and does not support the turns endpoint (https://docs.cartesia.ai/build-with-cartesia/stt/older-models).
- Brief's "Ink 2" name is correct; its model ID string is `ink-2`.

### 3.3 Query parameters (Auto endpoint)

Source: https://docs.cartesia.ai/api-reference/stt/turns/websocket

| Param | Required | Notes |
| - | - | - |
| `model` | yes | `ink-2` or `ink-preview` |
| `encoding` | yes | `pcm_s16le`, `pcm_s32le`, `pcm_f16le`, `pcm_f32le`, `pcm_mulaw`, `pcm_alaw` |
| `sample_rate` | yes | Integer Hz; must match the audio actually sent |
| `cartesia_version` | yes per spec | `2026-08-14` |
| `turn_start_threshold` | no | Default 0.8, range 0.5-0.9 |
| `turn_eager_end_threshold` | no | Default 0.6, range 0.3-0.8 |
| `turn_end_threshold` | no | Default 0.3, range 0.05-0.5 |
| `turn_end_timeout_ms` | no | Default 5600, range 640-11200 |
| `keyterm` | no | Repeat per term; up to 100 terms, 1200 chars total; fixed for the connection (https://docs.cartesia.ai/use-the-api/stt/keyterms) |

- Thresholds must stay strictly ordered: start > eager_end > end (https://docs.cartesia.ai/use-the-api/stt/turns).
- Documented presets: Balanced (0.8 / 0.6 / 0.3 / 5600, the default), Responsive (0.7 / 0.6 / 0.4 / 4500), Patient (0.8 / 0.3 / 0.1 / 8000).
- Thresholds can also be changed mid-session with a text frame: `{"type":"config","turn":{"start_threshold":0.8,"eager_end_threshold":0.6,"end_threshold":0.3,"end_timeout_ms":5600}}`.
- Keyterms are a good fit for household object names ("sugar", "salt", "keys") and the product name "Earmark".

### 3.4 Audio input

Source: https://docs.cartesia.ai/build-with-cartesia/stt/audio-input

- Realtime STT accepts raw headerless audio only; mono is expected.
- `pcm_s16le` pairs with 8000-48000 Hz; `pcm_f32le` with 16000-48000 Hz.
- Docs: "Speech recognition gains little from rates above 16 kHz, so downsampling to `pcm_s16le` at 16 kHz before you send cuts bandwidth with negligible impact on accuracy."
- Recommendation for the Mac mic: convert the input node's float audio to mono `pcm_s16le` at 16000 Hz and send 100 ms chunks (1600 samples, 3200 bytes).
- Audio goes as WebSocket binary frames, not base64 JSON; the concierge must base64-decode `mic_audio.chunk_b64` before forwarding.
- Pace sends at real time (about 1 s of audio per 1 s of wall clock); bursting a large buffer can overflow the server buffer and surface as an internal error (https://docs.cartesia.ai/use-the-api/stt/troubleshooting/auto).
- The server might not error on a wrong `encoding` or `sample_rate`; dump the raw stream and check with `ffplay -f s16le -ar 16000 -ac 1 audio.raw`.

### 3.5 Client to server messages (Auto)

- Binary frame: raw audio chunk.
- Text frame `{"type":"close"}`: flush buffered audio, emit the remaining events, then the server closes the socket.
- Text frame `{"type":"config", "turn": {...}}`: update thresholds mid-session.

### 3.6 Server to client events (Auto)

All are JSON text frames, and every one carries `request_id` (constant for the connection).

| `type` | Fields | Meaning |
| - | - | - |
| `connected` | `request_id` | Fires once on connect; no need to wait for it before sending audio |
| `turn.start` | `request_id` | User began speaking; use it to interrupt TTS (barge-in) |
| `turn.update` | `transcript` | Repeated; cumulative text of the current turn so far |
| `turn.eager_end` | `transcript` | Model predicts the user may be done; always followed by `turn.resume` or `turn.end` |
| `turn.resume` | none | Discard the last eager end; the user is still talking |
| `turn.end` | `transcript` | Definitive transcript for the completed turn |
| `error` | `status_code`, `title`, `message`, optional `error_code`, `doc_url` | Error |

- `transcript` is cumulative within a turn, never a delta, and emitted text is never revised (https://docs.cartesia.ai/use-the-api/stt/turns).
- Do not concatenate `turn.update` texts; take `turn.end` for the final text, and join separate turns with a space.
- Latency trick from the docs: start intent resolution on `turn.eager_end`, cancel on `turn.resume`, and commit on `turn.end`.
- Turn detection adds roughly half a second to `turn.end` compared with manual `finalize` (https://docs.cartesia.ai/use-the-api/stt/troubleshooting/auto).

### 3.7 Manual endpoint differences (for push-to-talk)

Source: https://docs.cartesia.ai/api-reference/stt/websocket and https://docs.cartesia.ai/use-the-api/stt/troubleshooting/manual

- Same `model`, `encoding`, `sample_rate`, `cartesia_version`, and `keyterm` parameters.
- `language`, `min_volume`, and `max_silence_duration_secs` are documented as `ink-whisper`-only.
- Commands are plain text frames, not JSON: `finalize` (transcribe what's buffered; acknowledged with `{"type":"flush_done"}`) and `close` (drain, then `{"type":"done"}`, then the server closes with code 1000).
- Events: `{"type":"transcript","is_final":bool,"text":...,"duration":...,"words":[{"word","start","end"}],"request_id":...}`.
- `text` is a delta: append every `is_final: true` chunk exactly as received, without trimming or adding spaces.
- Without `finalize`, the model falls back to slower silence-based finalization.
- Only send `finalize` after speech ends; finalizing mid-speech causes transcription errors.
- Cartesia explicitly recommends this endpoint for push-to-talk apps (https://docs.cartesia.ai/use-the-api/stt/migrations).

### 3.8 STT gotchas

- The server waits when audio stops arriving rather than treating it as silence, so while the mic is muted or gated, send zeros (https://docs.cartesia.ai/use-the-api/stt/turns).
- With the Auto endpoint and push-to-talk, simply stopping audio on key release means `turn.end` may never fire; either keep streaming zeros after release or send `{"type":"close"}`, which ends the session.
- Always send `close` and keep reading until the server closes, or the last second or so of audio is never transcribed.
- Idle STT WebSockets are closed after 3 minutes, and idle sockets still count toward STT concurrency (https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts).
- Billing counts silence: `ink-2` costs 3 credits per second of audio on both realtime endpoints, which is about 10,800 credits per hour of always-on listening (https://docs.cartesia.ai/pricing).
- UNVERIFIED: whether audio arriving while the socket is closed or reconnecting is lost; assume it is and buffer client-side.

### 3.9 Raw `websockets` sketch (not run)

```python
from websockets.asyncio.client import connect  # websockets >= 13

url = ("wss://api.cartesia.ai/stt/turns/websocket?model=ink-2"
       "&encoding=pcm_s16le&sample_rate=16000&cartesia_version=2026-08-14")
headers = {"Authorization": f"Bearer {api_key}", "Cartesia-Version": "2026-08-14"}
async with connect(url, additional_headers=headers) as ws:
    # sender task: await ws.send(chunk_3200_bytes) every 100 ms; at the end, await ws.send('{"type":"close"}')
    async for raw in ws:
        event = json.loads(raw)  # connected / turn.start / turn.update / turn.eager_end / turn.resume / turn.end / error
```

## 4. Sonic streaming TTS

### 4.1 Endpoint and models

- `wss://api.cartesia.ai/tts/websocket`, with `cartesia_version` required as header or query parameter (https://docs.cartesia.ai/api-reference/tts/websocket).
- `model_id` enum in the current spec: `sonic-3.6`, `sonic-3.5`, `sonic-3`, `sonic-latest`.
- `sonic-3.6` tracks the latest stable snapshot; `sonic-3.6-2026-08-27` never changes; `sonic-preview` is beta (https://docs.cartesia.ai/build-with-cartesia/tts-models/latest).
- Pin `sonic-3.6-2026-08-27` for both live speech and cached phrases so they sound identical (https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching).
- UNVERIFIED: the WebSocket spec's enum lists only alias names, while the caching guide recommends the dated snapshot; confirm with `GET /models?capability=tts` that the snapshot ID is accepted.
- `sonic`, `sonic-english`, `sonic-multilingual`, and several `sonic-2` and `sonic-turbo` snapshots were discontinued on June 1, 2026 (https://docs.cartesia.ai/changelog/2026).

### 4.2 Generation request (text frame)

```json
{
  "model_id": "sonic-3.6",
  "transcript": "It's at your two o'clock, about an arm's length away.",
  "voice": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
  "language": "en",
  "context_id": "utt-0007",
  "output_format": {"container": "raw", "encoding": "pcm_f32le", "sample_rate": 48000},
  "continue": false,
  "max_buffer_delay_ms": 0
}
```

- Required: `model_id`, `transcript`, `voice` (ID string or `{"id": ...}`; embeddings are no longer accepted), `output_format`, `context_id`.
- Optional: `language` or `locale` (never both), `continue` (default false), `max_buffer_delay_ms` (0-5000, default 3000), `flush`, `add_timestamps`, `add_phoneme_timestamps`, `use_normalized_timestamps`, `pronunciation_dict_id`, `normalization`, `accent`, and `generation_config` (`volume` 0.5-2.0, `speed` 0.6-1.5, `emotion` such as `neutral`, `calm`, `content`).
- All fields except `transcript`, `continue`, and `duration` must stay the same across messages on one context (https://docs.cartesia.ai/use-the-api/tts-websocket/contexts).
- Transcript chunks are concatenated verbatim, so include spaces between chunks.
- Use a fresh `context_id` per utterance; contexts expire 1 second after their last audio is streamed and cannot be reused.
- Cancel: `{"context_id": "utt-0007", "cancel": true}`.
- Cancel only stops requests that have not started generating; audio already generating keeps arriving, so barge-in must also stop playback locally and drop that context's remaining chunks.

### 4.3 Responses (text frames)

| `type` | Fields |
| - | - |
| `chunk` | `data` (base64 audio), `done` (false), `status_code` (206), `step_time` (ms), `context_id`, plus `flush_id` when flushing |
| `done` | `done: true`, `status_code`, `context_id`; sent only after the whole context finishes |
| `flush_done` | `flush_done: true`, `flush_id`, `context_id` |
| `timestamps` / `phoneme_timestamps` | Only when requested |
| `error` | `done: true`, `status_code`, `title`, `message`, `error_code`, `request_id`, `context_id` |

- Chunks for a context arrive in input order.
- With raw `websockets`, the `data` string can go straight into the bus `speak.chunk_b64` without decoding and re-encoding.

### 4.4 Buffering and latency

Source: https://docs.cartesia.ai/use-the-api/tts-websocket/buffering and https://docs.cartesia.ai/use-the-api/compare-tts-endpoints

- Earmark's response text is computed in code and is complete before TTS, so send the whole sentence in one message with `continue: false` and `max_buffer_delay_ms: 0` ("custom buffering").
- Don't combine client-side sentence aggregation with the default 3000 ms buffer delay; the server may wait up to 3 s for more text.
- End sentences with punctuation; otherwise the model may wait out the buffer delay.
- Keep one TTS WebSocket open: a new HTTPS request pays TCP and TLS setup, which is "often on the same order as TTFB for the audio itself."
- TTS WebSockets close after 5 minutes idle, so reconnect lazily or on a timer (https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts).
- The docs publish no TTFB numbers; any specific millisecond figure is UNVERIFIED.

### 4.5 Output format

Source: https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format

- WebSocket and SSE support only `container: "raw"`; `wav` and `mp3` work only on the bytes endpoint.
- Encodings: `pcm_f32le`, `pcm_s16le`, `pcm_mulaw`, `pcm_alaw`.
- Sample rates: 8000, 16000, 22050, 24000, 44100, 48000.
- The docs give no latency ranking between formats or sample rates; the official quickstart uses `pcm_f32le` at 44100 Hz.
- The docs' advice for browsers is to match the output device's sample rate to avoid resampling latency; the same reasoning applies to AVAudioEngine.
- Recommendation: `pcm_f32le`, mono, at the Mac output device's rate (read `engine.outputNode.outputFormat(forBus: 0).sampleRate` in Phase 0; likely 48000).
- UNVERIFIED (Apple-side, not Cartesia): Float32 maps directly onto AVAudioEngine's standard format and avoids an Int16-to-Float conversion step in Swift.
- `pcm_s16le` at 24000 Hz (the caching guide's choice) is a fine alternative if bus bandwidth matters, at the cost of conversion in the Mac app.
- Whatever is chosen, cached phrases must use the same encoding, sample rate, model snapshot, voice, and language as live speech.

### 4.6 Voices

- Voice agents work best with "stable, realistic" voices, per https://docs.cartesia.ai/build-with-cartesia/capability-guides/choosing-a-voice
- Stock voice IDs documented on https://docs.cartesia.ai/build-with-cartesia/tts-models/latest:

| Name | Locale | ID |
| - | - | - |
| Skylar | en-US, female | `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4` |
| Daniel | en-US, male | `47c38ca4-5f35-497b-b1a3-415245fb35e1` |
| Jacqueline | en-US, female | `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc` |
| Gemma | en-GB, female | `62ae83ad-4f6a-430b-af41-a9bede9286ca` |
| Archie | en-GB, male | `ef191366-f52f-447a-a398-ed8c0f2943a1` |

- The Cal Hacks page uses `a0e99841-438c-4a64-b679-ae501e7d6091` as its sample voice; the SDK examples use `6ccbfb76-1fc6-48f7-b71d-91ac6298247b` (names not given on those pages).
- Browse voices at https://play.cartesia.ai/voices, or list them with `GET /voices` (params `q`, `gender`, `language`, `is_owner`, `limit`, `starting_after`, `ending_before`, `expand[]`; https://docs.cartesia.ai/api-reference/voices/list).
- SDK: `client.voices.list()` returns a paginated page with `.data`, `.has_next_page()`, and `.get_next_page()`.
- Put the chosen voice ID in an env var, per brief rule 4.

## 5. Non-streaming TTS (bytes) for cached phrases

Source: https://docs.cartesia.ai/api-reference/tts/bytes

- `POST https://api.cartesia.ai/tts/bytes` with headers `Authorization: Bearer <key>`, `Cartesia-Version: 2026-08-14`, and `Content-Type: application/json`.
- Body: `model_id`, `transcript`, `voice`, `output_format` (required), plus optional `language` or `locale`, `generation_config`, `pronunciation_dict_id`, `normalization`.
- `output_format` example: `{"container": "wav", "encoding": "pcm_f32le", "sample_rate": 48000}`; WAV defaults are `pcm_s16le` at 44100 if omitted.
- The response is streamed binary `audio/*`.
- SDK: `client.tts.generate(model_id=..., transcript=..., voice=..., output_format={...}, language="en").write_to_file("config/phrases/<id>.wav")` (https://docs.cartesia.ai/examples/tts-generate-to-file).
- Cartesia's own caching guide generates raw PCM over the WebSocket and splices it into the live stream; WAV is fine for Earmark because `speak_cached` plays whole files rather than concatenating them (https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching).
- Generate phrases one at a time on the Free plan, since each bytes request counts as one TTS concurrency slot (limit 2).

## 6. Official Python SDK

- PyPI package `cartesia`; latest is 4.2.0 (released 2026-09-02), with `requires_python >= 3.9` (https://pypi.org/project/cartesia/).
- Install with `pip install 'cartesia[websockets]'`; the extra pins `websockets>=13,<16`, so the hub's `websockets` must stay in that range if they share a venv.
- The client-libraries page says `pip install --pre cartesia`, but 4.2.0 is a stable release, so `--pre` is unnecessary (https://docs.cartesia.ai/tools/client-libraries).
- The SDK has had several major versions in five months (3.1.0 on 2026-05-22, 4.0.0 on 2026-08-14, 4.2.0 on 2026-09-02); pin the exact version.
- The SDK defaults to `cartesia-version: 2026-08-14` and `Authorization: Bearer` (`src/cartesia/_client.py`).

Streaming STT, async (https://docs.cartesia.ai/examples/stt-auto-finalize-websocket):

```python
client = AsyncCartesia(api_key=os.environ["CARTESIA_API_KEY"])
async with client.stt.auto_finalize.websocket(
    model="ink-2", encoding="pcm_s16le", sample_rate=16000, keyterm=["sugar", "salt"],
) as conn:
    await conn.send_raw(chunk)            # bytes, about 100 ms each, paced in real time
    await conn.send({"type": "close"})    # when done
    async for event in conn:              # event.type in connected, turn.start, turn.update, ...
        ...
```

- The manual endpoint is `client.stt.manual_finalize.websocket(...)`, with `conn.send("finalize")` and `conn.send("close")`.

Streaming TTS, async (https://docs.cartesia.ai/get-started/realtime-text-to-speech-quickstart and `examples/async_examples.py` in the SDK repo):

```python
async with client.tts.websocket_connect() as ws:
    ctx = ws.context(model_id="sonic-3.6", voice=VOICE_ID, language="en",
                     output_format={"container": "raw", "encoding": "pcm_f32le", "sample_rate": 48000})
    await ctx.push("Got it, that's the sugar.", continue_=False)
    async for r in ctx.receive():         # r.type in chunk, done, error, ...; r.audio is decoded bytes
        ...
```

- Other helpers: `ctx.no_more_inputs()`, `ctx.cancel()`, and `ws.context(..., max_buffer_delay_ms=0)`.

SDK or raw `websockets`:

- STT: raw `websockets` is about 20 lines (binary frames out, JSON events in), and Earmark already depends on `websockets` for the bus.
- SDK auto-reconnect for STT is opt-in via `on_reconnecting`.
- When reconnect is enabled, `send_raw` queues audio by calling `data.decode("utf-8")` on the bytes (`src/cartesia/resources/stt/auto_finalize.py` line 264 in v4.2.0), which looks like it would raise on arbitrary PCM.
- Recommendation: use raw `websockets` for STT and handle reconnects in the concierge.
- TTS: both are simple; raw lets the concierge pass the base64 `data` straight through to `speak.chunk_b64`, while the SDK decodes it to bytes.
- Recommendation: use raw `websockets` for live TTS, and use the SDK's `tts.generate` for build-time phrase synthesis.
- Cartesia's Cal Hacks rules say "Prefer official SDKs for app code"; that is a preference, not a judging criterion.

## 7. Limits, pricing, latency, gotchas

Source: https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts and https://docs.cartesia.ai/pricing

| Plan | TTS concurrency | STT concurrency | Credits/month |
| - | - | - | - |
| Free | 2 | 8 | 20K |
| Pro | 3 | 12 | 100K |
| Startup | 5 | 20 | 1.25M |
| Scale | 15 | 60 | 8M |

- TTS concurrency counts active contexts; requests reusing one `context_id` don't add usage, and each HTTP request is one context.
- TTS WebSocket connections are capped at 10x the TTS concurrency limit.
- STT counts each open stream, idle or not.
- Going over either limit returns HTTP 429 (`concurrency_limited`).
- Idle timeouts: TTS WebSocket 5 minutes, STT WebSocket 3 minutes.
- Costs: TTS is about 1 credit per character; `ink-2` realtime is 3 credits per second including silence; failed requests cost nothing.
- Budget example: a 2-hour always-listening demo uses about 21,600 STT credits, which is more than the whole Free plan.
- Push-to-talk over the manual endpoint only bills while audio is actually sent (UNVERIFIED that an open socket with no audio is free).
- Overages are off by default on Free; once credits run out, requests fail (https://docs.cartesia.ai/pricing).
- Realtime STT accepts at most about 1 second of audio per second; send pre-recorded files through batch `/stt`, which supports `ink-whisper` only.
- Other tips: keep sockets open across turns, set `continue: false` on the last chunk, use `turn.eager_end` to get ahead, and use the manual endpoint plus `finalize` to avoid the roughly 0.5 s turn-detection overhead when the user's turn end is known (key release).

## 8. Where the brief conflicts with Cartesia's docs

1. Brief 2.5 says to extract "Credits" from the Cal Hacks page, but the page has no credits or claim process (https://docs.cartesia.ai/calhacks).
2. Brief 2.5 and 3: "Ink (streaming, with built-in turn detection)" is only true for `ink-2`/`ink-preview` on `/stt/turns/websocket`; the manual `/stt/websocket` endpoint and `ink-whisper` have no turn events.
3. Brief 4.4: the `transcript` message's `is_final` has no counterpart on the Auto endpoint; map `turn.update` and `turn.eager_end` to `is_final: false` and `turn.end` to `is_final: true`.
4. Brief 4.4 has no bus message for `turn.start`, which Cartesia positions as the barge-in signal; a contract proposal may be needed if Earmark should stop speech when the user starts talking.
5. Brief 5.E push-to-talk: Cartesia recommends the manual endpoint plus `finalize` for push-to-talk; on the Auto endpoint, stopping audio at key release stalls the turn (section 3.8).
6. Brief 5.E says to capture audio "at the sample rate Cartesia STT expects"; Cartesia accepts any declared rate from 8000 to 48000 Hz for `pcm_s16le`, and recommends 16 kHz as enough for speech.
7. Brief 5.E muting: if the Mac app gates or mutes the mic (for example while speech plays), it must keep sending zeros on the Auto endpoint, or the server stalls.
8. Brief 5.D latency budget ("final transcript to first audible audio in 1.2 s or less") starts after `turn.end`, which already includes about 0.5 s of turn-detection delay; use `turn.eager_end` to start Moss and LLM work early.
9. Brief 5.D and 3: model names come from env vars, but the cached phrases only match live speech if both use the same pinned snapshot (`sonic-3.6-2026-08-27`), so default the env var to the snapshot.
10. Brief 5.E "always-listening" mode costs about 10,800 credits per hour on `ink-2`, which exhausts the Free plan in under 2 hours; this needs paid credits or push-to-talk by default.
11. Brief 3 tech choices: the SDK's websockets extra constrains `websockets` to >= 13 and < 16.
12. Cal Hacks page vs brief: Cartesia's suggested routes are Managed Agents or plain Sonic TTS, and the page doesn't mention Ink; building a custom Ink plus Sonic pipeline is allowed ("use any part of Cartesia in your own way").
13. Docs inconsistency (not the brief): the manual-endpoint troubleshooting page says to pass `?language=xx` and that language detection isn't supported, while the API reference says `language` applies only to `ink-whisper` and that `ink-2` auto-detects; UNVERIFIED which is current, but the Auto endpoint avoids the question.

## Sources

- https://docs.cartesia.ai/calhacks
- https://docs.cartesia.ai/llms.txt
- https://docs.cartesia.ai/use-the-api/api-conventions
- https://docs.cartesia.ai/get-started/authenticate-your-client-applications
- https://docs.cartesia.ai/use-the-api/api-errors
- https://docs.cartesia.ai/api-reference/models/list
- https://docs.cartesia.ai/get-started/realtime-speech-to-text-quickstart
- https://docs.cartesia.ai/build-with-cartesia/stt/latest
- https://docs.cartesia.ai/build-with-cartesia/stt/older-models
- https://docs.cartesia.ai/use-the-api/stt/compare-endpoints
- https://docs.cartesia.ai/use-the-api/stt/turns
- https://docs.cartesia.ai/use-the-api/stt/keyterms
- https://docs.cartesia.ai/build-with-cartesia/stt/audio-input
- https://docs.cartesia.ai/use-the-api/stt/migrations
- https://docs.cartesia.ai/use-the-api/stt/troubleshooting/auto
- https://docs.cartesia.ai/use-the-api/stt/troubleshooting/manual
- https://docs.cartesia.ai/api-reference/stt/turns/websocket
- https://docs.cartesia.ai/api-reference/stt/websocket
- https://docs.cartesia.ai/examples/stt-auto-finalize-websocket
- https://docs.cartesia.ai/examples/stt-manual-finalize-websocket
- https://docs.cartesia.ai/get-started/realtime-text-to-speech-quickstart
- https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
- https://docs.cartesia.ai/api-reference/tts/websocket
- https://docs.cartesia.ai/api-reference/tts/bytes
- https://docs.cartesia.ai/use-the-api/compare-tts-endpoints
- https://docs.cartesia.ai/use-the-api/tts-websocket/contexts
- https://docs.cartesia.ai/use-the-api/tts-websocket/buffering
- https://docs.cartesia.ai/use-the-api/tts-websocket/context-flushing-and-flush-i-ds
- https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format
- https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching
- https://docs.cartesia.ai/build-with-cartesia/capability-guides/choosing-a-voice
- https://docs.cartesia.ai/api-reference/voices/list
- https://docs.cartesia.ai/examples/tts-generate-to-file
- https://docs.cartesia.ai/tools/client-libraries
- https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts
- https://docs.cartesia.ai/pricing
- https://docs.cartesia.ai/changelog/2026
- https://cartesia.ai/pricing
- https://pypi.org/project/cartesia/
- https://github.com/cartesia-ai/cartesia-python (tag v4.2.0)
