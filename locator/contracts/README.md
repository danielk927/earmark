# Locator message contracts

Message contracts between the Earmark **locator** (this repo's `locator/` component) and
the Earmark **hub** (the Mac-side WebSocket bus, owned by the teammate's session).
Everything here implements [LOCATOR_BRIEF.md](../LOCATOR_BRIEF.md) sections 2.3–2.4:
the four locator message types as JSON Schemas (draft 2020-12), one example per
variant under `examples/`, and the bridge that lets the locator talk to today's hub.

## Layout

- `<type>.schema.json` — JSON Schema (draft 2020-12) per message type. Exact fields,
  no extras: every schema sets `additionalProperties: false` (brief §2.4, "send no extra fields").
- `examples/<type>.<variant>.json` — valid example messages. Every example is validated
  against its schema by `tests/test_contracts.py`; the tests also prove the schemas
  reject extra fields, wrong enum values, and missing required fields.

## The four locator message types (brief §2.4)

The locator **sends** `listener_pose`, `mic_audio`, and `status`. `ptt` flows both ways:
the Mac app publishes it, the locator consumes it, and the locator's backup button
sends it too. The locator sends no other bus message types (brief §2.2) and ignores
every incoming type except `ptt`.

| Type | Direction | Purpose |
|---|---|---|
| `listener_pose` | locator → hub | The user's EAR position, one per valid fix (~3.33 Hz) |
| `mic_audio` | locator → hub | Push-to-talk speech audio, 40 ms PCM chunks |
| `status` | locator → hub | Health heartbeat, every 2 s and on state changes |
| `ptt` | Mac app ↔ bus ↔ locator | Push-to-talk start/stop |

### Publish rules (brief §2.4)

- One `listener_pose` per valid fix — about 3.33 Hz when all 5 beacons are heard.
  No pose at all when a cycle produced no valid fix.
- After 1.5 s with no valid fix: **exactly one** pose with `quality: "lost"` holding
  the last position, then nothing until fixes resume. This keeps the Mac app's
  1.5 s hold and 5 s mat-origin fallback timers meaningful.
- `position` is the **EAR position** (center of the head), room frame: origin = floor
  point directly under the mat center, +x right, +y forward, +z up, meters (§2.1).
- `t` is Unix epoch seconds (float) of the **measurement time** — the time the position
  refers to, not the send time.
- `mic_audio.seq` resets to 0 at each `ptt start` and increments by 1 per 40 ms chunk
  (640 samples = 1280 bytes at 16 kHz). The example files use a short placeholder
  chunk for readability; real chunks are 1280 bytes.
- Never queue stale poses: if the WebSocket is down, drop them (§8.4).

## Integration bridge with today's hub (verified facts)

The brief's contracts describe the negotiated end state. The hub that exists **today**
differs, so the locator runs a small bridge until Appendix B negotiation lands.
The facts below were verified against the hub's live source on **2026-10-24**
(file:line references into this repo's `hub/earmark/`):

1. **Endpoint** — aiohttp server; the WebSocket route is `ws://<mac-ip>:8765/ws`.
   `server.py:78` adds `/ws`; `server.py:81` serves the operator dashboard at `/`.
2. **No token auth** — `hub.py:150-152`: a `hello` message sets the client role from
   `msg.get("role", "unknown")`, accepted as any string. The locator connects and
   sends `{"type":"hello","role":"sensor","name":"locator"}`. The brief's `?token=`
   and hello-token modes (§2.3) remain implemented for the negotiation, but today's
   hub ignores tokens.
3. **Unknown message types are silently ignored** — `hub.py:173-174` falls through to
   `log.debug("ignoring message type %r", kind)`. A `listener_pose` sent today is a
   harmless no-op on the hub.
4. **Native pose message** — `{"type":"pose","pos":[x,y,z]?,"yaw":<degrees>?,"source":<string>}`.
   Dispatched at `hub.py:160-161` into `brain.on_pose` (`brain.py:205`), which merges
   `pos` and `yaw` **independently** (`brain.py:207-211`): a pos-only pose never
   clobbers the Mac app's head-tracking yaw. The hub defaults `source` to `"app"`
   when omitted, so the locator always sets it explicitly.

### The bridge

The locator sends **both**:

- the native `pose` message — `pos` only, **no** `yaw`, `source: "beacons"` — so
  today's hub tracks the listener; and
- the rich `listener_pose` per brief §2.4 — ignored by today's hub, adopted when the
  other repo accepts Appendix B.

The native `pose` type belongs to the other repo; its shape is documented here but
not owned here. This directory defines schemas only for the four locator types.
When the hub adopts `listener_pose` (and `mic_audio`/`ptt`/`status`), the `pose`
bridge shim retires.

## For the other team (Appendix B checklist)

1. `listener_pose` fields: `type`, `position` [x,y,z] (EAR position, room frame:
   origin = floor under mat center, +x right, +y forward, +z up), `quality`
   (`ok|degraded|lost`), `beacons_heard`, `source` (`beacons|steps|sim|manual`),
   `t` (Unix seconds of the MEASUREMENT time).
2. Poses ~3.3 Hz, valid fixes only; after 1.5 s without a fix, ONE `lost` pose, then
   silence until recovery. Treat `lost` as no pose; your 1.5 s hold and 5 s fallback
   timers still apply.
3. No velocity field — derive velocity from successive poses for your 25+ Hz prediction.
4. `mic_audio`: pcm_s16le mono, `sample_rate` 16000 default (configurable — tell us
   what Cartesia STT wants), 40 ms chunks, seq resets to 0 at each `ptt start`.
5. `ptt` `start|stop` flows both ways (your Mac app publishes; our backup button sends).
6. Auth: the hub currently has none; the locator sends
   `{"type":"hello","role":"sensor","name":"locator"}`. Tell us when token auth lands.
7. The locator also sends `{"type":"status","component":"locator","ok":bool,"detail":str}`
   every 2 s and on state changes.
8. Beacon positions are read from your `space.json` `beacons` key: `[{id, position, slot}]`.
9. Item spot coordinates come from the locator app's "Save point" (the mic position
   when the phone is held at the spot), for your `space.json` spots.
