# Earmark Convex backend

Convex is Earmark's database and cloud API.
The hub posts events and object states to HTTP actions, the dashboard subscribes to live queries, and the memory agent reads HTTP endpoints.
Everything follows `convex/_generated/ai/guidelines.md` (validators on every function, internal functions for anything not client-facing, indexed and bounded reads, no clock in queries).

## Run it locally (no Convex account)

```sh
npm install
CONVEX_AGENT_MODE=anonymous npx convex dev --once   # first time only: creates the local deployment, writes .env.local
npx convex env set EARMARK_HUB_SECRET "$(openssl rand -hex 24)"
npx convex env set EARMARK_READ_SECRET "$(openssl rand -hex 24)"
npm run dev      # keep running: local backend + watcher (client http://127.0.0.1:3210, HTTP actions http://127.0.0.1:3211)
npm run seed     # in another terminal
```

| Script | Command | What it does |
| - | - | - |
| `npm run dev` | `convex dev` | Runs against the deployment in `.env.local` and re-pushes on save. |
| `npm run dev:local` | `CONVEX_AGENT_MODE=anonymous convex dev` | Same, but forces the no-account local deployment (first run on a fresh checkout). |
| `npm run push` | `convex dev --once` | Codegen, typecheck, push once, exit (fails while `npm run dev` is running; it re-pushes anyway). |
| `npm run seed` | `node convex/scripts/seed.node.mjs seed` | Loads `config/space.json` and `config/objects.seed.json` (see below). |
| `npm run reset` | `node convex/scripts/seed.node.mjs reset` | Back to the demo starting state in about half a second. Never touches trials. |
| `npm test` | `vitest run` | All tests (convex-test, Vitest, edge-runtime). |
| `npm run typecheck` | `tsc -p convex --noEmit` | Includes the client-contract type test. |

Extra arguments after `seed` or `reset` go to `npx convex run`, for example `node convex/scripts/seed.node.mjs reset --prod`.
The local dashboard is `npx convex dashboard` (opens http://127.0.0.1:6790, not in Safari).

## Environment variables (on the deployment)

Set with `npx convex env set NAME value` (or `printf %s "$VALUE" | npx convex env set NAME` to keep it out of shell history).
They are declared in `convex/convex.config.ts` and read through the typed `env` export.
All are optional at deploy time, so a fresh deployment pushes before they are set.

| Name | Used by | If unset |
| - | - | - |
| `EARMARK_HUB_SECRET` | every HTTP route | every route answers 401 |
| `EARMARK_READ_SECRET` | `GET /api/*` only | only the hub secret works |
| `ANTHROPIC_API_KEY` | `labeling:suggestFromPhoto` | the action deletes the photo and throws "Photo suggestions are not set up: ANTHROPIC_API_KEY is missing..." |
| `ANTHROPIC_BASE_URL` | same | `https://api.anthropic.com/v1` |
| `ANTHROPIC_VISION_MODEL` | same | `claude-haiku-5-5` |

Clients only need the URLs from `.env.local`: `CONVEX_URL` (client, dashboard) and `CONVEX_SITE_URL` (HTTP actions, hub, agents).

## Tables (`schema.ts`)

| Table | Contents | Indexes |
| - | - | - |
| `household` | Singleton: `name`, `timezone` (IANA), `registryVersion` (ms, strictly increasing) | - |
| `objects` | `objectId`, `name`, `aliases`, `notes`, `description`, `tag` (uppercase NFC UID or null), `homeSpot`, `isMedication`, `fobId`, `updatedAt` (ms) | `by_objectId`, `by_tag`, `by_fobId`, `by_name` |
| `spots`, `areas`, `receivers` | From `config/space.json`; positions are `[x, y, z]` meters | `by_spot`, `by_area`, `by_receiver` |
| `events` | Append-only hub events: `eventId` (unique), `kind`, `objectId`, `t`, `spot`, `data` (the original snake_case message) | `by_eventId`, `by_t`, `by_objectId_and_t`, `by_objectId_and_kind_and_t`, `by_kind_and_t` |
| `objectState` | One row per object, the newest `t` wins | `by_objectId` |
| `medications` | `objectId`, `scheduleTimes` ("HH:MM", household-local), `windowMinutes` (default 60), `activeSinceT` | `by_objectId` |
| `doses` | Materialized adherence: `objectId`, `date`, `scheduledLocalTime`, `scheduledFor`, `status`, `takenT`, `evidenceEventId` | `by_date_and_scheduledFor`, `by_objectId_and_date` |
| `trials` | Brief 5.I fields; `tester` is a pseudonym. Written only by `trial_start`/`trial_end` events | `by_trialId`, `by_startedAt` |
| `unknownTags` | Unlabeled tags on a spot; cleared when labeled or removed | `by_tag`, `by_t` |
| `dailySummaries` | One per household-local date | `by_date` |
| `dailyCounts` | Pickup counter per local date, incremented in the ingest transaction | `by_date` |

## HTTP actions (`http.ts`)

Bodies are exactly `contracts/schemas/convex_http.schema.json` (and `registry.schema.json` for the registry).
JSON is snake_case on the wire; conversion happens only in `http.ts` via `lib/wire.ts`.
Header `X-Earmark-Secret` is compared in constant time (SHA-256 of both sides, then XOR).
Errors are `{"ok": false, "error": "..."}`: 401 for auth, 400 for an invalid body or query (the message names the field), 404 for an unknown `objectId`.

| Route | Secret | Notes |
| - | - | - |
| `POST /ingest` | hub | One transaction per request, at most 500 events and 500 states. Idempotent by `event_id` (duplicates counted, including within a batch). Bodies are validated strictly; any invalid item rejects the whole batch with 400. `accepted_states` counts states written (an older `t` than the stored one is ignored). Side effects: pickups count toward the day and re-materialize that medication's doses; `trial_start`/`trial_end` upsert `trials`; `unknown_tag` upserts `unknownTags`; `removed` or `label` of that tag clears it. |
| `POST /api/label` | hub | Creates an object for the tag (objectId from the name, `_2` suffix on collision; `spot` becomes `home_spot`) or renames the object that has it (existing aliases kept, new ones added). |
| `GET /api/registry` | hub or read | Registry shape; `version` changes on every registry write (objects or schedules, including removals), so the hub can compare one number. |
| `GET /api/object?name=` | hub or read | Case-insensitive exact name, then alias, then substring (either direction, whole words), best first. |
| `GET /api/objects` | hub or read | Every object with state, spot labels, and last pickup or placement. |
| `GET /api/history?objectId=&since=` | hub or read | `since` in unix seconds, default 7 days ago; newest first, max 200; `detail` is a deterministic sentence. |
| `GET /api/adherence?date=` | hub or read | Household-local date, default today. Recomputes that date at request time, then returns it. |
| `GET /api/daily-summary?date=` | hub or read | Default today. Past days return the stored summary; today, or a day without one, is built on demand. `text` is generated by code. |

## Client functions (the dashboard contract)

Names, arguments, and return shapes match `contracts/ts/convexFunctions.ts`; `contract.test.ts` checks this at compile time and every name at run time.

| Function | Kind | Notes |
| - | - | - |
| `dashboard:liveMap` | query | Household, spots, areas, objects, states, unlabeled tags (newest first). Re-runs whenever `/ingest` writes, so the dashboard never polls (measured: pushed to a subscriber 15 ms after `/ingest` returned). |
| `objects:list` / `create` / `update` / `remove` | query / mutations | Validation errors are `ConvexError`s with a readable message. `remove` also deletes the object's state, schedule, and doses; events stay. |
| `events:recent` | query | `limit` default 50, max 200; sentences name the object. |
| `medications:list` / `upsert` | query / mutation | `upsert` validates "HH:MM" and a window of 1 to 720 minutes, marks the object as a medication, and recomputes today and yesterday. |
| `doses:forDate` | query | Reads materialized doses only. |
| `trials:list` / `summary` | queries | Summary: per mode, completed trials, found, distinct testers, median seconds to find (found trials), total wrong picks. Raw counts only. |
| `labeling:generateUploadUrl` | mutation | Upload URL for one photo. |
| `labeling:suggestFromPhoto` | action | See below. |

## Adherence (`lib/adherence.ts`)

The rules in `contracts/README.md`, as a pure function with unit tests (boundaries, early pickups, multiple pickups, nearest-dose assignment, DST day).
For one date, the doses of the day before and after take part in the nearest-dose assignment, so pickups near midnight are attributed correctly.
Doses are materialized in mutations, never computed from the clock in a query: on every ingested pickup of a medication, by a cron every minute for today and yesterday, by `medications:upsert`, and by `GET /api/adherence`.

## Crons (`crons.ts`)

| Job | Schedule | Target |
| - | - | - |
| Recompute today's and yesterday's doses | `crons.interval`, 1 minute | `doses:recomputeRecent` |
| Daily summary for the previous local day | `crons.cron("5 * * * *")` (hourly, UTC) | `summaries:buildYesterday` |
| Delete abandoned photos | `crons.interval`, 5 minutes | `labeling:sweepStalePhotos` |

## Photo-assisted labeling

1. The dashboard calls `labeling:generateUploadUrl`, POSTs the photo to it (with its `Content-Type`), and gets `{ storageId }`.
2. It calls `labeling:suggestFromPhoto({ storageId })`.
   The action reads the photo, sends it inline as a base64 `image` block to `${ANTHROPIC_BASE_URL}/messages` with thinking disabled, effort `low`, a `json_schema` output format, `max_tokens: 300`, and an 8 s timeout.
3. The photo is deleted in a `finally` block on success and on every failure.
   It returns `{ name, aliases, description, model, latencyMs, photoDeleted: true }` and saves nothing.
4. The dashboard shows the suggestion, the human confirms or edits, and the dashboard saves with `objects:create` or `objects:update`.

Accepted types are JPEG, PNG, WebP, and GIF up to 4 MB; downscale in the browser first (about 1024 px, JPEG) to keep uploads small.
Errors are readable sentences (timeout, HTTP status and Claude error type, unreadable reply, missing key) and never contain the key.
A cron deletes any stored file older than 10 minutes, so an upload that is never sent for a suggestion does not persist.

## Seed and reset

`npm run seed` passes both config files to `seed:seed` (an internal mutation):
- Upserts the household, replaces spots, areas, and receivers, upserts the seed objects and schedules (the config wins any tag or fob conflict).
- Only if the deployment has no non-trial events yet: writes two days of history relative to now, household-local (the day before yesterday, yesterday, and today so far).
  Salt and sugar are picked up and put back around meals, the sugar spends yesterday evening on the far-left spot, the pills are picked up near 08:00 and 20:00 except yesterday's 20:00 dose (the one missed dose), and the keys' fob chirps once a day.
- Initial states for objects without one: tagged objects on their home spot, the keys roaming near the hub receiver, the pepper (no home spot) not yet seen.
- Materializes doses for the three days and builds the two past daily summaries.
- Safe to run again: it applies config changes (for example a new calibration) without duplicating history or overwriting live state.

`npm run reset` runs `seed:reset` (an internal action): it deletes, in batches, every table except `trials` and `household` (events of kind `trial_start`/`trial_end` are kept too), then seeds.
Real trial data is never deleted or edited by either command.
Tested at many times of day and across both DST transitions: there is always exactly one missed dose.

## Tests

`npm test` runs 108 tests in about a second:
- `lib/time.test.ts`, `lib/adherence.test.ts`: pure logic, including America/Los_Angeles DST.
- `http.test.ts`: every route via `t.fetch`, the auth matrix, 400s, idempotent ingest, label create and rename, registry version changes; every response is validated against the contract schemas with ajv (draft 2020-12, all schema files loaded).
- `functions.test.ts`: every client function called through the contract references.
- `seed.test.ts`: exactly one missed dose, idempotency, reset preserves trials byte for byte.
- `labeling.test.ts`: mocked Claude `fetch`, the request shape, photo deletion on every path, timeout, the sweeper.
- `contract.test.ts`: compile-time and run-time checks against `contracts/ts/convexFunctions.ts`.

## Moving to a cloud deployment later

1. `npx convex login` (interactive); accept linking the local deployment, or later `npx convex login --link-deployments`.
2. `npx convex deployment select dev` (or `npx convex dev --configure existing --team <team> --project <project> --dev-deployment cloud`); `.env.local` switches to `https://<name>.convex.cloud` and `https://<name>.convex.site`.
3. Re-set every environment variable above on the new deployment (they are per deployment).
4. `npm run seed` (data is per deployment), or move data with `npx convex export --path snap.zip` (local `npm run dev` running) and `npx convex import snap.zip`.
5. For production: `npx convex deploy`, set the variables with `--prod`, and seed with `node convex/scripts/seed.node.mjs seed --prod`.

A cloud deployment is what makes remote family labeling, an Azure-hosted dashboard, and an off-Mac memory agent possible; the local one listens only on this Mac.

## Decisions

- Registry `version` is a strictly increasing ms counter on the household row (`max(now, previous + 1)`), also stored as each changed object's `updatedAt`. Plain "max of `objects.updatedAt`" would not change on a removal or a schedule edit.
- Seed is non-destructive and only writes history into a deployment with no non-trial events; reset is the destructive one.
- Reset keeps trial events as well as the `trials` table, so no trial evidence is ever lost.
- Medications have `activeSinceT`: no doses are generated for times before monitoring started (the seed sets it to the start of its history; a new schedule starts now). Otherwise any old date would show fabricated "missed" doses.
- When several pickups qualify for one dose, the earliest is the evidence; an exact tie between two doses goes to the earlier dose.
- `untouched_7d` lists only objects with an NFC tag. Fob-only objects (the keys) never produce pickups or placements, so listing them would state something the data cannot show. "7 days" is the 7 household-local days ending with `date`.
- The daily-summary cron runs hourly and rebuilds the previous local day, because cron strings are UTC, the timezone is data, a day's last dose settles up to 2W after it, and late events from the hub's offline queue still get counted.
- `GET /api/daily-summary` and `GET /api/adherence` default to today.
- Object states: the newest `t` wins, so offline-queue replays never move an object back in time. States for objects not (yet) in the registry are stored but not shown.
- `/ingest` is strict (`additionalProperties: false` is enforced) and atomic; a bad item returns 400 with its path so the hub can drop it rather than retry forever.
- Batch cap of 500 events and 500 states per `/ingest` request keeps each request well inside Convex transaction limits.
- Label renames merge aliases instead of replacing them, so a voice relabel never erases family-entered aliases.
- Pickups per day are a counter row updated in the ingest transaction (the guidelines rule out counting with `.collect().length`).
- `storageId` is validated as a string and normalized with `ctx.db.system.normalizeId`, because the contract types it as `string`.
- Positions use `v.array(v.number())` cast to a 3-tuple type (Convex has no tuple validator); lengths are checked where data enters.
- Tests use `vitest --no-experimental-webstorage` (in `vitest.config.ts`) to silence a Node 25+ warning from the edge-runtime environment.

## What is mocked

- Claude: only in tests (`vi.stubGlobal("fetch", ...)`). No `ANTHROPIC_API_KEY` exists tonight, so the live action has not run against the real model; without a key it fails cleanly and deletes the photo.
- The local deployment uses dummy secrets.
- The seed's two days of history are synthetic demo data (event ids start with `seed-`); trials are never seeded.

## Not done / open

- Client functions have no authentication: anyone with the deployment URL can call them. Caregiver access control needs Convex auth (for example Clerk) before a real household uses it.
- Real Claude latency and suggestion quality are unverified until a key exists.
