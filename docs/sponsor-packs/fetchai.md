# Fetch.ai - Cal Hacks 13.0 sponsor pack

Source: https://docs.google.com/document/d/1pbsW7tH946iooPZxhn2FOuWZ1UjlEfJu4Hi9CQQPBpo/edit?tab=t.0
Fetched 2026-10-24 via the public export URLs `.../export?format=txt` and `.../export?format=md` (no sign-in needed).
The Google Doc is only a short index of links.
The real challenge statement, judging criteria and deliverables live on Fetch.ai's hack pack web page, which the doc points to.
I fetched that page and the two linked Google Docs (5-minute setup, submission process) too, and all three are copied or summarized below.
Nothing here needs the human to export anything.

Technical notes (packages, code, gotchas) are in `docs/vendor-notes/fetchai.md`.

## Documents covered

| Document | URL | Status |
| :---- | :---- | :---- |
| Sponsor Google Doc (index of links) | https://docs.google.com/document/d/1pbsW7tH946iooPZxhn2FOuWZ1UjlEfJu4Hi9CQQPBpo/edit?tab=t.0 | Fetched, full copy below |
| Fetch.ai hack pack web page (challenge, judging, deliverables) | https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack | Fetched, full summary below |
| "5 Minute setup" Google Doc | https://docs.google.com/document/d/1_Tb76j7zlzodhTiofHX_uPuEIfrDuQ3QAyk7c4osrd4/edit?usp=sharing | Fetched, full copy below |
| Submission process Google Doc | https://docs.google.com/document/d/1UDW-X1C24hxZviFOQzjTeh0pXRNAoflMb8lhJqZP9Z0 | Fetched, full copy below |
| Pre-hack workshop recording | https://drive.google.com/file/d/1UKOz1kmxXulFWwajimJriH9mi8GiC3B6/view?usp=sharing | Video, not watched |
| "Submission Process on ASI:One" videos | See the links in the sections below | Video, not watched |
| Devpost prize list | https://cal-hacks-13-0.devpost.com/ | Fetched, used to cross-check prizes |

## 1. Full copy of the sponsor Google Doc

**HackPack with challenge statement:** https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack
(Go through hackpack to know the challenge statement, judging criteria, deliverables.)

**5 Minute setup to register your first agent with agentverse and check its working from asi1:**
https://docs.google.com/document/d/1_Tb76j7zlzodhTiofHX_uPuEIfrDuQ3QAyk7c4osrd4/edit?usp=sharing

**Pre-hack Workshop Recording:** [Recording](https://drive.google.com/file/d/1UKOz1kmxXulFWwajimJriH9mi8GiC3B6/view?usp=sharing)

**Track:**

1. **Most Basic ASI1 Compatible Agent to get started:** https://uagents.fetch.ai/docs/examples/asi-1
2. **Multiagent Example:** https://github.com/fetchai/innovation-lab-examples/tree/main/fetch-hackathon-quickstarter
3. **Concepts and tech:** https://innovationlab.fetch.ai/resources/docs/intro
4. **Repo of Agent Examples with different agentic frameworks and LLMs:** https://github.com/fetchai/innovation-lab-examples
5. **Payment Protocol with Stripe:** https://innovationlab.fetch.ai/resources/docs/examples/agent-transaction/stripe-horoscope-payment-protocol
   **Examples of payment agents:** https://github.com/fetchai/innovation-lab-examples/tree/main/stripe-payment-agents

**Past Hackathon Projects:** https://innovationlab.fetch.ai/projects

**Submission Process and Deliverables**

1. Submit your project through Devpost.
2. You also need to register your submission through the [**CalHacks ASI:One Submission Agent**](https://asi1.ai/festival/calhacks2026/dashboard?utm_source=calhacks2026) (steps below).
   Watch the video here: [**Submission Process on ASI:One**](https://drive.google.com/file/d/1IgmLW2-wqeozL4TP8w876ECK6ywDVOk0/)

Refer this Doc for more details on submission: https://docs.google.com/document/d/1UDW-X1C24hxZviFOQzjTeh0pXRNAoflMb8lhJqZP9Z0

## 2. Fetch.ai hack pack web page (summary, requirements copied verbatim)

Source: https://www.fetch.ai/events/hackathons/calhacks-13-0/hackpack

### Offer

One month free of ASI:One Pro and Agentverse Premium.
The page shows two codes: `CALHACKS26` and `CALHACKS26AV`.
The page does not say which code is for which product.
My guess is `CALHACKS26` for ASI:One Pro and `CALHACKS26AV` for Agentverse ("AV") Premium - UNVERIFIED.
Redemption guides (Google Drive): ASI:One Pro https://drive.google.com/file/d/17iBT9I2xnllnYerECd53nnhAfOxS-WdD/view?usp=drive_link and Agentverse Premium https://drive.google.com/file/d/1adhDjri7DvzGwEcZNlVlHj7rweMdv_0u/view?usp=drive_link (not opened).

### Prizes (as listed on the Fetch.ai page)

| Prize | Amount |
| :---- | :---- |
| Best Use of Fetch.ai - 1st Prize | $1250 cash + internship interview opportunity |
| Best Use of Fetch.ai - 2nd Prize | $750 cash + internship interview opportunity |
| Best Use of Fetch.ai - 3rd Prize | $500 cash + internship interview opportunity |
| Special Recognition Prize | $250 cash |
| Special Recognition Prize | $250 cash |

**Devpost disagrees on amounts.**
https://cal-hacks-13-0.devpost.com/ lists "[Fetch.ai] 1st Place Best Use of Fetch.ai" $1,500, "2nd Place" $1,000, and "3rd Place" $500, with no special recognition prizes.
This doesn't change what we build.
Ask at the Fetch.ai table if it matters.

### Challenge statement: "ASI:One Agent Challenge - From Intent to Action"

"Most AI applications stop at conversation.
Your challenge is to build an AI agent that can be discovered through ASI:One, understand a user's intent, and take meaningful action to solve a real-world problem."

"The result should be more than a chatbot or a thin wrapper around an API."

**What to Build** - a single agent or multi-agent system that:

- Solves a clearly defined real-world problem.
- Performs multi-step planning, reasoning, or orchestration.
- Uses tools, APIs, external services, data sources, MCP, or other agents to produce an executable outcome.
- Is registered on Agentverse and discoverable through ASI:One.
- Implements the Agent Chat Protocol (ACP).
- Allows the complete primary workflow to be demonstrated directly inside an ASI:One conversation without requiring a custom frontend.
- (Recommended) Uses ASI1 Interactive Cards (https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards) to provide rich, guided user interactions such as forms, carousels, review screens, detail views, or custom interactive layouts directly inside ASI:One conversations.

Any framework is allowed (Google ADK, LangGraph, CrewAI, OpenAI Agents SDK, Claude Agent SDK, uAgents, or plain Python).

### Mandatory requirements (verbatim)

"To be eligible for prizes, your project must:

- Register at least one agent on Agentverse.
- Implement the Agent Chat Protocol (ACP).
- Be discoverable and directly usable through ASI:One.
- Demonstrate meaningful tool execution or multi-agent orchestration.
- Complete the primary user workflow entirely within an ASI:One conversation.
- Submit a public GitHub repository with instructions to run or test the project."

### Bonus points (verbatim)

- Effective multi-agent collaboration.
- Implementation of the Payment Protocol with a credible monetization model.
- Effective use of ASI Interactive Cards to create intuitive, guided, and action-oriented user experiences inside ASI:One.
- Strong reliability, error handling, and recovery from failed tool calls.
- Creative use of real-time data and external services.
- An agent that could realistically continue operating after the hackathon.

### Judging criteria (verbatim)

| Criterion | Weight | Questions |
| :---- | :---- | :---- |
| Functionality & Technical Implementation | 25% | Does the agent system work as intended? Are the agents properly communicating and reasoning in real time? |
| Use of Fetch.ai Technology | 20% | Are agents registered on Agentverse? Is the Chat Protocol implemented for ASI:One discoverability? Is the Payment Protocol integrated to enable monetisation? |
| Innovation & Creativity | 20% | How original or creative is the solution? Is it solving a problem in a new or unconventional way? |
| Real-World Impact & Usefulness | 20% | Does the solution solve a meaningful problem? How useful would this be to an end user? |
| User Experience & Presentation | 15% | Is the solution presented clearly with a well-structured demo? Is there a smooth and intuitive user experience? |

Judges: Sana Wajid (Chief Development & Operations Officer, Fetch.ai; COO, Innovation Lab) and Rajashekar Vennavelli (Senior AI Engineer, Fetch.ai).
Mentors: Devam Sheth, Aldridge Fonseca, Gitika Rath, Davel Radindra, Shambhavi Kumar.

### What to submit (verbatim where quoted)

**Code**

- "Share the link to your public GitHub repository to allow judges to access and test your project."
- "Ensure your README.md file includes key details about your agents, such as their name and address, for easy reference."
- "Mention any extra resources required to run your project and provide links to those resources."
- "All agents must be categorized under Innovation Lab.
  To achieve this, include the following badge in your agent's README.md file:"

```markdown
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
```

**Video**

- "Include a demo video (3-5 minutes) demonstrating the agents you have built."

**Deliverables & How to Submit**

- Submit through Devpost.
- Also register the submission through the CalHacks Hackathon ASI:One Submission Agent: https://asi1.ai/auth/signup?returnTo=%2Ffestival%2Fcalhacks2026%2Fdashboard%3Futm_source%3Dcalhacks2026
- Video: [Submission Process on ASI:One](https://drive.google.com/file/d/1EDfKrM7l8soO-40eKkPYDAEkRUTwQKyf) (a different video link from the one in the Google Doc).
- Full details: https://docs.google.com/document/d/1UDW-X1C24hxZviFOQzjTeh0pXRNAoflMb8lhJqZP9Z0 (copied in section 4 below).

### Important links on the page

- How to create an Agent with uAgents Framework: https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation
- Communication between two uAgents: https://innovationlab.fetch.ai/resources/docs/agent-communication/uagent-uagent-communication
- How to create ASI:One compatible uAgents: https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents
- ASI:One API: https://innovationlab.fetch.ai/resources/docs/asione/asi-one-quickstart
- Innovation Lab GitHub repo: https://github.com/fetchai/innovation-lab-examples
- Past hackathon projects: https://innovationlab.fetch.ai/projects
- How to Connect a Local Agent to Agentverse: https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation#mailbox-agents
- How to Integrate ASI:One LLM with your uAgent: https://innovationlab.fetch.ai/resources/docs/examples/asione/asi1-mini-language-tutor (returned HTTP 404 on 2026-10-24; Earmark doesn't need it)
- How to create an Image Generation Agent: https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/image-generation-agent
- Agentverse MCP Server: https://docs.agentverse.ai/documentation/advanced-usages/agentverse-mcp (full server `https://mcp.agentverse.ai/sse`, lite `https://mcp-lite.agentverse.ai/mcp`)
- MCP Integration Example: https://innovationlab.fetch.ai/resources/docs/mcp-integration/what-is-mcp

The page also has a "Quick start example" Chat Protocol agent.
As printed on the page it has an indentation error (`return ChatMessage(` is over-indented) and is missing `from uagents import Agent, Context, Protocol`.
It also calls `Agent()` with no seed, which gives the agent a new random address on every run.
I checked this against the page's raw HTML, not just a text extraction.
Use the code in `docs/vendor-notes/fetchai.md` instead, which follows the working official examples.

## 3. Full copy of the "5 Minute setup" Google Doc

Source: https://docs.google.com/document/d/1_Tb76j7zlzodhTiofHX_uPuEIfrDuQ3QAyk7c4osrd4/edit?usp=sharing

1. Easiest way to register your first agent on agentverse and interact with it from asi1.
   Follow this as it is and just copy paste the code from here ***agent.py*** snippet into your project IDE: https://uagents.fetch.ai/docs/examples/asi-1
2. Just 2 installs in ur IDE virtual env - `pip install uagents`, `pip install openai`
3. Add your asi1 api key from here: https://asi1.ai/developer
4. Change the name and seed phrase to something unique to your agent: `name="<your-agent-name"`, `seed="<your-agent-seedphrase>"`,

"Do this and you have successfully registered your first agent, once this works, you can change the logic, build upon this for your usecase."

"I would recommend you all to do this basic thing today and once you do this, you can keep iterating on your agent logic and testing it out from ASI1"

Note: the ASI:One API key in step 3 is only there because the example agent uses the ASI:One LLM.
The mandatory requirements do not require the ASI:One LLM, so Earmark reasons with Claude instead.

## 4. Full copy of the submission process Google Doc

Source: https://docs.google.com/document/d/1UDW-X1C24hxZviFOQzjTeh0pXRNAoflMb8lhJqZP9Z0

**Cal Hacks ASI:One Submission - Deliverables & How to Submit**

**Submission Process**

- Submit your project through Devpost.
- Register your submission through the **Cal Hacks ASI:One Submission Agent** (steps below).
  Watch the video here: [Submission Process on ASI:One](https://drive.google.com/file/d/1LhKHQ00laG70TYc0ImaCkPfblwN1DY01/view?usp=sharing)

**Before You Start: Get Your URLs Ready**

*ASI:One Shared Chat URL*

- Go to https://asi1.ai and open the chat where you demo your agent.
- Click the search icon in the left sidebar.
- Under **Current chat**, click **Share chat**.
- Copy the link (e.g. `https://asi1.ai/shared-chat/...`).

*Agentverse Agent Profile URL*

- Go to https://agentverse.ai and open your agent.
- Go to the agent's profile page.
- Copy the URL (e.g. `https://agentverse.ai/agents/details/agent1q.../profile`).
- Repeat for each agent you built.

**Team Lead: Create Your Submission**

1. In ASI:One, message **Cal Hacks ASI:One Submission agent**.
   Something simple like "Hi" works.
2. On the welcome card, click **Create team (I'm the lead)**.
3. Fill in the required details:

| Field | Required? |
| :---- | :---- |
| Project name | **Yes** |
| Table number | Optional |
| Your name | **Yes** |
| Your email | **Yes** |
| Team size including you (1-4) | **Yes** |
| What problem does your project solve? | **Yes** |
| Public GitHub repository URL | **Yes** |
| Devpost project URL | **Yes** |
| Demo video URL | **Yes** |

*Bonus Points: Agentverse Agents & ASI:One Shared Chats (Optional)*

- **How many agents did you build?** Set the number.
- **Agent profile URLs:** Paste them, separated by commas.
- **How many shared chats?** Set the number.
- **Shared chat URLs:** Paste them, separated by commas.

4. Click **Continue to review**.
5. Check your details:
   1. Everything correct? Click **Confirm submission**.
   2. Need a change? Click **Edit details**, update the form, then **Continue to review** again.
6. After you confirm, you'll get a **Team ID** (e.g. lahacks-ce25ed57).
   Share it with your teammates.

**Teammates: Join Your Team**

1. In ASI:One, start a chat with **Cal Hacks ASI:One Submission agent** (e.g. "Hi").
2. Click **Join with Team ID**.
3. Enter the Team ID from your lead and click **Continue**.
4. Enter your name and email, then click **Join team**.

**Submission Status**

| Status | Meaning |
| :---- | :---- |
| **Incomplete** | Your details are saved. Still waiting for teammates to join. |
| **Submitted** | All teammates have joined. You're done! |

Note: The team lead can click **Edit details** any time before the deadline.

(The example Team ID says "lahacks", so this doc was probably reused from LA Hacks.
The steps should still apply.)

## 5. What this means for Earmark (checklist)

Human-only steps are marked **[HUMAN]**.

- [ ] **[HUMAN]** Create accounts at https://agentverse.ai and https://asi1.ai, and redeem the `CALHACKS26` / `CALHACKS26AV` codes.
- [ ] Memory agent implements the Agent Chat Protocol with `publish_manifest=True` (mandatory).
- [ ] **[HUMAN]** Connect the running agent to Agentverse via the Inspector, choosing Connect, then Mailbox (mandatory: registered on Agentverse).
- [ ] **[HUMAN]** On the Agentverse profile, set a name, a custom `@handle`, a description, and an avatar, and check that the README shows up (needed for discoverability).
- [ ] The full caregiver workflow works inside an ASI:One conversation, with no custom frontend (mandatory).
      Example: "Did Mom take her evening pills?" answered from Convex data, with timestamps.
- [ ] Tool execution is visible: the agent calls Convex read endpoints (mandatory: "meaningful tool execution").
      Multi-step reasoning, such as looking up objects, then events, then the adherence result, helps with "multi-step planning, reasoning, or orchestration."
- [ ] Repo README lists the agent name and `agent1q...` address, both badges, run instructions, and links to extra resources (Convex, Anthropic).
- [ ] The agent's own Agentverse README (`readme_path`) contains both badges (`innovationlab`, `hackathon`).
- [ ] Demo video of 3-5 minutes showing the agent (Fetch.ai deliverable; separate from the 2-minute Cal Hacks pitch).
- [ ] **[HUMAN]** Make an ASI:One shared chat URL and copy the Agentverse agent profile URL (bonus fields in the submission form).
- [ ] **[HUMAN]** Submit on Devpost, and register via the "Cal Hacks ASI:One Submission agent" in ASI:One (team lead creates the team; every teammate joins with the Team ID, or the status stays "Incomplete").
- [ ] Optional bonus: ASI Interactive Cards (for example a detail card for the medication log), Payment Protocol, or multi-agent.
      The brief doesn't mention any of these, so they are product decisions for the human.
- Deadline: Devpost says Oct 25, 2026 @ 9:00am PDT (https://cal-hacks-13-0.devpost.com/).
  The ASI:One submission agent is also needed, and Fetch.ai's docs don't give a separate deadline for it.
