# Earmark hub

The hub turns raw detections (NFC spot readers, BLE fobs, the simulator) into debounced object state.
For walking guidance it also turns UWB distances from the wearer iPhone into the listener's position (`listener_pose`, see "UWB walking guidance" below).
It runs the local WebSocket bus at `ws://127.0.0.1:8765` (or on the private network for the iPhones) and syncs to Convex.
Spec: `BUILD_BRIEF.md` sections 5.A, 5.B and 5.I, and `docs/UWB-PRD.md` section 8; the contracts in `contracts/` are authoritative.

## Run

All commands run from the repo root.
`services/hub` is its own uv project (Python 3.12), so prefix commands with `uv run --project services/hub`.

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

# UWB walking guidance without phones (simulated wearer; see "UWB walking guidance")
EARMARK_ADAPTERS=simulator,uwb_sim uv run --project services/hub earmark-hub --no-convex                # scripted walk
EARMARK_ADAPTERS=simulator,uwb_sim uv run --project services/hub earmark-hub --interactive --no-convex  # keyboard wearer
uv run --project services/hub earmark-tail --types listener_pose

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

With `uwb_sim` also enabled, the same keyboard drives the simulated wearer:

| Key | Action |
|---|---|
| `w` `a` `s` `d` or the arrow keys | Move the wearer `step_m` (0.25 m); `w` / up is toward the counter. The wearer counts as moving for 0.6 s after each key |
| `x` | Stand still now |
| `f` | Say "I'm here" (`listener_command freeze`) |

The simulator keeps polling every spot every 0.5 s (and the fob every 1 s), so the hub sees exactly what real readers would send.
On a terminal, keys act immediately; with piped stdin, each line is one command (`3`, `m1`, `t where is the sugar`).

## Test

```sh
cd services/hub && uv run pytest -q
```

219 tests, about 23 s.
The `test_uwb_*.py` files cover the UWB module (`docs/UWB-PRD.md` 12.1): solver accuracy and outlier rejection, the freeze state machine, NFC re-anchor, lost to fixed, the token relay and bus secret, and `uwb_sim` pose rate.
They include an end-to-end smoke test that starts the real `earmark-hub --adapters simulator --scenario scenarios/full_demo.jsonl --speed 10 --no-convex` process and asserts the pickup sequence salt(2), sugar(3), sugar(1) over the WebSocket.
A second one runs `earmark-sim`, `earmark-send` and `earmark-tail` against a running hub.
No test touches real Bluetooth, serial ports, Convex, `config/`, or `var/`.

## Configure

`config/hub.json` holds the hub's own settings; every key is optional and defaults to the values shown there.

| Section | Keys |
|---|---|
| `adapters` | Enabled adapters: `simulator`, `nfc_serial`, `ble_fobs`, `camera_stub`, `uwb_sim`. Several can run at once. |
| `bus` | `host`, `port`, `client_queue_max` (per-client send queue bound). The secret is never in this file: set `EARMARK_BUS_SECRET`. |
| `debounce` | `placement_reads` (2), `removal_s` (1.5), `tick_s` (0.25, how often removals are checked without reads). |
| `simulator` | `poll_s`, `fob_poll_s`, `start_delay_s` (1.0 wall seconds, so bus clients can connect before a scenario starts), `fob_rssi` per class. |
| `nfc_serial` | `port_globs`, `baud`, `reconnect_s`. |
| `ble_fobs` | `receiver`, `fobs` (`fob_id` -> `{address, name}`), `ema_tau_s`, `stale_s`, `near_dbm`, `mid_dbm`, `emit_interval_s`, `chirp_timeout_s`, `connect_timeout_s`, `alert_service_uuid`, `alert_char_uuid`, `alert_level`, `link_loss_service_uuid`, `link_loss_value`. |
| `convex` | `registry_poll_s` (2), `timeout_s` (3), `flush_interval_s`, `batch_max`, `backoff_initial_s`, `backoff_max_s`. |
| `uwb` | Walking guidance (below). `enabled`, `solve_hz` (10), `freshness_s` (0.5), `lost_after_s` (2), `lost_hold_s` (3), `max_speed_mps` (2.5), `outlier_rms_m` (0.25), `alpha` / `beta` (0.5 / 0.1), `alpha_still` (0.2), `phone_z` (-0.35), `head_offset_m` (0.2), `head_pose_max_age_s` (0.5), `counter_ref` ([0, 0]), `freeze_enter_m` (1.0), `freeze_exit_m` (1.3, must be at least `freeze_enter_m`), `still_for_s` (0.6), `average_window_s` (1.0), `unfreeze_move_m` (0.35), `blend_s` (0.4, used by the Mac app only), `freeze_mode` (`average` or `snap`), `reach_max_m` (0.75), `convex_pose_hz` (2). |
| `uwb_sim` | Simulated wearer. `rate_hz` (15 ranges per anchor per second), `noise_sigma_m` (0.07), `dropout_prob` (0.03), `jump_m` (0.4), `block_every_s` (8), `block_s` (1), `path` (start mark to counter, `[[0.4, -3.0], [0.1, -1.5], [0.0, 0.0]]`), `speed_mps` (0.6), `dwell_s` (4), `loop` (true), `step_m` (0.25), `seed` (null = random). |
| `health` | `interval_s` (5). |
| `paths` | `space`, `seed`, `cache`, `queue`, `trials`, `logs`, relative to the repo root unless absolute. |

### Environment variables

The hub and every CLI load the repo-root `.env` if present, without overriding the real environment.
Precedence: CLI flags, then the environment, then `config/hub.json`.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `EARMARK_BUS_HOST` | `127.0.0.1` | hub | Bus bind address. `0.0.0.0` for the UWB iPhones, on a private network only. |
| `EARMARK_BUS_PORT` | `8765` | hub | Bus port. |
| `EARMARK_BUS_SECRET` | unset | hub | Required in `hello` from every non-loopback client (the iPhones); never logged. |
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
  `reset` stops chirps, resets the simulator's physical state, re-reads the registry cache or seed, resets the engine, is re-broadcast, and every client gets a fresh `snapshot`.
- Each client has a bounded send queue with its own writer task; when full, the oldest audio frame is dropped first, then the oldest message.
- `status` from the hub every 5 s and on every change: `info.adapters`, `info.convex` (`disabled`, `connecting`, `online`, `offline`), `info.queue_depth`, `info.clients`, `info.registry_version`.

### UWB walking guidance (`earmark_hub/uwb/`)

Spec: `docs/UWB-PRD.md` section 8.
The phones send distances; the hub does all the math and publishes one `listener_pose` that the Mac app, concierge, and dashboard follow.

- **Token relay** (`relay.py`): each `uwb_token` goes only to the client whose `hello.device_id` equals `to` (`uwb_1`, `uwb_2`, `uwb_3`, `wearer`), never to the whole bus.
  The latest token per `(from, to)` is kept in memory and replayed when that phone says `hello`; `reset` keeps them.
- **Solver** (`solver.py`, `tracker.py`), at `solve_hz`: ranges older than `freshness_s` (hub receive time) are ignored; slant correction with `phone_z` and each anchor's height; least-squares position from 3 anchors with leave-one-out rejection above `outlier_rms_m` (the dropped anchor is listed in `blocked`), or the in-room circle intersection from 2; a speed gate (`max_speed_mps`); an alpha-beta filter, heavier while `motion_state` is `still`; then the head is placed `head_offset_m` behind the phone, facing from the AirPods `head_pose` when recent, else the direction of travel, else toward the counter inside the freeze radius.
- **Modes:**
  - `fixed`: listener at the origin. This is today's seated behavior: UWB disabled, no ranges yet, or lost for too long.
  - `tracked`: the live estimate while walking.
  - `frozen`: the landing spot at the counter (below).
  - `lost`: fewer than 2 fresh anchors for `lost_after_s` while tracked; it holds the last position for `lost_hold_s`, then goes to `fixed`. The concierge says the lost message once.
- **Freeze:** inside `freeze_enter_m` of `counter_ref`, still for `still_for_s`, with at least 2 fresh anchors, the listener freezes at the average over `average_window_s` (or at `counter_ref` with `freeze_mode: snap`).
  "I'm here" (`listener_command freeze`, from the concierge or the `f` key) freezes at once, even outside the radius.
  It unfreezes when moving and more than `unfreeze_move_m` from the frozen point, or outside `freeze_exit_m` (not after a voice freeze).
- **NFC re-anchor:** while frozen, a `pickup` or `placed` on spot N farther than `reach_max_m` from the listener pulls the frozen point toward spot N until it is exactly `reach_max_m` away, and logs the correction. Never while tracked.
- **Output:** `listener_pose` on every tick while tracked, frozen, or lost, and at once on every mode change (nothing while fixed); it carries `residual_m`, `anchors_used`, `blocked`, and per-anchor health (`online`, latest distance).
  New clients get the latest pose right after their snapshot.
  Convex gets anchor health when it differs from what Convex last acknowledged, and the latest pose (one overwritten row, at most `convex_pose_hz`); no pose history is kept there.
- **Config:** anchors come from `config/space.json` `anchors`, and `tracking.phone_z` / `tracking.head_offset_m` there override the `uwb` defaults in `hub.json`.
  The Mac app's Calibrate screen or `scripts/calibrate.py` write them; `reset` reloads `space.json` and pushes the anchors to Convex.
  `uwb.enabled: false` turns the tracker off (always `fixed`).
- **Simulator** (`sim.py`, adapter `uwb_sim`): a fake wearer that sends `uwb_range` to every anchor in `space.json` at `rate_hz` plus `motion_state`, with Gaussian noise, dropouts, and a body-block burst (+`jump_m` on one anchor for `block_s`) every `block_every_s`.
  Scripted (default): stand at the start of `path` for `dwell_s`, walk to the counter at `speed_mps`, stand, and with `loop` walk back and forth.
  Interactive (`--interactive`): keys above.
  Enable it with `EARMARK_ADAPTERS=simulator,uwb_sim` or `--adapters simulator,uwb_sim`.
  `scripts/run_stack.sh sim` passes `--adapters simulator` itself, so add it there as `scripts/run_stack.sh sim --interactive --adapters simulator,uwb_sim` (the last `--adapters` wins).
  Simulated poses have `source: sim`; ranges from an `ios_wearer` client are `source: uwb`.

**Network and the bus secret.** The phones reach the hub over Wi-Fi, so the bus must listen on the network: `EARMARK_BUS_HOST=0.0.0.0` (or `bus.host` in `hub.json`) and set `EARMARK_BUS_SECRET`.
Loopback clients are trusted.
Any other client receives nothing and may send nothing until its `hello` carries the secret; otherwise it gets `status ok:false` and is closed (code 1008).
With no secret set, every non-loopback client is refused, and the hub warns at startup.
**Only do this on the team's private router or hotspot, never on venue Wi-Fi**: the bus has no TLS, and anyone on the network who learns the secret can read and send every message.

### Adapters (`earmark_hub/adapters/`)

- `simulator`: replays `scenarios/*.jsonl` or runs the keyboard mode (above).
  Non-detection lines (e.g. `transcript`) are published as if sent by component `simulator`.
  `earmark-sim` runs the same simulator as a bus client.
- `nfc_serial`: parses `SPOT <n> TAG <uid>`, `SPOT <n> EMPTY`, `SPOT <n> ERROR <reason>` (errors become a hub `status`); raw lines go to `logs/serial.log`; it re-detects and reopens the port when the board is unplugged.
- `ble_fobs`: follows `docs/vendor-notes/bleak.md`.
  One continuous scan; fobs matched by CoreBluetooth address (or advertised name, cached per address); time-weighted RSSI EMA; thresholds -> `distance_class`; `lost` after `stale_s` without advertisements.
  Chirp: connect with the scanner's `BLEDevice`, log every service and characteristic, resolve Alert Level `2a06` through service `1802`, choose the write type from the characteristic's properties, write `alert_level`, hold the connection until `stop` or `chirp_timeout_s`, write `0x00`, optionally write `link_loss_value` to `1803/2a06`, and disconnect.
  If the connect times out while scanning, it retries once with the scanner paused.
- `camera_stub`: interface only; its docstring describes how a vision adapter would emit `position` events.
- `uwb_sim`: the simulated wearer iPhone (above).

### Registry and Convex (`earmark_hub/registry.py`, `earmark_hub/convex.py`)

- The registry loads `config/objects.cache.json` if present, else `config/objects.seed.json`.
- With Convex configured, `GET /api/registry` is polled every 2 s; a new `version` rewrites the cache and broadcasts `registry_update`.
- A `label` updates the registry at once (new `object_id` from the name: lowercase, `[a-z0-9_]`, deduplicated with `_2`; or rename the object that has the tag), writes the cache, broadcasts `registry_update`, and queues `POST /api/label` plus a `label` hub_event.
- `POST /ingest` batches hub_events (`placed`, `removed`, `pickup`, `unknown_tag`, plus forwarded `pickup_result`, `chirp`, `label`, `trial_start`, `trial_end`) with the latest `state_update` per object.
  `placed`/`removed` data is `{spot, tag, source}`; other kinds carry the originating bus message.
- Events and labels go through a durable queue (`var/hub/queue.jsonl`), are sent strictly in order with a 3 s timeout and exponential backoff, and survive restarts.
  Each event has a UUID `event_id`, so retries after a lost response are harmless.
  401/403/404/408/429 and 5xx are retried; other 4xx answers drop that item with an error log that contains the dropped data.

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
- UWB: no iPhone has connected to this hub yet. The tracker has only run against `uwb_sim`, which models noise, dropouts, and body blocks but not real Nearby Interaction behavior.

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
