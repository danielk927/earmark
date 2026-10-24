# Earmark

Earmark helps blind and low-vision people find everyday objects by sound.
Ask "Where's the sugar?" and a ping plays through AirPods from the sugar's direction, staying fixed in the room as you turn your head.
Say "I put my keys in the drawer" and Earmark remembers; later it tells you where the keys are, when it noted that, and where they were before.
There are no cameras in the home.

Built for Cal Hacks 13.0. Sponsor tracks and what we do for each: `docs/sponsors/TRACKS.md`. Current state and open items: `docs/project/STATUS.md`.

## What's in here

| Folder | What it is |
|---|---|
| `services/hub` | Turns raw tag and fob reads into object state; local message bus; syncs to Convex |
| `services/concierge` | Voice: Cartesia speech, Claude picks the action, Moss finds the item |
| `services/memory_agent` | Fetch.ai agent that answers family questions from the records (Claude) |
| `convex/` | Real-time backend: items, places, events, medication doses, trials |
| `dashboard/` | Family web app: live map, items, timeline, medications, trials |
| `mac/` | Mac app: head-tracked spatial audio through AirPods |
| `services/ranging` | Works out the user's position from chirps between phones (the phone-beacon plan) |
| `locator/` | Tracks where the user is standing using sound beacons: beacon firmware, an iPhone mic-only app, and Python reference tools (from Aidan's repo) |
| `firmware/` | ESP32 firmware for NFC readers, an ESP-NOW gateway and Bluetooth anchors (from Aidan's repo) |
| `contracts/` | The message and data formats every part shares |
| `scenarios/` | Replayable test scenarios (including `put_in_place`) |
| `docs/project/` | Status, next steps, architecture, demo script, privacy, production plan |
| `docs/sponsors/` | Sponsor prizes (`TRACKS.md`) and research notes for each sponsor |

## Run it

Copy `.env.example` to `.env` and fill in the keys you have (everything falls back to offline behavior without them).

```
make test        # every test suite
make demo-sim    # the demo with no hardware (see docs/project/DEMO_SCRIPT.md)
```

Needs `uv` (Python 3.12), Node, and for the Mac app the Swift command line tools. More in each folder's README.
