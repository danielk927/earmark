# UWB walking guidance: product requirements (UWB-PRD)

Status: draft, 2026-10-24 17:10 PDT. Owner: UWB track (Leo). Parallel track: sound-based ranging (teammate), see section 14.
Scope: let a user **walk** to an object guided by spatial audio, using iPhone ultra-wideband (UWB) ranging to fixed anchor iPhones, a **freeze** at the counter, and the existing **NFC** spots for object identity, position, and pickup confirmation.

---

## 1. Summary

Today Earmark guides a user who is already at the counter. The listener position is fixed (`config/space.json` origin), AirPods head tracking keeps the ping fixed in the room, and NFC readers say which jar is on which spot and which one was lifted. Spatial audio from a fixed position is verified working.

This PRD adds the missing piece: **where the user is while they walk.**

- Three iPhones sit at fixed, measured spots in the booth as **UWB anchors**, labeled **"UWB Reader/Emitter 1/2/3"** in every UI.
- A fourth iPhone, held by the user, measures its distance to each anchor with Apple's Nearby Interaction framework and streams those distances to the hub.
- The hub turns three distances into a live 2D position (trilateration), smooths it, and publishes it as `listener_pose`.
- The Mac app moves the audio listener to that position, so the ping from the sugar jar gets closer and louder as the user walks toward it, with no sweeps and no warmer/colder guessing.
- Near the counter, the system **freezes** the listener position (averaged while the user stands still) so the last-meter guidance doesn't wobble between jars that are about 26 cm apart.
- **NFC** keeps doing what it does: exact object positions, pickup confirmation, wrong-jar correction. It also re-anchors the frozen position when a jar is lifted (section 8.4).

Nothing about this uses a camera.

---

## 2. Why UWB (decisions from the brainstorm)

| Idea | Verdict | Why |
|---|---|---|
| Bluetooth signal strength (RSSI) | Rejected for position | Only near/far; noisy; no direction. Kept for keys (roaming fob proximity + chirp). |
| High-frequency tone, loudness only | Rejected for position | Gives rough distance (±30-50%) and no direction; echoes, crowds, phone orientation. Being explored by the sound track as a cheaper alternative (section 14). |
| Phone GPS | Rejected | 3-5 m outdoors, worse or none indoors; the booth is ~3 m across. |
| Compass + sound sweep | Rejected as primary | Heading is orientation, not position: sidesteps are invisible. Magnetic compass is unreliable indoors. |
| Phone step counter | Rejected | Misses slow, cautious steps; 3-5 step walks make one missed step a 20-30% error; batched, late updates; no step direction. |
| Foot-mounted IMU with zero-velocity updates | Rejected for demo | Accurate (~1% of distance) but needs a shoe strap. |
| ARKit / LiDAR on the person | Rejected | ARKit tracking always uses the camera; LiDAR alone gives depth, not position. Conflicts with the "no cameras" pillar. |
| Pocket phone | Rejected | Muffles sound, swinging heading, pocket offset. Demo holds the phone in hand, close to the chest. |
| Room radar / 2D LiDAR | Not chosen | Good, but hardware we don't have (LiDAR too expensive). |
| **Fixed UWB anchors + handheld iPhone** | **Chosen** | ~10 cm ranging, unaffected by crowd noise, inaudible, camera-free, hardware in hand (4 UWB iPhones). Apple's chip does the timing. |

Key insight: **don't track the person from their body; measure them from fixed points in the room.** Fixed anchors know exactly where they are, and each position is measured fresh, so error does not accumulate with distance walked (unlike step counting or inertial dead reckoning). Error depends on where the user is relative to the anchors, not how far they have walked.

---

## 3. Goals, non-goals, success metrics

### Goals
1. A user standing 2-4 m from the counter asks "Where's the sugar?" and is guided by spatial audio from the jar's real position while walking.
2. At the counter, guidance is as stable as today's seated setup (the freeze).
3. Wrong-jar correction and pickup confirmation work exactly as today (NFC).
4. Anchors, the wearer, and the tracking mode are visible on the Mac app and the dashboard as "UWB Reader/Emitter 1/2/3" plus the wearer dot.
5. If UWB fails, Earmark degrades to today's fixed-position behavior without code changes.

### Non-goals (tonight)
- Spatial audio rendered on the iPhone (stays on the Mac; it's the production story).
- UWB direction (angle) measurement. On iPhone 14 and later it typically needs camera assistance, which we will not enable.
- Dedicated UWB accessory modules (production path only).
- Multi-room or multi-user tracking.
- Storing a location history of the user.

### Success metrics (measured, never estimated; see section 12)
| Metric | Target |
|---|---|
| Static position error at 5 floor marks | median ≤ 0.20 m, max ≤ 0.35 m |
| Frozen position error at the counter mark | ≤ 0.15 m in 8 of 10 arrivals |
| Pose update rate at the hub | ≥ 5 Hz sustained |
| Range-to-audio latency (phone measurement to listener update on the Mac) | ≤ 150 ms median |
| Eyes-closed walk from 3 m to the correct jar | ≥ 4 of 5 attempts, with NFC confirming the pick |

---

## 4. Hardware, roles, and booth layout

### 4.1 Devices
| Device | Role | Notes |
|---|---|---|
| iPhone A | **UWB Reader/Emitter 1** | Fixed, counter left end. Plugged in, auto-lock off, app foregrounded. |
| iPhone B | **UWB Reader/Emitter 2** | Fixed, counter right end. Same. |
| iPhone C | **UWB Reader/Emitter 3** | Fixed, side or back of the booth, forming a triangle (not in line with 1 and 2). Same. |
| iPhone D | **Wearer** | Held in hand close to the chest. Runs ranging to all three anchors. Optional push-to-talk mic (section 13.2). |
| Mac | Hub, concierge, Mac app, AirPods audio | AirPods connected to the **Mac**, not the iPhone. |
| AirPods | Head tracking + audio output | Output only; never use the AirPods mic. |
| NFC readers | Spots 1-4 on the counter | Unchanged. |
| Travel router or phone hotspot | Private network for all devices | Venue Wi-Fi usually blocks device-to-device traffic. |

All four iPhones must have UWB (iPhone 11 or later, not SE). Confirm each with `NISession.deviceCapabilities.supportsPreciseDistanceMeasurement` on first launch.

### 4.2 Booth layout (top view, Earmark coordinates)

```
                 +y (forward, toward the counter)
                        ^
   [UWB 1]  ==== counter: spot1 spot2 spot3 spot4 ====  [UWB 2]
                        |
                        o  <- origin: listening position (floor mark, tactile strip)
                        |      user stands here facing the counter
                        |
   [UWB 3]              |        walking area (2-4 m)
   (side/back)          |
                        S  <- start mark
```

- Anchors 1 and 2 at least 1.2 m apart; anchor 3 at least 1.5 m from the line between them.
- All anchors at roughly the same height (counter or chest height) and measured.
- No metal shelving or big screens directly between the walking area and an anchor if avoidable.

---

## 5. Coordinate frame

Unchanged from `contracts/README.md`:
- Meters; +x right, +y forward, +z up; origin = center of the head at the calibrated listening position (standing at the counter, facing it).
- Head yaw: degrees from calibrated forward, positive turning right.

New for UWB:
- **Anchor positions** are measured in this same frame (tape measure from the origin mark; section 10).
- **Tracking is 2D.** The solver estimates x, y. The listener's z is fixed at 0 (standing head height, same as calibration).
- **Slant-range correction:** the phone is below the head and anchors may be at other heights. Each raw distance d is converted to a horizontal distance with `h = sqrt(max(d² - Δz², 0))`, where `Δz = anchor_z - phone_z`, and `phone_z` is configurable (default -0.35 m: chest height relative to the ears).
- **Phone-to-head offset:** the phone is in front of the body. The listener (head) is estimated as the phone position shifted back by `head_offset_m` (default 0.20 m) along the user's facing direction (section 8.3).

---

## 6. System architecture

```
 iPhone D (Wearer)                          iPhones A/B/C (UWB Reader/Emitter 1/2/3)
  NISession x3  <==== UWB two-way ranging ====>  NISession x1 each
  CoreMotion (moving/still)
        |  uwb_token, uwb_range, motion_state          |  uwb_token, status
        +---------------- Wi-Fi (private) -------------+
                              |
                              v
                 hub (Python) ws://<mac>:8765
                  - token relay
                  - uwb solver: slant correction -> trilateration
                    -> outlier rejection -> smoothing
                  - freeze state machine (+ NFC re-anchor)
                  - publishes listener_pose
                  - syncs anchors + latest pose to Convex (2 Hz)
                     |                    |                     |
                     v                    v                     v
             Mac app (Swift)        concierge (Python)      Convex -> dashboard
             listener position      phrasing relative       Live map: anchors,
             + AirPods yaw          to the listener         wearer dot, mode
             -> spatial ping        (meters / clock face)
```

Design rules (from `BUILD_BRIEF.md`, unchanged):
- Contracts are law: every new message is added to `contracts/` with examples and tests before use.
- Math lives in code: trilateration, smoothing, freeze, and phrasing are deterministic and unit-tested.
- Detection-agnostic: downstream components consume `listener_pose` and never know whether it came from UWB, sound, or a simulator. **This is what lets the sound track plug in with zero Mac/dashboard changes.**

---

## 7. iPhone app: `ios/EarmarkUWB`

### 7.1 Build setup
- New Xcode project at `ios/EarmarkUWB/` (SwiftUI, iOS 17+). Requires full Xcode on the Mac (not installed yet; install first).
- Reuse `contracts/swift` (`EarmarkContracts` Swift package) for bus message types.
- Signing: free Apple ID personal team is enough (7-day profiles). Install on all four phones.
- Info.plist keys:
  - `NSNearbyInteractionUsageDescription`: "Earmark measures distance to the Earmark anchors in this room to guide you by sound."
  - `NSLocalNetworkUsageDescription`: "Earmark connects to the Earmark hub on this network."
  - `NSMotionUsageDescription`: "Earmark checks whether you are walking or standing still to steady its guidance."
  - `NSMicrophoneUsageDescription` (only if push-to-talk from the phone is built, section 13.2).
- `UIApplication.shared.isIdleTimerDisabled = true` while a role is active (Nearby Interaction suspends in the background).

### 7.2 Launch flow
1. Role picker, large buttons, VoiceOver-labeled: **UWB Reader/Emitter 1**, **2**, **3**, **Wearer**. Remember the last choice.
2. Hub address field (default from a QR code or last used, e.g. `ws://192.168.8.10:8765`) and pairing secret (section 9.4).
3. Connect: send `hello` (component `ios_anchor` or `ios_wearer`, `device_id`, `role`).
4. Capability check; if UWB isn't supported, show it in large text and report `status ok:false`.

### 7.3 Anchor role
- Create **one** `NISession` dedicated to the wearer.
- Publish its token: `uwb_token { from: "uwb_1", to: "wearer", token_b64 }` (token archived with `NSKeyedArchiver.archivedData(withRootObject:requiringSecureCoding: true)`, base64-encoded).
- When the wearer's token addressed to this anchor arrives, run `NINearbyPeerConfiguration(peerToken:)`.
- Screen: huge "UWB Reader/Emitter 1", connection state, last distance to wearer, battery level. Report `status` every 5 s with `info: { role, uwb_running, last_distance_m, battery }`.
- Anchors do **not** send ranges (the wearer is the single source of measurements; avoids double counting).

### 7.4 Wearer role
- Create **one `NISession` per anchor** (three sessions). Each `NIDiscoveryToken` belongs to one session, so the wearer sends three tokens: `uwb_token { from: "wearer", to: "uwb_1" | "uwb_2" | "uwb_3", token_b64 }`.
- When each anchor's token arrives, run that session with the anchor's token.
- In `session(_:didUpdate:)`, for each `NINearbyObject` with a non-nil `distance`, send:
  `uwb_range { anchor: "uwb_1", distance_m, t, seq }`. Ignore `direction` (camera assistance stays off).
- Rate: forward every update; if updates exceed 20 Hz per anchor, decimate to 20 Hz.
- Also send `motion_state` (section 7.5).
- Screen: three rows "UWB Reader/Emitter 1: 2.41 m", update rate per anchor, motion state, hub connection. Big "Talk" button if push-to-talk is built.

### 7.5 Motion state (moving vs still)
- `CMMotionManager.deviceMotion` at 50 Hz; magnitude of `userAcceleration`.
- `still` when the 0.5 s RMS stays below 0.03 g; `moving` when above 0.06 g (hysteresis).
- Send `motion_state { state: "moving" | "still", t }` on every change, plus a heartbeat every 1 s.
- This is reliable even for slow, shuffling steps, which is why it's used instead of the step counter.

### 7.6 Session lifecycle and recovery
| Event | Action |
|---|---|
| `sessionWasSuspended` | Show "Paused", report status. |
| `sessionSuspensionEnded` | Re-run the same configuration. |
| `session(_:didRemove:reason: .timeout)` | Re-run configuration with the last peer token; after 3 failures, create a new session and publish a new token. |
| `session(_:didRemove:reason: .peerEnded)` | Wait for a fresh token from that peer. |
| `session(_:didInvalidateWith:)` | Create a new session, publish a new token. |
| Bus disconnect | Reconnect with backoff (0.5 s → 5 s); on reconnect, re-send `hello` and current tokens. |
| App backgrounded | Sessions suspend; on foreground, resume as above. |

**Open risk to test first:** three concurrent `NISession`s on the wearer phone. If the device can't sustain three, fall back to round-robin (run two at a time, rotate every 2 s) and widen smoothing.

---

## 8. Hub: UWB module (`services/hub/earmark_hub/uwb/`)

### 8.1 Token relay
- Keep the latest token per `(from, to)` pair in memory.
- Forward each `uwb_token` to the client(s) whose `device_id` equals `to`.
- When an iOS client connects (`hello`), replay every stored token addressed to it.
- On `reset`, clear nothing (phones keep their sessions); on hub restart, phones re-send.

### 8.2 Position solver
Run at 10 Hz on the latest range per anchor.

1. **Freshness:** a range is fresh if `now - t ≤ 0.5 s`.
2. **Slant correction:** `h_i = sqrt(max(d_i² - Δz_i², 0))`.
3. **Solve** (x, y) by Gauss-Newton least squares on `Σ (|p - a_i| - h_i)²`, initialized from the previous estimate (or the anchors' centroid). 5 iterations max.
   - 3 fresh anchors: full solve, plus leave-one-out: if the residual RMS > 0.25 m, re-solve with each pair and keep the one with the lowest residual that's consistent with the previous estimate. Flag the dropped anchor as `blocked`.
   - 2 fresh anchors: two circle intersections; choose the one in the walking area (y < counter line) closest to the prediction.
   - Fewer than 2 for more than 2 s: mode `lost` (section 8.5).
4. **Gate:** reject a solution implying speed > 2.5 m/s from the last accepted estimate.
5. **Smooth:** alpha-beta filter (position + velocity), α = 0.5, β = 0.1 at 10 Hz; when `motion_state = still`, α = 0.2 (heavier smoothing, the user isn't moving).
6. **Head offset:** listener = phone estimate shifted back by `head_offset_m` along the facing direction. Facing comes from the AirPods yaw (`head_pose`, which the Mac app already publishes at ≤ 10 Hz). Without a recent `head_pose`, use the direction of travel, or toward the counter inside the counter zone.

Quality: publish `residual_m`, `anchors_used`, and `blocked` with every pose.

### 8.3 Freeze state machine (the landing spot)

States: `tracked` → `frozen` → `tracked`, plus `lost` and `fixed`.

Constants (in `config/hub.json` under `uwb`):
| Name | Default | Meaning |
|---|---|---|
| `counter_ref` | `[0, 0]` | The listening position (origin) |
| `freeze_enter_m` | 1.0 | Must be within this distance of `counter_ref` |
| `freeze_exit_m` | 1.3 | Leaving this radius unfreezes (hysteresis) |
| `still_for_s` | 0.6 | `motion_state = still` for this long before freezing |
| `average_window_s` | 1.0 | Average the smoothed position over this window while still |
| `unfreeze_move_m` | 0.35 | Moving this far from the frozen point (while `moving`) unfreezes |
| `blend_s` | 0.4 | How long the Mac glides the listener between positions |

Rules:
- **Enter frozen** when inside `freeze_enter_m` AND still for `still_for_s` AND ≥ 2 fresh anchors. Frozen position = mean of the smoothed estimates over `average_window_s`, with the head offset applied facing the counter.
- **Voice override:** "I'm here" (keyword grammar) freezes immediately at the current smoothed estimate, even outside the radius.
- **While frozen:** publish the frozen position; keep solving only to check the exit conditions.
- **Exit frozen** when (`moving` AND displaced > `unfreeze_move_m` from the frozen point) OR outside `freeze_exit_m`.
- Every transition publishes a `listener_pose` immediately (not waiting for the 10 Hz tick).

### 8.4 NFC re-anchor (freeze + NFC together)
NFC already gives exact spot positions and pickups. A pickup also tells us **where the user's hand just was**, which constrains where the user is.

- On `pickup` from spot N while `frozen`: if the frozen listener is farther than `reach_max_m` (default 0.75 m) from spot N's position, move the frozen point toward spot N until it's exactly `reach_max_m` away. Log the correction size.
- On `placed` at spot N while frozen: same rule.
- Never re-anchor while `tracked` (the user may have walked away with the jar).
- The wrong-jar correction and "Got it" confirmation logic in the concierge are unchanged: they depend only on NFC and spot relationships, never on UWB.

This makes the freeze self-correcting: if the user stopped off to one side, their first touch of the counter pulls the listener back to the right place.

### 8.5 Fallbacks
| Condition | Mode | Behavior |
|---|---|---|
| ≥ 2 fresh anchors | `tracked` / `frozen` | Normal. |
| < 2 fresh anchors for > 2 s while tracked | `lost` | Hold the last good position for up to 3 s, then switch to `fixed`. Concierge says once: "I've lost track of where you are. Walk to the counter and say 'I'm here'." |
| UWB disabled or no iOS clients | `fixed` | Listener at the origin: **exactly today's behavior**. |
| Wearer reconnects with ranges | back to `tracked` | Announce nothing; just resume. |

### 8.6 Simulator adapter (`uwb_sim`)
So the Mac app, concierge, and dashboard can be built before the phones work:
- Generates `uwb_range` from a scripted path (start mark → counter), with configurable Gaussian noise (default σ = 0.07 m), occasional body-block dropouts and +0.4 m jumps on one anchor, and `motion_state` from path speed.
- Scenario file `scenarios/uwb_walk.jsonl` (generated by `scripts/gen_scenarios.py`), and an interactive mode (arrow keys move the wearer) for live demos without phones.
- Enabled with `EARMARK_ADAPTERS=simulator,uwb_sim`.

---

## 9. Contracts (proposed changes)

All changes go into `contracts/schemas/bus_message.schema.json` with at least two examples each in `contracts/examples/bus/<type>/`, regenerated TS types, Python models, and Swift `Codable`s. `make contracts-test` must pass.

**Agree `listener_pose` with the sound track before splitting work** (section 14).

### 9.1 Changed
- `component` enum: add `ios_wearer`, `ios_anchor`.
- `hello`: add optional `device_id` (string, e.g. `"uwb_1"`, `"wearer"`), `role` (`"anchor" | "wearer"`), `secret` (string, section 9.4).
- `config/space.json` (`space.schema.json`): add optional `anchors` array:
  ```json
  "anchors": [
    { "anchor": "uwb_1", "label": "UWB Reader/Emitter 1", "position": [-0.9, 0.75, -0.25] },
    { "anchor": "uwb_2", "label": "UWB Reader/Emitter 2", "position": [ 0.9, 0.75, -0.25] },
    { "anchor": "uwb_3", "label": "UWB Reader/Emitter 3", "position": [-1.4, -1.8, -0.25] }
  ]
  ```
  (Positions above are placeholders until calibration.)

### 9.2 New bus messages
| `type` | Direction | Fields |
|---|---|---|
| `uwb_token` | iOS → hub → iOS | `from`, `to`, `token_b64`, `t` |
| `uwb_range` | wearer → hub | `anchor`, `distance_m`, `seq`, `t` |
| `motion_state` | wearer → hub | `state` (`moving` / `still`), `t` |
| `listener_pose` | hub → bus | `position` [x, y, z], `mode` (`tracked` / `frozen` / `lost` / `fixed`), `source` (`uwb` / `sound` / `sim` / `none`), `residual_m` (number or null), `anchors_used` (int), `blocked` (array of anchor ids), `t` |

Example `listener_pose`:
```json
{ "type": "listener_pose", "position": [0.12, -1.85, 0.0], "mode": "tracked", "source": "uwb",
  "residual_m": 0.06, "anchors_used": 3, "blocked": [], "t": 1761351234.5 }
```

### 9.3 Convex HTTP (`convex_http.schema.json`)
- `/ingest` accepts an optional `anchors` array (id, label, position, online, last_distance_m, last_seen_t) and an optional `pose` object (position, mode, source, t).

### 9.4 Security (bus leaves localhost)
- The bus must listen on the private network (`bus.host: "0.0.0.0"`) for the phones. That's a change from today's `127.0.0.1`.
- Add `bus.secret` (from `.env`, `EARMARK_BUS_SECRET`). Clients other than localhost must send it in `hello`; the hub rejects others.
- Only on the team's private network; never on venue Wi-Fi.

---

## 10. Mac app changes (`mac/`)

### 10.1 Listener position in the audio engine
- `SpatialRenderer`: add `setListener(position: EarmarkPoint)`.
- `AVAudioCueRenderer`: set `env.listenerPosition = Geometry.avPoint(position)` (mapping `(x, y, z) → (x, z, -y)` as today). Glide over `blend_s` (0.4 s) with per-frame interpolation; never jump.
- Distance attenuation: `env.distanceAttenuationParameters`: model `.inverse`, `referenceDistance` 0.6 m, `maximumDistance` 8 m, `rolloffFactor` 1.0. Tune by ear (section 12).
- `PHASECueRenderer` (Option B): same, via its listener transform.
- `MockRenderer`: record positions for tests.

### 10.2 Guidance relative to the listener
Today `Guidance` and `Geometry` compute angles from the origin. Change them to use the vector **target − listener**:
- `Geometry.azimuthDeg(target, from: listener)`, `horizontalDistance(target, from: listener)`.
- `Guidance.update(headYawDeg:listener:now:)`.
- **Ping interval:** keep the angle curve (900 ms at ≥ 90°, 150 ms under 10°) and multiply by a distance factor: `1.0` within 1 m, rising linearly to `1.6` at 4 m. Far = slower, close = faster, aligned = fastest.
- "Behind" cue and "locked" tone: unchanged, computed from the relative vector.

### 10.3 Bus handling
- Subscribe to `listener_pose`; on each message, update the renderer and guidance.
- `fixed` or no messages: listener at the origin (today's behavior).
- Publish `head_pose` at 10 Hz whenever UWB is active (the hub needs facing for the head offset).

### 10.4 Map view
- Auto-scale bounds to include spots, anchors, and the walking area.
- Draw anchors as labeled triangles, **"UWB Reader/Emitter 1/2/3"**, with online/blocked state shown by **icon and text**, never color alone.
- Draw the wearer as a dot plus the head-direction cone (from AirPods yaw), with a mode badge: "Tracking", "Frozen at counter", "Lost", "Fixed position".
- Text list equivalent below the map (accessibility rule 7): "UWB Reader/Emitter 1: online, 2.4 m from you."

### 10.5 Status bar
Add: `UWB: 3/3 anchors · ±0.06 m · Frozen`.

### 10.6 Calibration screen (new, in `DebugAndSettings.swift` or a new `CalibrationView.swift`)
Keyboard- and VoiceOver-accessible sheet:
1. **Anchor positions.** For each of UWB Reader/Emitter 1/2/3: fields for forward / side / height in cm, measured from the origin floor mark (same convention as `scripts/calibrate.py`). Live status next to each: online, last distance to the wearer.
2. **Phone height** (`phone_z`) and **head offset** fields, with defaults.
3. **Verify.** "Stand on the origin mark, facing the counter, and press Verify." Shows the solved position and its error from (0, 0). Then four more marks (e.g. 1 m back, 2 m back, 1 m left, 1 m right) with pass/fail against the targets in section 3.
4. **Recenter** prompt at the end (AirPods yaw 0 = facing the counter), so the room and the AirPods agree on "forward".
5. **Save:** write `config/space.json` (keep `.bak`), then send `reset` so the hub reloads it. The hub pushes anchors to Convex.

`scripts/calibrate.py` gets matching anchor prompts as a terminal fallback.

---

## 11. Concierge and dashboard

### 11.1 Concierge (`services/concierge/`)
- Subscribe to `listener_pose`; keep the latest.
- `direction_phrase` takes the target position **relative to the listener**.
- Phrasing by mode:
  - `tracked` and farther than 1.2 m: "The sugar is ahead of you, a little to the right, about 3 meters." (Meters rounded to the nearest half meter; direction in plain words.)
  - `frozen` or `fixed`: today's clock-face phrasing ("at your one o'clock, about an arm's length").
  - `lost`: the lost message in 8.5, once per guidance.
- On transition to `frozen` during guidance: "You're at the counter." then the clock-face phrase.
- Keyword grammar: add "I'm here" (freeze override) and "recenter".
- Pickup confirmation and wrong-jar correction: unchanged.

### 11.2 Convex (`convex/`)
- New table `anchors`: `anchorId`, `label`, `position`, `online`, `lastDistanceM`, `lastSeenT`. Upserted from `/ingest`.
- New table `wearerPose`: **one row**, overwritten: `position`, `mode`, `source`, `t`. Cleared by reset.
- Hub syncs anchors on change and pose at **≤ 2 Hz**.
- **Data minimization:** no pose history is stored, ever. Pose is not written to `events`. Update `docs/RESPONSIBLE_DESIGN.md` to say so.

### 11.3 Dashboard Live map (`dashboard/src/pages/LiveMapPage.tsx`)
- Show anchors as **"UWB Reader/Emitter 1/2/3"** with online/offline text and icon.
- Show the wearer dot with its mode in words ("Walking toward the counter", "At the counter").
- Update the caption: today it says the listener sits at the bottom facing the spots; it becomes "Seen from above. The dot is the person; the triangles are the UWB anchors."
- Text-list equivalent, both themes, axe clean (existing test harness).

---

## 12. Test plan and gates

### 12.1 Automated (no phones)
| Suite | Tests |
|---|---|
| contracts | New schemas and examples validate in Python, TS, Swift. |
| hub/uwb | Solver: exact ranges → exact position; σ = 0.07 m noise → median error < 0.10 m; one anchor +0.4 m outlier → rejected and flagged; 2-anchor intersection picks the in-area solution; speed gate. Slant correction. |
| hub/freeze | Enter on still + radius; no enter while moving; hysteresis exit; voice override; NFC re-anchor moves the point to exactly `reach_max_m`; no re-anchor while tracked; lost → fixed timing. |
| hub/uwb_sim | Scenario `uwb_walk` produces tracked → frozen; pose rate ≥ 5 Hz. |
| mac | Listener-relative azimuth and distance; ping interval distance factor; blend never jumps more than the per-frame step; map shows anchors and text list. |
| concierge | Phrase selection by mode; "I'm here" routing. |
| dashboard | Anchors and wearer render; text list; axe in both themes. |
| e2e | `uwb_walk` through real hub + concierge processes: correct phrases, freeze, then the existing wrong_jar flow. |

### 12.2 On-device gates (in order; record results in `docs/STATUS.md`)
1. **Ranging gate:** one anchor + wearer, tape at 0.5 / 1 / 2 / 3 m. Pass: each within ±0.10 m (averaged over 2 s).
2. **Concurrency gate:** wearer with three sessions sustains ≥ 5 Hz per anchor for 2 minutes.
3. **Position gate:** stand on 5 floor marks. Pass: section 3 targets.
4. **Freeze gate:** walk to the counter 10 times, stop naturally. Pass: frozen point ≤ 0.15 m from the mark in 8 of 10.
5. **Body-block check:** walk with the wearer's body between the phone and one anchor; confirm the outlier is flagged and the pose doesn't jump more than 0.3 m.
6. **Walk gate:** eyes closed, start mark to the sugar, 5 attempts. Pass: 4 of 5 lift the correct jar (NFC-confirmed), with a spotter (section 13.6).

---

## 13. Things we were missing (and decisions)

### 13.1 AirPods auto-switching (P0)
AirPods automatically jump between Apple devices on the same Apple ID. If the wearer's iPhone plays any sound or notification, the AirPods may leave the Mac mid-demo.
- On the wearer iPhone: Settings → Bluetooth → AirPods → "Connect to This iPhone" → **When Last Connected to This iPhone**, or sign the wearer phone into a different Apple ID, or simply forget the AirPods on that phone.
- Turn on Do Not Disturb / Focus on all four phones.

### 13.2 Voice input when the user walks away from the Mac (P0)
The Mac's built-in mic, from 3 m in a loud hall, will hear the user poorly.
- Recommended: the wearer app streams the **iPhone's** mic as `mic_audio` (same contract the Mac app uses today) while a big "Talk" button is held. The AirPods are connected to the Mac, so the iPhone mic doesn't touch the AirPods' audio quality.
- Fallback: the operator types the request (`--text`) or holds push-to-talk on the Mac.

### 13.3 Network (P0)
Bring a travel router or use one phone's hotspot (not an anchor or the wearer; a fifth device if possible). Reserve IPs or show the Mac's IP as a QR code in the Mac app for the phones to scan.

### 13.4 Xcode (P0)
Not installed on the demo Mac. Start the download immediately; it's large and gates everything in section 7.

### 13.5 Power and heat (P1)
Four phones with screens on and UWB running for hours. Plug in all anchors; keep the wearer phone charged between judges; low brightness.

### 13.6 Physical safety (P1)
A judge walking with eyes closed in a crowded hall: clear the floor, tape the walking path, always have a spotter beside them, and keep the walk to 2-4 m.

### 13.7 Booth space (P1)
Needs roughly 3 × 3 m of clear floor in front of the counter. Confirm with organizers what the table area allows.

### 13.8 Recentering and drift (P1)
AirPods yaw drifts slowly. Recenter at the start mark facing the counter for each judge; add the "recenter" voice command; the calibration screen ends with a recenter prompt.

### 13.9 Docs and pitch (P1)
- `docs/DEMO_SCRIPT.md`: add the walking segment, operator checklist items (network, anchors online, wearer app, AirPods on the Mac).
- `docs/PRODUCTION.md`: UWB anchors as small dedicated modules (e.g. Qorvo's Apple-interoperable modules) instead of iPhones; the user's own iPhone as the wearer.
- `docs/RESPONSIBLE_DESIGN.md`: no camera; pose is transient and never stored; anchors are radios, not sensors of the room.

### 13.10 Bake-off and cutoff (P0, team process)
Set a fixed time (suggested 02:00) to compare the UWB and sound tracks on the same gates (section 12.2, items 3, 4, 6) and pick one for the demo. The seated, fixed-position demo stays ready as the guaranteed fallback whatever happens.

---

## 14. Interface with the sound track

Both tracks produce the **same** `listener_pose` message, with `source: "uwb"` or `source: "sound"`. Everything downstream (Mac app, concierge, dashboard, freeze, NFC re-anchor) is shared and built once.

| Shared (build once) | UWB track only | Sound track only |
|---|---|---|
| `listener_pose` contract | iOS app, NI sessions, token relay | Speaker chirp scheduling from the Mac |
| Freeze state machine + NFC re-anchor | `uwb_range` solver | Chirp detection and timing on the phone |
| Mac listener position, guidance, map | Anchor calibration (positions of iPhones) | Speaker calibration |
| Concierge phrasing by mode | | |
| Dashboard map + Convex tables | | |

Rule: the freeze and re-anchor logic live in the hub, after the source-specific solver, so they work for either source. Sound's rougher accuracy means its freeze should use a fixed snap to the origin mark rather than the averaged position (configurable: `freeze_mode: "average" | "snap"`).

---

## 15. Milestones (tonight)

| Time (PDT) | Milestone | Done when |
|---|---|---|
| now - 18:30 | Xcode download; network; agree `listener_pose` with the sound track; contracts PR | Contracts tests pass with new messages |
| 18:30 - 20:30 | iOS app: role picker, one anchor + wearer ranging, on-screen distance | Ranging gate passes |
| 19:00 - 21:00 | Hub: token relay, solver, freeze, `uwb_sim` (in parallel, no phones needed) | Hub tests pass; `uwb_walk` scenario works |
| 20:30 - 22:00 | Three anchors, ranges over the bus | Concurrency gate passes |
| 21:00 - 23:00 | Mac: listener position, relative guidance, map, status bar | Walk works against `uwb_sim` |
| 23:00 - 00:30 | Calibration screen; dashboard anchors + wearer; concierge phrasing | Position gate passes |
| 00:30 - 02:00 | Freeze + NFC re-anchor on device; tuning; mic from phone | Freeze and walk gates pass |
| 02:00 | **Bake-off with the sound track; pick one** | Decision in `docs/STATUS.md` |
| 02:00 - 04:00 | Demo script, docs, rehearsal, backup video | Full demo run twice in a row |

---

## 16. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Xcode not ready in time | Medium | Blocks the iOS app | Start the download now; build the hub, Mac, and dashboard against `uwb_sim` meanwhile. |
| Three concurrent NI sessions unstable | Medium | Lower rate or gaps | Round-robin fallback; 2-anchor solve; heavier smoothing. |
| Venue Wi-Fi blocks devices | High | Nothing connects | Own router or hotspot. |
| AirPods switch to the iPhone | Medium | Audio disappears mid-demo | Section 13.1 settings; Focus mode. |
| Bodies block UWB | High | Pose jumps | Leave-one-out rejection, speed gate, still-mode smoothing, phone held at chest. |
| Mac mic can't hear the walking user | High | Requests missed | Phone push-to-talk (13.2); operator typing. |
| Anchor phones lock or background | Medium | Ranging stops | Idle timer off, plugged in, Guided Access. |
| Freeze lands off to one side | Medium | Wrong clock direction at the counter | NFC re-anchor; "I'm here" override; tactile origin mark. |
| Everything UWB fails | Low | No walking demo | `fixed` mode = today's working seated demo, no code change. |

---

## 17. Open questions

1. Exact iPhone models for the four phones (affects nothing in the design, since direction isn't used, but confirm UWB support).
2. Booth dimensions and where the counter sits, for anchor placement.
3. Does the wearer phone stream the mic (13.2), or does the operator handle voice?
4. Do we keep the "sweep" sound approach at all, or is it fully replaced by the teammate's timing-based sound track?
5. Who owns the shared pieces in section 14 (suggest: the UWB track owns the hub freeze and Mac listener changes; the sound track reviews)?
