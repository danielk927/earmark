# Convex - Cal Hacks 13.0 sponsor pack

Fetched 2026-10-24 (about 03:40 PDT, Saturday of the event).
Technical notes are in `docs/sponsors/vendor-notes/convex.md`.
The official AI code-generation guidelines are copied verbatim in `docs/sponsors/vendor-notes/convex-ai-guidelines.md`.

Sources:
- Convex home page: https://www.convex.dev
- Convex hackathon resources: https://www.convex.dev/hackathons/resources (also served as Markdown with `Accept: text/markdown`)
- Cal Hacks 13.0 hacker hub: https://hive.hackberkeley.org (data from its JSON endpoints `/api/live/prizes`, `/api/live/schedule`, `/api/live/resources`)

## Summary for the team

| Item | Value | Source |
| - | - | - |
| Prize | "Best use of Convex (Convex)": $5,000 cash to the winning team | https://hive.hackberkeley.org/prizes (`/api/live/prizes`, updated 2026-10-24T04:55Z) |
| Judging criteria | Not published anywhere I could find. The prize entry has only the line above plus Convex's tagline. | same |
| Workshop | "Convex Workshop: Build Your Backend with Convex", Saturday 10/24, 4:00-5:00 PM PDT, Gate 3 | https://hive.hackberkeley.org/schedule (`/api/live/schedule`) |
| Workshop status | Still upcoming at the time of writing. Tell the human. | - |
| Starter pack | The Cal Hacks "starter packs" page links Convex only to https://docs.convex.dev/home | https://hive.hackberkeley.org/resources |
| Credits | No fixed credit amount is published. The FAQ says Convex "sometimes" provides coupon codes, applied in Team Settings, then Billing. | https://www.convex.dev/hackathons/resources |
| Help | Convex Discord, `#hackathon` channel: https://convex.dev/community | same |
| Hacking deadline | Hacking ends 2026-10-25T16:00Z (Sunday 9:00 AM PDT) | `/api/live/schedule` event record |

Prize entry, verbatim (from `/api/live/prizes`):

> **Best use of Convex (Convex)**
> $5,000 cash to the winning team.
> The reactive backend platform that keeps up with you and your agents. Database, functions, workflow, sync, search, file storage, and more. All TypeScript, zero glue.

Workshop entry, verbatim (from `/api/live/schedule`, start `2026-10-24T23:00:00+00:00`, end `2026-10-25T00:00:00+00:00`, location Gate 3):

> Build Your Backend with Convex
>
> Join Convex for a quick intro to our reactive backend platform, followed by a live demo of how to build full-stack apps with AI coding agents. We’ll walk through how Convex fits into your stack, show you what’s possible, and leave time for Q&A so you can get back to building.

The brief calls this "a workshop on building agentic apps on Saturday at 4 pm".
The official title is "Build Your Backend with Convex", and the time matches.

Since no judging criteria are published, the safest reading of "Best use of Convex" is the brief's own plan: make Convex load-bearing and visibly reactive (live map updates the instant a jar is lifted, remote labeling taking effect in seconds, adherence and trial results computed in Convex functions, crons and scheduled functions doing real work).
That reading is my inference, not a published rubric.

## Home-page agent prompt (verbatim)

This is the text behind the "Copy the setup prompt for your agent" button.
It is in the home page HTML (inside `<div class="md-only">`, after "Set up Convex with your agent:") and is byte-identical to the copy embedded in the hackathon resources page's JavaScript.

````markdown
# Convex setup

Set up Convex in the current folder. Run the commands yourself, without asking the user.

- Empty folder: `npm create convex@latest . -- -t bare`
- Convex project (`convex` in `package.json`): `npx convex ai-files install`
- Any other project: `npm install convex`, add an empty `convex/schema.ts` and a `convex dev` script, then `npx convex ai-files install`. Never `npm create convex` here, it replaces the folder.

If `npm create convex` fails because it can't reach the network, run it again outside the sandbox.

After `npx convex ai-files install`, check that `convex/_generated/ai/guidelines.md` and `.agents/skills` exist. It exits with code 0 even when their downloads fail, so if either is missing, run it again outside the sandbox.

Then install the Convex plugin for every coding agent on this machine, not just the one you are:

- Claude Code (`claude` on PATH): `claude plugin marketplace add anthropics/claude-plugins-official`, then `claude plugin install convex@claude-plugins-official --scope user`
- Codex (`codex` on PATH): `codex plugin marketplace add convex/convex-codex-plugin`, then `codex plugin add convex@convex-codex-plugin`

Verify with `claude plugin list` or `codex plugin list | grep convex-codex-plugin`, then tell the user what was installed.
````

How it applies to Earmark:
- The repo is "any other project" (it is not empty and has no `package.json` with `convex` yet), so the path is `npm install convex`, a `convex/schema.ts`, a `convex dev` script, then `npx convex ai-files install`.
  Never run `npm create convex` in this repo.
- The plugin step installs at `--scope user`, which changes the human's global Claude Code (and Codex) configuration, not just this repo.
  The orchestrator should decide whether to run it now or leave it for the human.
- What `npx convex ai-files install` actually writes is listed in `docs/sponsors/vendor-notes/convex.md`, section 1 (observed in a scratch project).

## Hackathon resources page (contents)

Page title: "Hackathon Resources".
Headline: "All gas, no breakages."
Tagline: "The reactive backend platform that keeps up with you and your agents. Paste one prompt, start hacking."
It shows the same "Copy the setup prompt for your agent" button as the home page.

### Resources

- Components ("Agent, Workflow, Stripe, Resend…"): https://www.convex.dev/components
- Convex Auth ("Sign-in in your backend"): https://docs.convex.dev/auth/overview
- AI Gateway ("Any model, no keys, no markup"): https://docs.convex.dev/ai-gateway/overview
- Static hosting ("Front + back, one deploy"): https://www.convex.dev/components/static-hosting
- MCP ("Your app inside their agent"): https://github.com/get-convex/mcp

### Project ideas listed (each starts from a component)

- Your app, from ChatGPT (MCP): https://www.convex.dev/components/mcp
- Research agent (Agent): https://www.convex.dev/components/agent
- Agent with an inbox (AgentMail): https://www.convex.dev/components/agentmail/convex
- iMessage concierge (Photon): https://www.convex.dev/components/spectrum-ts/convex
- Chat with your docs (RAG): https://www.convex.dev/components/rag
- Multiplayer whiteboard (Presence): https://www.convex.dev/components/presence
- Live trivia night (Sharded Counter): https://www.convex.dev/components/sharded-counter
- Browser agent (Stagehand): https://www.convex.dev/components/stagehand

### FAQ (verbatim)

> **New to Convex? Here's where to start**
> Copy the setup prompt above into your coding agent (Claude Code, Codex, Cursor, or Copilot) and ask it to build a new app with Convex. Prefer doing it by hand? Pick your framework in the [Convex quickstarts](https://docs.convex.dev/quickstart/overview) or build a real-time chat app with the [tutorial](https://docs.convex.dev/tutorial/overview).

> **Where do I get help during the hackathon?**
> Join the [Convex Discord](https://convex.dev/community) and post in the #hackathon channel. Ask questions, share what you’re building, and get unstuck fast. The team and community are there to help you ship.

> **How do I apply my coupon code?**
> Sometimes we provide codes for hackathon participants. Got a code? Sign in to your [Convex dashboard](https://dashboard.convex.dev), pick the team you want to upgrade, then go to Team Settings → Billing and enter it.

> **Does AI Gateway need an API key?**
> No. Convex holds the provider credentials, so there’s no key to get, store, or rotate. Your action signs in with a short-lived token scoped to your deployment. You need a paid plan (your hackathon coupon covers this) and Convex 1.45+. [Read the setup guide](https://docs.convex.dev/ai-gateway/overview).

AI Gateway is not part of Earmark's plan (Claude owns the LLM calls), and it needs a logged-in, paid team, so it is out of scope tonight.

### More resources

- Discord #hackathon, live help from the team: https://convex.dev/community
- Developer search across docs, Stack, and Discord: https://search.convex.dev/
- Changelog: https://ship.convex.dev/

## ESP32 client (alpha)

The brief links https://github.com/convex/convex-esp32.
Its README installs from `https://github.com/get-convex/convex-esp32.git` and describes it as alpha with "no guarantee of support".
It connects over TLS to the `https://<deployment>.convex.cloud` URL, so it targets cloud deployments.
Earmark's NFC board talks to the hub over serial, so this client is not on the critical path.
Details are in `docs/sponsors/vendor-notes/convex.md`, section 9.
