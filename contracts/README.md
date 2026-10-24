# Earmark contracts

The contracts are law.
Every component talks to every other component only through these schemas.
If a component needs a change, it proposes one to the orchestrator; it never edits this directory itself.

## Layout

- `schemas/` - JSON Schema (draft 2020-12), the source of truth.
  - `detection_event.schema.json` - adapter to hub.
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

- Units are meters; +x right, +y forward, +z up, from the listener at calibration time.
  The origin is the calibrated listening position (center of the head).
- Head yaw is degrees from the calibrated forward direction, positive when the head turns right.
  Pitch is positive looking up.
- Every time is unix seconds as a float (`t`, `*_t`).
  In `scenarios/*.jsonl`, `t` is seconds from scenario start and the simulator rewrites it to wall time.
- All JSON on the wire and on disk is snake_case.
  Convex tables are camelCase internally and convert only at the HTTP boundary (`convex/http.ts`).
  The one exception is query-string names on the Convex read endpoints, kept exactly as the brief specifies (`objectId`, `since`, `date`, `name`).
- A field listed in a schema's `required` but typed nullable must be sent as `null`, never omitted.

## Bus rules

- Every client sends `hello` first and receives a `snapshot` (space, registry, all object states).
- The hub forwards each message to every other client whose `subscribe` list includes its type.
  Without `subscribe`, a client receives everything except `mic_audio` and `speak`; `["*"]` means everything.
- The hub validates every inbound message against the schema and drops invalid ones with a logged `status` error.
- `detection` messages from bus clients (e.g. the simulator) are fed into the hub's state engine exactly like in-process adapter events.

## Spot reader semantics

- Readers report by polling: `kind: "seen"` with the tag on the spot, or `kind: "removed"` with `tag: "EMPTY"` when the spot is empty.
- The hub's debounce turns that into placements (2 consecutive matching reads) and removals (about 1.5 s of continuous absence).
- `kind: "placed"` is for adapters that debounce themselves (e.g. a future camera adapter).
- `status: "roaming"` means tracked by any non-spot method (BLE proximity today, camera position or area later).
- A `pickup` is emitted when removal is confirmed, about 1.5 s after the lift; trial times include that same debounce in both modes, so Earmark-vs-baseline comparisons stay fair.

## Medication adherence (deterministic, implemented and unit-tested in Convex)

For each scheduled time S (household-local) and window W minutes, using pickups of the medication object:
- `taken`: a pickup with |pickup - S| <= W.
- `late`: no `taken` pickup, but a pickup with W < pickup - S <= 2W.
- `missed`: neither, and now > S + 2W.
- `pending`: neither, and now <= S + 2W.
Each pickup is evidence for at most one dose (the nearest scheduled time).

## Changing a contract

1. Edit the schema and add or adjust examples.
2. Mirror the change in `python/earmark_contracts/__init__.py` and `swift/Sources/EarmarkContracts/BusMessage.swift`; regenerate `ts/index.ts`.
3. Run `make contracts-test`.
4. Note the change in `docs/project/STATUS.md` under "Contract changes".
