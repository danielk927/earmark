# Earmark

**Find anything by sound.**
Ask for your heart pills, and a ping in your AirPods comes from exactly where they are, stays fixed in the room as you turn your head, and speeds up as you walk in.
No cameras in the home, nothing new to wear.

## Inspiration

I spent all four years of high school working and volunteering with people who are blind.
The thing that surprised me most was not the big challenges, it was the small ones that never stop.
Finding things.
A set of keys put down in the wrong place, a remote that slid between cushions, and above all, medication.

Pill bottles all feel the same.
A bottle of heart pills and a bottle of vitamins are the same shape, the same weight, and make the same rattle.
The usual answers are rubber bands, Braille labels, a fixed spot on the counter, or asking someone else, and every one of them breaks the moment anything is moved.
Picking up the wrong bottle is not an inconvenience, it is a safety problem.

So we asked a simple question: what if you could just *hear* where something is?

## What it does

Earmark is a voice assistant that guides you to objects with spatial audio.

- **Ask in your own words.** "Hey, where are my heart pills?", or "where's my blood pressure medicine?" without knowing the exact name. Earmark answers with a direction: "The heart pills are at your three o'clock, about four steps away."
- **Follow the sound.** A ping plays through your AirPods from the item's real position. Head tracking keeps it fixed in the room, so when you turn your head the sound stays put, and you simply turn toward it.
- **It tells you when you're on target.** The ping speeds up as you face the item, and a two-note chime plays when you lock on. If you turn too far, the ping slides to your other ear and slows down, so you correct naturally.
- **It guides you across the room.** Three phones around the room act as sound beacons, so Earmark knows where *you* are standing. The ping gets faster and louder as you walk in, and within half a meter it plays an arrival tone.
- **The last inch.** On arrival it says where to reach: "You're here. The heart pills are down low, at your one o'clock."
- **The right bottle, every time.** Items sit on tagged spots with readers underneath, so Earmark knows *which* bottle left its spot. Lift the right one and it says "Got it, that's the heart pills." Lift the wrong one and it says "That's the vitamins," and points you to the right one.
- **It remembers.** Say "I put my keys in the drawer" and Earmark saves it. Later, "where are my keys?" answers with the place and when it was noted, and "where did I put them before?" walks back through the history.
- **Medication memory.** "Did I take my pills today?" answers from the record: "I can't give medical advice, but I can tell you what the sensors saw. The heart pills were last picked up at 8:14 this morning." Earmark only states what it saw, never that a pill was swallowed.
- **Family, in real time.** A family dashboard shows a live map, items, a timeline of every pickup and placement, medication adherence, and find-time trials, all updating live. A family member can also ask an AI agent, "Where did Dad leave his keys?", and get an answer grounded in the records.

### How this differs from camera glasses

Camera-based assistants such as smart glasses describe what is in front of you.
Earmark solves a different problem, and three things set it apart:

1. **Privacy.** There are no cameras in the home. Position comes from sound, identity from tags, and the only photo ever taken (to name a new item) is deleted as soon as Claude suggests a name.
2. **It finds what you cannot see.** A camera only knows what is in its field of view. Earmark knows where an item is even when it is inside a cabinet, in a drawer, or behind you ("It's behind you. Turn left.").
3. **It tells identical objects apart.** Two pill bottles look and feel the same, and a camera has to read a small label at the right angle. Earmark knows which bottle is which because each one is tagged, so heart pills and vitamins are never confused.

## How we built it

Earmark is six components that talk over one local WebSocket bus, plus a cloud backend.

| Component | Stack | Job |
|---|---|---|
| Hub | Python | Turns raw reader events into object state, detects pickups, runs the bus, syncs to Convex |
| Concierge | Python | Speech in, Claude tool choice, Moss item matching, deterministic directions, speech out |
| Mac app | Swift (SwiftPM) | AirPods head tracking and HRTF spatial audio |
| Ranging | Python + iPhone app | Finds where the user stands from beacon chirps |
| Convex | TypeScript | Memory layer: objects, places, events, doses, trials |
| Dashboard | React + Vite + three.js | Family dashboard and live 3D room view |
| Memory agent | Python (Fetch.ai uAgents) | Answers family questions with Claude, from Convex |

One rule shaped the whole design: **code decides every position, angle, distance, and time; the language models only choose an action and phrase an answer from facts the code fetched.**
Guidance that is wrong by thirty degrees is worse than no guidance, so none of it is left to a model.

### 1. Where is the user? Acoustic positioning with phones

Three iPhones stand around the room as beacons, and the user's own phone listens.
There is no shared clock and no network between beacons: each one chirps on its own audio clock, on a strict schedule.

**The chirp.**
Each beacon plays a 40 ms linear frequency sweep in the 12 to 16 kHz band, Tukey-windowed, once every 0.5 s, in its own 125 ms slot.
Odd beacons sweep up and even beacons sweep down, so neighbours never look alike.

**Detecting it.**
The Mac band-passes the user's phone audio (4th-order Butterworth), correlates it against the up and down templates (a matched filter), and takes the Hilbert envelope of the correlation.
A peak counts when it stands well above the median background and clearly prefers one sweep direction over the other.
Arrival time is refined below one sample with parabolic interpolation around the peak $y_0$:

$$\delta = \frac{1}{2}\,\frac{y_{-1} - y_{+1}}{y_{-1} - 2y_0 + y_{+1}}$$

For self-timed beacons an echo always arrives *late*, so the detector keeps the earliest strong peak, not the loudest one, and suppresses the faint opposite-sweep "ghost" that follows each real chirp.

**Calibration: learning each beacon's clock.**
On the user's recording, beacon $k$'s chirps land on a line

$$t_{k,n} = a_k + b_k\, n$$

where $n$ is the cycle number, $b_k \approx 0.5$ s (off by tens of ppm, the two phones' clock difference) and $a_k$ is unknown.
The user stands still on a mat at a known point for a few seconds; a least-squares fit gives $a_k$ and $b_k$, and the known distance $d_0$ to the mat turns the arrival line into the play line, $a_k \leftarrow a_k - d_0 / c$.
A calibration is rejected if fewer than 12 chirps fit, if the residual exceeds 0.3 ms (about 10 cm of sound), or if the period is off by more than 150 ppm (which means the phone was moving).

**From time to distance.**
After calibration, every chirp heard is a distance on its own:

$$n = \operatorname{round}\!\left(\frac{t - a_k}{b_k}\right), \qquad d_k = c\,\bigl(t - a_k - b_k n\bigr), \qquad c = 331.3 + 0.606\,T \ \text{m/s}$$

Fixed delays inside the phones (speaker to microphone, audio buffers) are absorbed by calibration.
A distance that changes faster than a blindfolded person walks (1.2 m/s plus 0.3 m slack) is held as suspect until the next one agrees.

**From distances to a position.**
With beacon positions $\mathbf{q}_k$, the user's position is a nonlinear least-squares fit (Levenberg-Marquardt, SciPy):

$$\hat{\mathbf{p}} = \arg\min_{\mathbf{p}} \sum_k \bigl(\lVert \mathbf{p} - \mathbf{q}_k \rVert - d_k\bigr)^2 + \lambda^2 \,(p_z - z_0)^2, \qquad \lambda = \frac{0.05}{\sigma_z}$$

The beacons sit at the same height, so three spheres meet in two mirror-image points; a light height prior ($z_0 = 1.25$ m, $\sigma_z = 0.25$ m, a phone held at chest height) picks the right one, then a second pass without the prior lets the distances alone decide.
A fix is rejected if its RMS residual is above 25 cm, and a fix that implies moving faster than

$$\lVert \mathbf{p}_t - \mathbf{p}_{t-1} \rVert \le 0.10 + 1.5\,\Delta t \ \text{m}$$

is thrown away (after three rejections in a row we accept the next fix, so tracking recovers from a real jump).
The published position is the median of the last three fixes.
If one beacon is blocked by a body, the remaining two keep the position going for up to 8 s on the same side of the line between them (two circles at chest height), flagged as "degraded".
At five or more beacons, the solver also tries dropping each distance in turn to catch a single echo.

**Setup without a tape measure.**
Instead of measuring the beacons, the user can stand on four taped floor marks $\mathbf{p}_j$; every chirp then obeys $t = a + b\,n + \lVert \mathbf{p}_j - \mathbf{q} \rVert / c$, and one robust least-squares fit over the walk recovers each beacon's position $\mathbf{q}$ and its schedule $(a, b)$ together.
In simulation with real-phone timing jitter (0.15 ms per chirp), beacons come out within about 5 to 15 cm.

### 2. Which way are they facing? AirPods head tracking

The Mac app reads AirPods head orientation through `CMHeadphoneMotionManager` (about 54 updates per second on AirPods Pro).
The item's position relative to the user is

$$\mathbf{r} = \mathbf{x}_{\text{item}} - \mathbf{x}_{\text{user}}$$

and the signed angle between where they face and where the item is, with head yaw $\psi$, is

$$e = \operatorname{wrap}_{[-180^\circ,\,180^\circ)}\!\bigl(\operatorname{atan2}(r_x, r_y) - \psi\bigr)$$

### 3. Making the sound come from the item: spatial audio

The ping is a 70 ms 1 kHz blip with 2nd and 3rd harmonics, short enough that Bluetooth latency does not smear it.
It is rendered through `AVAudioEnvironmentNode` with HRTF-HQ, and the listener is rotated by the head yaw and pitch every frame, so the sound stays fixed in the room.
Earmark's frame is $(x, y, z)$ = right, forward, up; AVAudio's is right, up, back, so a point maps to $(x, z, -y)$.

The guidance rules are pure, tested code that runs at 50 Hz:

- **Ping rate follows your aim.** With $s(u) = 3u^2 - 2u^3$ (smoothstep),

$$\Delta t_{\text{ping}} = \Bigl[\,0.15 + 0.75\, s\!\Bigl(\operatorname{clamp}\bigl(\tfrac{|e| - 10^\circ}{80^\circ}\bigr)\Bigr)\Bigr] \cdot \Bigl[\,0.4 + 0.6 \min\bigl(1, \tfrac{d}{3\,\text{m}}\bigr)\Bigr] \ \text{s}$$

  so it is 900 ms apart when the item is off to the side, 150 ms when you face it, and faster still as you close in.
- **Loudness follows distance,** from full at 0.5 m down to 25% at 4 m and beyond:

$$g(d) = 1 - 0.75\,\operatorname{clamp}\!\Bigl(\frac{d - 0.5}{3.5}\Bigr)$$

- **Lock.** When $|e| < 8^\circ$ for more than 300 ms, a two-note rising chime (E6 then A6) plays; it unlocks above $12^\circ$ (hysteresis, so it never flickers).
- **Behind you.** Past $100^\circ$ the ping is replaced by a low, muffled thud and "It's behind you. Turn left" (or right, whichever turn is shorter), because front and back are the hardest directions to tell apart by ear.
- **Arrival.** Within 0.5 m horizontally the ping stops, the arrival tone plays, and the concierge speaks where to reach, with a clock-face direction and height.

Clock-face directions are computed, not generated: the hour is $h = \operatorname{round}(e / 30^\circ) \bmod 12$ (with 0 read as twelve), and distance becomes "within easy reach", "about an arm's length", "about a step", or "about $n$ steps" (0.75 m per step).
If head tracking is lost, the app falls back to spatial audio without head tracking, then exaggerated stereo panning with spoken directions, then speech only.

### 4. Which item is it? Tags, readers, and memory

- **Tagged spots.** Items sit on spots with NFC readers underneath (ESP32 boards with PN532 or RC522 readers, firmware in the repo, plus ESP-NOW satellites for room-scale setups). The hub debounces the reads into `placed`, `removed`, and `pickup` events, so it knows *which* bottle was lifted. This is what makes "That's the vitamins" possible.
- **Fobs.** Bluetooth key-finder fobs cover things that roam, like keys; "make my keys beep" rings the fob.
- **Spoken places.** "I put my keys in the drawer" matches a saved place ("the counter", "the drawer", "the bag") and stores a `stored` event; "I'm leaving my glasses here" saves the user's current position from the beacons, and creates the item if Earmark has never heard of it.
- **Offline first.** The local loop (readers, hub, concierge, Mac app, AirPods) runs without internet except for speech, and speech degrades to cached phrases, then the system voice. The hub queues every event on disk and flushes it to Convex when the connection returns.

### 5. The conversation

1. The Mac app streams microphone audio over the bus to the concierge, which streams it to **Cartesia Ink**; Ink's turn detection ends the utterance.
2. **Claude** picks exactly one of nine tools (`locate_object`, `guide_to_object`, `put_in_place`, `place_history`, `last_seen`, `label_object`, `chirp_fob`, `list_objects`, `stop_guidance`), raced against a keyword grammar with a 1.5 s timeout.
3. **Moss** resolves the user's words ("my blood pressure medicine") to a registry object (the heart pills).
4. Deterministic code reads that object's state, computes the direction and distance, writes the sentence, and starts guidance.
5. **Cartesia Sonic** streams the reply back, and the Mac app plays it centered while ducking the ping.

## How we used each sponsor

### Anthropic: Claude

Claude does the reasoning in three places, each with a narrow, verifiable job.

- **Understanding the user (concierge, `claude-haiku-5-5`).** Every spoken request becomes one tool call. The call forces exactly one tool, turns thinking off and uses low effort for speed, and the object id is constrained to an `enum` of real registry ids, so Claude can only pick something that exists. Its answer is validated before anything runs, and it races a keyword grammar under a 1.5 s timeout, so a slow or failed call never leaves the user waiting. Claude also follows context: "where did I put *it* before?" resolves "it" to the last item.
- **Answering the family (memory agent, `claude-sonnet-5-5`).** A multi-step tool loop over five tools (`find_object`, `list_objects`, `history`, `adherence`, `daily_summary`), each a read-only call to Convex. Sonnet reasons across them, for example finding the keys, then their history, then phrasing when and where they were last noted in the household's time zone. It is instructed never to give medical advice and never to claim more than the records show; a deterministic keyword router answers if the model is unavailable.
- **Naming a new item from a photo (Convex action, `claude-haiku-5-5`).** A family member snaps a photo on the dashboard; a Convex action sends it to Claude as an image with a JSON-schema output format, gets a suggested name and aliases, and deletes the photo on every path. It has an 8 s timeout and a rate limit, and a cron deletes any upload that was abandoned.

Convex is the memory; Claude does the thinking.

### Cartesia: the voice

Voice is the only interface, so Cartesia is the product's front door.

- **Ink (speech to text):** microphone audio streams as raw 16 kHz PCM over Ink's turns WebSocket (`ink-2`), and Ink's turn detection decides when the user has finished speaking. A watchdog switches to on-device Apple speech recognition if Ink goes silent.
- **Sonic (text to speech):** every reply streams from `sonic-3.6-2026-08-27` as raw 48 kHz float PCM, played the moment the first chunk arrives. The model is pinned so cached phrases sound identical to live speech, and common phrases ("One moment", "It's behind you. Turn left.") are pre-synthesized for when the network is down.
- **The demo film** is narrated with Sonic too, with word-level timestamps driving every caption and animation beat.

### Moss: understanding what you mean

People do not say the exact name.
Moss keeps an in-process session index with one document per object (name, aliases, notes, description) and is rebuilt by diff whenever the registry changes.
A query like "my blood pressure medicine" returns ranked hits, and the heart pills win.
If Moss is unavailable, the resolver falls back to exact name and alias matching, then fuzzy string matching, and retries Moss in the background at most once a minute.

### Convex: the memory layer

Convex holds everything Earmark remembers, and everything the family sees updates live.

- **Schema with indexes** for objects, spots, saved places, readers, events, object state, medications, doses, trials, unknown tags, and daily summaries (`convex/schema.ts`), including compound indexes such as `by_objectId_and_kind_and_t` for history queries.
- **HTTP actions** are the hub's door in: `POST /ingest` takes batches of events and state, idempotent by event id, so the hub's offline queue can retry safely. Read-only `GET /api/*` routes serve the memory agent. Every route checks a shared secret in constant time.
- **Realtime queries:** the dashboard's live map, items, timeline, medications, and trials pages all use `useQuery`, so "I put my keys in the drawer" appears on the family's screen about as fast as it is said (we measured a live-map update 15 ms after an ingest on the local backend).
- **Crons:** dose status is recomputed every minute (pending becomes missed only by the clock), daily summaries build every hour for the previous household-local day, and abandoned photo uploads are deleted every five minutes.
- **File storage and actions** power photo naming with Claude.
- **Medication adherence** is computed per scheduled dose $S$ with window $W$, from pickups of the pill bottle at time $p$: taken if $|p - S| \le W$, late if $W < p - S \le 2W$, missed if neither and now $> S + 2W$, otherwise pending.

### Fetch.ai: the family question agent

The memory agent is a uAgent that speaks the Agent Chat Protocol (0.3.0, manifest published) over an Agentverse mailbox, so a caregiver can ask it from ASI:One: "Did Mom take her evening pills?", "Where did Dad put his keys before?", "What hasn't been touched in a week?".
It reads Convex through the read-only HTTP routes and reasons with Claude Sonnet, as above.
Answers always say when something was recorded, in the household's time zone, and never go beyond the records.

## Challenges we ran into

- **Phones have no shared clock.** Our first idea needed every phone's clock to agree, and they never do. The fix was to stop asking for agreement: each beacon chirps on its own clock, and the listener learns each schedule once during a short calibration on the mat.
- **Ghosts and echoes.** Our first real calibration failed with "ragged" chirps 88 ms out of phase. Analysing the recordings showed two bugs at once: a beacon set to the wrong number, and faint opposite-sweep ghosts 32 ms after every real chirp, which the calibrator had locked onto. We added ghost suppression, earliest-peak selection, and a plain-words warning when a chirp arrives from a beacon nobody configured.
- **Mirror images.** Three beacons at one height always give two answers, one above and one below. A light height prior picks the right one without biasing the result.
- **Front and back.** Pure tones are hard to place front-to-back by ear, so the cue design (short blips, a distinct behind sound, and spoken turns) had to carry what the HRTF alone could not.
- **No Xcode on the demo Mac.** We built the Mac app as a Swift package and wrote our own signing script to bundle it as a `.app` with only the command line tools.

## Accomplishments that we're proud of

- A fully working loop from a spoken question to a head-tracked ping to "Got it, that's the heart pills", with every direction and distance computed by tested code.
- Room-scale positioning from three ordinary iPhones, with no shared clock and no network between beacons.
- Over 900 automated tests across the services (contracts, hub, concierge, ranging, Convex, memory agent, dashboard, Mac app, and end-to-end scenarios), plus a simulator for every piece of hardware so the whole system runs with none.
- Graceful degradation everywhere: no internet, no Claude, no Moss, no head tracking, a beacon blocked by a body, and Earmark still answers.
- A design that respects privacy by construction: no cameras, and every answer only claims what the system actually saw or was told.

## What we learned

- Language models are excellent at understanding people and terrible at geometry. Splitting the job, Claude for meaning and plain code for angles, made the system both flexible and trustworthy.
- The hard part of indoor audio positioning is not the math, it is echoes and clocks. Robust choices (earliest peak, speed gates, median smoothing, rejecting bad calibrations loudly) mattered more than clever solvers.
- For blind users, how something sounds *is* the interface. Ping rate, the lock chime, and the wording of a clock-face direction deserved as much care as any screen.

## What's next for Earmark

- **Testing with blind and low-vision users,** measuring time to find an item with and without Earmark (the dashboard's Trials page already records this).
- **Phone-only setup:** using the AirPods stem as push-to-talk and the phone's microphone for speech, so the Mac becomes optional.
- **Smaller beacons:** the repo already has firmware for buzzer beacons on one board, a cheaper alternative to spare phones.
- **Medication schedules with reminders,** built on the adherence data Convex already computes.
- **Family sign-in** for the dashboard, and a production deployment.

## Built with

Swift, AVAudioEngine, CoreMotion, Python, NumPy, SciPy, TypeScript, React, Vite, three.js, Convex, Claude (Anthropic API), Cartesia Ink and Sonic, Moss, Fetch.ai uAgents, Agentverse, ASI:One, ESP32, PN532, RC522, ESP-NOW, Bluetooth LE, Remotion.

## Team

Doyoon Kim, Aidan Wu, Leonardo Garcia, Aditya Harshavardhan.
