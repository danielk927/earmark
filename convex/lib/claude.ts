/**
 * Photo-assisted labeling with Claude's Messages API: the photo goes inline as a
 * base64 image block, thinking is off for latency, and the reply is constrained to a
 * JSON schema. Pure apart from the injected fetch.
 */
import { ConvexError } from "convex/values";

export const DEFAULT_BASE_URL = "https://api.anthropic.com/v1";
export const DEFAULT_VISION_MODEL = "claude-haiku-5-5";
const API_VERSION = "2026-10-21";
export const TIMEOUT_MS = 8000;
export const MAX_PHOTO_BYTES = 4 * 1024 * 1024;
export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

export interface LabelSuggestion {
  name: string;
  aliases: string[];
  description: string;
}

const SYSTEM_PROMPT =
  "You help a family label household items for a blind or low-vision person. " +
  "Look at the photo and name the single main item the way someone would say it aloud. " +
  "Read any printed label; if two items could look alike (for example salt and sugar jars), rely on the label text. " +
  "Do not guess what a medication is for and do not give any medical or usage advice.";

const USER_PROMPT =
  "Reply with JSON only. name: a short lowercase spoken name (1 to 4 words, e.g. \"sugar\"). " +
  "aliases: up to 4 other lowercase names a person might say. " +
  "description: one short sentence describing what the container looks like (shape, material, color, lid), no advice.";

const RESPONSE_SCHEMA = {
  type: "object",
  properties: {
    name: { type: "string" },
    aliases: { type: "array", items: { type: "string" } },
    description: { type: "string" },
  },
  required: ["name", "aliases", "description"],
  additionalProperties: false,
};

/** Base64 in chunks: spreading a large Uint8Array into String.fromCharCode overflows the stack. */
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export function buildRequest(model: string, mime: string, bytes: Uint8Array) {
  return {
    model,
    max_tokens: 300,
    system: SYSTEM_PROMPT,
    messages: [
      {
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: mime, data: bytesToBase64(bytes) } },
          { type: "text", text: USER_PROMPT },
        ],
      },
    ],
    thinking: { type: "disabled" },
    output_config: { effort: "low", format: { type: "json_schema", schema: RESPONSE_SCHEMA } },
  };
}

const tidy = (s: string, max: number) => s.trim().replace(/\s+/g, " ").slice(0, max);

/** Validate and tidy the model's JSON reply. */
export function parseSuggestion(content: unknown): LabelSuggestion {
  let parsed: unknown;
  try {
    parsed = typeof content === "string" ? JSON.parse(content) : null;
  } catch {
    parsed = null;
  }
  const o = parsed as Record<string, unknown> | null;
  if (
    !o ||
    typeof o !== "object" ||
    typeof o.name !== "string" ||
    !Array.isArray(o.aliases) ||
    typeof o.description !== "string"
  ) {
    throw new ConvexError("The photo model returned an unreadable suggestion. Try another photo or type the name.");
  }
  const name = tidy(o.name, 60).toLowerCase();
  if (name.length === 0) throw new ConvexError("The photo model could not name the item. Type the name instead.");
  const seen = new Set([name]);
  const aliases: string[] = [];
  for (const a of o.aliases) {
    if (typeof a !== "string") continue;
    const t = tidy(a, 60).toLowerCase();
    if (t.length === 0 || seen.has(t)) continue;
    seen.add(t);
    aliases.push(t);
    if (aliases.length === 5) break;
  }
  return { name, aliases, description: tidy(o.description, 200) };
}

/** Call Claude once with a hard timeout. Errors are ConvexErrors the dashboard can show; the key is never included. */
export async function requestSuggestion(opts: {
  fetchImpl: typeof fetch;
  baseUrl: string;
  apiKey: string;
  model: string;
  mime: string;
  bytes: Uint8Array;
  timeoutMs?: number;
}): Promise<LabelSuggestion & { model: string; latencyMs: number }> {
  const timeoutMs = opts.timeoutMs ?? TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  let res: Response;
  let text: string;
  try {
    res = await opts.fetchImpl(`${opts.baseUrl.replace(/\/+$/, "")}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": opts.apiKey, "anthropic-version": API_VERSION },
      body: JSON.stringify(buildRequest(opts.model, opts.mime, opts.bytes)),
      signal: controller.signal,
    });
    text = await res.text();
  } catch (err) {
    if (controller.signal.aborted) {
      throw new ConvexError(`The photo model did not answer within ${timeoutMs / 1000} seconds. Try again or type the name.`);
    }
    throw new ConvexError(`Could not reach the photo model (${err instanceof Error ? err.message : "network error"}).`);
  } finally {
    clearTimeout(timer);
  }
  const latencyMs = Date.now() - started;
  if (!res.ok) {
    let code = "";
    try {
      const body = JSON.parse(text) as { error?: { type?: unknown; message?: unknown } };
      code = typeof body.error?.type === "string" ? ` ${body.error.type}` : "";
    } catch {
      // Non-JSON error bodies (e.g. a plain "Unauthorized") carry no code.
    }
    throw new ConvexError(`The photo model returned HTTP ${res.status}${code}. Type the name instead.`);
  }
  let content: unknown = null;
  try {
    const body = JSON.parse(text) as { content?: { type?: unknown; text?: unknown }[] };
    content = body.content?.find((b) => b.type === "text")?.text ?? null;
  } catch {
    content = null;
  }
  return { ...parseSuggestion(content), model: opts.model, latencyMs };
}
