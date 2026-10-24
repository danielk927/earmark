# Sponsor tracks

What each prize is, what the judges want, what Earmark already does, and what is still ours to do.
Prize details come from the team's design doc (v7), which took them from each sponsor's Cal Hacks Slack channel.
Re-check them on Devpost before submitting. On Devpost you opt in to each track at submission (around step 3 or 4); join the Cal Hacks 13.0 Devpost first.
Longer per-sponsor notes are in `docs/sponsors/sponsor-packs/`.

## Summary

| Track | Prize | Entering | Status |
|---|---|---|---|
| Anthropic: Claude for Public Benefit | $5,000 Claude credits, 1 year of Claude Max 20x for the team, Applied AI office hours, HQ visit | Yes | Claude is wired in, tests are mocked; needs a key and a real user conversation |
| Cartesia: Best use of Cartesia | Meta glasses | Yes | Built against fake servers; needs a key and a voice |
| Moss: Best use of Moss | AirPods Pro or Max, interviews | Yes | Built with a fallback; needs a key |
| Convex: Best use of Convex | $5,000 cash | Yes | Running locally; needs `npx convex login` for a cloud deployment |
| Microsoft: Built for the Real World / Customer Impact | Surface laptops (grand); tech talk and mentorship | Yes | Docs written; needs real customer research |
| Fetch.ai: ASI:One Agent Challenge | $1,250 / $750 / $500 plus internship interviews | Optional | Agent works offline; needs Agentverse registration |
| Bitdeer, Creao, Hyphenate, finance tracks | - | No | Dropped. They do not fit without forcing it |

## Anthropic: Claude for Public Benefit

- **They judge:** a narrow named community, a real problem you have lived or heard from someone affected, a fully working product with a clear way to measure impact, and meaningful use of Claude.
- **What we do:**
  - Community: blind and low-vision people finding things at home.
  - Claude does three jobs: it turns each spoken request into a clear action (concierge, `claude-haiku-5-5`), it answers family questions from the records (memory agent, `claude-sonnet-5-5`), and it suggests a name from a photo when a family member adds an item (Convex, `claude-haiku-5-5`).
  - Code decides positions, times and directions. Claude only picks the action and phrases answers from facts the code fetched.
  - Impact measure: time to find an item, with and without Earmark. The Trials page in the dashboard records this.
- **Still to do:**
  - Put `ANTHROPIC_API_KEY` in `.env` and on the Convex deployment, then run each path once for real (all tests mock the API).
  - Talk to at least one blind or low-vision person before judging and get one quote for the pitch (`docs/project/CUSTOMER.md` never invents interviews).
  - Redeem the $50 Claude credit link in `#cohost-anthropic`.
  - The track was not on Devpost yet; organizers said it will be added.

## Cartesia: Best use of Cartesia

- **They judge (25% each):** problem and originality, use of Cartesia, execution, impact and responsibility. Teams up to 4. Voice must be core.
- **What we do:** Cartesia Ink transcribes push-to-talk speech and Sonic speaks every reply ("Top shelf, front left"). Voice is the only interface.
- **Still to do:** key `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` (credit code `CARTESIACALHACKS`), generate cached phrases with `synth-phrases`, and test on the real AirPods.

## Moss: Best use of Moss

- **They judge:** strong use of fast retrieval for agents.
- **What we do:** Moss matches vague requests to the right item ("something for my eggs" finds salt and pepper, then asks which one). If Moss is down, a local fuzzy matcher takes over.
- **Still to do:** key `MOSS_PROJECT_ID` and `MOSS_PROJECT_KEY` (redeem code `CALHACKS` on the Moss billing page), tune the match thresholds on real queries. Moss also suggests storing the memory log; ours lives in Convex today.
- A separate prize exists for best social media engagement.

## Convex: Best use of Convex

- **They judge:** best use of Convex's real-time backend.
- **What we do:** objects, places, events, medication doses and trials all live in Convex. The dashboard and live map update the moment something happens, including when the user says "I put my keys in the drawer".
- **Still to do:** run `npx convex login` and deploy to the cloud so phones and the memory agent can reach it. Attend the Convex workshop (Saturday 4:00 PM, Gate 3).

## Microsoft: Built for the Real World (grand) / Customer Impact Award

- **They judge:** customer understanding, measurable usefulness, path from prototype to production, responsible design, end-to-end function. Microsoft technology is not required (Microsoft confirmed on Slack).
- **What we do:** the story is a production-minded assistant with no cameras in the home. `docs/project/RESPONSIBLE_DESIGN.md`, `docs/project/PRODUCTION.md` and `docs/project/CUSTOMER.md` cover the rest, and the time-to-find measure comes from the Trials page.
- **Still to do:** real customer research, and a short "how this ships" slide (phone-only version, better location hardware).

## Fetch.ai: ASI:One Agent Challenge (optional)

- **They require:** the whole workflow inside ASI:One, an agent registered on Agentverse, the Agent Chat Protocol, a public GitHub repo with run instructions, the `innovationlab` and `hackathon` README badges, and a 3 to 5 minute demo video. Payment Protocol, multi-agent work and Interactive Cards earn bonus points.
- **What we do:** the memory agent (`services/memory_agent/`) answers family questions such as "When did Mom last go to her pill box?" and "Where did Dad put his keys before?". Answers say when something was recorded and never claim more than the records show.
- **Still to do:** a seed phrase (`MEMORY_AGENT_SEED`), a browser login to Agentverse and ASI:One for the mailbox step, make the repo public, add the badges, record the video.

## Not entering

Bitdeer (low prize value; the project now uses Claude instead), Creao (needs a Creao agent to do the core work), Hyphenate and the other finance tracks, and all other sponsors.

## Submission checklist

- [ ] Join the Cal Hacks 13.0 Devpost.
- [ ] Opt in to Anthropic, Cartesia, Moss, Convex, Microsoft (and Fetch.ai if the agent is registered).
- [ ] Keys in `.env`: Anthropic, Cartesia, Moss, Fetch.ai seed.
- [ ] Convex cloud deployment.
- [ ] AirPods spatial test run (see `docs/project/STATUS.md`).
- [ ] One conversation with a blind or low-vision person, plus a quote.
- [ ] Demo video (Fetch.ai needs 3 to 5 minutes).
