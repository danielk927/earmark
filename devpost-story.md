## Inspiration

We spent all four years of high school working and volunteering with people who are blind. What surprised us most were the small challenges that never stop: a set of keys put down in the wrong place, a remote that slid between the cushions, and above all, medication.

Pill bottles all feel the same. A bottle of heart pills and a bottle of vitamins have the same shape, the same weight and the same rattle. The usual fixes are rubber bands, Braille labels, a fixed spot on the counter, or asking someone else, and every one of them breaks the moment something gets moved. Picking up the wrong bottle is a safety problem.

So we asked: what if you could just hear where something is?

## What it does

Earmark is a voice assistant that guides you to your things with spatial audio.

Ask in your own words, like "where are my heart pills?" or "where's my blood pressure medicine?", and Earmark answers with a direction: "The heart pills are at your three o'clock, about four steps away." A ping plays in your AirPods from the item's real position. When you turn your head, the sound stays where the item is, so you simply turn toward it. The ping speeds up as you face the item and as you walk closer, and a chime tells you when you're locked on. Within half a meter it says where to reach: "You're here. The heart pills are down low, at your one o'clock."

It remembers too. Say "I put my keys in the drawer" and Earmark saves it. Later, "where are my keys?" gets the place and when it was noted. Items sit on tagged spots with readers underneath, so Earmark knows which bottle was lifted. Lift the wrong one and it says "That's the vitamins" and points you to the right one. For medication, it only says what it saw, like "The heart pills were last picked up at 8:14 this morning." It never claims a pill was swallowed and never gives medical advice.

Family members get a live dashboard with a map, a timeline of every pickup and placement, and medication history. They can also ask an AI agent, "Where did Dad leave his keys?", and get an answer from the records.

There are no cameras in the home. Position comes from sound and identity comes from tags, so Earmark can find things inside a drawer or behind you, and it never confuses two bottles that look the same.

## How we built it

Earmark runs on a few small programs that talk to each other, plus a cloud backend. Our own code decides every position, angle and distance, and the AI picks an action and phrases the answer. Guidance that is wrong by thirty degrees is worse than none, so we leave none of it to a language model.

Finding where you stand. Three ordinary phones around the room act as beacons. Each one plays a short chirp every half second on its own schedule, and your phone listens and times when each chirp arrives. Because sound is slow, those arrival times turn into distances, and three distances give your position. You calibrate once by standing on a mat for a few seconds, which teaches the system each beacon's schedule. The beacons need no network between them.

Knowing which way you face. A Mac app reads head tracking from your AirPods and rotates the 3D sound so it stays fixed in the room as you turn. The ping is a short blip that stays clear over Bluetooth, and the rules for its speed, loudness, the lock chime and the "behind you" sound all run as plain tested code.

Talking to it. Your speech streams to **Cartesia**, which hears you and speaks every reply. **Claude** picks one action from a fixed list of nine, like "guide me to the keys" or "remember this spot", and a keyword matcher runs alongside it as a backup, so a slow answer never leaves you waiting. **Moss** finds the right item when you don't use its exact name, so "my blood pressure medicine" finds the heart pills. Our code then writes the directions, such as the clock position and the steps.

Remembering. The tagged spots tell Earmark which bottle was lifted. **Convex** stores everything Earmark remembers, and the family dashboard updates live the moment something happens. **Claude** also answers family questions from those records, and suggests a name for a new item from a photo. A memory agent on **Fetch.ai**'s Agentverse lets a caregiver ask about the home from **ASI:One**.

If the internet drops, the local loop of readers, hub, voice and AirPods keeps running, and the system queues what happened and sends it to **Convex** when the connection returns.

## Challenges we ran into

Phones don't share a clock, and our first idea needed every phone's clock to agree. Now each phone plays its sound on its own schedule, and the listener learns each schedule once in a short calibration.

Our first real test failed. The recordings showed one phone on the wrong number, and faint echoes just after each real chirp that the system had locked onto. We taught it to take the earliest strong sound, ignore the faint ghost, and warn you by name when a phone is set up wrong.

Three beacons at the same height give two possible answers, one above the floor and one below. A rough guess that you hold the phone at chest height picks the right one.

Front and back are the hardest directions to tell apart by ear, so we added a distinct sound for "behind you" and spoken turns like "Turn left".

The demo Mac had no Xcode, so we built the Mac app as a Swift package and wrote our own script to bundle and sign it.

## Accomplishments that we're proud of

We built a full loop from a spoken question to a head-tracked ping to "Got it, that's the heart pills", with every direction and distance worked out by tested code. Three ordinary phones are enough for room-scale positioning.

We wrote more than 900 automated tests across the whole system, and a simulator for every piece of hardware, so everything runs even with none of it plugged in. It keeps working when something goes wrong: no internet, no head tracking, no **Claude**, or a phone blocked by a body.

It also respects privacy by design. There are no cameras, and every answer says only what the system saw or was told.

## What we learned

Language models are great at understanding people and unreliable at geometry. Letting **Claude** handle meaning and plain code handle angles made the system flexible and trustworthy.

The hard part of indoor audio positioning was the echoes and clocks. Choices like taking the earliest sound, ignoring jumps that are too fast for a person, and rejecting a bad calibration loudly mattered more than a clever solver.

For blind users, how something sounds is the interface, so the ping, the chime and the wording of a direction deserved as much care as any screen.

## What's next for Earmark

We want to test with blind and low-vision users and measure how much faster they find things with Earmark. The dashboard already records this.

After that, we'd like cheaper beacons (we already have firmware for a small buzzer beacon on one board), medication reminders built on the history we already keep, sign-in for the family dashboard, and a real deployment.

## Built with

Swift, AVAudioEngine, CoreMotion, Python, NumPy, SciPy, TypeScript, React, Vite, three.js, Convex, Claude (Anthropic API), Cartesia Ink and Sonic, Moss, Fetch.ai uAgents, Agentverse, ASI:One, ESP32, PN532, RC522, ESP-NOW, Bluetooth LE, Remotion.

## Team

Doyoon Kim, Aidan Wu, Leonardo Garcia, Aditya Harshavardhan.
