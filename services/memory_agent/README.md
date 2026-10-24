# Earmark memory agent (Fetch.ai uAgent + Bitdeer)

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

A caregiver asks a question in ASI:One, such as "Did Mom take her evening pills?".
This agent looks up the answer in Earmark's Convex records and replies with times in the household's time zone.
It is a uAgent that speaks the Agent Chat Protocol over an Agentverse mailbox.
It reasons with a Bitdeer-hosted chat model in a multi-step tool-calling loop, and falls back to a deterministic keyword router when the model is unavailable.
It never gives medical advice.

| | |
| - | - |
| Agent name | `earmark-memory` (`MEMORY_AGENT_NAME`) |
| Agent address | `agent1q...` (placeholder: fill in after setting `MEMORY_AGENT_SEED`; print it with `uv run earmark-memory address`) |
| Agentverse profile | `https://agentverse.ai/agents/details/<address>/profile` (placeholder) |
| Protocol | `AgentChatProtocol` 0.3.0, manifest published |
| Agentverse README | [`AGENTVERSE_README.md`](AGENTVERSE_README.md), published through `readme_path` |

Extra resources it needs, all optional offline:
- A Convex deployment with Earmark's read endpoints ([`convex/`](../../convex/README.md), https://docs.convex.dev).
- A Bitdeer Model Studio API key (https://www.bitdeer.ai/en/model/apikeys, docs https://developers.bitdeer.ai/docs/guides).
- An Agentverse account (https://agentverse.ai) and an ASI:One account (https://asi1.ai) for registration and chat.

## Example questions

- "Did Mom take her evening pills?"
- "Where did Dad leave his keys?"
- "What hasn't been touched in a week?"
- "When was the salt last used?"
- "Give me yesterday's summary."
- "Should she take a double dose tonight?" (answered with facts only, plus a pointer to her clinician or pharmacist)

Offline answers from the fixture (now = Friday 2025-10-24 17:00 America/Los_Angeles):

```
$ uv run earmark-memory ask --fixture "Did Mom take her evening pills?"
Not yet tonight. Today (Friday, October 24): the 8:00 PM dose of blood pressure pills isn't due yet. Yesterday (Thursday, October 23): the 8:00 PM dose of blood pressure pills was missed (no pickup of the bottle was recorded for it).

$ uv run earmark-memory ask --fixture "Where did Dad leave his keys?"
The keys were last put down in the drawer at 4:52 PM today. At the front.

$ uv run earmark-memory ask --fixture "What hasn't been touched in a week?"
Not picked up or put down in the last week: the pepper (no pickup or put-down on record).
```

## How it works

```
ASI:One --ChatMessage--> Agentverse mailbox --> earmark-memory (uAgent)
                                                  | ack, then MemoryPipeline.answer(question)
                                                  |   guard:    dosing/health question -> facts built by code
                                                  |   llm:      Bitdeer tool loop (<= 4 tool calls)
                                                  |   fallback: keyword router + templates
                                                  v
                                   Convex GET /api/object, /api/objects, /api/history,
                                              /api/adherence, /api/daily-summary
```

- **Tools** (`earmark_memory/tools.py`): `find_object(name)`, `list_objects()`, `history(object_id, since?)`, `adherence(date?)`, `daily_summary(date?)`.
  Each calls one Convex read endpoint over HTTPS with `X-Earmark-Secret`, a 5 s timeout, and typed errors (timeout, unreachable, unauthorized, not found, bad request, off-contract response).
  Every response is parsed with the `earmark_contracts` pydantic models.
- **Household time** (`earmark_memory/household.py`): "yesterday", "last night", "on Thursday", "October 23", and "evening" (doses from 17:00) or "morning" (before 12:00) are resolved in code.
  The model sees pre-formatted times such as "8:15 AM today", never raw timestamps to convert.
- **LLM loop** (`earmark_memory/llm.py`): OpenAI-compatible client against Bitdeer with `reasoning_effort: "none"`, an 8 s request timeout, `max_retries=0`, and a 20 s total budget.
  The model may make up to 4 tool calls; after that tools are switched off (`tool_choice: "none"`) so it must answer.
- **Guards** (`earmark_memory/pipeline.py`):
  - Questions about dosing or health never reach the model; code answers with the dose facts.
  - A model answer for a data question that made no tool call is rejected as ungrounded.
  - A model answer that reads like medical advice is replaced by the code-built answer.
- **Fallback** (`earmark_memory/router.py`): pills/medication/dose route to adherence, where/keys/leave to `find_object`, "hasn't been touched"/"in a week" to `list_objects` filtered by last touch, summary/today to `daily_summary`, and "when ... last" to `history`.
  Answers are templates filled from the same data.
- **Logs**: every tool call with its latency and data source, every model round with latency and the tools it chose, and one line per answer with the path (`llm`, `fallback`, `guard`), the model, and the reason.
  Secrets are never logged.

## Run

Python 3.12 through uv (uAgents crashes on Python 3.14 and later).

```sh
cd services/memory_agent
uv sync                                              # creates .venv with Python 3.12

uv run earmark-memory ask "Did Mom take her evening pills?"          # same pipeline as the agent, no network agent
uv run earmark-memory ask --fixture "Where did Dad leave his keys?"  # force the offline fixture
uv run earmark-memory ask --no-llm "What hasn't been touched in a week?"

uv run earmark-memory run                 # the uAgent with its Agentverse mailbox (needs MEMORY_AGENT_SEED)
uv run earmark-memory run --fixture       # offline demo; without a seed it runs local-only
uv run earmark-memory run --no-mailbox    # local only, no Agentverse
uv run earmark-memory address             # the agent1q... address for MEMORY_AGENT_SEED (never prints the seed)

EARMARK_READ_SECRET=dev uv run earmark-memory fixture-server --port 8011   # fixture over HTTP, real routes and auth
```

`ask` prints the answer on stdout and the step log on stderr.
Settings come from the environment, and a repo-root `.env` is loaded without overriding variables that are already set.

## Test

```sh
cd services/memory_agent
uv run pytest -q
```

The suite covers:
- The fixture: every response validates against `contracts/schemas/convex_http.schema.json` and the pydantic models, and the adherence rule is tested at its boundaries.
- The HTTP tool layer against a local fixture server: the secret header, query names, timeouts, unreachable hosts, off-contract bodies, and error responses.
- Offline Q&A with the LLM disabled: the example questions, medical questions, and Convex being down.
- The LLM loop with a scripted model (multi-step calls, the 4-call cap, the time budget, the guards) and the real `openai` client against a mock transport (request shape, `reasoning_effort: "none"`, no retries).
- The Chat Protocol handler with a fake context, agent construction, and a real two-agent uAgents exchange (in a subprocess, offline).

## Configure

| Variable | Default | Purpose |
| - | - | - |
| `CONVEX_SITE_URL` | unset: the offline fixture | Convex HTTP actions base URL, e.g. `https://<name>.convex.site` or `http://127.0.0.1:3211` locally. Must be https except on localhost. |
| `EARMARK_READ_SECRET` | none (required with `CONVEX_SITE_URL`) | Sent as `X-Earmark-Secret` on every read. |
| `BITDEER_API_KEY` | unset: keyword router only | Bitdeer Model Studio key. |
| `BITDEER_BASE_URL` | `https://api-inference.bitdeer.ai/v1` | OpenAI-compatible endpoint. |
| `BITDEER_AGENT_MODEL` | `deepseek-ai/DeepSeek-V4.1-Flash-1017` | Chat model with tool calling that can turn reasoning off. |
| `MEMORY_AGENT_SEED` | none (required for the mailbox) | The agent's identity; it fixes the address. Long, random, secret, never committed. |
| `MEMORY_AGENT_NAME` | `earmark-memory` | Agent name. |
| `MEMORY_AGENT_PORT` | `8010` | Local port for the Inspector and REST endpoints (8001 to 8003 are taken on the demo Mac). |

Fixed in code (`earmark_memory/config.py`): Convex timeout 5 s, Bitdeer request timeout 8 s, LLM total budget 20 s, at most 4 tool calls, `max_tokens` 500, `reasoning_effort` `none`.
The concierge's `LLM_TIMEOUT_S` is not used here.

## Register on Agentverse and chat through ASI:One (human steps)

These follow `docs/vendor-notes/fetchai.md` section 5.
The browser steps are needed once per agent address.

1. Create accounts at https://agentverse.ai and https://asi1.ai, and stay logged in to both in Chrome.
2. Put `MEMORY_AGENT_SEED` in the repo-root `.env`.
   Use a long random phrase, for example from `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, and never commit it.
   Also set `CONVEX_SITE_URL`, `EARMARK_READ_SECRET`, and `BITDEER_API_KEY`.
3. Start the agent: `cd services/memory_agent && uv run earmark-memory run`.
   The terminal prints `Starting agent with address: agent1q...` and an `Agent inspector available at https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8010&address=agent1q...` line.
   Until you connect it, it also logs `Agent mailbox not found: create one using the agent inspector`.
4. Open the Inspector URL in Chrome on the same Mac.
   If Chrome asks to allow access to devices on your local network, click Allow (or enable it under Settings, Privacy and Security, Site Settings, Additional permissions, Local network access).
5. Click Connect, choose Mailbox, then Finish.
   The terminal should print `Successfully registered as mailbox agent in Agentverse` and `Agent details updated in Agentverse`.
6. In the Inspector click Agent Profile (or find the agent under My Agents with a Mailbox tag).
   Set a short name, a custom `@handle`, a description, and an avatar, and check that the README (with both badges) rendered.
7. Click Chat with Agent, which opens ASI:One chat with the agent, and ask "Did Mom take her evening pills?".
   The agent must be running for this to work.
8. Copy the agent address into the table at the top of this README.
   For the submission, share the ASI:One chat (search icon, Current chat, Share chat) and copy the Agentverse profile URL.

Changing the seed creates a new agent, and steps 3 to 7 must be repeated.
To refresh the README on Agentverse after editing `AGENTVERSE_README.md`, restart the agent and connect through the Inspector again, or edit it in the Agentverse dashboard.
Never run two copies with the same seed at once (for example the laptop and Azure).

## What is mocked

- **Convex**: when `CONVEX_SITE_URL` is unset (or with `--fixture`), `earmark_memory/fixture.py` serves the contract from `config/objects.seed.json`, `config/space.json`, and two scripted days of history with a fixed clock (Friday 2025-10-24 17:00).
  It uses the walking room of Amendment 01 (keys in the drawer, salt and sugar in the cupboard, pills in the box, wallet in the bag), has one missed dose (yesterday's 20:00), and the pepper is never detected.
  Verified against the real backend too (its pre-Amendment-01 seed): with the local Convex deployment running, every example question was answered correctly.
- **Bitdeer**: no key exists tonight, so the model path has only run against scripted models and a mock HTTP transport.
  Without `BITDEER_API_KEY`, the keyword router answers.
- **Agentverse / ASI:One**: not exercised (needs the human's browser login).
  The Chat Protocol was tested with a fake context and with two real uAgents talking offline.

## Decisions

- Medical-advice-style questions (dosing, "is it safe", "should she", health interpretation) bypass the LLM entirely and are answered by code, so "no medical advice" does not depend on a prompt.
  LLM answers also pass an output check, and anything that reads like advice is replaced by the code-built answer.
- An LLM answer to a data question is accepted only if the model used at least one tool; otherwise the fallback answers, so replies are always grounded.
- All date and time handling (relative days, weekday names, part of day, formatting) is in code; tool results reach the model pre-formatted.
- "Taken" is reported as "marked taken (the bottle was picked up at ...)", because Earmark sees bottle pickups, not swallowed pills.
- For "Did Mom take her evening pills?" when tonight's dose isn't due yet, the answer also reports the most recent earlier day, which is what a caregiver usually means.
- "Hasn't been touched": objects without a pickup or put-down in the window.
  Since Amendment 01 the keys carry an NFC tag (the drawer), so they count like everything else.
  A fob-only object (fob, no home spot, no pickups) would be reported separately with its last detection; that path is kept for the fob stretch.
- Answers name the container ("in the drawer", "in the cupboard") plus the spot's detail from `config/space.json` ("Top shelf, front left."), because the read endpoints return only spot labels.
  Containers are named by id ("the box"), not by their mat-relative label ("the box behind you"), because the caregiver isn't standing on the mat.
- Every reply ends the session (`EndSessionContent`), as in the official ASI:One example, because each answer is self-contained and no history is kept.
- Messages are handled one at a time (the uAgents default).
- Without a seed, local-only mode uses a throwaway in-memory identity, because uAgents would otherwise write `private_keys.json` into the working directory.
  The seed is never generated for the human or printed.
- `CONVEX_SITE_URL` must be https except for localhost, so the read secret never crosses a network in cleartext.
- `uagents` is pinned to `>=0.26.1,<0.27`; it imports and runs on Python 3.12 (`AgentChatProtocol 0.3.0`).
- The fixture's "now" is fixed (the instant the contract examples use) so tests and the offline demo are deterministic, and it emits no doses before its history starts (like `activeSinceT` in `convex/`).

## Open issues

- Bitdeer latency and tool-calling quality are unverified until a key exists; with a key, ask the example questions and check the `llm round` log lines.
- Whether ASI:One shows the reply word for word is unverified (fetchai.md section 6); check the wording survives on the first live chat.
- Not built (product decisions for the human): Interactive Cards, the Payment Protocol, multi-agent orchestration.
