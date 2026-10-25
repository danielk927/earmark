# Earmark: responsible design

Earmark is used by people who cannot check its answers by looking, and some of those answers concern medication.
A wrong answer said confidently is the worst thing it can do, so most of the design below exists to make Earmark either right or clearly uncertain.
Each section says what is built today (2026-10-24) and what is still a plan.
The last sections map these choices to Microsoft's Responsible AI principles and the Guidelines for Human-AI Interaction (HAX).

## 1. Summary

| Design choice | Built today | Microsoft principle |
|---|---|---|
| No cameras in the home | Yes: detection is NFC tags and Bluetooth fobs; the camera adapter is an empty interface | Privacy and security |
| Labeling photos deleted right after use; only text kept | Yes, in Convex, tested with a mocked model | Privacy and security |
| Store only item names, spots, and timestamps | Yes | Privacy and security |
| UWB walking guidance keeps only the person's current position, never a trail | Yes: one overwritten row, at most 2 updates a second, never written to events | Privacy and security |
| Caregiver access controls | Partly: shared secrets on HTTP routes; dashboard functions have no auth yet | Privacy and security, accountability |
| No medical advice | Yes, in the concierge; planned in the memory agent | Reliability and safety |
| Identity from tags, never from appearance; ask when unsure | Yes | Reliability and safety, transparency |
| The language model chooses a tool and never writes what is said aloud | Yes, in the concierge | Reliability and safety, transparency |
| Every external service has a timeout and a fallback | Yes (hub, concierge); Mac app ladder in progress | Reliability and safety |
| Trial data is never fabricated or edited | Yes, enforced in code and tests | Accountability, transparency |
| Works by voice alone; accessible dashboard | Voice loop yes; dashboard in progress | Inclusiveness, fairness |

## 2. No cameras in the home

- Earmark knows where things are from NFC stickers read by readers under fixed home spots, and from Bluetooth signal strength of key fobs.
  No camera, microphone recording, or image of the home is part of detection.
- `camera_stub` in the hub is an interface with a docstring only (`services/hub/README.md`).
  If a camera adapter is ever added, it must be opt-in, run on-device, and send only object positions, never images.
- The cost of this choice: Earmark only knows tagged items, and an item away from every spot is known only by its last sighting.
  We accept that, and Earmark says so out loud (section 6).
- UWB walking guidance adds no camera either.
  The UWB anchors are phones used as radios: each one only measures its distance to the wearer's phone.
  They are not sensors of the room, and they never record who or what else is there.

## 3. One-time caregiver photos

A family member can photograph an item once to get a suggested name and description.
Built in `convex/labeling.ts` (`convex/README.md`, "Photo-assisted labeling"):

1. The dashboard uploads the photo to Convex file storage through a one-time upload URL.
2. The `labeling:suggestFromPhoto` action sends it inline (base64) to Claude, so the photo never needs a public URL.
3. The photo is deleted in a `finally` block on success and on every failure, including a missing API key and a timeout.
4. The action returns `{ name, aliases, description, model, latencyMs, photoDeleted: true }` and saves nothing.
   The family member confirms or edits the text before it is saved as a label.
5. A cron deletes any stored file older than 10 minutes, so an upload that is never sent for a suggestion does not persist.

Tested: `convex/labeling.test.ts` checks photo deletion on every path, the timeout, and the sweeper, with a mocked model.
Not yet tested: the live Claude model (no key yet).
Planned: the dashboard states, before upload, that the photo is deleted after the suggestion (HAX G16).
Residual exposure: the photo is processed by Anthropic, whose retention terms we have not reviewed yet (`docs/project/PRODUCTION.md` 6.1).

## 4. Data minimization

What Earmark stores: item names, aliases, family-written notes and descriptions, NFC tag IDs, home spot numbers, which saved place (drawer, bag, box) the user said an item is in, and timestamps of placements, removals, pickups, labels, chirps, and those spoken placements.
What it does not store: images, audio, video, the person's location or a history of where they have been, or any health data beyond the medication item's schedule and its pickup times.
No camera is used for detection, so no images of the home are stored; the one caregiver photo is deleted after labeling (section 3). The wearer's pose (from UWB or the beacon locator) is transient: the hub keeps only the latest one, to draw the live map, and overwrites it in place; it is never stored as history. Object positions the user marks are stored, because that is the point of the product.
Family members choose item names, so a medication can be called "evening pills" instead of a drug name.

Two gaps we know about:
- The concierge writes each final transcript, with timings, to `logs/latency.jsonl` on the hub machine for the latency report.
  It is never sent to Convex; production keeps timings only (`docs/project/PRODUCTION.md` 6.1).
- The concierge sends the transcript plus item names, aliases, notes, and saved place names to Claude to choose a tool.

The full storage and retention table is in `docs/project/PRODUCTION.md` 6.1.

### 4.1 The wearer's position (UWB walking guidance)

When walking guidance is on, the dashboard's Live map shows where the person is right now.
That is the only place the position is kept, and it is transient by construction:
- Convex holds one `wearerPose` row. Each update overwrites it in place, and only if it is newer. The hub sends at most 2 updates a second.
- The pose is never written to `events`, and no pose history, trail, or heat map exists in any table, log, or export.
  A reset clears the row.
- The `anchors` table holds each anchor's fixed position (set by us when we set up the space) and whether it is online.
  Anchors are radios, not sensors of the room: a distance reading to the wearer's phone is all they produce.
- Position is shown to caregivers only as the current dot and its mode in words (for example "At the counter" or "Location lost").
  Changes in position are not announced to screen readers, so a caregiver is not flooded; an anchor going offline is.

## 5. Caregiver access controls

- **Today:** HTTP routes use two shared secrets: `EARMARK_HUB_SECRET` for the hub and `EARMARK_READ_SECRET` for read-only agents, compared in constant time and never logged.
  The dashboard's Convex client functions have no authentication yet, so anyone with the deployment URL can call them (`convex/README.md`, "Not done / open").
  That is acceptable only with the synthetic demo household.
- **Production:** each person signs in through Convex auth with an OpenID Connect provider such as Clerk; every row carries a `householdId`; every function checks membership and role.
  The primary user owns the data, caregiver visibility requires the user's consent, and the user can withdraw it.
  Roles and the permission matrix are in `docs/project/PRODUCTION.md` 5.2.
- **Proposal:** an access log the primary user can hear ("Your daughter checked the medication log today at 9:02 AM"), so caregiver access is never invisible to the person it concerns.

## 6. No medical advice

- Rule 8 of `BUILD_BRIEF.md`: agents report what the events show and nothing more.
- Adherence status (taken, late, missed, pending) is computed by deterministic, unit-tested Convex code from pickups and the schedule window (`contracts/README.md`, "Medication adherence").
  No language model decides whether a dose was taken.
- The concierge's medication answers report pickups and the bottle's current spot only.
  If the wording asks for advice, it adds: "I can't give medical advice, but I can tell you what the sensors saw." (`services/concierge/earmark_concierge/policy.py`)
- The tool-choice prompt says "never give medical advice; medication questions use last_seen", and the model is told "Never reply with text", so it cannot add advice to an answer.
- Wording is evidence, not inference: "picked up at 8:04 PM", never "took her pills".
  Lifting a bottle is not proof a pill was swallowed, and a pill taken from an organizer shows as missed.
- The memory agent (in progress) does write answers with a language model.
  Its requirements: answer only from Convex read endpoints, include the data's timestamps, and never give advice (`BUILD_BRIEF.md` 5.G).

## 7. Honest uncertainty

Earmark never guesses which of two identical containers is which.
Identity comes from the tag on the item, read by the reader under its spot, never from what the item looks like.

| Situation | What Earmark says or does | Where |
|---|---|---|
| Item exactly located on a spot | Clock direction, distance band, and a spatial ping | `policy.py`, `phrasing.py` |
| Request matches more than one item | "Do you mean the salt or the pepper?"; extra evidence can widen one answer into a question, never narrow a question into a guess | concierge, "Decisions" |
| Item near a receiver but not on a spot | "It's near the counter" and the fob chirps; no ping, because a receiver's position is not the item's | concierge, "Decisions" |
| Item not seen for a while, or off every spot | "I last saw it on the far-left spot at 8:12." | `BUILD_BRIEF.md` 5.D |
| Item never seen, with family notes | Reads the notes and says they are notes: "Its notes say: usually kept in the pantry." | concierge, "Decisions" |
| Unknown item or unlabeled tag | "I don't know that item yet. Put it on the setup spot and say, this is, then its name." | `config/phrases.json` |
| Pickups before the concierge started | "I haven't seen them picked up since I started at 7:03 AM." | `policy.py` |
| Speech not understood | "Sorry, I didn't catch that." | `config/phrases.json` |

The language model's only job in the voice loop is to pick one tool.
Directions, distances, times, ambiguity, and every spoken sentence are produced by code, so the system cannot invent a location.

## 8. Safe failure modes

### 8.1 When a service fails

From `docs/project/ARCHITECTURE.md` ("Failure handling") and the concierge fallback ladder:

| Failure | Behavior | What the user notices |
|---|---|---|
| Convex unreachable | Hub keeps working from `config/objects.cache.json`; events queue on disk and replay in order on reconnect | Nothing; the caregiver dashboard lags until reconnect |
| Claude slow (more than 1.5 s) or down | Keyword grammar handles where/find, stop/cancel, "this is X", "make X beep", and "I put X in the drawer" | Nothing for common requests |
| Moss unavailable | Exact name or alias match, then fuzzy match, then notes and descriptions, in code | Nothing for known names |
| Cartesia speech-to-text silent or down | Switch to on-device Apple speech recognition; Cartesia is retried every 60 s | "Switching to backup listening." |
| Cartesia speech output down | Pre-recorded phrases, then the system voice, then macOS `say` | A different voice |
| AirPods head tracking lost | Spatial audio without head tracking, then exaggerated stereo plus spoken clock directions, then speech only; the screen shows the active mode | Less precise direction, never silence |

### 8.2 When detection is wrong

| Problem | What happens | Residual risk |
|---|---|---|
| A reader flickers between tag and empty | Placement needs 2 matching reads and removal about 1.5 s of continuous absence, so flicker produces no events (`flicker` scenario) | None found in tests |
| A reader is unplugged | Silence never counts as removal, so a cable fault cannot create a false pickup; reader errors become a hub status | Items on that spot show their last state until it returns |
| User lifts the wrong look-alike | "That's the salt. The sugar is one spot to your right." Guidance keeps running | None; this is the designed case |
| Item put back on a different spot | It is reported where it now is, because the tag moved with it | None |
| Item off every spot | Last sighting with its time; no ping | User searches by touch near the last spot |
| Target behind the listener | A distinct "behind" sound plus "It's behind you. Turn left." (front-back confusion is the most common spatial-audio error) | Front-back errors are possible; measured in the spatial gate |
| Fob not heard for a while | The hub reports it lost instead of keeping its last proximity (`ble_fobs.py`); Earmark chirps the fob | Rooms with weak signal |
| A tag is moved to a different container | Earmark names the container by its new tag, confidently and wrongly | **Real risk.** Mitigations: tags on jar bottoms; relabel flow; planned "That was wrong" voice report logged against the guidance event |
| Medication taken without lifting the bottle | Shows as missed | Caregivers are told evidence is partial; wording is "picked up", never "took" |

## 9. Trial data integrity

Trial mode (`BUILD_BRIEF.md` 5.I) produces the "measurable usefulness" numbers, so its data rules are enforced in code:
- Trials are written only from `trial_start` and `trial_end` bus events; `convex/trials.ts` exposes read queries only, and no function edits a trial (`convex/README.md`, tables).
- `npm run reset` never deletes or edits trials or trial events; `seed.test.ts` checks that reset preserves trials byte for byte.
- Trials are never seeded.
  Seeded history is synthetic demo data, and every seeded event ID starts with `seed-`.
- Testers are pseudonyms; the trial CLI rejects anything that looks like a real full name (`services/hub/README.md`, "Trials").
- The dashboard shows raw counts (trials, testers, wrong picks), never only percentages.
- Blindfolded sighted teammates are not blind or low-vision users.
  Their results are reported as a pilot with the exact number of trials and testers, and never as evidence about real users.

## 10. Accessibility as a requirement

- The primary user needs no screen: every job works by voice and sound, and the Mac app design adds push-to-talk for noisy rooms.
- The caregiver dashboard must be fully usable with a screen reader and keyboard: semantic HTML, visible focus, high contrast, no information by color alone, light and dark modes, and a text list equivalent of the map (`BUILD_BRIEF.md` rule 7 and 5.F).
  Production target: an audit against WCAG 2.2 level AA (https://www.w3.org/TR/WCAG22/) before the home pilot.
- Older users often have hearing loss as well as vision loss; voice-only use by people with both is an open question in `docs/project/CUSTOMER.md` 6.
- Users without head-tracking headphones still get stereo panning and spoken clock directions, then speech only.

## 11. Mapping to Microsoft's Responsible AI principles

Principle descriptions are Microsoft's, from https://www.microsoft.com/en-us/ai/principles-and-approach (collected in `docs/sponsors/sponsor-packs/microsoft.md` 4.1).

| Principle | Microsoft | What Earmark does | Known gap |
|---|---|---|---|
| Fairness | "AI systems should treat all people fairly." | Works by voice alone, with no reading, braille, or screen required; low-cost parts (`docs/project/PRODUCTION.md` 1); no recognition of people at all | Speech recognition quality varies across accents and speech differences; untested with real users |
| Reliability and safety | "AI systems should perform reliably and safely." | Deterministic, unit-tested math and adherence rules; the model only picks a tool; identity from tags; timeouts and fallbacks on every external call; debounce; durable offline queue | Spatial gate on real AirPods not run yet; no real readers or fobs tested yet |
| Privacy and security | "AI systems should be secure and respect privacy." | No cameras; labeling photos deleted; data minimization; secrets never logged; constant-time secret comparison | Dashboard functions have no auth yet; vendor retention terms not reviewed |
| Inclusiveness | "AI systems should empower everyone and engage all people, regardless of their backgrounds." | Designed for blind and low-vision people first; caregivers and family included through labeling and evidence; fallbacks for users without AirPods | No blind or low-vision person has been involved yet (`docs/project/CUSTOMER.md`) |
| Transparency | "AI systems should be understandable." | Says when it is unsure, why ("last seen at 8:12"), and which mode is active; the latency log attributes every decision path | No first-run spoken explanation of what Earmark can and cannot do yet |
| Accountability | "People should be accountable for AI systems." | Labels change only by explicit human action; trial data is immutable; every decision is logged with its path | No incident or feedback process until the pilot (`docs/project/PRODUCTION.md` 10) |

### 11.1 Harms: identify, measure, mitigate, operate

Following Microsoft's four stages for responsible generative AI (https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/overview, summarized in `docs/sponsors/sponsor-packs/microsoft.md` 4.3):

| Harm (identify) | Measure | Mitigate | Operate |
|---|---|---|---|
| Wrong item named or confirmed | Wrong-identity confirmations in trials and the pilot; target zero | Tags, not appearance; ask when ambiguous; wrong-pick correction | Every reported error reviewed; "That was wrong" report (planned) |
| Stale location stated as current | Share of answers given from a last sighting, and how old | Say the time of the last sighting; no ping without an exact position | Pilot logs reviewed weekly |
| False reassurance about medication | Pickups compared with the user's own record in the pilot | "Picked up", never "took"; no advice; deterministic rules | Caregiver onboarding explains what evidence means |
| Overreliance | Whether users keep their own backup techniques | Earmark announces fallbacks and offline states | Partner organization's staff check in during the pilot |
| Caregiver access felt as surveillance | Ask both sides, separately, in interviews | Consent, revocable access, spoken access log (proposal) | Consent re-confirmed at the end of each pilot phase |
| Data exposure | Security review before the home pilot | Auth and household scoping, per-device credentials, deletion | Incident response and rollback plans (`docs/project/PRODUCTION.md` 10) |

### 11.2 Guidelines for Human-AI Interaction (HAX)

Guideline titles from https://www.microsoft.com/en-us/haxtoolkit/library/; the mapping is ours.

| Guideline | Earmark | Status |
|---|---|---|
| G1 Make clear what the system can do | Spoken first-run introduction: finds tagged items, never sees the room | Planned |
| G2 Make clear how well the system can do what it can do | Says when it is unsure and how old a sighting is | Built (concierge) |
| G7 Support efficient invocation | One spoken request starts guidance | Built |
| G8 Support efficient dismissal | "Stop" or "cancel" ends guidance at once | Built (keyword grammar) |
| G9 Support efficient correction | Wrong-pick correction; family relabels from the dashboard in seconds | Built (concierge, Convex); dashboard in progress |
| G10 Scope services when in doubt | Asks "salt or pepper?" instead of guessing | Built |
| G11 Make clear why the system did what it did | "I last saw it on the far-left spot at 8:12." | Built |
| G14 Update and adapt cautiously | Labels change only by explicit human action | Built |
| G15 Encourage granular feedback | "That was wrong" logged against the guidance event | Planned |
| G16 Convey the consequences of user actions | Dashboard says the photo is deleted after labeling | Planned |
| G17 Provide global controls | Caregiver access controls and data deletion | Planned (`docs/project/PRODUCTION.md` 5 and 6) |
| G18 Notify users about changes | Spoken notice when a caregiver relabels an item | Planned |
