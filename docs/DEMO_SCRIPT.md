# Earmark demo script (2 minutes + 2 minutes Q&A)

Roles: **Presenter** (talks), **Operator** (at the Mac), **Judge** (wears the AirPods), **Spotter** (walks beside the judge; walking demo only).
Numbers in brackets come from tomorrow's real trials and latency runs; never say a number we did not measure.

There are two versions of the live demo.
The **walking demo** (UWB, `docs/UWB-PRD.md`) starts 2-4 m from the counter.
The **seated demo** starts at the counter and needs no phones; it is also the fallback when anything UWB fails (see "If something fails").

## Before the demo (Operator, once per session)

Walking demo only. Each item is a yes/no check; don't start until all are yes.

1. **Private network:** the travel router (or a fifth phone's hotspot) is on, and the Mac and all four iPhones are on it. Never venue Wi-Fi: it usually blocks device-to-device traffic, and the bus must not be exposed there.
2. **Bus secret and host:** `.env` has `EARMARK_BUS_SECRET` set and `EARMARK_BUS_HOST=0.0.0.0` (or `bus.host` in `config/hub.json`). Restart the hub after changing either. Each phone has the Mac's address (`ws://<mac-ip>:8765`, from `ipconfig getifaddr en0`) and the same secret.
3. **Three anchors online:** UWB Reader/Emitter 1, 2 and 3 are at their measured spots, plugged in, app open on their role, hub dot green. The Mac status bar's UWB item reads `3/3 anchors` once the wearer is ranging, and the dashboard Live map shows all three as online.
4. **Wearer app:** the wearer phone is on the Wearer role and shows a distance for all three anchors, each updating at least 5 times a second.
5. **AirPods connected to the Mac, not the phone.** On the wearer phone: Settings > Bluetooth > AirPods > Connect to This iPhone > **When Last Connected to This iPhone** (or forget the AirPods on that phone). Auto-switch off this way on any other phone signed into the same Apple ID.
6. **Focus on:** Do Not Disturb (or a Focus) on all four phones, so no notification sound pulls the AirPods over.
7. **Calibrated:** anchor positions, phone height and head offset saved (Mac app Settings > Calibrate UWB anchors, or `make calibrate`), and the five-mark Verify passed. After saving, the hub was reset or restarted.
8. **Floor:** tactile origin mark at the counter, start mark taped 2-4 m back, path between them clear and taped. Nothing metal or a big screen between the path and an anchor, if avoidable.

## Before each judge (Operator, 60 seconds)

1. `make reset` (bus reset plus Convex back to the demo starting state; trials are kept).
2. Salt on spot 2, sugar on spot 3, pills on spot 4, spot 1 empty, keys hidden somewhere in the booth.
3. AirPods on the judge, connected to the Mac, menu-bar AirPods icon: Spatial Audio **Off**.
4. Earmark app status bar: Bus connected, Head tracking "Tracking", Output = AirPods at **48 kHz** (16 or 24 kHz means hands-free mode: check System Settings > Sound > Input is the MacBook Pro Microphone).
5. Walking demo: judge on the **start mark**, facing the counter, wearer phone in hand close to the chest. Press **R** (Recenter) now, so "forward" is the counter. The Spotter stands beside the judge.
   Seated demo: judge in the demo chair at the origin mark, facing forward; press **R**.
6. Dashboard open on the second screen (Live map page). Walking demo: the wearer dot is at the start mark, "Walking toward the counter".

## Script

**0:00 - 0:15 Hook (Presenter)**
- "Two identical jars. One is salt, one is sugar. If you're blind, the only way to tell is to taste it."
- "Earmark helps blind and low-vision people find everyday things by sound, and it never needs a camera in the home."

**0:15 - 1:10 Live demo, walking version (Judge + Operator + Spotter)**
- Judge, eyes closed, on the start mark: "Where's the sugar?" (Hold **Talk** on the wearer phone. The Mac mic hears poorly from 3 m; if the phone mic fails, the Operator types it.)
- Earmark: "The sugar is ahead of you, a little to the right, about 3 meters." A ping plays from the jar.
- Judge walks toward the sound. The Spotter stays beside them, a hand ready, and stops them if anything is in the way.
- Presenter: "Three phones around the booth are fixed ultra-wideband anchors. Each one measures how far the phone in your hand is. Earmark turns that into where you are, so the ping gets closer as you walk. No camera."
- Judge stops at the counter. Earmark freezes their position: "You're at the counter. The sugar is at your one o'clock, about an arm's length away."
- Presenter: "When you stop, Earmark holds your position still, so the last half meter doesn't wobble between jars that sit a hand's width apart."
- **Wrong-jar finale.** Judge reaches. If they lift the salt: "That's the salt. The sugar is one spot to your right." (This is the hero moment; it is fine to nudge the judge toward the wrong jar first.)
- Judge lifts the sugar: "Got it, that's the sugar." The dashboard's live map updates at the same instant: the wearer dot "At the counter" and the sugar lifted (point at it).
- If there is time: "Where are my keys?" Earmark: proximity phrase, and the fob beeps.

**0:15 - 1:10 Live demo, seated version (Judge + Operator)**
- Judge (push-to-talk: Operator holds Space, or always-listening): "Where's the sugar?"
- Earmark: "The sugar is at your one o'clock, about an arm's length away." A ping plays from the jar.
- Presenter: "Turn your head. The sound stays on the jar, because we read the AirPods' head tracking ourselves and render the audio in 3D."
- Judge reaches. If they lift the salt: "That's the salt. The sugar is one spot to your right." (This is the hero moment; it is fine to nudge the judge toward the wrong jar first.)
- Judge lifts the sugar: "Got it, that's the sugar." The dashboard's live map updates at the same instant (point at it).
- Judge: "Where are my keys?" Earmark: proximity phrase, and the fob beeps.

**1:10 - 1:40 How it works (Presenter, over the architecture slide)**
- Each item sits on an NFC "home spot" or carries a Bluetooth fob; detection is pluggable, and everything downstream only sees one event format.
- Walking: the phone measures its distance to three fixed ultra-wideband anchors; the hub turns the distances into a position, freezes it at the counter, and an NFC pickup pulls it back if it landed off to one side.
- Directions, distances, debouncing, and medication adherence are deterministic code; the LLM only chooses an action and phrases it.
- Cartesia Ink and Sonic for both directions of speech; Moss resolves fuzzy requests ("something for my eggs"); Convex is the real-time backend for the dashboard, adherence, and trials; Bitdeer models choose tools, label items from one caregiver photo, and reason for a Fetch.ai agent that caregivers reach through ASI:One.

**1:40 - 2:00 Impact (Presenter)**
- Measurable: "[TRIAL RESULTS: n trials with m blindfolded testers; median time to find with Earmark vs touch only; wrong picks]." Say "pilot" if there are only a handful of trials.
- Walking: "[WALK GATE: k of 5 eyes-closed walks lifted the right jar]" (PRD 12.2 gate 6; only if it was run).
- Caregivers: the dashboard shows medication adherence from pickups (the seeded missed evening dose), and a family member can label items remotely.
- Responsible: no cameras in the home, the one caregiver photo is deleted after labeling, no medical advice, and Earmark asks "salt or pepper?" instead of guessing.

## Q&A crib

- **Why not a camera app?** Scene-description apps describe what the camera sees now; they don't remember where things are and can't tell identical containers apart. Earmark's identity comes from tags, not appearance (`docs/CUSTOMER.md`).
- **Front/back confusion?** Past 100 degrees off target the cue switches to a distinct "behind" sound and Earmark says which way to turn.
- **Latency?** Final transcript to first audio: [LATENCY: median and p90 from `make latency`], target 1.2 s.
- **How do you know where I am?** Ultra-wideband ranging between the phone in your hand and three fixed anchors, measured fresh every time, so errors don't add up as you walk. Position error at five floor marks: [POSITION GATE: median and max]. No camera, no GPS.
- **Why does it freeze at the counter?** Jars sit about 26 cm apart; a live position that moves a few centimeters would swing the direction between them. Standing still at the counter locks the position; touching a jar corrects it.
- **Do you store where I walk?** No. Only the latest position is kept, for the live map, and it is cleared on reset; no position history is stored (`docs/RESPONSIBLE_DESIGN.md`).
- **Why iPhones as anchors?** They were the UWB hardware we had tonight. In a home they would be small dedicated modules, and your own iPhone is the wearer (`docs/PRODUCTION.md`).
- **What if the internet is down?** The local loop keeps working; speech falls back to cached phrases, then the system voice; intent falls back to a keyword grammar (`docs/ARCHITECTURE.md`, failure table).
- **Cost per home?** About $147-$559 in parts, an estimate (`docs/PRODUCTION.md`).
- **Privacy?** `docs/RESPONSIBLE_DESIGN.md`.

## If something fails (Operator)

| Failure | Do this | What the judge hears |
|---|---|---|
| NFC readers dead | Quit the hub (Ctrl-C), `make demo-sim`; press the spot number when the judge lifts or returns a jar (`m` + digit to move) | Same experience |
| Head tracking lost | Nothing; the app drops to "spatial without head tracking" and says clock directions | Clock directions still guide them |
| AirPods audio degraded (hands-free) | Set the input to the MacBook mic, reconnect the AirPods | - |
| AirPods jumped to the phone | Reconnect them to the Mac from the menu bar; recheck the wearer phone's "When Last Connected" setting and Focus | Silence for a few seconds |
| An anchor offline mid-walk | Nothing; two anchors still give a position. Afterwards check that phone's screen (locked, unplugged, app closed) | Same experience |
| UWB lost (fewer than 2 anchors) | Let the judge finish the walk; the Spotter guides them to the origin mark if needed | "I've lost track of where you are. Walk to the counter and say 'I'm here'." |
| Frozen position off to one side | Nothing; the first jar the judge touches pulls it back. Or the judge says "I'm here" on the origin mark | A corrected direction after the first touch |
| Phones can't reach the hub | Check the network, the Mac's IP, the secret, and that the hub listens on 0.0.0.0 (the phone shows the hub's refusal reason in red) | - |
| Anything UWB won't work | **Seated demo.** Close the wearer app; within a few seconds the hub falls back to fixed mode (listener at the origin, today's behavior, no code change). Judge in the demo chair at the origin mark, press **R**, run the seated version | Same seated experience |
| Cartesia down | Nothing; cached phrases and the system voice take over, Apple Speech listens | A different voice |
| LLM slow | Nothing; the keyword grammar answers within the same turn | - |
| Everything on fire | Play the backup demo video | - |
