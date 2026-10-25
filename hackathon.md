# Hackathon log

- **Project:** Earmark
- **Event:** Cal Hacks 13.0
- **What it does:** Helps blind and low-vision people find everyday objects by sound, with a ping through AirPods that comes from the item's direction.
- **Live app:** not deployed
- **Repo:** https://github.com/danielk927/earmark (private)
- **Frontend:** not deployed
- **Convex deployment:** https://diligent-ptarmigan-12.convex.cloud
- **Components:** none
- **Convex features:** schema, indexes, queries, mutations, actions, HTTP actions, crons, file storage, realtime useQuery
- **Auth:** none
- **AI models:** claude-haiku-5-5, claude-sonnet-5-5
- **Started:** 2026-10-24T10:21:19Z
- **Last updated:** 2026-10-25T10:47:47Z

## How we use Convex

- **Family live map and items:** the `dashboard.liveMap` query feeds the map, items and header through `useQuery` (`convex/dashboard.ts`, `dashboard/src/pages/LiveMapPage.tsx`).
- **Timeline of pickups and spoken placements** ("I put my keys in the drawer"): the hub posts events to the `/ingest` HTTP action, which writes the indexed `events` and `objectState` tables (`convex/http.ts`, `convex/ingest.ts`, `convex/schema.ts`).
- **Medication tracking:** a cron recomputes dose status every minute and another builds daily summaries every hour (`convex/crons.ts`, `convex/doses.ts`, `convex/summaries.ts`).
- **Family questions agent:** a Fetch.ai agent reads history, adherence and summaries over read-only HTTP actions, and Claude reasons over them (`convex/http.ts`, `services/memory_agent/earmark_memory/convex.py`).
- **Naming an item from a photo:** file storage upload URL, then an action asks Claude for a name and deletes the photo, and a cron removes abandoned uploads (`convex/labeling.ts`).

Screens that update live without a refresh: Live map, Items, Timeline, Medications and Trials.

## Log

- 2026-10-24 `4fadf08` Build brief (`BUILD_BRIEF.md`)
- 2026-10-24 `0798b8f` Convex function contract (`contracts/ts/convexFunctions.ts`)
- 2026-10-24 `cfbd574` Convex AI guidelines and skills (`convex/_generated/ai/`)
- 2026-10-24 `22d6321` Hub with offline queue syncing to Convex (`services/hub/earmark_hub/`)
- 2026-10-24 `83a6b8c` Convex schema, HTTP actions, adherence, summaries, photo labeling (`convex/`)
- 2026-10-24 `18550a2` Convex HTTP route tests with contract validation (`convex/http.test.ts`)
- 2026-10-24 `7ce4497` Memory agent tools and Chat Protocol (`services/memory_agent/`)
- 2026-10-24 `1c12309` Family dashboard pages and data layer (`dashboard/src/`)
- 2026-10-24 `e96ff67` Screenshots of every page against a real Convex (`dashboard/e2e/live.mjs`)
- 2026-10-24 `62a9874` Claude for voice, family questions and photo naming (`convex/lib/claude.ts`, `services/memory_agent/earmark_memory/llm.py`)
- 2026-10-24 `f4f638c` Remember where items are put (`services/concierge/earmark_concierge/policy.py`)
- 2026-10-24 `78f2b56` Beacon locator and firmware (`locator/`, `firmware/`)
- 2026-10-24 `c56e946` Phone position service (`services/ranging/`)
- 2026-10-25 `f8e4d2d` Live room page (`dashboard/src/room/`)
- 2026-10-25 `10e3e3c` Convex fixes: clean reset, no false missed doses, photo rate limit (`convex/labeling.ts`)
- 2026-10-25 `7e9e467` Hub stops forged pickups and survives bad Convex replies (`services/hub/earmark_hub/hub.py`)
- 2026-10-25 `f80cad7` Family dashboard redesign (`dashboard/src/`)
- 2026-10-25 `e8c8bf3` Keep position when one beacon drops out (`services/ranging/earmark_ranging/listen.py`)
