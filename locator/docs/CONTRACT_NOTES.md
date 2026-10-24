# CONTRACT_NOTES.md — locator ↔ hub interface notes

For the other repo's session (the Mac hub, spatial audio, voice) and for the human
carrying the message between the two sessions. The brief requires this document and
its Phase-D use: *"run docs/CONTRACT_NOTES.md against the other repo's actual schemas
and report any mismatch to the human immediately, with the exact field difference"*
(§10 Phase D, §2.3–2.4).

The file of record for the four locator message contracts is
[contracts/README.md](../contracts/README.md) with the JSON Schemas beside it; this
document summarizes those contracts and adds what today's hub actually does, verified
against its live source. It does not contradict the contracts README — it extends it
with integration facts.

---

## 1. Verified hub facts (read from the live source, 2026-10-24)

Verified against `hub/earmark/` in this repo (the other session's code, read
read-only). File:line references as of that date; **re-verify if the hub changes**:

1. **Endpoint** — aiohttp server; the WebSocket route is **`ws://<mac-ip>:8765/ws`**
   (`server.py:78` adds `/ws`; `server.py:81` serves the operator dashboard at `/`).
   The port in the brief (§2.3, 8765) is right; the path is `/ws`.
2. **No token auth** — `hub.py:150-152`: a `hello` message sets the client role from
   `msg.get("role", "unknown")`, accepted as **any string**. There is no token check.
   The locator connects and sends `{"type":"hello","role":"sensor","name":"locator"}`.
3. **Unknown message types are silently ignored** — `hub.py:173-174` falls through to
   `log.debug("ignoring message type %r", kind)`. A `listener_pose` sent today is a
   harmless no-op on the hub.
4. **Native pose message** — `{"type":"pose","pos":[x,y,z]?,"yaw":<degrees>?,
   "source":<string>?}`. Dispatched at `hub.py:160-161` into `brain.on_pose`
   (`brain.py:205`), which merges `pos` and `yaw` **independently**
   (`brain.py:207-211`): a pos-only pose never clobbers the Mac app's head-tracking
   yaw. The hub defaults `source` to `"app"` when omitted, so the locator always sets
   it explicitly.
5. **The hub has NO handlers yet for** `mic_audio`, `ptt`, `listener_pose`, or
   `status` — none appear in the dispatch (`hub.py` `handle()`), and unknown types are
   ignored per fact 3. They are future-facing contract traffic (part 3).

## 2. The adapter decision (what the locator sends today)

The brief's contracts (§2.4) describe the negotiated end state; the hub that exists
today speaks only its own dialect. Decision (also in [contracts/README.md](../contracts/README.md)):

- The locator sends **both**:
  1. the **native `pose` bridge message** — `{"type":"pose","pos":[x,y,z],
     "source":"beacons"}` — **`pos` only, no `yaw`** — so today's hub tracks the
     listener; and
  2. the rich **`listener_pose`** of brief §2.4 — ignored by today's hub, adopted
     when the other repo accepts Appendix B.
- **Why both:** the hub's independent pos/yaw merge (fact 4) means a pos-only bridge
  pose composes with the Mac app's head tracking instead of overwriting it. The bridge
  pose carries the *ear* position in the same room frame as `listener_pose`
  (origin = floor under mat center, +x right, +y forward, +z up — §2.1), so the two
  agree by construction.
- **PTT ships per contract, pending hub adoption:** the locator already honors `ptt
  start/stop` and streams `mic_audio` per §2.4/§8.5, but until the hub grows handlers
  (fact 5) the Mac app's own push-to-talk path stays the one that works. No locator
  change is needed when the hub adopts the contract — the messages are already
  correct.
- **Retirement condition:** when the hub handles `listener_pose` (and `mic_audio` /
  `ptt` / `status`), the `pose` bridge shim is removed (one config flip, not a fork).

The native `pose` type belongs to the other repo; its shape is documented in the
contracts README but not owned or schema-validated here.

## 3. The four locator message types (contract summary)

Full schemas with `additionalProperties: false` (exact fields, no extras — §2.4) and
one validated example per variant:

| Type | Direction | Schema | Example |
|---|---|---|---|
| `listener_pose` | locator → hub | `contracts/listener_pose.schema.json` | `contracts/examples/listener_pose.ok.json` (+ `.degraded`, `.lost`) |
| `mic_audio` | locator → hub | `contracts/mic_audio.schema.json` | `contracts/examples/mic_audio.chunk.json` |
| `ptt` | Mac app ↔ bus ↔ locator | `contracts/ptt.schema.json` | `contracts/examples/ptt.start.json`, `ptt.stop.json` |
| `status` | locator → hub | `contracts/status.schema.json` | `contracts/examples/status.healthy.json`, `status.unhealthy.json` |

Field-level summary (§2.4; the schemas' `description` fields are normative):

- **`listener_pose`**: `type`, `position` [x,y,z] — the user's **EAR** position (=
  filtered mic position + ear offset, §6.8), room frame per §2.1 — `quality`
  (`ok|degraded|lost`), `beacons_heard` (0–5, number actually used in the solve),
  `source` (`beacons|steps|sim|manual`), `t`.
- **`mic_audio`**: `type`, `seq`, `sample_rate` (default 16000), `encoding`
  (`pcm_s16le`), `chunk_b64` (40 ms = 640 samples = 1280 bytes at 16 kHz).
- **`ptt`**: `type`, `state` (`start|stop`).
- **`status`**: `type`, `component` (`locator`), `ok`, `detail` (short human summary,
  never a payload dump — debug data stays local, §2.2).

## 4. Semantics the other side must know

- **Publish rules** (§2.4): one `listener_pose` per valid fix, ~3.33 Hz with all five
  beacons; **no pose at all** when a cycle produced no valid fix; after **1.5 s**
  without a valid fix, **exactly one** pose with `quality: "lost"` holding the last
  position, then silence until fixes resume. Treat `lost` as *no pose* — the Mac
  app's own 1.5 s hold and 5 s mat-origin fallback timers still apply (§2.4).
- **No velocity field** — the Mac app derives velocity from successive poses for its
  25+ Hz prediction (§2.4, Appendix B point 3).
- **`t` semantics**: Unix epoch seconds (float) of the **measurement time** — the time
  the position refers to, not the send time (§2.4). Converted from the phone's sample
  clock via `hostTime` anchors (§6.8, §8.1). If you timestamp on receipt, you add
  variable network latency — use `t`.
- **`seq` semantics** (§2.4): `mic_audio.seq` resets to **0 at each `ptt start`** and
  increments by 1 per 40 ms chunk. Gaps mean dropped chunks (the locator never queues
  stale audio, §8.4); a seq of 0 mid-stream means a new push-to-talk turn began.
- **Auth modes** (§2.3): the locator implements both `?token=<token>` on the URL
  (default) and the hello-token first message — but **today's hub has no token auth**
  (fact 2), so effectively the locator sends
  `{"type":"hello","role":"sensor","name":"locator"}` and connects. Tell the locator
  when token auth lands on the hub.
- **Inbound filtering** (§2.3): the locator ignores every incoming type except `ptt`;
  it never echoes or reacts to your other traffic.
- **`status` cadence** (§2.4): every 2 s and whenever something changes; `ok` is false
  when quality is `lost`, the mic isn't running, or the config is invalid.
- **Network expectation** (§1): phone and Mac share a LAN — prefer the iPhone's
  Personal Hotspot or a travel router, not the venue Wi-Fi.

## 5. What the locator reads from you

- **Beacon positions** from the `beacons` key of your `space.json`:
  `[{"id","position","slot"}]` — bare `{"beacons":[...]}` files are accepted too
  (§2.2 import rule). Everything else in `space.json` is ignored by the locator.
- **Item spot coordinates** come back to you from the locator app's "Save point"
  (the *mic* position when the phone is held at the spot, §8.3 step 5), formatted
  `{"label","position"}` for your `space.json` `spots`. Note it is the mic position
  at the spot, not the ear position.

## 6. Appendix B — paste-ready block for the other session

The human hands this block to the other repo's session (updated from brief Appendix B
with the verified facts of part 1):

```text
LOCATOR INTERFACE NOTES (from the locator repo). Please confirm or flag conflicts:

CONTEXT — verified against your hub source on 2026-10-24 (hub/earmark/hub.py,
brain.py, server.py): your WebSocket endpoint is ws://<mac-ip>:8765/ws; you have no
token auth (a hello message sets role from any string); unknown message types are
silently ignored (log.debug fallthrough); your native "pose" message
{type:"pose", pos?, yaw?, source?} is dispatched to brain.on_pose, which merges pos
and yaw independently (a pos-only pose does not clobber your head-tracking yaw); and
you have NO handlers yet for mic_audio, ptt, listener_pose, or status.

WHAT WE DO TODAY (no change needed on your side for basic tracking):
1. We connect to ws://<mac-ip>:8765/ws and send {"type":"hello","role":"sensor",
   "name":"locator"} (your hub accepts any role string; no token).
2. We send your native pose message with pos ONLY, no yaw, source "beacons":
   {"type":"pose","pos":[x,y,z],"source":"beacons"} — so your independent pos/yaw
   merge keeps your Mac app's head-tracking yaw. Same room frame as below:
   EAR position, origin = floor under mat center, +x right, +y forward, +z up, meters.
3. We ALSO send the listener_pose described below; your hub silently ignores it
   today. It becomes live when you accept this note.

THE NEGOTIATED CONTRACT (brief sections 2.3-2.4; JSON Schemas + examples live in
locator/contracts/):
1. listener_pose has exactly the fields: type, position [x,y,z] (EAR position, room
   frame, origin = floor under mat center, +x right, +y forward, +z up), quality
   (ok|degraded|lost), beacons_heard, source (beacons|steps|sim|manual), t (Unix
   seconds of the MEASUREMENT time — not the send time).
2. Poses are sent about 3.3 Hz, only on valid fixes. After 1.5 s without a fix, we
   send ONE pose with quality "lost", then nothing until it recovers. Treat "lost"
   as no pose; your 1.5 s hold and 5 s fallback timers still apply.
3. No velocity field — derive velocity from successive poses for your 25+ Hz
   prediction.
4. mic_audio: pcm_s16le mono, sample_rate 16000 by default (configurable; tell us
   what Cartesia STT needs), 40 ms chunks (640 samples = 1280 bytes), seq resets to
   0 at each ptt start and increments by 1 per chunk.
5. ptt {"type":"ptt","state":"start|stop"} flows both ways: your Mac app publishes
   it, we consume it, and our backup button also sends it. We stream mic_audio only
   while PTT is active. Your hub has no ptt/mic_audio handler yet — until you adopt
   them, your own PTT path stays the working one.
6. Bus auth: your hub currently has none; we send hello {"role":"sensor"}. We also
   implement ?token= on the URL and a hello-token first message (brief 2.3) — tell
   us which one you want when you add auth.
7. We also send {"type":"status","component":"locator","ok":bool,"detail":str} every
   2 s and on state changes (no handler on your side yet — ignored is fine).
8. We read beacon positions from the "beacons" key of your space.json:
   [{"id","position","slot"}]; a bare {"beacons":[...]} file works too.
9. Item spot coordinates come from our app's "Save point" (the MIC position when
   the phone is held at the spot) as {"label","position"} for your space.json spots.

TELL US: (a) confirm or correct items 1-9; (b) the Cartesia STT sample rate if not
16000; (c) when listener_pose/mic_audio/ptt/status handlers land, so we retire our
native-pose bridge shim.
```

## 7. Verification trail

- Hub facts re-verified this session against the live source in this repo:
  `hub/earmark/hub.py` (`handle()` dispatch — hello/role at 150-152, pose at 160-161,
  ignore fallthrough at 173-174), `hub/earmark/brain.py` (`on_pose` at 205, independent
  pos/yaw merge at 207-211), `hub/earmark/server.py` (`/ws` route at 78, dashboard at
  81). Verified 2026-10-24.
- The same facts, with the same references, are recorded in
  [contracts/README.md](../contracts/README.md) ("Integration bridge with today's
  hub") — that file is the contracts side of record; if hub code changes, re-verify
  and update both.
- No web sources were needed for this document; every integration claim above points
  into the repo.
