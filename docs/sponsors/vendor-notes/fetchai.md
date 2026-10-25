# Fetch.ai vendor notes (uAgents, Chat Protocol, Agentverse, ASI:One)

> **Update 2026-10-24:** the memory agent now reasons with Claude (`claude-sonnet-5-5`, see `services/memory_agent/README.md`). Every Bitdeer mention below is from the first research pass and is out of date.

Verified 2026-10-24 for `services/memory_agent/`.
Sources: the PyPI JSON API, the uAgents GitHub source at tag `v0.26.1`, the released `uagents-core 0.4.12` wheel (I listed its files and diffed them against GitHub, without installing it), and the official docs pages linked below.
This was read-only research.
Nothing was installed or run, except that the snippet in section 7 was syntax-checked with `py_compile` on Python 3.12.
Anything I could not confirm from a source is marked UNVERIFIED.
The hack pack summary is in `docs/sponsors/sponsor-packs/fetchai.md`.

## 1. Key facts

- `uagents` **0.26.1** (released 2026-10-08) and `uagents-core` **0.4.12** (2026-10-13).
  `uagents-core` is a separate package, and installing `uagents` pulls it in automatically.
- Supported Python versions: **3.10 to 3.13**.
  **3.14 and later is broken** (open issue #903).
  This Mac's default `python3` is **3.15.0**, so use `uv venv --python 3.12`.
- Chat Protocol import: `from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, EndSessionContent, StartSessionContent, TextContent, chat_protocol_spec`.
  The protocol is `AgentChatProtocol` version `0.3.0`.
- To register on Agentverse with a mailbox, a human must use a browser **once per agent address**: log in to agentverse.ai, open the Inspector URL that the agent prints, then click Connect, then Mailbox.
  After that, the agent runs headless.
- The ASI:One LLM API is **not** required by the hack pack, so Bitdeer can handle reasoning.

## 2. Packages and Python support

| Item | Value | Source |
| :---- | :---- | :---- |
| `uagents` latest | 0.26.1, `requires_python >=3.10,<4.0` | https://pypi.org/pypi/uagents/json |
| `uagents` deps | `uagents-core>=0.4.11`, `pydantic>=2.8,<3`, `aiohttp`, `uvicorn`, `cosmpy>=0.12.1`, `cronsim`; extra `llm` adds `litellm` | https://raw.githubusercontent.com/fetchai/uAgents/v0.26.1/python/pyproject.toml |
| `uagents-core` latest | 0.4.12, `requires_python >=3.10,<4.0` | https://pypi.org/pypi/uagents-core/json |
| Chat protocol location | `uagents_core/contrib/protocols/chat/__init__.py` (the released 0.4.12 file is byte-identical to `main`) | https://github.com/fetchai/uAgents/blob/main/python/uagents-core/uagents_core/contrib/protocols/chat/__init__.py |
| Also in 0.4.12 | `contrib/protocols/chat/cards` (Interactive Cards), `contrib/protocols/payment`, `utils/registration.py` | Wheel listing of `uagents_core-0.4.12-py3-none-any.whl` |
| CI test matrix | Python 3.10, 3.11, 3.12, 3.13 | https://github.com/fetchai/uAgents/blob/main/.github/workflows/ci-tests.yml |
| `openai` | Not bundled, so install it separately | https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents |

**Install** (from `services/memory_agent/`):

```bash
uv venv --python 3.12
uv pip install "uagents==0.26.1" openai python-dotenv httpx
uv run python -c "from uagents_core.contrib.protocols.chat import chat_protocol_spec; print(chat_protocol_spec.name, chat_protocol_spec.version)"
# expected: AgentChatProtocol 0.3.0
```

The protocol check command comes from https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents.
That page pins `uagents==0.25.5`.
I chose 0.26.1 because it is the current release and its chat module is identical, but I have not run it - UNVERIFIED at runtime.
If 0.26.1 misbehaves, fall back to the documented `uagents==0.25.5`.

**Python 3.14 and later is broken.**
`Agent()` raises `RuntimeError: There is no current event loop in thread 'MainThread'`, because `agent.py` line 373 calls `asyncio.get_event_loop_policy().get_event_loop()`.
- Issue: https://github.com/fetchai/uAgents/issues/903 (open, filed against 0.25.2).
- Fix PRs https://github.com/fetchai/uAgents/pull/904 and https://github.com/fetchai/uAgents/pull/905 are open and not merged.
- The same line is still in v0.26.1: https://raw.githubusercontent.com/fetchai/uAgents/v0.26.1/python/src/uagents/agent.py
- On this Mac, `/opt/homebrew/bin/python3` is 3.15.0 and `/usr/local/bin/python3` is 3.14.0, so both would fail.
  `uv` already has CPython 3.12.12, and Homebrew `python3.11` is also installed.

**Native wheels:** `grpcio`, `pydantic-core`, `aiohttp`, `bcrypt==5.0.0`, `pynacl==1.6.0` and `pycryptodome` all publish macOS arm64 wheels that cover 3.12 and 3.13 (checked on PyPI), so no compiler should be needed.
The install docs mention a `coincurve` build failure on macOS with Python 3.11, fixed with `brew install automake autoconf libtool` (https://uagents.fetch.ai/docs/getting-started/install).
`coincurve` is not in the current dependency tree, so this probably no longer applies - UNVERIFIED.

**Out-of-date doc:** the install page still says "Python 3.8+" (https://uagents.fetch.ai/docs/getting-started/install).
PyPI metadata and CI say 3.10 to 3.13.

**Pydantic v1 models:** `uagents_core.models.Model` subclasses `pydantic.v1.BaseModel` (https://github.com/fetchai/uAgents/blob/main/python/uagents-core/uagents_core/models.py).
Chat messages therefore use the v1 API (`.dict()`, `.json()`, `.parse_raw()`) even with Pydantic 2 installed.
Don't pass Earmark's Pydantic v2 contract models directly as uAgents messages.

## 3. Chat Protocol: exact API (uagents-core 0.4.12)

Source of truth: https://github.com/fetchai/uAgents/blob/main/python/uagents-core/uagents_core/contrib/protocols/chat/__init__.py
Docs: https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol and https://uagents.fetch.ai/docs/examples/asi-1

```python
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)
```

Also exported: `AgentContent`, `ResourceContent`, `Resource`, `MetadataContent`, `StartStreamContent`, `EndStreamContent`.

| Model | Constructor (0.4.12) | Notes |
| :---- | :---- | :---- |
| `ChatMessage` | `ChatMessage(content, msg_id=None, timestamp=None)` | `msg_id` defaults to `uuid4()` and `timestamp` to `datetime.now(timezone.utc)`. `msg.text()` joins all `TextContent` text. |
| `ChatAcknowledgement` | `ChatAcknowledgement(acknowledged_msg_id, metadata=None, timestamp=None)` | `timestamp` defaults to UTC now. |
| `TextContent` | `TextContent(text, type="text")` | Markdown is "supported by most clients". |
| `StartSessionContent` | `StartSessionContent()` | `type="start-session"` |
| `EndSessionContent` | `EndSessionContent()` | `type="end-session"` |
| `MetadataContent` | `MetadataContent(metadata: dict[str, str])` | Carries Interactive Cards (section 9). |
| `chat_protocol_spec` | `name="AgentChatProtocol"`, `version="0.3.0"` | Interactions: `ChatMessage -> {ChatAcknowledgement}`, `ChatAcknowledgement -> {}` |

**Handler signature** (both handlers are in every official example):

```python
chat = Protocol(spec=chat_protocol_spec)

@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage): ...

@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement): ...

agent.include(chat, publish_manifest=True)
```

Rules from the docs:

- **Acknowledge every incoming `ChatMessage`** with `await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))`.
  Docs: "Always acknowledge incoming ChatMessage values with ChatAcknowledgement" (https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents).
- **Reply** with `await ctx.send(sender, ChatMessage(content=[TextContent(text=reply)]))`.
- **Ending a session:** add `EndSessionContent()` to the reply's `content`.
  The uAgents ASI-1 example does this on every reply, which "signal[s] that the session is over, this also informs the user that we are not recording any of the previous history of messages" (https://uagents.fetch.ai/docs/examples/asi-1).
  The hack pack quick-start and `av-script-example` instead handle `StartSessionContent` and `EndSessionContent` as they arrive and only end the session when the caller does (https://github.com/fetchai/innovation-lab-examples/blob/main/av-script-example/agent.py).
  Both patterns are official.
- `agent.include(protocol, publish_manifest=True)` publishes the protocol manifest so Agentverse and ASI:One know the agent speaks ACP.
  Expect this log line: `Manifest published successfully: AgentChatProtocol`.
- `ctx.session` is a per-conversation UUID.
  The ASI:One tutorial uses `ctx.storage.set(str(ctx.session), sender)` to remember who to reply to (https://docs.asi1.ai/documentation/tutorials/agent-chat-protocol.md).

## 4. `Agent(...)` constructor (v0.26.1)

Source: https://raw.githubusercontent.com/fetchai/uAgents/v0.26.1/python/src/uagents/agent.py (lines 299-329).

Parameters that matter for Earmark, with their defaults:

- `name: str | None = None`
- `port: int | None = None`, which becomes **8000** if unset (`self._port = port or 8000`)
- `seed: str | None = None`; if unset, a **random identity is generated on every run**
- `mailbox: bool = False`
- `publish_agent_details: bool = True`
- `readme_path: str | None = None`; the path is joined to `os.getcwd()`, so pass an absolute path
- `description: str | None = None`, the short description shown on the Agentverse profile
- `handle: str | None = None`, sent at connect time.
  Whether it overrides a handle set in the dashboard is UNVERIFIED, so set the handle in the Agentverse UI.
- `avatar_url`, `banner_url`, `metadata`
- `enable_agent_inspector: bool = True`, which serves the local REST endpoints the Inspector uses
- `network: "mainnet" | "testnet" = "mainnet"`
- `handle_messages_concurrently: bool = False`, so messages are processed one at a time by default

## 5. Mailbox and Agentverse registration

### How it works (from the source)

- With `mailbox=True`, the agent's advertised endpoint becomes Agentverse's mailbox endpoint.
  The agent then polls its mailbox every 1.0 s over outbound HTTPS (`MAILBOX_POLL_INTERVAL_SECONDS = 1.0`; https://raw.githubusercontent.com/fetchai/uAgents/v0.26.1/python/src/uagents/config.py).
  **No inbound port or public URL is needed**, so it works behind hackathon Wi-Fi.
- The mailbox is created when a **logged-in Agentverse user** connects the agent from the Inspector.
  The browser POSTs the user's token to the agent's local `/connect` endpoint (`AgentverseConnectRequest{user_token, agent_type, endpoint, team}`).
  The agent then signs an identity challenge with its seed key and registers itself (`register_in_agentverse` in https://raw.githubusercontent.com/fetchai/uAgents/v0.26.1/python/src/uagents/mailbox.py).
- Until that happens, the agent logs `Agent mailbox not found: create one using the agent inspector`.

### Steps (code steps vs. **[HUMAN]** browser steps)

Docs: https://uagents.fetch.ai/docs/agentverse/mailbox, https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation#mailbox-agents, https://uagents.fetch.ai/docs/examples/asi-1

1. **[HUMAN]** Create accounts at https://agentverse.ai and https://asi1.ai, and stay logged in to both in **Chrome**.
2. Run the agent: `uv run python agent.py`.
   The terminal prints:
   ```
   INFO: [earmark-memory]: Starting agent with address: agent1q...
   INFO: [earmark-memory]: Agent inspector available at https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8010&address=agent1q...
   INFO: [earmark-memory]: Starting mailbox client for https://agentverse.ai
   ```
3. **[HUMAN]** Open the Inspector URL in Chrome on the **same machine** as the agent.
   For an agent on a remote machine, port-forward the agent's port first (https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation#2-local-inspector-ui-based-registration).
4. **[HUMAN]** Chrome 142+ and Brave show "Allow this site to access devices on your local network": click **Allow**.
   If you missed it, enable it under Chrome Settings -> Privacy and Security -> Site Settings -> Additional permissions -> Local network access (https://uagents.fetch.ai/docs/agentverse/mailbox).
5. **[HUMAN]** Click **Connect**, choose **Mailbox**, then click **Finish**.
   The Inspector may show an "add mailbox to your code" checklist.
   That only confirms `mailbox=True` and needs no code change (https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents).
   The terminal should then print `[mailbox]: Successfully registered as mailbox agent in Agentverse` and `[mailbox]: Agent details updated in Agentverse`.
6. **[HUMAN]** Click **Agent Profile** in the Inspector, or find the agent under Agentverse "My Agents" with a Mailbox tag.
   Set a short name (under 20 characters is recommended), a custom `@handle` (up to 20 characters), a description, and an avatar.
   Then confirm the README rendered (https://docs.agentverse.ai/documentation/agent-discovery/profile).
7. **[HUMAN]** Click **Chat with Agent**, which opens ASI:One chat with the agent (https://uagents.fetch.ai/docs/examples/asi-1).

This is a one-time step per address.
The docs say "Once registration succeeds, you do not need to re-register your agent repeatedly" (https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation).
Changing the seed creates a new agent, and you have to repeat steps 3-7.
To refresh the README after editing it, restart the agent and connect through the Inspector again (https://uagents.fetch.ai/docs/agentverse/mailbox), or edit it in the Agentverse dashboard Overview tab (https://innovationlab.fetch.ai/resources/docs/agentverse/searching).

**Keeping the mailbox alive:** on the free tier, "logging in to Agentverse at least once every 30 days" is required, or the mailbox is deactivated.
Free-tier limits are 8 local agents and 10K processed messages (https://docs.agentverse.ai/documentation/advanced-usages/agentverse-subscriptions-and-quotas).
The hack pack's `CALHACKS26AV` code is presumably for Agentverse Premium.
"Whenever working with multiple local Agents, you need a different dedicated Mailbox for each one of them!" (https://uagents.fetch.ai/docs/agentverse/mailbox).

### Headless alternative: API-key registration (needs a public endpoint)

```python
from uagents_core.utils.registration import register_chat_agent, RegistrationRequestCredentials

register_chat_agent(
    "Earmark Memory",
    "https://<public-host>/submit",
    active=True,
    credentials=RegistrationRequestCredentials(
        agentverse_api_key=os.environ["AGENTVERSE_API_KEY"],
        agent_seed_phrase=os.environ["MEMORY_AGENT_SEED"],
    ),
    readme=README_TEXT,
    description="...",
)
```

- The signature, including `starter_prompts` and `metadata`, is verified in the 0.4.12 wheel.
  Docs: https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation#1-programmatic-registration
- Docs: "Your agent must expose a public endpoint that Agentverse can reach" (https://docs.agentverse.ai/documentation/launch-agents/launch-asi-one-compatible-u-agent).
  That fits an Azure Container Apps deployment with public HTTPS, not a laptop.
- The Agentverse API key is created on the Agentverse dashboard (https://innovationlab.fetch.ai/resources/docs/agentverse/agentverse-api-key).
- `av-script-example` calls this at startup together with `mailbox=True` (https://github.com/fetchai/innovation-lab-examples/blob/main/av-script-example/agent.py).
  Whether that creates a working mailbox without the Inspector is UNVERIFIED.
- For the laptop demo, use the Inspector flow.

## 6. ASI:One: how a user finds and chats with the agent

- Chat UI: https://asi1.ai/chat (returns HTTP 200).
  The user needs an ASI:One account.
- There are three ways in:
  1. From the agent's Agentverse profile, click **Chat with Agent** (https://uagents.fetch.ai/docs/examples/asi-1).
     This is the most reliable path for the demo.
  2. Paste the agent's `@handle` into ASI:One chat along with the request: "Copy the handle into ASI:One chat with a request to talk to that Agent directly" (https://docs.agentverse.ai/documentation/agent-discovery/profile).
  3. Organic discovery, where ASI:One picks the agent on its own.
     Ranking depends on having the Chat Protocol, a good README, a custom handle, active status, an avatar, a description, and interaction history ("Receive at least 10 interactions") (https://docs.agentverse.ai/documentation/agent-discovery/setup-guide, https://docs.agentverse.ai/documentation/agent-optimization/ranking).
     Don't count on this for a brand-new agent.
- The agent must be running: "Remember that the Agent needs to be running otherwise you won't be able to chat with it!" (https://uagents.fetch.ai/docs/examples/asi-1).
- **Shared chat URL** (for the submission form): in the left sidebar click the search icon, then Current chat, then Share chat (submission doc, see `docs/sponsors/sponsor-packs/fetchai.md`).
- I could not confirm whether ASI:One shows the agent's reply word for word or rewrites it - UNVERIFIED.
  Test this early, because Earmark's "timestamps, no medical advice" wording has to survive.
- **ASI:One LLM API** (optional, not required by the hack pack): base URL `https://api.asi1.ai/v1`, OpenAI-compatible.
  Models are `asi1`, `asi1-ultra` and `asi1-mini`, and keys come from https://asi1.ai/dashboard/api-keys (https://innovationlab.fetch.ai/resources/docs/asione/asi-one-quickstart, https://docs.asi1.ai/llms.txt).
  The official examples use it only as a stand-in LLM.
  The hack pack's mandatory requirements and judging criteria never mention it (https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack).

## 7. Minimal Earmark memory agent (adapted from the official examples)

This is adapted from https://uagents.fetch.ai/docs/examples/asi-1 and https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents.
Changes from those examples:
- Bitdeer instead of ASI:One for the LLM.
- `AsyncOpenAI` with a timeout instead of the blocking sync client.
- Secrets come from the environment.
- `readme_path` is absolute.
- The timestamps use the defaults instead of the deprecated `datetime.utcnow()`.

The snippet is syntax-checked on Python 3.12 but has not been run.
The Bitdeer environment variable names are placeholders until the Bitdeer notes confirm the base URL and model ID.

```python
import os
from pathlib import Path

from openai import AsyncOpenAI
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

llm = AsyncOpenAI(
    base_url=os.environ["BITDEER_BASE_URL"],
    api_key=os.environ["BITDEER_API_KEY"],
    timeout=20.0,
)

agent = Agent(
    name="earmark-memory",
    seed=os.environ["MEMORY_AGENT_SEED"],
    port=int(os.environ.get("MEMORY_AGENT_PORT", "8010")),
    mailbox=True,
    publish_agent_details=True,
    readme_path=str(Path(__file__).with_name("README.md")),
    description="Answers caregiver questions about household objects and medication pickups from Earmark's event log.",
)

chat = Protocol(spec=chat_protocol_spec)


async def answer(question: str) -> str:
    # Placeholder: replace with Bitdeer tool calling over Convex read endpoints.
    r = await llm.chat.completions.create(
        model=os.environ["BITDEER_CHAT_MODEL"],
        messages=[
            {"role": "system", "content": "Answer only from the provided Earmark data. No medical advice."},
            {"role": "user", "content": question},
        ],
        max_tokens=512,
    )
    return r.choices[0].message.content or ""


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    if any(isinstance(c, EndSessionContent) for c in msg.content):
        return
    question = msg.text().strip()
    if not question:
        return  # e.g. a StartSessionContent-only message
    try:
        reply = await answer(question)
    except Exception:
        ctx.logger.exception("answer failed")
        reply = "Sorry, I can't reach Earmark's records right now. Please try again in a minute."
    await ctx.send(sender, ChatMessage(content=[TextContent(text=reply)]))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
```

Notes:

- Make Convex calls with `httpx.AsyncClient(timeout=...)`, or wrap sync calls in `asyncio.to_thread`.
  The official examples call a blocking client inside `async` handlers, which stalls the agent's event loop and mailbox polling.
- To end every turn the way the uAgents example does, append `EndSessionContent()` to the reply's `content`.

**`.env.example` additions** (Bitdeer variables are defined by the Bitdeer notes):

```bash
# Fetch.ai memory agent
MEMORY_AGENT_SEED=        # long random string, unique to this agent; never commit; it IS the agent's identity
MEMORY_AGENT_PORT=8010    # local port for the Inspector; mailbox needs no inbound access
MEMORY_AGENT_ADDRESS=     # agent1q... printed at startup; documentation only
AGENTVERSE_API_KEY=       # only if using register_chat_agent (public-endpoint deployment)
```

## 8. README requirements (repo README and the agent's Agentverse README)

From the hack pack (https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack):

- The repo README must include "key details about your agents, such as their name and address".
- It must "Mention any extra resources required to run your project and provide links to those resources."
- "All agents must be categorized under Innovation Lab", using these badges in the agent's README.md:

```markdown
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
```

- Put the badges in **both** the repo README and the agent README that `readme_path` publishes to Agentverse.
- A domain tag is recommended for hackathon agents, using the pattern `![tag:domain/<your-domain>](https://img.shields.io/badge/<label>-<hexcolor>)` with a six-digit hex color (https://innovationlab.fetch.ai/resources/docs/agentverse/searching).
  For example: `![tag:domain/accessibility](https://img.shields.io/badge/accessibility-4CAF50)`.
- Badge color conflict: the hack pack uses `hackathon-5F43F1`, while the Innovation Lab example uses `hackathon-2E5C63`.
  Use the hack pack's `5F43F1`.

What ASI:One matching reads from the agent README (https://innovationlab.fetch.ai/resources/docs/agentverse/searching):

- A specific, keyword-rich title.
- A 2-4 sentence overview.
- 2-3 use-case examples (for example "Did Mom take her evening pills?", "Where did Dad leave his keys?", "What hasn't been touched in a week?").
- Capabilities in plain language.
- Interaction modes (ASI:One chat).
- Limitations: no medical advice, and answers come only from logged events.
- Keywords such as "caregiver", "medication adherence", "assistive technology", "blind and low vision" and "object finder".
- English Markdown.

## 9. Optional bonus items (each needs a human product decision)

- **Interactive Cards** (recommended by the hack pack and listed as a bonus): import from `uagents_core.contrib.protocols.chat.cards`.
  Helpers: `create_card_content`, `extract_card_response`.
  Payload types: `CarouselCardPayload`, `DetailCardPayload`, `FormCardPayload`, `ReviewCardPayload`, `CustomCardPayload`.
  Cards travel inside `MetadataContent` with `card_protocol_version="1"`.
  "When validation fails, ASI:One silently falls back to treating the message as a plain text reply" (https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards).
  There is a playground at https://asi1.ai/developer/card-playground.
  A `DetailCardPayload` (`title`, `summary_rows`, `ctas`) could show the medication log.
  It is verified in the 0.4.12 wheel.
- **Payment Protocol** (part of "Use of Fetch.ai Technology (20%)" and a bonus): `uagents_core.contrib.protocols.payment`, protocol `AgentPaymentProtocol` v0.1.0.
  Messages: `RequestPayment`, `CommitPayment`, `RejectPayment`, `CompletePayment`, `CancelPayment`, `Funds`.
  It works with any payment rail; Stripe is recommended for fiat (https://innovationlab.fetch.ai/resources/docs/agent-transaction/agent-payment-protocol, Stripe example https://innovationlab.fetch.ai/resources/docs/examples/agent-transaction/stripe-horoscope-payment-protocol).
- **Multi-agent** (bonus): see https://github.com/fetchai/innovation-lab-examples/tree/main/fetch-hackathon-quickstarter, an orchestrator plus two agents, each with its own seed and mailbox.

## 10. Gotchas

- **Python version:** see section 2.
  Pin 3.12 with `uv`, because this machine's default `python3` (3.15) will crash in `Agent()`.
- **The seed is the identity.**
  The address comes from the seed (`Identity.from_seed(seed, 0)`; https://github.com/fetchai/uAgents/blob/main/python/uagents-core/uagents_core/identity.py).
  - With no seed, you get a new random address every run, which breaks the mailbox and the address in the README.
  - Never reuse a seed from the docs, because that would collide with someone else's agent.
  - Never commit the seed, since anyone who has it can act as the agent.
  - Each agent needs its own seed.
  - Don't run two processes with the same seed (for example the laptop and Azure at the same time).
    They would both poll the same mailbox - UNVERIFIED behavior.
  - Fetch's quickstarter suggests seeds be "highly random and not contain white spaces" (https://github.com/fetchai/innovation-lab-examples/blob/main/fetch-hackathon-quickstarter/.env.example).
- **Getting the address:** there are three ways.
  - The startup log line `Starting agent with address: agent1q...`.
  - `agent.address` in code.
  - Offline: `uv run python -c "import os; from uagents_core.identity import Identity; print(Identity.from_seed(os.environ['MEMORY_AGENT_SEED'], 0).address)"`.
  The address stays the same as long as the seed does, so it can go in the README before the demo.
- **Ports on this Mac (checked 2026-10-24):**
  - The uAgents default is 8000, and the docs' examples use 8000-8002.
  - 8001, 8002 and 8003 are held by leftover `scar-tissue` uvicorn processes (`~/scar-tissue/{env,agent,train}`).
  - 5000 and 7000 belong to macOS AirPlay Receiver (ControlCenter), and 3000 to a node process.
  - Earmark's bus uses 8765.
  - Use **8010** through `MEMORY_AGENT_PORT`.
  - The agent binds `0.0.0.0`.
- **Browser:** use Chrome or Brave for the Inspector, and grant the Local Network Access prompt.
  Safari might block an HTTPS page from calling `http://127.0.0.1` - UNVERIFIED, just use Chrome.
- **`readme_path`** is resolved relative to the current directory, so use `Path(__file__).with_name("README.md")`.
- **Blocking calls** in handlers stall the agent.
  Use async clients with timeouts, which brief rule 5 also requires.
- **`datetime.utcnow()`** in the official snippets is deprecated in 3.12.
  Leave out `timestamp=`, and the models default to timezone-aware UTC.
- **The hack pack quick-start code is broken as printed:** an over-indented `return`, a missing `from uagents import ...`, and an `Agent()` with no seed.
  Use section 7.
- **Inactive agents are ranked lower.**
  Keep the agent running during judging (https://docs.agentverse.ai/documentation/agent-optimization/ranking).

## 11. Where the Earmark brief conflicts with official materials

1. **Python version.**
   The brief says "Python 3.11+" (section 3 tech choices, Phase 0 step 1) with no upper limit.
   uAgents supports only 3.10-3.13, and 3.14+ crashes (section 2).
   `services/memory_agent` must pin 3.12 or 3.13.
2. **README requirements.**
   Brief 5.G asks only for "the agent address and steps to reproduce."
   The hack pack also requires the agent **name**, the `innovationlab` and `hackathon` badges in the agent's README, links to extra resources (Convex, Bitdeer), and a **public** GitHub repo.
3. **Acceptance test.**
   Brief 5.G says "a question sent through the chat interface."
   The hack pack requires the full primary workflow "entirely within an ASI:One conversation" with no custom frontend.
   The acceptance test should therefore specify **ASI:One**, not the Agentverse chat or a local client.
4. **"Thin wrapper" risk.**
   The hack pack asks for "multi-step planning, reasoning, or orchestration" and "more than a chatbot or a thin wrapper around an API."
   One LLM call plus one Convex read may score low.
   Make the tool use multi-step and visible, for example: resolve the person or object, query events, call Convex's adherence computation, then answer with timestamps.
   This still follows brief rule 3 (math stays in code).
5. **Judging items the brief leaves out.**
   "Use of Fetch.ai Technology (20%)" explicitly asks about the Payment Protocol.
   The bonus points list multi-agent collaboration and Interactive Cards.
   The brief covers none of these.
   Adding them is a product decision for the human (section 9).
6. **Deliverables the brief leaves out.**
   Fetch asks for a **3-5 minute demo video** showing the agents.
   Teams must also register through the **Cal Hacks ASI:One Submission agent**, and every teammate must join with the Team ID or the status stays "Incomplete".
   The required form fields include the Devpost URL and the demo video URL.
   Details are in `docs/sponsors/sponsor-packs/fetchai.md`.
7. **Azure hosting (brief 6.1).**
   A mailbox agent runs anywhere with outbound HTTPS, but the Inspector step needs a browser on the same machine or a port-forward.
   For Azure Container Apps, either connect once through a port-forward, or register with `register_chat_agent` using the app's public HTTPS endpoint (section 5).
   Never run the laptop and cloud copies with the same seed at the same time.
8. **The brief expected the Google Doc might need sign-in (section 2.5).**
   It didn't: the export URL worked without sign-in.
9. **No conflict on the LLM.**
   Using Bitdeer for reasoning is allowed.
   The ASI:One LLM appears only in examples.

## 12. Smoke test for the builder (not run by me)

```bash
cd services/memory_agent
uv venv --python 3.12
uv pip install "uagents==0.26.1" openai python-dotenv httpx
uv run python -c "from uagents_core.contrib.protocols.chat import chat_protocol_spec; print(chat_protocol_spec.name, chat_protocol_spec.version)"   # AgentChatProtocol 0.3.0
uv run python agent.py   # expect "Starting agent with address: agent1q..." and an Inspector URL on port 8010
```

Then the human does the Inspector steps (section 5) and sends "Did Mom take her evening pills?" in ASI:One.

## Sources

- Hack pack (Google Doc): https://docs.google.com/document/d/1pbsW7tH946iooPZxhn2FOuWZ1UjlEfJu4Hi9CQQPBpo/edit?tab=t.0
- Hack pack (web): https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack
- PyPI: https://pypi.org/project/uagents/ and https://pypi.org/project/uagents-core/
- uAgents source: https://github.com/fetchai/uAgents (tag `v0.26.1`)
- uAgents docs: https://uagents.fetch.ai/docs/examples/asi-1, https://uagents.fetch.ai/docs/agentverse/mailbox, https://uagents.fetch.ai/docs/getting-started/install
- Innovation Lab: https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents, https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation, https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol, https://innovationlab.fetch.ai/resources/docs/agentverse/searching, https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards, https://innovationlab.fetch.ai/resources/docs/agent-transaction/agent-payment-protocol, https://innovationlab.fetch.ai/resources/docs/asione/asi-one-quickstart
- Agentverse docs: https://docs.agentverse.ai/documentation/agent-discovery/profile, https://docs.agentverse.ai/documentation/agent-discovery/setup-guide, https://docs.agentverse.ai/documentation/agent-optimization/ranking, https://docs.agentverse.ai/documentation/launch-agents/launch-asi-one-compatible-u-agent, https://docs.agentverse.ai/documentation/advanced-usages/agentverse-subscriptions-and-quotas
- ASI:One docs: https://docs.asi1.ai/llms.txt, https://docs.asi1.ai/documentation/tutorials/agent-chat-protocol.md
- Examples: https://github.com/fetchai/innovation-lab-examples (`av-script-example`, `fetch-hackathon-quickstarter`)
- Python 3.14 issue: https://github.com/fetchai/uAgents/issues/903
