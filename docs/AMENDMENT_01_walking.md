AMENDMENT 01 — WALKING DEMO. This overrides anything in BUILD_BRIEF.md that conflicts with it. Save it verbatim as docs/AMENDMENT_01_walking.md, update the affected brief sections and contracts, and send the relevant parts to any subagents already running. Don't throw away work in progress; adapt it. Report back with what changed.

1. THE DEMO IS WALKING. The user stands on a mat in a small mock room (about 3.5 x 3.5 m) and walks to items hidden in containers: a cupboard in front, a drawer on the right, a bag on the left, a box behind. The core experience is hearing the spatial ping change as they walk: louder and faster as they get closer, fixed in the room as they turn, swinging behind them if they walk past. The wrong-jar correction (salt vs sugar, side by side on NFC spots inside the cupboard) is the finale. A seated, fixed listener is a fallback only.

2. COORDINATES. Keep the brief's axes (+x right, +y forward, +z up, meters), but the ORIGIN is now a fixed room point: the floor directly under the center of the mat. "Forward" is the direction the mat's tape arrow points. The listener is no longer at the origin; their position comes from listener_pose. In the Mac renderer, convert to AVAudio's convention in ONE function: avaudio = (x, z, -y).

3. NEW CONTRACT: listener_pose (locator → hub bus, about 3 Hz):
   { "type": "listener_pose", "position": [x,y,z], "quality": "ok|degraded|lost",
     "beacons_heard": int, "source": "beacons|steps|sim|manual", "t": float }
   position is the user's EAR position; the locator adds the phone-to-ear offset itself. Add the schema, examples, types and tests.

4. THE LOCATOR IS BUILT SEPARATELY. A teammate is building the iPhone locator app (it listens to 5 acoustic beacons and computes position, like GPS) and the beacon firmware (ESP32 + passive buzzers) in another repo. This repo must:
   (a) let the hub's WebSocket bus accept LAN clients: bind 0.0.0.0, require a shared token from .env. The iPhone connects over the Mac's hotspot or LAN.
   (b) consume listener_pose everywhere it matters (Mac app renderer, dashboard map, concierge distance phrases).
   (c) provide a listener_pose simulator so walking can be tested without the beacons.

5. MAC APP / RENDERER CHANGES:
   - Listener position = latest listener_pose, predicted forward at 25+ Hz using its velocity (cap the prediction at 300 ms). Listener orientation = AirPods head tracking, as already specified.
   - No pose for 1.5 s: hold the last position and show "position lost". No pose for 5 s: fall back to the fixed mat origin, and have the concierge give spoken distances ("about two steps ahead").
   - Cue design replaces the angle-only ping rate:
     - ping interval = 0.15 + 0.3*distance s, clamped to 0.18–1.0 s
     - inverse distance attenuation, reference 0.5 m, max 6 m
     - keep the "locked" tone (angle error under ~10° for 300 ms) and the "behind" sound (over 100°)
     - height cue: a higher-pitched ping variant when the target is 0.3 m or more above the ears, lower when it's 0.6 m or more below
   - ARRIVAL: when the horizontal distance to the target is under 0.45 m, emit a new bus message `arrived {object_id, t}`. The concierge then speaks the spot detail ("Top shelf, front left") and the pickup check takes over.
   - Add a manual mode: arrow keys move the listener on the map, for testing only.
   - SpatialSpike / spatial gate: add the walking tests: (a) a scripted walk toward the target, where the sound grows and stays fixed in the room; (b) a scripted walk past the target, where the sound swings behind; (c) manual arrow-key walking.

6. SPEECH INPUT comes from the PHONE when the locator is connected, because the user walks away from the Mac. The AirPods stem press is push-to-talk: the Mac app sends `ptt {state: start|stop}` on the bus, and the locator streams `mic_audio` during PTT. The Mac's own mic is the fallback.

7. CONFIG (placeholders until tape-measured; brief axes, origin on the floor under the mat):
   - containers/spots: cupboard top shelf salt [-0.08,1.5,1.0] and sugar [0.08,1.5,1.0]; drawer [1.5,0,0.4]; bag [-1.5,0,0.5]; pill box behind [0,-1.5,0.8]
   - add "beacons" to space.json: B1 [-1.5,1.5,1.8], B2 [1.5,1.5,0.3], B3 [1.5,-1.5,1.8], B4 [-1.5,-1.5,0.3], B5 [-1.8,0,1.0], each with id, position and slot index (0–4)
   - mat: [0,0,0], forward = +y

8. SCENARIOS: add walk_to_cupboard, walk_past_target and pose_dropout (listener_pose streams), and update full_demo to: walk to the cupboard → wrong jar → correct jar → "my blood pressure pills" (behind) → walk and turn → arrival.

9. HARDWARE FACTS: we only have the hardware desk catalog. It has RC522 readers (15), ESP32s (6) and passive buzzers. It has NO Bluetooth fobs, so roaming_keys / ble_fobs becomes a stretch item (possibly an ESP32 + buzzer acting as a fob later). No cameras, ever.

10. PRIORITIES. The never-cut list now also includes: listener_pose consumption, the walking cue (distance-based loudness and rate, arrival), and the walking simulator. Move medication adherence, trials, photo labeling, the Fetch.ai agent and Azure below these on the cut list. Definition of done adds: "With simulated walking, and later real listener_pose, a blindfolded teammate walks from the mat to the cupboard by sound alone, and the sound gets louder and stays fixed in the room as they walk and turn."
