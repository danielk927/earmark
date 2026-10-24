# Earmark architecture

Earmark helps blind and low-vision people find everyday objects by sound.
Objects are tracked by pluggable detection adapters, a local hub turns raw reads into object state, a voice concierge answers requests, and a Mac app renders a head-tracked spatial ping through AirPods.

```
            +--------------- Detection adapters (pluggable) ---------------+
            | simulator (always) | nfc_serial | ble_fobs | camera (stub)   |
            +--------------------------+-----------------------------------+
                                       | DetectionEvent
                                       v
                     +---------------- hub (Python) ----------------+
                     | debounce - state engine - pickup detection   |
                     | registry cache - local WebSocket bus :8765   |
                     +-------+----------------------+---------------+
            bus messages     |                      | HTTPS (X-Earmark-Secret)
        +--------------------+-----------+          v
        v                    v           |   +-------------- Convex --------------+
 concierge (Python)   Mac app (Swift)    |   | objects - spots - areas - events  |
 voice agent:         head tracking      |   | objectState - medications - doses |
 Moss + LLM tools     spatial ping       |   | trials - HTTP actions - crons     |
 + Cartesia TTS ----> speech playback    |   +------+------------------+---------+
                      mic -> STT --------+          |                  |
                         |                          v                  v
                         v                  dashboard (React)   memory_agent (Fetch.ai
                      AirPods               caregiver + family  uAgent, Claude)
                                            labeling                <-- ASI:One
```

## Principles

- The contracts in `contracts/` are the only interfaces between components.
- Nothing downstream of the hub knows which detection method produced an event.
- Directions, distances, angles, debouncing, and adherence are deterministic, tested code.
  LLMs only choose a tool and phrase a response.
- The local loop (adapters, hub, concierge, Mac app, AirPods) runs without internet except for speech, and speech degrades to cached phrases and then the system voice.

## Components

| Component | Language | Owns | Talks to |
|---|---|---|---|
| hub | Python | `services/hub/` | adapters (in-process), bus server, Convex HTTP |
| concierge | Python | `services/concierge/` | bus client, Moss, Claude, Cartesia |
| Mac app | Swift | `mac/` | bus client, CoreMotion (AirPods), AVAudioEngine, Speech |
| Convex | TypeScript | `convex/` | hub (HTTP), dashboard (client), memory agent (HTTP) |
| dashboard | TypeScript (React + Vite) | `dashboard/` | Convex client |
| memory agent | Python | `services/memory_agent/` | Agentverse mailbox, Convex HTTP read endpoints, Claude |

## The local bus

A single WebSocket server inside the hub at `ws://127.0.0.1:8765`.
Every local component is a client.
Clients send `hello`, receive a `snapshot`, then exchange typed JSON messages (`contracts/schemas/bus_message.schema.json`).
The hub routes by each client's `subscribe` list, so high-rate audio (`mic_audio`, `speak`) only reaches the components that asked for it.

## The hero flow: "Where's the sugar?"

1. The Mac app streams built-in-mic audio as `mic_audio` to the concierge, which streams it to Cartesia Ink STT.
2. Ink's turn detection ends the utterance; the concierge publishes a final `transcript`.
3. The concierge asks Claude (Haiku) to choose one tool (with a 1.5 s timeout and a keyword-grammar fallback); Moss resolves "sugar" to `object_id: sugar`.
4. Deterministic code reads the sugar's `ObjectState` (spot 3, precision `exact`), computes "at your one o'clock, about an arm's length", and sends `guide_start` with the spot's position.
5. Cartesia Sonic streams the phrase as `speak` chunks; the Mac app plays them centered and ducks the ping.
6. The Mac app renders a mono ping at the target through `AVAudioEnvironmentNode` (HRTF), rotating the listener by AirPods head yaw and pitch every frame, so the sound stays fixed in the room.
7. The user lifts a jar; the hub's debounce emits `pickup`.
   If it is the sugar: `guide_stop(found)` and "Got it, that's the sugar."
   If it is the salt: "That's the salt. The sugar is one spot to your right."

## Memory: "I put my keys in the drawer"

Earmark remembers where the user said they put things, using the saved places in `config/space.json` (`areas`: the counter, cupboard, drawer, bag, box).
The app does not know where the user is standing, so "I'm leaving my keys here" is not saved; Earmark asks for a place instead.

1. The concierge hears "I put my keys in the drawer", matches "drawer" to a saved place, and sends a `place_item` bus message.
2. The hub moves the keys' state to that place (precision `area`) and logs a `stored` event to Convex.
3. "Where are my keys?" now answers "near the drawer. I noted that at 4:50 PM."
4. "Where did I put my keys before?" lists the current place and the one before it, each with when it was noted.
5. The family can see every move on the dashboard timeline, and the memory agent answers "where did Dad put his keys?" from the same events.

Rules: every answer says when; Earmark records only what it was told or saw (for example "went to the pill box"), never that someone took a pill.

## Walking: the locator

The locator (`locator/`) tells the system where the user is standing, so the ping can lead them across the room.

1. Five sound beacons chirp in turn; the iPhone's microphone hears them and works out the user's ear position. The beacons can be small buzzers on one board (`locator/firmware`) or five spare iPhones (`services/ranging`, `locator/ios/EarmarkPhone`). With phones there is no shared clock: each phone times the chirps on its own recording, and the Mac turns those timings into distances. Setup steps: `locator/docs/PHONE_BEACONS.md`.
2. The phone sends `listener_pose` (about 3 per second) to the bus. The hub passes it on; it needs no special handling.
3. The Mac app subtracts the user's position from the item's position, then turns it by the AirPods head angle. The ping gets faster and louder as the user gets closer.
4. Within half a meter the Mac app stops the ping, plays a short tone and sends `guide_feedback arrived`. The concierge then says "You're here. The keys are up high, at your twelve o'clock."
5. The concierge also uses the position for spoken directions ("at your four o'clock, a step away") and to save "I'm leaving my keys here" (`place_item` with a `position`).
6. With no fix for 5 seconds, everything falls back to the old behavior: the user is assumed to be on the mat.

When the locator is used, positions in `config/space.json` must be measured in the locator's frame: origin on the floor under the mat center, `z` up from the floor (a shelf at 1 m is `z = 1.0`). The older seated setup measured `z` from head height.

The Mac app sends `ptt start/stop` while the user speaks, so the phone can stream its microphone. Using the AirPods stem as the push-to-talk button and switching speech input to the phone microphone are not built yet.

## Coordinate system

Meters, +x right, +y forward, +z up, origin at the calibrated head position.
Head yaw is positive turning right.
`AVAudio3DPoint` uses +x right, +y up, -z forward, so the Mac app maps Earmark `(x, y, z)` to `(x, z, -y)`.
Sign constants (`yawSign`, `pitchSign`) live in one Swift file so they can be flipped after the on-device sign check.

## Failure handling

| Failure | Behavior |
|---|---|
| Convex unreachable | Hub keeps working from `config/objects.cache.json`; events queue on disk and flush on reconnect. |
| Claude slow (> 1.5 s) or down | Keyword grammar handles where/find, stop/cancel, "this is X", "make X beep", "I put X in the drawer". |
| Moss unavailable | Exact name/alias match, then fuzzy string match, in code. |
| Cartesia STT silent for 1 s after speech starts | Concierge sends `stt_mode: apple`; the Mac app switches to on-device `SFSpeechRecognizer`. |
| Cartesia TTS down | Pre-synthesized `speak_cached` phrases, then `speak_text` (system voice in the Mac app), then macOS `say`. |
| AirPods head tracking lost | Fallback ladder: spatial without head tracking, then exaggerated stereo panning plus clock-face speech, then speech only. The UI shows the active mode. |

## Deviations from the build brief

- Xcode is not installed on the demo Mac, so the Mac app is a SwiftPM package built into a signed `.app` bundle by `mac/build_app.sh` (Command Line Tools only).
  Xcode can still open the package directly.
- Bus messages added beyond the brief's table, all needed for the flows it describes: `hello`, `snapshot`, `registry_update`, `unknown_tag`, `label`, `stt_mode`, `guide_feedback`, `speak_text`, `playback`, `reset`, `place_item` (memory), and from the locator `listener_pose` and `ptt`.
