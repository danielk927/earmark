# Earmark hub

The hub turns raw detections (NFC spot readers, BLE fobs, the simulator) into debounced object state.
It runs the local WebSocket bus at `ws://127.0.0.1:8765` and syncs to Convex.
Spec: `BUILD_BRIEF.md` sections 5.A, 5.B and 5.I; the contracts in `contracts/` are authoritative.

## Run

All commands run from the repo root.
`services/hub` is its own uv project (Python 3.11 or newer; the checked-in venv is 3.14), so prefix commands with `uv run --project services/hub`.

```sh
# Replay a scenario (hardware-free), no Convex
uv run --project services/hub earmark-hub --scenario scenarios/full_demo.jsonl --no-convex

# Faster, looping, or one step at a time (Enter advances)
uv run --project services/hub earmark-hub --scenario scenarios/wrong_jar.jsonl --speed 4 --loop
uv run --project services/hub earmark-hub --scenario scenarios/normal_pickup.jsonl --step

# Wizard-of-Oz keyboard demo without hardware
uv run --project services/hub earmark-hub --interactive

# Real hardware
uv run --project services/hub earmark-hub --adapters nfc_serial,ble_fobs

# Bus tools (the hub must be running)
uv run --project services/hub earmark-tail                      # everything except audio
uv run --project services/hub earmark-tail --types pickup,state_update
uv run --project services/hub earmark-send reset
uv run --project services/hub earmark-send transcript --text "where's the sugar"
uv run --project services/hub earmark-send chirp --fob_id fob_keys --action start
uv run --project services/hub earmark-sim scenarios/normal_pickup.jsonl --speed 2   # against a live hub
uv run --project services/hub earmark-sim --interactive

# Trials (brief 5.I)
uv run --project services/hub python scripts/trial.py
```

`earmark-send <type> --field value ...` parses each value as JSON when it can (`--spot 3` is a number) and as a string otherwise.
`--json '{...}'` sets several fields at once.
`transcript` defaults to `is_final: true, source: typed`, `label` to `aliases: []`, and `chirp` to `action: start`.
Every message is validated against the contract before it is sent.

### Interactive keys

| Key | Action |
|---|---|
| `1`-`9` | Lift the object on that spot, or put a held object back on it |
| `m` then a digit | Move the held object to that spot |
| `k` / `K` | Key fob one step nearer / farther (lost, far, mid, near) |
| `t` | Type a transcript (published as `transcript`, source `typed`) |
| `r` | Reset (physical layout back to home spots, and a bus `reset`) |
| `?` | Help |
| `q` | Quit the simulator (the hub keeps running) |

The simulator keeps polling every spot every 0.5 s (and the fob every 1 s), so the hub sees exactly what real readers would send.
On a terminal, keys act immediately; with piped stdin, each line is one command (`3`, `m1`, `t where is the sugar`).

## Test

```sh
cd services/hub && uv run pytest -q
```

140 tests, about 17 s.
They include an end-to-end smoke test that starts the real `earmark-hub --adapters simulator --scenario scenarios/full_demo.jsonl --speed 10 --no-convex` process and asserts the pickup sequence salt(2), sugar(3), sugar(1) over the WebSocket.
A second one runs `earmark-sim`, `earmark-send` and `earmark-tail` against a running hub.
No test touches real Bluetooth, serial ports, Convex, `config/`, or `var/`.

## Configure

`config/hub.json` holds the hub's own settings; every key is optional and defaults to the values shown there.

| Section | Keys |
|---|---|
| `adapters` | Enabled adapters: `simulator`, `nfc_serial`, `ble_fobs`, `camera_stub`. Several can run at once. |
| `bus` | `host`, `port`, `client_queue_max` (per-client send queue bound). |
| `debounce` | `placement_reads` (2), `removal_s` (1.5), `tick_s` (0.25, how often removals are checked without reads). |
| `simulator` | `poll_s`, `fob_poll_s`, `start_delay_s` (1.0 wall seconds, so bus clients can connect before a scenario starts), `fob_rssi` per class. |
| `nfc_serial` | `port_globs`, `baud`, `reconnect_s`. |
| `ble_fobs` | `receiver`, `fobs` (`fob_id` -> `{address, name}`), `ema_tau_s`, `stale_s`, `near_dbm`, `mid_dbm`, `emit_interval_s`, `chirp_timeout_s`, `connect_timeout_s`, `alert_service_uuid`, `alert_char_uuid`, `alert_level`, `link_loss_service_uuid`, `link_loss_value`. |
| `convex` | `registry_poll_s` (2), `timeout_s` (8 in `config/hub.json`; the code default is 3), `flush_interval_s`, `batch_max`, `backoff_initial_s`, `backoff_max_s`. |
| `health` | `interval_s` (5). |
| `paths` | `space`, `seed`, `cache`, `queue`, `trials`, `logs`, relative to the repo root unless absolute. |

### Environment variables

The hub and every CLI load the repo-root `.env` if present, without overriding the real environment.
Precedence: CLI flags, then the environment, then `config/hub.json`.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `EARMARK_BUS_HOST` | `127.0.0.1` | hub | Bus bind address. |
| `EARMARK_BUS_PORT` | `8765` | hub | Bus port. |
| `EARMARK_BUS_URL` | `ws://127.0.0.1:8765` (built from host and port when unset) | CLIs, `scripts/trial.py` | Where clients connect. |
| `EARMARK_ADAPTERS` | from `config/hub.json` (`simulator`) | hub | Comma list; `--adapters` overrides it. |
| `NFC_SERIAL_PORT` | `auto` | `nfc_serial` | A device path, or `auto` to scan `port_globs`. |
| `NFC_BAUD` | `115200` | `nfc_serial` | Serial baud rate. |
| `CONVEX_SITE_URL` | unset (offline) | hub | Convex HTTP actions base URL (`https://<deployment>.convex.site`). |
| `EARMARK_HUB_SECRET` | unset (offline) | hub | Sent as `X-Earmark-Secret`; never logged. |
| `HUB_CONFIG` | `config/hub.json` | hub, CLIs | Alternate hub config file. |
| `HUB_LOG_DIR` | `logs` | hub | Where `hub.jsonl` and `serial.log` go. |

Without both Convex variables (or with `--no-convex`) the hub runs fully offline and logs that once.

## How it works

### State engine (`earmark_hub/state.py`)

Pure and deterministic: time comes only from event timestamps and `tick(now)`, and the engine's clock never moves backwards.

- Placement: 2 consecutive reads of the same tag on a spot (`kind: placed` from a self-debouncing adapter confirms at once).
- Removal: the confirmed tag is continuously absent for `removal_s`, counted from the first read that did not show it.
  It is checked on every event and on every tick, so one `EMPTY` followed by silence still removes.
- A tag confirmed on a new spot while still recorded on an old one is removed from the old spot first; a different tag confirmed on an occupied spot removes the old tag first.
- Every registered object leaving a spot emits `pickup`, and every change emits `state_update`.
- Statuses: on a spot `on_spot` (precision `exact`, position from `space.json`); lifted `held` (location null, precision `none`, `last_seen_t` = lift time); BLE seen `roaming` (precision `proximity`, `near` + `distance_class` + the receiver's position); BLE lost or never seen `missing` (precision `none`, last location kept).
- An unregistered tag placed on a spot emits one `unknown_tag` per placement; `EMPTY` is never a tag.
- Registry changes re-resolve tags already on spots, so labeling the unknown tag on spot 1 makes the new object `on_spot` immediately.

### Bus (`earmark_hub/bus.py`)

- `hello` gets a `snapshot` (space, registry objects, every object state, `registry_version`).
- Every other message is validated with `parse_bus` and routed to every other client whose `subscribe` includes its type.
  Default: everything except `mic_audio` and `speak`; `["*"]` is everything; `[]` is nothing (the snapshot still arrives).
- Invalid frames are dropped, logged, and reported with a hub `status` (at most one per client per second).
- Detections from clients (e.g. `earmark-sim`) enter the state engine exactly like in-process adapter events, and in-process adapter detections are broadcast like client ones.
- `chirp` is executed by `ble_fobs` when enabled.
  `label` updates the registry.
  `place_item` (an item and an `area` or `position`) makes the item `roaming` there and logs a `stored` event; it stands until a spot reader reads the tag again, or a fob is heard again, after it.
  `reset` stops chirps, resets the simulator's physical state, re-reads `config/space.json` (keeping the old layout if it fails to load) and the registry cache or seed, resets the engine, is re-broadcast, and every client gets a fresh `snapshot`.
- Each client has a bounded send queue with its own writer task; when full, the oldest audio frame is dropped first, then the oldest message.
- `status` from the hub every 5 s and on every change: `info.adapters`, `info.convex` (`disabled`, `connecting`, `online`, `offline`), `info.queue_depth`, `info.clients`, `info.registry_version`.

### Adapters (`earmark_hub/adapters/`)

- `simulator`: replays `scenarios/*.jsonl` or runs the keyboard mode (above).
  Non-detection lines (e.g. `transcript`) are published as if sent by component `simulator`.
  `earmark-sim` runs the same simulator as a bus client.
- `nfc_serial`: parses `SPOT <n> TAG <uid>`, `SPOT <n> EMPTY`, `SPOT <n> ERROR <reason>` (errors become a hub `status`); raw lines go to `logs/serial.log`; it re-detects and reopens the port when the board is unplugged.
- `ble_fobs`: follows `docs/sponsors/vendor-notes/bleak.md`.
  One continuous scan; fobs matched by CoreBluetooth address (or advertised name, cached per address); time-weighted RSSI EMA; thresholds -> `distance_class`; `lost` after `stale_s` without advertisements.
  Chirp: connect with the scanner's `BLEDevice`, log every service and characteristic, resolve Alert Level `2a06` through service `1802`, choose the write type from the characteristic's properties, write `alert_level`, hold the connection until `stop` or `chirp_timeout_s`, write `0x00`, optionally write `link_loss_value` to `1803/2a06`, and disconnect.
  If the connect times out while scanning, it retries once with the scanner paused.
- `camera_stub`: interface only; its docstring describes how a vision adapter would emit `position` events.

### Registry and Convex (`earmark_hub/registry.py`, `earmark_hub/convex.py`)

- The registry loads `config/objects.cache.json` if present, else `config/objects.seed.json`.
- With Convex configured, `GET /api/registry` is polled every 2 s; a new `version` rewrites the cache and broadcasts `registry_update`.
- A `label` updates the registry at once (new `object_id` from the name: lowercase, `[a-z0-9_]`, deduplicated with `_2`; or rename the object that has the tag), writes the cache, broadcasts `registry_update`, and queues `POST /api/label` plus a `label` hub_event.
- `POST /ingest` batches hub_events (`placed`, `removed`, `pickup`, `unknown_tag` (both only from the hub's own state engine; a `pickup` sent by a bus client is broadcast but never sent to Convex), plus forwarded `pickup_result`, `chirp`, `label`, `trial_start`, `trial_end`, and `stored` when a `place_item` says where an item was left) with the latest `state_update` per object.
  `placed`/`removed` data is `{spot, tag, source}`; other kinds carry the originating bus message.
- Events and labels go through a durable queue (`var/hub/queue.jsonl`), are sent strictly in order with the `convex.timeout_s` timeout (8 s) and exponential backoff, and survive restarts.
  Each event has a UUID `event_id`, so retries after a lost response are harmless.
  401/403/404/408/409/425/429 and 5xx are retried; other 4xx answers drop that item with an error log that contains the dropped data.

### Trials (`scripts/trial.py`, `earmark_hub/trial.py`)

The CLI suggests the next mode (alternating) and a random target, rejects anything that looks like a real full name, and sends `trial_start` when the operator presses Enter.
The trial ends on the target's `pickup`; in earmark mode it waits up to 1 s for the concierge's `pickup_result` with `correct: true`, then falls back to the pickup itself.
Every other pickup is a wrong pick; Enter ends it as `gave_up`, `a` + Enter as `aborted`.
`trial_end` is computed only from bus events; each one is also appended to `var/trials/trials.jsonl` for the next suggestion.
`seconds_to_find` runs from `trial_start` to the hub's `pickup`, so it includes the removal debounce (about 1.5 s) equally in both modes.

## Logs

JSON lines in `logs/hub.jsonl` (one object per line: `t`, `level`, `logger`, `msg`, plus fields) and raw serial lines in `logs/serial.log`.
The console shows a short human line per event (warnings only in `--interactive` and `--step`, so the keyboard display stays readable; `-v` for debug).

## What is mocked tonight

- No Convex deployment exists: the client is built against `contracts/schemas/convex_http.schema.json` and tested against a local fake HTTP server.
  `GET /api/registry` has no schema entry beyond `registry.schema.json`; the hub validates the response as a `Registry`.
- BLE is tested with fake `BleakScanner`/`BleakClient` objects; no real scan was started (it would trigger a macOS permission prompt).
- Serial is tested with a fake port; no real port was opened.
- Camera is a stub.

## Decisions

- The package is `earmark_hub/` with adapters in `earmark_hub/adapters/`, not a bare `services/hub/adapters/`, so it has a unique import name.
- Removal timing starts at the first read that did not show the tag.
  Pure silence (no reads at all, e.g. an unplugged reader) never removes anything, so a cable glitch cannot produce false pickups.
- `--speed` makes the whole hub run on a scaled clock (`ScaledClock`): debounce windows, ticks, and adapter timestamps all run faster, so a sped-up scenario behaves exactly like the real-time one.
  Timestamps then run ahead of the wall clock, so use `--speed` only for playback.
  `earmark-sim --speed` stamps events the same way; the engine's clock never moves backwards, so a live hub accepts them.
- "Change" for `state_update` means any field except `t` and `last_seen_t`, so redundant polls (2 Hz per spot) and steady BLE advertisements do not flood the bus or Convex.
  `last_seen_t` is still kept current and appears in snapshots and in the next update.
- A spot reading beats proximity: BLE or camera observations of an object that is `on_spot` are ignored until it leaves the spot.
- Position and area events (future camera) become `roaming` with the resolved position (see the contract proposals in the hand-off report).
- On rename, a label replaces the object's aliases with the label's aliases and keeps `object_id`, notes, description and home spot.
- Labels that Convex has not acknowledged yet are re-applied on top of every newer registry from Convex, so a voice label never flickers away.
- The registry cache is written on every registry change (Convex poll and local labels), so labels survive restarts even offline; `reset` re-reads it.
- In-process adapter detections are broadcast on the bus like client detections, so in-hub and `earmark-sim` playback look identical to clients.
- BLE chirp: hold the connection for the chirp (vendor notes: a disconnect ends an IAS alert), then `0x00` and disconnect; repeated `start` extends the timeout; `reset` stops all chirps without blocking.
- `--scenario` and `--interactive` are mutually exclusive; `--scenario`/`--interactive` enable the simulator automatically.
- The simulator waits `start_delay_s` (1 s) before playing so clients started alongside the hub do not miss the first lines.
- Without a scenario or `--interactive`, the `simulator` adapter idles, so the default config is a bus-only hub that `earmark-sim` can drive.
