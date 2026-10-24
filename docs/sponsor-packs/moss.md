# Moss - Cal Hacks 13.0 sponsor pack

Source: https://docs.google.com/document/d/1V6M4Mone7edq5bNJk6e4f7TFri1FSQEIFbVTRJXSBVU/edit?tab=t.0
Fetched 2026-10-24 via the public export URL `.../export?format=md` (no sign-in needed).
The `/pub` URL returned 401, but the txt, md and html exports all worked.
The document has a single tab (`t.0`).
The pack is short, so below is a full copy, reformatted, with links preserved.
Its section numbers jump from 01 to 04 to 06.
Sections 02, 03 and 05 are not in the document, so nothing was lost in the export.

## What the pack does NOT contain

- No prize description, no judging criteria, no required usage.
  See "Prize and judging (from Devpost)" below for what I found elsewhere.
- No code; it links to the docs instead.
  Technical notes are in `docs/vendor-notes/moss.md`.

## Full copy of the pack

**Getting Started with Moss - Hackathon Developer Guide**

Full documentation: https://docs.moss.dev (start with the Quickstart).

**About us.**
Moss combines sub-10 ms retrieval with optimized inference so AI agents can access the right context and respond in real time.
Use it to build voice assistants, personal agents with memory, and apps that answer questions from your own data.

### 01. Moss Retrieval

Moss runs retrieval in your application with sub-10 ms search.
Retrieve relevant documents and pass them to the model of your choice, while keeping control of your agent workflow.

- [Quickstart](https://docs.moss.dev/docs/start/quickstart): Create an index and search your data.
- [Sessions](https://docs.moss.dev/docs/integrate/sessions): Add and retrieve context during a live conversation.
- [Hybrid search](https://docs.moss.dev/docs/integrate/hybrid-search): Combine semantic and keyword search.

**Choosing an index model.**
Moss provides two complementary index models:

- Use a **session index** for data created or updated during a live interaction.
  Indexing and querying happen locally inside the application process.
  The session can optionally be persisted when the interaction ends.
- Use a **persistent index** for knowledge that must be shared across processes, containers, or deployments.
  The canonical index is maintained in Moss Cloud and loaded into each application process for local querying.

In production, create and update persistent indexes through a controlled ingestion workflow.
Serving containers should normally load an existing index at startup rather than recreate it every time a container starts.
If you want an index that persists in Moss cloud storage and can be loaded by other processes, use a cloud index instead of a session.
See [Sessions](https://docs.moss.dev/docs/integrate/sessions) and [Storage and persistence](https://docs.moss.dev/docs/integrate/storage-persistence) for when to use which.

### 04. Moss Inference

Moss Inference runs the retrieval and inference on the same host to reduce latency (<200 ms TTFT), and an OpenAI-compatible API makes it easy to use with your existing agent.

- [Python inference guide](https://docs.moss.dev/docs/reference/python/inference): Generate and stream answers from your indexes.
- [JavaScript inference guide](https://docs.moss.dev/docs/reference/js/inference): Use Moss Inference in a Node.js application.
- [Chat Completions API](https://docs.moss.dev/docs/api-reference/v1/inference/chat-completions): Connect an existing OpenAI-compatible client.

### 06. Documentation Credits

1. Open the [billing page](https://portal.usemoss.dev/dashboard/settings/billing) in the Moss Portal.
2. Enter the code `CALHACKS` to redeem your credits.

| Topic | URL |
| :---- | :---- |
| Documentation | https://docs.moss.dev/docs |
| GitHub | https://github.com/usemoss/moss |
| Discord | https://moss.link/discord |

## Credentials (from the official docs, not the pack)

- Sign in at https://portal.usemoss.dev, copy the **Project ID**, and create a key on the project's **API Keys** page.
  Source: https://docs.moss.dev/docs/start/quickstart and https://docs.moss.dev/docs/integrate/authentication
- A key is shown only once, at creation.
  New projects start with no key.
  Source: https://docs.moss.dev/docs/integrate/authentication
- Export them as `MOSS_PROJECT_ID` and `MOSS_PROJECT_KEY`.
- Redeem `CALHACKS` on the billing page before heavy use.
  The free Developer plan includes only 60 session minutes a month (https://docs.moss.dev/docs/pricing).

## Prize and judging (from Devpost, not the pack)

Source: https://cal-hacks-13-0.devpost.com/ (fetched 2026-10-24).

- Prize: **"[Moss] Best Use of Moss"**, 1 winner.
  Devpost shows "$996 in cash" and the description "Airpod Max/pros".
  It probably means AirPods worth $996 rather than cash - UNVERIFIED.
- Devpost lists no Moss-specific judging criteria.
- General Cal Hacks 13.0 judging criteria, copied from Devpost:
  - **Application:** feasible real-world use, clear benefit, who it helps and why they would use it.
  - **Intentionality:** intuitive, engaging experience, with purposeful design choices.
  - **Functionality:** works as intended, with a smooth live demo.
    "Submissions should also include a clear, meaningful video demo on devpost for sponsors evaluating asynchronously."
  - **Creativity:** original thinking, with unexpected combinations of ideas or technologies.
  - **Technical Complexity:** command of the frameworks and infrastructure, with sound architecture and engineering depth.
- Devpost deadline: Oct 25, 2026 @ 9:00am PDT.
- The Cal Hacks prizes page (https://hive.hackberkeley.org/prizes) renders its prizes client-side and showed only "Loading prizes..." to a plain fetch.
  I did not get past that.
  **Human action:** open that page in a browser (sign in if needed) and check for Moss-specific judging notes or required usage.
  You can also ask at the Moss table or in their Discord (https://moss.link/discord).
