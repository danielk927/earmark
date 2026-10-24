# Cartesia sponsor pack (Cal Hacks 13.0)

Summary of Cartesia's official Cal Hacks 13.0 starter pack, fetched 2026-10-24.
Primary source: https://docs.cartesia.ai/calhacks (raw Markdown at https://docs.cartesia.ai/calhacks.md).
Prize listing cross-checked on Devpost: https://cal-hacks-13-0.devpost.com/
Technical integration details are in `docs/vendor-notes/cartesia.md`.

## Prize

- Cartesia's page says the winning team (up to 4 people) gets Meta glasses.
- Devpost lists it as "[Cartesia] Best Use of Cartesia", 1 winner, value shown as $1,516, with the note "Meta glasses (still TBD)".
- Cartesia favors "a strong working prototype over a large unfinished idea."
- Voice must be core to the product, not a feature added for the demo.
- Other tools are allowed, but the submission must make clear what Cartesia contributes.

## Judging criteria (each 25%)

| Criterion | What judges look for |
| - | - |
| Problem and originality | Useful, clearly scoped, and thoughtfully designed |
| Use of Cartesia | Meaningfully integrated into the core experience, with clear, responsive, natural voice |
| Execution | The main flow works and likely edge cases are handled |
| Impact and responsibility | Accessibility, privacy, and responsible use are considered |

Note that these differ from the general Cal Hacks criteria in BUILD_BRIEF.md section 1 (real-world application, functionality, creativity, technical complexity).

## What to submit

- A working demo.
- A two-minute, demo-first presentation: one complete user flow first, then the problem and how it was built.
- A short README with setup steps, the Cartesia features used, and known limitations.
- Source code access for judges, per event rules.
- No API keys or other secrets committed.

## Credits and how to claim

- The Cal Hacks page does not mention hackathon credits, promo codes, or any claim process.
- UNVERIFIED: whether Cartesia is handing out credits at the event; ask Cartesia staff on site or email support@cartesia.ai.
- Default allowances from https://cartesia.ai/pricing: Free plan $0 with 20K credits/month; Pro $5/month with 100K credits/month.
- Cost reference from https://docs.cartesia.ai/pricing: TTS is about 1 credit per character; `ink-2` realtime STT is 3 credits per second of audio, silence included.
- At 3 credits/s, always-on Ink 2 streaming uses about 10,800 credits per hour, so the Free plan covers under 2 hours of STT in total.
- Prize claim: no procedure is documented beyond submitting the project; UNVERIFIED that selecting the Cartesia prize on Devpost is the only step.

## Setup steps from the page

1. Create an account in the Playground: https://play.cartesia.ai/
2. Create an API key at https://play.cartesia.ai/keys and export it as `CARTESIA_API_KEY`.
3. Never put the key in browser or mobile code; frontends should get a short-lived access token from a server (https://docs.cartesia.ai/get-started/authenticate-your-client-applications).
4. Optionally point the coding agent at https://docs.cartesia.ai/llms.txt and the integration rules below.

## Integration rules Cartesia gives coding agents (condensed)

- Fetch https://docs.cartesia.ai/llms.txt before guessing endpoints, fields, or voice IDs.
- Send `Cartesia-Version` on every request; default `2026-08-14`.
- Base URL `https://api.cartesia.ai` (WebSockets `wss://`), HTTPS only.
- Server auth: `Authorization: Bearer <api_key>`.
- On WebSockets the `?cartesia_version=` query parameter wins over the header when both are set.
- Prefer the official SDKs (https://github.com/cartesia-ai/cartesia-python, https://github.com/cartesia-ai/cartesia-js).
- Use `generation_config` for speed, volume, and emotion, not deprecated top-level fields.
- Expect structured JSON errors for `Cartesia-Version` 2026-03-01 and newer.
- Managed Agents is a separate product from the raw TTS/STT APIs.

## Suggested routes on the page

- "Build a voice agent" with Managed Agents (https://docs.cartesia.ai/agents/introduction), no code to start.
- "Add speech to your app" with Sonic 3.6 (`sonic-3.6`) via the TTS API.
- Build with Managed Agents, not the Line SDK; Cartesia stops hosting Line SDK agents on December 1, 2026.
- The page says "you can use any part of Cartesia in your own way," so Earmark's own pipeline (Ink 2 STT plus Sonic TTS) is within the rules.
- The page itself does not mention Ink STT; the Ink docs are at https://docs.cartesia.ai/build-with-cartesia/stt/latest

## Project ideas listed (for context)

Commute stand-up, ambient assistant on a wearable or speaker, keep-your-voice accessibility, live coach or translator, multi-speaker agent.

## How Earmark maps to the criteria

- Problem and originality: finding household objects by sound for blind and low-vision users, scoped to a home with tracked spots.
- Use of Cartesia: Ink 2 turn detection decides when the user finished asking, and Sonic speaks every directional answer and pickup confirmation; the README must spell this out.
- Execution: the salt and sugar hero flow, plus fallbacks (cached Sonic phrases, then macOS `say`, Apple Speech for STT).
- Impact and responsibility: no cameras, no medical advice, accessible dashboard, and a stated privacy story for mic audio sent to Cartesia.

## Support

support@cartesia.ai
