# Bitdeer AI - sponsor pack summary (Cal Hacks 13.0)

Compiled 2026-10-24 by a read-only research agent.
The human has the starter pack as a PDF; this agent could not read it.
This file summarizes the PDF's contents as described in BUILD_BRIEF.md section 2.5, checked against Bitdeer's public version of the same starter pack and the Cal Hacks Devpost page.
Technical details (base URL, model IDs, tool calling, image input) are in `docs/vendor-notes/bitdeer.md`.

## Sources

- Bitdeer's public starter pack (blog post, Oct 23, 2026): https://www.bitdeer.ai/en/blog/bitdeer-ai-starter-pack-for-cal-hacks-13-0/
- Cal Hacks 13.0 Devpost prize list: https://cal-hacks-13-0.devpost.com/
- Workshop demo repo: https://github.com/BitdeerAI/cal-hacks-demo

The blog post matches the PDF description in the brief: the same steps, the same four model categories, and the same four linked resources.
Anything the PDF may add beyond that is unknown.

## What Bitdeer provides

Bitdeer says it is providing Model Studio API credits to all Cal Hacks 13.0 participants.
The credits apply to:

- **Chat models**, both text-only and multimodal (text plus image).
- **Embeddings:** `BAAI/bge-m3`, for semantic search, RAG, and clustering.
- **Reranker:** `BAAI/bge-reranker-v2-m3`, for reordering search results.
- **Image generation:** listed as `byteplus/Seedream-5.0-Lite`.
  The live catalog and pricing API call it `seedream-5.0-lite`.

Source: https://www.bitdeer.ai/en/blog/bitdeer-ai-starter-pack-for-cal-hacks-13-0/

The credit amount per participant or team is not stated in the public pack (UNVERIFIED; ask the human what the form granted).

## Getting started steps

1. Create an account at https://www.bitdeer.ai/en.
2. Submit the credit request form to receive Model Studio credits.
   Form: https://docs.google.com/forms/d/e/1FAIpQLSenQ5h8j2zyccRnxb0QLli6isVeb72lT32HjUmKA5v4BCdiNA/viewform
3. Open **Model Studio** in the left sidebar after signing in.
   From there you can create an API key, explore and test models, and monitor credit usage.
   Direct links: model explorer https://www.bitdeer.ai/en/model/explore and API keys https://www.bitdeer.ai/en/model/apikeys.
   The key is shown only once when generated (https://developers.bitdeer.ai/docs/guides/getting-started/authentication).

Source for steps 1 to 3: https://www.bitdeer.ai/en/blog/bitdeer-ai-starter-pack-for-cal-hacks-13-0/

## Linked resources

| Resource | URL | Notes |
|---|---|---|
| Getting Started Guide | https://developers.bitdeer.ai/docs/guides/getting-started | Installation, authentication, first request |
| Model Catalog | https://developers.bitdeer.ai/docs/api/models-catalog | 7 chat models plus embeddings, reranker, image generation as of 2026-10-24 |
| Integrations | https://developers.bitdeer.ai/docs/guides/integrations | Cursor, Claude Code CLI, Codex, LangChain, OpenAI Agents SDK, Dify, LiteLLM |
| Workshop Demo Code (Python) | https://github.com/BitdeerAI/cal-hacks-demo | Simple call, streaming, multimodal (base64 image), and a RAG project with embeddings and rerank |

The demo code is for a "1-hour technical workshop".
The workshop time is not given in the pack or on the Cal Hacks pages checked (UNVERIFIED).
The repo was last updated 2026-10-22, so the material is available now whether or not the session has happened.

Caution: the demo code uses `deepseek-ai/DeepSeek-V4.1-Flash`, which Bitdeer removes on 2026-10-26, and `moonshotai/Kimi-K3`, which is not in the public catalog.
Use `deepseek-ai/DeepSeek-V4.1-Flash-1017` instead, and see the vendor notes for the full list.
Source: https://developers.bitdeer.ai/docs/guides/deprecations/deprecation-history

## Support

- Email: kehan.jin@bitdeer.com (the contact address on the starter pack page).
- The Cal Hacks Slack channel.

Source: https://www.bitdeer.ai/en/blog/bitdeer-ai-starter-pack-for-cal-hacks-13-0/

## Prizes

From the Cal Hacks 13.0 Devpost prize list (https://cal-hacks-13-0.devpost.com/):

| Prize | Award |
|---|---|
| [Bitdeer AI] 1st Place Best Use of Bitdeer AI Model Studio | USD 500 in Bitdeer AI Model Studio credits for the winning team, plus four gaming mice (one per teammate) |
| [Bitdeer AI] 2nd Place Best Use of Bitdeer AI Model Studio | USD 200 in Bitdeer AI Model Studio credits for the winning team, plus one LEGO Technic set for the team |

Devpost's headline value for these prizes reads "$500 in cash" and "$200 in cash", but the descriptions say the award is Model Studio credits.
Treat it as credits unless Bitdeer says otherwise (UNVERIFIED).

No judging criteria for the Bitdeer prize were published on the pages found (UNVERIFIED).
The prize name, "Best Use of Bitdeer AI Model Studio", suggests that visible, load-bearing use of several Model Studio capabilities matters.
That fits BUILD_BRIEF section 6, which plans three distinct Bitdeer uses (text chat, tool calling, multimodal) and asks for each to be attributed in the logs and the Devpost write-up.

## What the pack does not cover

- The credit amount.
- Judging criteria for the Bitdeer prize.
- The workshop time and room.
- Rate limits and latency.
  The docs give a default of 100 requests per minute (https://developers.bitdeer.ai/docs/api/errors); latency is covered in `docs/vendor-notes/bitdeer.md`.
- That reasoning is on by default for every chat model.
  This matters a lot for Earmark's latency budgets; see the vendor notes, section 5.
