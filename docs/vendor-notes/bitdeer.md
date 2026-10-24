# Bitdeer AI (Model Studio) - vendor notes for Earmark

Researched 2026-10-24 by a read-only research agent.
Every claim has a source URL.
Anything not confirmed against an official page is marked UNVERIFIED.
No Bitdeer API key was available, so nothing here has been run against an authenticated endpoint.
The starter pack summary is in `docs/sponsor-packs/bitdeer.md`.

Tip for agents: the per-model capability flags in section 2 come from the public JSON API that powers the Model Studio site.
`POST https://www.bitdeer.ai/api/model/v1/ListModels` with body `{}` lists models, and `POST https://www.bitdeer.ai/api/model/v1/GetModel` with body `{"modelId": "mdl-..."}` returns one model's details (context length, reasoning levels, tool support, code samples).
Both are undocumented site endpoints, readable without a key.
The same data renders at https://www.bitdeer.ai/en/model/explore.

## TL;DR

- **Base URL:** `https://api-inference.bitdeer.ai/v1`.
  **Auth:** `Authorization: Bearer <BITDEER_API_KEY>`.
  The official `openai` Python and JS packages work by setting `base_url` / `baseURL`.
- **Tool calling:** supported (`tools`, `tool_choice`, `parallel_tool_calls`, `tool_calls` in the response), and every current chat model is flagged `supportFunctionCalling: true`.
  Structured output (`response_format` `json_schema` and `json_object`) is supported too.
- **Biggest risk:** every chat model has **reasoning ON by default** (`high`, `max`, or `xhigh`).
  Artificial Analysis measured Bitdeer at 12.8 to 17.3 s end-to-end with reasoning on.
  For the 1.5 s concierge budget and the 5 s photo budget you must send `reasoning_effort: "none"`, and only models that can disable reasoning qualify.
  The GLM models cannot disable reasoning.
- **Recommended IDs (all UNVERIFIED for latency until a Phase 0 benchmark):**
  - Concierge tool selection: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B` with `reasoning_effort: "none"`, benchmarked against `deepseek-ai/DeepSeek-V4.1-Flash-1017`.
  - Memory agent: `deepseek-ai/DeepSeek-V4.1-Flash-1017`.
  - Photo labeling: `deepseek-ai/DeepSeek-V4.1-Flash-1017` with `reasoning_effort: "none"` and a `json_schema` response format, A/B tested against `Qwen/Qwen3.8-27B`.
- **Image input:** OpenAI-style `image_url` content parts, either an https URL (which must be public, because Bitdeer's server downloads it) or a `data:image/jpeg;base64,...` URL.
  Keep base64 images under about 1 MB.
- **Model churn is fast:** 7-day deprecation notice, no redirect from old IDs.
  The docs' own code samples use removed models (`deepseek-ai/DeepSeek-V4-Pro`, `moonshotai/Kimi-K2.6`), so never copy model IDs from guide snippets.
  `deepseek-ai/DeepSeek-V4.1-Flash` (used in the workshop demo code) is removed on 2026-10-26.
- **Limits:** default 100 requests per minute on every endpoint.
  Running out of credits returns HTTP 403 `NOT_ENOUGH_BALANCE`, not 429.

## 1. Endpoint, auth, clients

| Fact | Detail | Source |
|---|---|---|
| Base URL | `https://api-inference.bitdeer.ai/v1` | https://developers.bitdeer.ai/docs/api |
| Auth header | `Authorization: Bearer {API_KEY}` | https://developers.bitdeer.ai/docs/api/authentication |
| Get a key | Console, Models -> API Keys (https://www.bitdeer.ai/en/model/apikeys), "Generate API Key". The secret is shown only once. | https://developers.bitdeer.ai/docs/guides/getting-started/authentication |
| Python client | `pip install openai`, then `OpenAI(api_key=..., base_url="https://api-inference.bitdeer.ai/v1")`. Python 3.10+. Sync and async (`AsyncOpenAI`) both shown. Default client timeout is 600 s. | https://developers.bitdeer.ai/docs/guides/sdks/python and https://developers.bitdeer.ai/docs/guides/getting-started/installation |
| JS client | `npm install openai`, then `new OpenAI({ apiKey, baseURL: "https://api-inference.bitdeer.ai/v1" })`. Node 20+. | https://developers.bitdeer.ai/docs/guides/sdks/javascript |
| Env var name used by docs | `BITDEER_API_KEY` | https://developers.bitdeer.ai/docs/guides/sdks/python |
| Documented endpoints | `POST /v1/chat/completions` (streaming, tools, vision), `POST /v1/embeddings`, `POST /v1/rerank`, `GET /v1/models` | https://developers.bitdeer.ai/docs/api |
| Extra protocols | Model pages also show the OpenAI Responses API (`POST /v1/responses`, `client.responses.create`) and an Anthropic-compatible Messages API (`anthropic.Anthropic(auth_token=KEY, base_url="https://api-inference.bitdeer.ai")`, `POST /v1/messages`). | `GetModel` API `apiSamples` field (see the tip above); also https://www.bitdeer.ai/en/blog/how-bitdeer-ai-builds-more-reliable-and-efficient-model-apis/ |
| Integrations guides | Cursor, Claude Code CLI, Codex, LangChain, OpenAI Agents SDK, Dify, LiteLLM | https://developers.bitdeer.ai/docs/guides/integrations |

The OpenAI Agents SDK guide configures Bitdeer purely with `OPENAI_API_KEY` and `OPENAI_BASE_URL` env vars.
Source: https://developers.bitdeer.ai/docs/guides/integrations/openai-agents-sdk

Observed from this Mac on 2026-10-24 (no key, so only the auth gateway answered):
- The host is behind Cloudflare (edge `SJC` in the `cf-ray` header).
- Unauthenticated `POST /v1/chat/completions` returned a JSON 401 with time to first byte of about 0.22 s.
- Unauthenticated `GET /v1/models` returned a plain-text `Unauthorized` body (not the documented JSON error shape) after about 0.6 s.
- This only measures the network and gateway, not inference.

## 2. Model catalog (as of 2026-10-24)

Sources:
- Model Catalog: https://developers.bitdeer.ai/docs/api/models-catalog
- Pricing page: https://www.bitdeer.ai/en/pricing/ai-models (rendered from `POST https://www.bitdeer.ai/api/model/v1/ListPublicModelPricings`)
- Per-model flags: `GetModel` API (see the tip at the top)
- Removal dates: https://developers.bitdeer.ai/docs/guides/deprecations/deprecation-history

The pricing API returns prices in **US cents** (the site's price component names them `promoCents` / `originalCents`).
The table converts them to USD per 1M tokens.
Most prices are currently discounted (for example 52% off on DeepSeek-V4.1-Flash-1017).

### Chat models

| Model ID | Input | Context | Max output | Params | Reasoning levels (default) | Can disable reasoning | Tools | Structured output | USD per 1M in / out (cached in) | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `deepseek-ai/DeepSeek-V4.1-Flash-1017` | text, image | 1,048,576 | 393,216 | 552B (16B active) | none, low, high, max (high) | yes | yes | yes | 0.144 / 0.576 (0.0029) | current, created 2026-10-19 |
| `zai-org/GLM-5.3` | text | 1,048,576 | 131,072 | 753B | low, high, max (max) | **no** | yes | yes | 0.63 / 1.98 (0.117) | current |
| `zai-org/GLM-5.3-Flash` | text, image | 1,048,576 | 131,072 | 320B (18B active) | low, high, max (max) | **no** | yes | yes | 0.0825 / 0.275 (0.0165) | current |
| `Qwen/Qwen3.8-27B` | text, image | 262,144 | 131,072 | 27B dense | low, medium, xhigh (xhigh) | yes | yes | yes | 0.40 / 2.40 (0.08) | current |
| `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B` | text, image | 262,144 | not stated | 120B (12B active) | not listed; on by default, off with `"reasoning_effort": "none"` | yes | yes | yes | 0.10 / 0.40 (0.08) | current, created 2026-10-15 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | text, image | 1,048,576 | 393,216 | 552B (16B active) | none, low, high, max (high) | yes | yes | yes | 0.144 / 0.576 | **removed 2026-10-26**, replacement `-1017` |
| `deepseek-ai/DeepSeek-V4-Flash` | text | 1,048,576 | 393,216 | 284B (13B active) | none, low, high, max (high) | yes | yes | yes | 0.14 / 0.28 | **removal date 2026-10-23 has passed**, but it is still listed on 2026-10-24 |

"Max output" is the model page's `maxOutputTokens`.
The per-request `max_tokens` default shown in Model Studio is 32,768 for every chat model, so always set `max_tokens` yourself.
Source: `GetModel` API `modelConfigParams`.

### Specialized models (not used by Earmark, per BUILD_BRIEF section 3)

| Model ID | Task | Context | Price |
|---|---|---|---|
| `BAAI/bge-m3` | Embeddings | 8,192 | USD 0.01 per 1M tokens |
| `BAAI/bge-reranker-v2-m3` | Reranker (`POST /v1/rerank`) | 8,192 | USD 0.01 per 1M tokens |
| `seedream-5.0-lite` | Text-to-image (`client.images.generate`), `n` up to 2 | - | USD 0.035 per image |

### Mentioned elsewhere but not in the catalog

- `moonshotai/Kimi-K3` is used by the workshop's `3_multimodal.py`, appears in an Oct 23 Bitdeer blog list of available models, and is the recommended replacement for several retired models.
  It is **not** in the Model Catalog or in the public `ListModels` API.
  UNVERIFIED whether your account can call it; check `GET /v1/models` with a key.
  Sources: https://github.com/BitdeerAI/cal-hacks-demo/blob/main/3_multimodal.py, https://www.bitdeer.ai/en/blog/how-bitdeer-ai-builds-more-reliable-and-efficient-model-apis/, https://developers.bitdeer.ai/docs/guides/deprecations/deprecation-history
- Retired IDs that the guide snippets still use: `deepseek-ai/DeepSeek-V4-Pro` (removed 2026-09-22, replacement `zai-org/GLM-5.3`) and `moonshotai/Kimi-K2.6` (removed 2026-09-22, replacement `moonshotai/Kimi-K3`).
  Source: https://developers.bitdeer.ai/docs/guides/deprecations/deprecation-history

### Third-party latency of Bitdeer's endpoint (reasoning ON)

Artificial Analysis benchmarks Bitdeer AI as a provider for two of these models.
These runs use reasoning (DeepSeek at `max`), so they show the default-settings worst case, not the `reasoning_effort: "none"` case Earmark needs.

| Model on Bitdeer | Median output tokens/s | Median first chunk (s) | Total response (s) | Of which reasoning (s) | Fastest provider for comparison | Source |
|---|---|---|---|---|---|---|
| DeepSeek V4.1 Flash (max) | 164 | 2.04 | 17.26 | 12.17 | LithosAI: 604 t/s, 0.89 s | https://artificialanalysis.ai/models/deepseek-v4-1-flash/providers |
| GLM-5.3-Flash | 220 | 1.42 | 12.77 | 9.08 | see page | https://artificialanalysis.ai/models/glm-5-3-flash/providers |

The page says the speed and latency figures are medians over the past 72 hours.
The input size AA used for these runs was not checked (UNVERIFIED).
Bitdeer is not an OpenRouter provider for any of these models, so OpenRouter has no Bitdeer latency data (checked via `https://openrouter.ai/api/v1/models/<id>/endpoints`).

## 3. Recommendations for Earmark

Keep every model ID in env vars (the brief already requires this, and Bitdeer's lifecycle page says the same).
Suggested names: `BITDEER_API_KEY`, `BITDEER_BASE_URL`, `BITDEER_TOOL_MODEL`, `BITDEER_AGENT_MODEL`, `BITDEER_VISION_MODEL`.
Source for the lifecycle advice: https://developers.bitdeer.ai/docs/guides/deprecations/lifecycle-guidelines

### 3.1 Concierge tool selection (1.5 s timeout)

**Recommend:** `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B` with `reasoning_effort: "none"`.
**Alternative to benchmark against it:** `deepseek-ai/DeepSeek-V4.1-Flash-1017` with `reasoning_effort: "none"`.

Why:
- It has the fewest active parameters (12B) of the models that support tools and can fully disable reasoning, and it uses a hybrid Mamba-Transformer design with multi-token prediction.
  Source: `GetModel` API `modelIntro` for this model and https://www.bitdeer.ai/en/blog/nvidia-nemotron-3-5-super-vl/
- Its Bitdeer page is the only one that documents the reasoning-off switch for this platform explicitly: `"reasoning_effort": "none"` on OpenAI-compatible APIs.
  It also states that tool calling and JSON-schema structured output are supported.
- It is the cheapest tool-capable model that can disable reasoning (USD 0.10 / 0.40 per 1M).
- DeepSeek on Bitdeer showed a 2.04 s first chunk in the AA run, already over the 1.5 s budget, though that run had reasoning on.
- GLM-5.3 and GLM-5.3-Flash are ruled out because reasoning cannot be disabled (`canDisableReasoning: false`, minimum level `low`).
  Source: `GetModel` API, plus the GLM-5.3 model page note that "Disabling reasoning is no longer supported".
- The speed claim is UNVERIFIED on Bitdeer.
  No third-party benchmark of this model on Bitdeer was found.

Phase 0 benchmark (do this before wiring the concierge):
1. Create one client and reuse it, so later calls reuse the TLS connection.
2. Send 20 identical tool-selection requests to each candidate with the real system prompt and the 7 tool schemas.
3. Record p50 and p95 wall time, and check that each response has exactly one `tool_calls` entry with valid JSON arguments.
4. Pick the model with p95 under about 1.3 s.
   If neither gets there, the keyword fallback grammar in 5.D will fire on most turns, so tell the human.

Request shape (Python, matches the official function-calling guide plus the reasoning switch):

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["BITDEER_API_KEY"],
    base_url=os.environ.get("BITDEER_BASE_URL", "https://api-inference.bitdeer.ai/v1"),
    timeout=1.5,     # the SDK default is 600 s
    max_retries=0,   # the SDK retries twice by default, which would blow the budget
)

resp = client.chat.completions.create(
    model=os.environ["BITDEER_TOOL_MODEL"],
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},  # keep byte-identical across turns
        {"role": "user", "content": transcript},
    ],
    tools=TOOLS,                 # locate_object, guide_to_object, chirp_fob, ...
    tool_choice="required",      # the brief says exactly one tool per turn
    parallel_tool_calls=False,
    max_tokens=200,
    temperature=0,
    extra_body={"reasoning_effort": "none"},
)
call = resp.choices[0].message.tool_calls[0]
name, args = call.function.name, call.function.arguments  # arguments is a JSON string
```

Notes:
- `extra_body` sends the field untouched, which avoids depending on whether the installed `openai` version's type hints include `"none"`.
  Passing `reasoning_effort="none"` directly should also work.
- The brief computes the spoken reply in code, so the concierge never needs a second round trip with a `role: "tool"` message.
  That halves latency and avoids the schema gap noted in section 4.
- Put the system prompt and tool list first and keep them identical between calls.
  Bitdeer says it uses prefix caching to improve time to first token, and it bills cached input at a lower rate.
  Source: https://www.bitdeer.ai/en/blog/how-bitdeer-ai-builds-more-reliable-and-efficient-model-apis/
- `tool_choice: "required"` is documented ("forces a tool call"), but whether every model honors it is UNVERIFIED.
  Validate the result in code regardless.

### 3.2 Memory agent reasoning (no tight latency budget)

**Recommend:** `deepseek-ai/DeepSeek-V4.1-Flash-1017`.
- Strong agentic model, 1M context, tools and structured output supported, cheap (USD 0.144 / 0.576 per 1M).
  Source: `GetModel` API.
- Use the standard tool loop from the function-calling guide: append the assistant message, then a `{"role": "tool", "tool_call_id": ..., "content": ...}` message, then call again.
  Source: https://developers.bitdeer.ai/docs/guides/llm/function-calling
- Start with `reasoning_effort: "low"`.
  The default `high` costs about 9 to 12 s per answer on Bitdeer (section 2), which is slow for a chat reply through ASI:One.
- Do not use `deepseek-ai/DeepSeek-V4.1-Flash` without the `-1017` suffix; it is removed on 2026-10-26.

### 3.3 Photo-assisted labeling (one photo, under 5 s)

**Recommend:** `deepseek-ai/DeepSeek-V4.1-Flash-1017` with `reasoning_effort: "none"` and `response_format` `json_schema`.
**A/B in Phase 0 against:** `Qwen/Qwen3.8-27B` (also reasoning off).
**Fallback:** `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B`.

Why:
- DeepSeek-V4.1-Flash-1017 is the largest current multimodal model, natively multimodal, and its release notes claim "substantial improvements" on visual benchmarks over V4.1-Flash.
  Source: `GetModel` API `modelDesc`.
- Reading printed labels matters for look-alike items (salt versus sugar, two pill bottles).
  Qwen3.8-27B is a native vision-language model and Qwen's VL line has a strong record on text in images, so it is the right A/B candidate.
  Which one is better on real household photos is UNVERIFIED; test 5 to 10 real photos.
  If you use Qwen with reasoning off, its model page recommends `temperature=0.7`, `top_p=0.8`, `presence_penalty=1.5`.
  Source: `GetModel` API `modelIntro` for `Qwen/Qwen3.8-27B`.
- Using one model ID for both the memory agent and labeling keeps configuration small; that is a convenience, not a requirement.

Request shape (TypeScript, for the Convex action):

```ts
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.BITDEER_API_KEY,
  baseURL: "https://api-inference.bitdeer.ai/v1",
  timeout: 5000,
  maxRetries: 0,
});

const resp = await client.chat.completions.create({
  model: process.env.BITDEER_VISION_MODEL!,
  messages: [
    {
      role: "user",
      content: [
        { type: "image_url", image_url: { url: `data:image/jpeg;base64,${b64}` } },
        { type: "text", text: LABEL_PROMPT },
      ],
    },
  ],
  response_format: {
    type: "json_schema",
    json_schema: {
      name: "item_label",
      strict: true,
      schema: {
        type: "object",
        properties: {
          name: { type: "string" },
          aliases: { type: "array", items: { type: "string" } },
          description: { type: "string" },
        },
        required: ["name", "aliases", "description"],
      },
    },
  },
  max_tokens: 300,
  reasoning_effort: "none", // Bitdeer extension; if the installed SDK's types reject "none", pass it through an untyped object
});
const suggestion = JSON.parse(resp.choices[0].message.content ?? "{}");
```

Send the photo as a base64 data URL from the Convex action rather than as a storage URL.
An https URL would have to be publicly reachable for Bitdeer's server to download it, which works against the brief's "delete the photo, store only text" story.
Downscale in the browser before upload (for example longest edge 1024 px, JPEG) to stay under the 1 MB guidance.

## 4. Tool calling and structured output

| Fact | Detail | Source |
|---|---|---|
| Request fields | `tools` ("Currently, only functions are supported as a tool"), `tool_choice`, `parallel_tool_calls` | https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |
| `tool_choice` values | `none`, `auto`, `required` ("forces a tool call"), or an object to force a specific function | same |
| Function schema | `{type: "function", function: {name, description, parameters (JSON Schema), strict}}`. Name: a-z, A-Z, 0-9, underscores or dashes, max 64 chars. `strict: true` makes the model follow the schema strictly. | https://developers.bitdeer.ai/docs/guides/llm/function-calling |
| Response | `choices[0].message.tool_calls[]` with `id`, `type: "function"`, `function.name`, `function.arguments` (a JSON string). `finish_reason` can be `tool_calls`. Streaming deltas also carry `tool_calls`. | https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |
| Tool result turn | Append the assistant message, then `{"role": "tool", "tool_call_id": ..., "content": ...}` | https://developers.bitdeer.ai/docs/guides/llm/function-calling |
| Which models | `supportFunctionCalling: true` and `supportStructuredOutput: true` for all 7 current chat models | `GetModel` API |
| Caveat from Bitdeer | "Tool calling is model-specific. Confirm that your model exposes tools / function calling in the Model Catalog and the Bitdeer console before shipping agents that depend on it." | https://developers.bitdeer.ai/docs/guides/integrations/openai-agents-sdk |
| `response_format` | `text`, `json_object` (valid JSON, no schema), `json_schema` (recommended; `{name, schema, strict}`) | https://developers.bitdeer.ai/docs/guides/llm/structured-outputs |
| Strict schema rules | Types: string, number, integer, boolean, array, object, enum, anyOf. All object properties must be listed explicitly. Unsupported schemas return an error. | https://developers.bitdeer.ai/docs/guides/llm/structured-outputs |

UNVERIFIED:
- Whether `tool_choice: "required"` and named-function forcing are honored by each model.
- Whether `tools` and `response_format` can be combined in one request (Earmark does not need this).
- Whether `strict: true` on a function is enforced server-side or only passed to the model.
- The API reference request schema lists message roles as only `system`, `user`, `assistant`, while the function-calling guide sends `role: "tool"`.
  The guide is probably right and the schema incomplete, but test it in the memory agent.

## 5. Reasoning controls (critical for latency)

| Fact | Detail | Source |
|---|---|---|
| Default | Reasoning is on for every chat model: DeepSeek `high`, GLM `max`, Qwen `xhigh`, Nemotron on | `GetModel` API `defaultReasoningEffort`, Nemotron `modelIntro` |
| Switch | `"reasoning_effort": "none"` on OpenAI-compatible APIs; `"thinking": {"type": "disabled"}` on the Anthropic-compatible API | Nemotron `modelIntro` ("Using It on Bitdeer AI" section) |
| Allowed values | DeepSeek: `none`, `low`, `high`, `max`. Qwen: `low`, `medium`, `xhigh`, and reasoning can be disabled. GLM: `low`, `high`, `max`, cannot be disabled. | `GetModel` API `supportedReasoningEffort`, `canDisableReasoning`; also the Chinese catalog's reasoning-level column at https://developers.bitdeer.ai/zh/docs/api/models-catalog |
| Where reasoning text appears | Nemotron: `message.reasoning` (explicitly "not `reasoning_content`"). The API reference documents `message.reasoning_content` "if separate_reasoning was requested". | Nemotron `modelIntro`; https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |

UNVERIFIED:
- `reasoning_effort: "none"` is documented only on the Nemotron page; for DeepSeek and Qwen it is inferred from the `supportedReasoningEffort` / `canDisableReasoning` flags.
- The API reference request schema does not list `reasoning_effort` (or `seed`, which Bitdeer's own model samples send) and declares `additionalProperties: false`.
  The schema looks incomplete rather than enforced, but confirm in Phase 0 that the server accepts the field and that responses get faster.
- `separate_reasoning` is mentioned in a response field description but is not a documented request parameter.

## 6. Multimodal (image) input

| Fact | Detail | Source |
|---|---|---|
| Format | OpenAI-style content array: `{"type": "image_url", "image_url": {"url": ...}}` plus `{"type": "text", ...}` | https://developers.bitdeer.ai/docs/guides/llm/vision |
| URL kinds | https URL, or base64 data URL `data:image/jpeg;base64,<b64>` ("Either a URL of the image or base64 encoded image data") | https://developers.bitdeer.ai/docs/guides/llm/vision and https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |
| Size | "Base64-encoded images should ideally be under 1 MB to avoid timeouts." No hard limit is documented. | https://developers.bitdeer.ai/docs/guides/llm/vision |
| Image count | The vision guide shows multiple images per request, but the Nemotron page says "One image per request". Earmark sends one, so this does not matter. | same, and Nemotron `modelIntro` |
| Public URLs | "Image URLs are downloaded by the server, so they must be publicly reachable; for private or local images, send base64." | Nemotron `modelIntro` |
| Billing | Image tokens are billed together with text tokens | https://developers.bitdeer.ai/docs/guides/llm/vision |
| Streaming | Supported with vision inputs | https://developers.bitdeer.ai/docs/guides/llm/vision |
| Which models | Image-to-Text tag: DeepSeek-V4.1-Flash-1017, GLM-5.3-Flash, Qwen3.8-27B, Nemotron-3.5-Super-VL (and the retiring DeepSeek-V4.1-Flash) | https://developers.bitdeer.ai/docs/api/models-catalog |
| Other parts | The schema also has `video_url` and `input_audio` content parts (not needed by Earmark) | https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |

Do not copy the model from the vision guide: it uses `moonshotai/Kimi-K2.6`, which was removed on 2026-09-22.

## 7. Streaming

- `stream: true` returns Server-Sent Events.
  Each line is `data: <json chunk>` and the stream ends with `data: [DONE]`.
  "All text generation models support streaming."
  Source: https://developers.bitdeer.ai/docs/guides/llm/streaming
- `stream_options: {"include_usage": true}` adds a final chunk with `usage` before `[DONE]`.
  Source: same page.
- The workshop's streaming demo skips chunks with empty `choices` (`if not chunk.choices: continue`), which you need when the usage chunk is on.
  Source: https://github.com/BitdeerAI/cal-hacks-demo/blob/main/2_streaming_output.py
- Earmark's concierge tool call is short (a few dozen tokens), so non-streaming is simpler and costs almost nothing extra.

## 8. Rate limits, errors, credits

| Fact | Detail | Source |
|---|---|---|
| Rate limit | Default 100 requests per minute for all endpoints; exceeding it returns 429 `RATE_LIMIT_EXCEEDED` | https://developers.bitdeer.ai/docs/api/errors |
| Token limit | 429 `TOKEN_LIMIT_EXCEEDED` exists; the token limit value is not documented (UNVERIFIED) | same |
| Out of credits | 403 `NOT_ENOUGH_BALANCE` | same |
| Unknown model | 404 `MODEL_NOT_FOUND`. This is what a retired model ID returns: "There is no fallback routing to another model, and no redirect". | same, and https://developers.bitdeer.ai/docs/guides/deprecations/lifecycle-guidelines |
| Retryable | 429 and 503 only. 400, 401, 403, 404, and 500 are marked not retryable. | https://developers.bitdeer.ai/docs/api/errors |
| Error body | `{"error": {"message", "type", "param", "code"}}` | same |
| Deprecation notice | 7 days for Model Studio serverless models, possibly shorter; email to accounts with recent traffic | https://developers.bitdeer.ai/docs/guides/deprecations/lifecycle-guidelines |
| Client advice | Set a timeout that fits the scenario, retry with a capped count and backoff, and control context length | https://www.bitdeer.ai/en/blog/how-bitdeer-ai-builds-more-reliable-and-efficient-model-apis/ |
| Content safety | Bitdeer-proprietary request flags `enable_guard` (content moderation) and `sync_guard` (synchronous check). The response then carries `guard_usage`, `guard_check_result`, or `guard_task_id`. Possibly useful for the Microsoft "responsible design" criterion in the memory agent. Behavior and cost are UNVERIFIED. | https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion |

## 9. Gotchas

1. Reasoning is on by default everywhere; without `reasoning_effort: "none"` the concierge will always miss 1.5 s (section 5).
2. The guides' code samples use retired model IDs (`deepseek-ai/DeepSeek-V4-Pro`, `moonshotai/Kimi-K2.6`), and the workshop code uses `deepseek-ai/DeepSeek-V4.1-Flash`, which retires 2026-10-26.
   Always take IDs from the Model Catalog or `GET /v1/models`.
3. The catalog can lag the deprecation list: `deepseek-ai/DeepSeek-V4-Flash` is still listed although its removal date (2026-10-23) has passed.
4. The `openai` SDKs default to a 600 s timeout and 2 retries; set `timeout` and `max_retries=0` (Python) or `maxRetries: 0` (JS) for latency-bound calls.
   Sources: https://developers.bitdeer.ai/docs/guides/sdks/python (timeout) and https://github.com/openai/openai-python#retries (retries).
5. The Model Studio default `max_tokens` is 32,768; set a small explicit `max_tokens`.
6. Reasoning text is in `message.reasoning` for Nemotron but `message.reasoning_content` per the API reference; do not depend on either field.
7. Image URLs must be public; use base64 for private photos.
8. The image generation model ID is `seedream-5.0-lite` in the catalog and pricing API but `byteplus/Seedream-5.0-Lite` in the starter pack and deprecation history (Earmark does not use it).
9. `GET /v1/models` without a valid key returns a plain-text 401 body, not JSON, so error parsing should not assume JSON.

## 10. Python workshop demo code

Repo: https://github.com/BitdeerAI/cal-hacks-demo ("Cal Hacks demo code from workshop."), last commit 2026-10-22.

| File | What it shows | Model used |
|---|---|---|
| `1_simple_call.py` | Basic `client.chat.completions.create` with `max_tokens=128` | `deepseek-ai/DeepSeek-V4.1-Flash` (retires 2026-10-26) |
| `2_streaming_output.py` | `stream=True`, skipping chunks with no `choices` | `deepseek-ai/DeepSeek-V4.1-Flash` |
| `3_multimodal.py` | Reads `image_1.jpg`, sends it as `data:image/jpeg;base64,...` in an `image_url` part with a text prompt | `moonshotai/Kimi-K3` (not in the public catalog) |
| `4_RAG_project/embeddings.py` | Embeds the Bitdeer docs into a local Chroma DB with `client.embeddings.create(model="BAAI/bge-m3")` | `BAAI/bge-m3` |
| `4_RAG_project/rag_app.py` | Retrieves 15 docs, reranks with `client.post("/rerank", cast_to=object, body={"model": "BAAI/bge-reranker-v2-m3", "query": ..., "documents": ..., "top_n": 5})`, then answers with chat | `BAAI/bge-reranker-v2-m3`, `deepseek-ai/DeepSeek-V4.1-Flash` |

Every script uses the same client setup:

```python
client = OpenAI(
    api_key=os.environ["BITDEER_API_KEY"],
    base_url="https://api-inference.bitdeer.ai/v1",
)
```

The `4_RAG_project/guides/` folder is a snapshot of Bitdeer's docs source (MDX), useful for offline reading, but its model tables are older than the live catalog.

## 11. Where BUILD_BRIEF.md differs from official material

1. **Image generation model ID.**
   The brief (from the starter pack) says `byteplus/Seedream-5.0-Lite`; the live catalog and pricing API say `seedream-5.0-lite`.
   Not used by Earmark, so it has no impact.
2. **Latency budgets assume a fast model but do not mention reasoning.**
   5.D's 1.5 s tool-selection timeout and 5.F's "under 5 seconds" photo suggestion are both impossible with Bitdeer's default reasoning (12.8 to 17.3 s measured end-to-end).
   Add `reasoning_effort: "none"` to both, and do not pick a GLM model for either.
3. **"Verify in Phase 0 that the chosen chat model supports tool calling."**
   Official material answers yes for every current chat model, and `json_schema` structured output is also supported, so the JSON fallback in 5.D is available if needed.
   A live check is still worth doing (section 4 UNVERIFIED items).
4. **5.F photo privacy.**
   If the Convex action passed a storage URL, Bitdeer would need that URL to be publicly reachable.
   Send base64 instead so the photo never has to be exposed.
5. **Starter pack links.**
   The brief says to find the Getting Started guide, Model Catalog, Integrations guide, and workshop code or ask the human.
   All four were found and are listed in `docs/sponsor-packs/bitdeer.md`; no need to ask.
6. Everything else in the brief matches: OpenAI-compatible endpoint (section 3 Tech choices), env-var model IDs (5.D), and the "chat, multimodal chat, embeddings, reranker, image generation" model list (2.5).

## 12. Open questions for the human

1. Has the Bitdeer account been created and the credit request form submitted?
   How many credits were granted?
   The amount is not published.
2. Once a key exists, run `GET /v1/models` and confirm which IDs the account can call, especially `moonshotai/Kimi-K3`.
3. When is (or was) the 1-hour Bitdeer technical workshop?
   The time is not published on the pages found.
4. Should the memory agent use Bitdeer's `enable_guard` content moderation as part of the responsible-design story?

## Sources

- https://developers.bitdeer.ai/docs/guides
- https://developers.bitdeer.ai/docs/guides/getting-started
- https://developers.bitdeer.ai/docs/guides/getting-started/installation
- https://developers.bitdeer.ai/docs/guides/getting-started/authentication
- https://developers.bitdeer.ai/docs/guides/getting-started/first-request
- https://developers.bitdeer.ai/docs/guides/llm
- https://developers.bitdeer.ai/docs/guides/llm/streaming
- https://developers.bitdeer.ai/docs/guides/llm/vision
- https://developers.bitdeer.ai/docs/guides/llm/function-calling
- https://developers.bitdeer.ai/docs/guides/llm/structured-outputs
- https://developers.bitdeer.ai/docs/guides/sdks/python
- https://developers.bitdeer.ai/docs/guides/sdks/javascript
- https://developers.bitdeer.ai/docs/guides/integrations
- https://developers.bitdeer.ai/docs/guides/integrations/openai-agents-sdk
- https://developers.bitdeer.ai/docs/guides/faq
- https://developers.bitdeer.ai/docs/guides/deprecations/deprecation-history
- https://developers.bitdeer.ai/docs/guides/deprecations/lifecycle-guidelines
- https://developers.bitdeer.ai/docs/api
- https://developers.bitdeer.ai/docs/api/authentication
- https://developers.bitdeer.ai/docs/api/errors
- https://developers.bitdeer.ai/docs/api/models-catalog
- https://developers.bitdeer.ai/zh/docs/api/models-catalog
- https://developers.bitdeer.ai/docs/api/bitdeer-llm/inference/create-chat-completion
- https://www.bitdeer.ai/en/pricing/ai-models
- https://www.bitdeer.ai/en/model/explore
- https://www.bitdeer.ai/api/model/v1/ListModels (POST `{}`)
- https://www.bitdeer.ai/api/model/v1/GetModel (POST `{"modelId": ...}`)
- https://www.bitdeer.ai/api/model/v1/ListPublicModelPricings (POST `{}`)
- https://www.bitdeer.ai/en/blog/bitdeer-ai-starter-pack-for-cal-hacks-13-0/
- https://www.bitdeer.ai/en/blog/how-bitdeer-ai-builds-more-reliable-and-efficient-model-apis/
- https://www.bitdeer.ai/en/blog/nvidia-nemotron-3-5-super-vl/
- https://www.bitdeer.ai/en/blog/glm-5-3-flash-live-on-bitdeer-ai/
- https://www.bitdeer.ai/en/blog/smarter-faster-with-native-visual-understanding-deepseek-v4-1-flash-is-now-live-on-bitdeer-ai-model-studio/
- https://github.com/BitdeerAI/cal-hacks-demo
- https://artificialanalysis.ai/models/deepseek-v4-1-flash/providers
- https://artificialanalysis.ai/models/glm-5-3-flash/providers
