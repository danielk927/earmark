# Earmark contracts

The contracts are law.
Every component talks to every other component only through these schemas.
If a component needs a change, it proposes one to the orchestrator; it never edits this directory itself.

## Layout

- `schemas/` - JSON Schema (draft 2020-12), the source of truth.
  - `object_state.schema.json` - hub to bus and Convex (`type: "state_update"`).
  - `bus_message.schema.json` - every message on the local bus `ws://127.0.0.1:8765`, discriminated by `type`.
  - `space.schema.json` - `config/space.json`.
  - `registry.schema.json` - `config/objects.seed.json`, `config/objects.cache.json`, and Convex `GET /api/registry`.
  - `phrases.schema.json` - `config/phrases.json`.
  - `convex_http.schema.json` - request and response bodies of the Convex HTTP actions.
- `examples/` - at least two valid examples per message type, used by every language's tests.
- `python/` - `earmark-contracts` pydantic models (`parse_bus`, `dump`, `to_dict`).
- `ts/` - TypeScript types generated from the schemas (`npm run gen`; `npm run check` fails if stale).
- `swift/` - `EarmarkContracts` Swift package (`BusCoding.decode` / `BusCoding.encode`).

Run all contract tests with `make contracts-test`.

## Conventions

- Units are meters; +x right, +y forward, +z up.
- **Amendment 01 (walking):** the origin is a fixed room point, the floor directly under the center of the mat.
  Forward (+y) is the direction of the mat's tape arrow.
  The listener is not at the origin: their ear position comes from `listener_pose` (about 3 Hz, from the iPhone locator, or the simulator).
  Without a pose for 1.5 s, consumers hold the last position ("position lost"); after 5 s they use `space.listener.fallback_position` (the mat at standing ear height).
- Head yaw is degrees from the calibrated forward direction (recentered facing the mat arrow), positive when the head turns right.
  Pitch is positive looking up.
- The only Earmark-to-AVAudio conversion is `avaudio = (x, z, -y)`, in one Swift function.
- Every time is unix seconds as a float (`t`, `*_t`).
  In `scenarios/*.jsonl`, `t` is seconds from scenario start and the simulator rewrites it to wall time.
- All JSON on the wire and on disk is snake_case.
  Convex tables are camelCase internally and convert only at the HTTP boundary (`convex/http.ts`).
  The one exception is query-string names on the Convex read endpoints, kept exactly as the brief specifies (`objectId`, `since`, `date`, `name`).
- A field listed in a schema's `required` but typed nullable must be sent as `null`, never omitted.

## Bus rules

- The hub binds `0.0.0.0:8765` so LAN clients (the iPhone locator over the Mac's hotspot or Wi-Fi) can connect.
  Non-loopback clients must present `EARMARK_BUS_TOKEN` as `ws://<mac>:8765/?token=<token>` or the header `X-Earmark-Token`; without a configured token, non-loopback clients are refused.
  Loopback clients (the components on the Mac) need no token.
- The locator sends `hello` with component `locator`, publishes `listener_pose`, subscribes to `ptt`, and streams `mic_audio` between `ptt` start and stop.

- Every client sends `hello` first and receives a `snapshot` (space, registry, all object states).
- The hub forwards each message to every other client whose `subscribe` list includes its type.
  Without `subscribe`, a client receives everything except `mic_audio` and `speak`; `["*"]` means everything.
- The hub validates every inbound message against the schema and drops invalid ones with a logged `status` error.
- `save_spot` from the locator updates an item's saved spot; the hub then re-sends a `snapshot` to every client.

## Item locations (design v7)

- There is no detection hardware: no NFC, no Bluetooth tags, no cameras.
- Each item's location is a **saved spot**: during setup the locator sends `save_spot {object_id, position}` while the phone is held at the spot.
  The hub stores it in `config/space.json` (and the object's `home_spot`), syncs it to Convex (`POST /api/spot`), and re-sends a `snapshot` to every client.
- `state_update` reports `on_spot` (with the saved position) or `missing` (no saved spot yet).
- `status: "roaming"` and `kind`-style detection events no longer exist.

## Medication adherence (deterministic, implemented and unit-tested in Convex)

Evidence is **arrival** at the medication's spot (the user asked for the pills, was guided, and found them), not proof that a dose was taken; every answer says "found", never "took".
For each scheduled time S (household-local) and window W minutes, using `arrived` events for the medication object:
- `found`: an arrival with |arrival - S| <= W.
- `late`: no `found` arrival, but one with W < arrival - S <= 2W.
- `missed`: neither, and now > S + 2W.
- `pending`: neither, and now <= S + 2W.
Each arrival is evidence for at most one dose (the nearest scheduled time).

## Walking guidance (Amendment 01, implemented in the Mac app)

- Ping interval = 0.15 + 0.3 x distance seconds, clamped to 0.18-1.0 s (distance from the ear to the target, 3D).
- Inverse distance attenuation with reference distance 0.5 m and maximum 6 m.
- Locked tone when the azimuth error stays under about 10 deg for 300 ms; behind sound when it exceeds 100 deg.
- Height cue: a higher-pitched ping when the target is 0.3 m or more above the ears, lower when it is 0.6 m or more below.
- The ping is a short click (easier to localize than a beep).
- `arrived` when the horizontal distance to the target drops below 0.45 m: the Mac app stops the ping and plays a short "you're here" tone; the concierge speaks the spot's `detail` and sends `guide_stop` (reason `arrived`).

## Changing a contract

1. Edit the schema and add or adjust examples.
2. Mirror the change in `python/earmark_contracts/__init__.py` and `swift/Sources/EarmarkContracts/BusMessage.swift`; regenerate `ts/index.ts`.
3. Run `make contracts-test`.
4. Note the change in `docs/STATUS.md` under "Contract changes".
