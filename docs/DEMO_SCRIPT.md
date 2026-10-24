# Earmark demo script (2 minutes + 2 minutes Q&A)

Roles: **Presenter** (talks), **Operator** (at the Mac), **Judge** (wears the AirPods).
Numbers in brackets come from tomorrow's real trials and latency runs; never say a number we did not measure.

## Before each judge (Operator, 60 seconds)

1. `make reset` (bus reset plus Convex back to the demo starting state; trials are kept).
2. Salt on spot 2, sugar on spot 3, pills on spot 4, spot 1 empty, keys hidden somewhere in the booth.
3. AirPods on the judge, connected to the Mac, menu-bar AirPods icon: Spatial Audio **Off**.
4. Earmark app status bar: Bus connected, Head tracking "Tracking", Output = AirPods at **48 kHz** (16 or 24 kHz means hands-free mode: check System Settings > Sound > Input is the MacBook Pro Microphone).
5. Judge seated in the demo chair, facing forward: press **R** (Recenter).
6. Dashboard open on the second screen (Live map page).

## Script

**0:00 - 0:15 Hook (Presenter)**
- "Two identical jars. One is salt, one is sugar. If you're blind, the only way to tell is to taste it."
- "Earmark helps blind and low-vision people find everyday things by sound, and it never needs a camera in the home."

**0:15 - 1:10 Live demo (Judge + Operator)**
- Judge (push-to-talk: Operator holds Space, or always-listening): "Where's the sugar?"
- Earmark: "The sugar is at your one o'clock, about an arm's length away." A ping plays from the jar.
- Presenter: "Turn your head. The sound stays on the jar, because we read the AirPods' head tracking ourselves and render the audio in 3D."
- Judge reaches. If they lift the salt: "That's the salt. The sugar is one spot to your right." (This is the hero moment; it is fine to nudge the judge toward the wrong jar first.)
- Judge lifts the sugar: "Got it, that's the sugar." The dashboard's live map updates at the same instant (point at it).
- Judge: "Where are my keys?" Earmark: proximity phrase, and the fob beeps.
- Walking beat (needs the locator running): "Where are my keys?" The ping comes from the drawer; as the judge walks toward it, it gets faster and louder; within half a meter it stops, a tone plays, and Earmark says "You're here. The keys are up high, at your twelve o'clock."
- Memory beat: Judge: "I put my keys in the drawer." Earmark: "Got it, the keys are in the drawer." Later: "Where are my keys?" -> "The keys are near the drawer. I noted that at [time]." Then "Where did I put my keys before?" -> the earlier place, with its time. The timeline on the dashboard shows each move. "I'm leaving my keys here" saves the spot the locator says the judge is standing at; without a locator fix Earmark says "tell me the place" instead.

**1:10 - 1:40 How it works (Presenter, over the architecture slide)**
- Each item sits on an NFC "home spot" or carries a Bluetooth fob; detection is pluggable, and everything downstream only sees one event format.
- Directions, distances, debouncing, and medication adherence are deterministic code; the LLM only chooses an action and phrases it.
- Cartesia Ink and Sonic for both directions of speech; Moss resolves fuzzy requests ("something for my eggs"); Convex is the real-time backend for the dashboard, adherence, and trials; Claude chooses the action, labels items from one caregiver photo, and reasons for a Fetch.ai agent that caregivers reach through ASI:One.

**1:40 - 2:00 Impact (Presenter)**
- Measurable: "[TRIAL RESULTS: n trials with m blindfolded testers; median time to find with Earmark vs touch only; wrong picks]." Say "pilot" if there are only a handful of trials.
- Caregivers: the dashboard shows medication adherence from pickups (the seeded missed evening dose), and a family member can label items remotely.
- Responsible: no cameras in the home, the one caregiver photo is deleted after labeling, no medical advice, and Earmark asks "salt or pepper?" instead of guessing.

## Q&A crib

- **Why not a camera app?** Scene-description apps describe what the camera sees now; they don't remember where things are and can't tell identical containers apart. Earmark's identity comes from tags, not appearance (`docs/CUSTOMER.md`).
- **Front/back confusion?** Past 100 degrees off target the cue switches to a distinct "behind" sound and Earmark says which way to turn.
- **Latency?** Final transcript to first audio: [LATENCY: median and p90 from `make latency`], target 1.2 s.
- **What if the internet is down?** The local loop keeps working; speech falls back to cached phrases, then the system voice; intent falls back to a keyword grammar (`docs/ARCHITECTURE.md`, failure table).
- **Cost per home?** About $147-$559 in parts, an estimate (`docs/PRODUCTION.md`).
- **Privacy?** `docs/RESPONSIBLE_DESIGN.md`.
- **Can it save "leaving my keys here"?** Not yet: the app does not know where the user is standing, so it asks for a named place (cupboard, drawer, bag, box). Tracking the user is the next step (`docs/PRODUCTION.md`).

## If something fails (Operator)

| Failure | Do this | What the judge hears |
|---|---|---|
| NFC readers dead | Quit the hub (Ctrl-C), `make demo-sim`; press the spot number when the judge lifts or returns a jar (`m` + digit to move) | Same experience |
| Head tracking lost | Nothing; the app drops to "spatial without head tracking" and says clock directions | Clock directions still guide them |
| AirPods audio degraded (hands-free) | Set the input to the MacBook mic, reconnect the AirPods | - |
| Cartesia down | Nothing; cached phrases and the system voice take over, Apple Speech listens | A different voice |
| LLM slow | Nothing; the keyword grammar answers within the same turn | - |
| Everything on fire | Play the backup demo video | - |
