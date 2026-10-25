/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fn } from "../contracts/ts/convexFunctions";
import { internal } from "./_generated/api";
import type { Id } from "./_generated/dataModel";
import { bytesToBase64, parseSuggestion, requestSuggestion } from "./lib/claude";
import { setup, type T } from "./test.helpers";

const PHOTO = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4, 5]);

function claudeReply(content: unknown, status = 200) {
  return new Response(
    JSON.stringify(status === 200 ? { content: [{ type: "text", text: JSON.stringify(content) }] } : content),
    { status, headers: { "content-type": "application/json" } },
  );
}

async function upload(t: T, type = "image/jpeg", bytes: Uint8Array<ArrayBuffer> = PHOTO): Promise<Id<"_storage">> {
  return await t.run(async (ctx) => await ctx.storage.store(new Blob([bytes], { type })));
}

async function exists(t: T, id: Id<"_storage">) {
  return await t.run(async (ctx) => (await ctx.storage.get(id)) !== null);
}

let t: T;
beforeEach(() => {
  t = setup();
  vi.stubEnv("ANTHROPIC_API_KEY", "test-key");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("labeling:suggestFromPhoto", () => {
  test("sends the photo inline to Claude, returns the suggestion, deletes the photo", async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) =>
      claudeReply({ name: " Sugar ", aliases: ["white sugar", "Sugar", "sweetener", ""], description: "Small glass jar with a white lid." }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const id = await upload(t);
    const r = await t.action(fn.labeling.suggestFromPhoto, { storageId: id });
    expect(r).toMatchObject({
      name: "sugar",
      aliases: ["white sugar", "sweetener"],
      description: "Small glass jar with a white lid.",
      model: "claude-haiku-5-5",
      photoDeleted: true,
    });
    expect(r.latencyMs).toBeGreaterThanOrEqual(0);
    expect(await exists(t, id)).toBe(false);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.anthropic.com/v1/messages");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("test-key");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    const body = JSON.parse(init.body as string);
    expect(body.thinking).toEqual({ type: "disabled" });
    expect(body.output_config.effort).toBe("low");
    expect(body.output_config.format.type).toBe("json_schema");
    expect(body.messages[0].content[0]).toEqual({
      type: "image",
      source: { type: "base64", media_type: "image/jpeg", data: bytesToBase64(PHOTO) },
    });
  });

  test("uses ANTHROPIC_BASE_URL and ANTHROPIC_VISION_MODEL when set", async () => {
    vi.stubEnv("ANTHROPIC_BASE_URL", "https://example.test/v1/");
    vi.stubEnv("ANTHROPIC_VISION_MODEL", "claude-sonnet-5-5");
    const fetchMock = vi.fn(async () => claudeReply({ name: "salt", aliases: [], description: "Jar." }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await t.action(fn.labeling.suggestFromPhoto, { storageId: await upload(t, "image/png") });
    expect(r.model).toBe("claude-sonnet-5-5");
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe("https://example.test/v1/messages");
  });

  test("without an API key: a clear error, no network call, photo deleted", async () => {
    vi.stubEnv("ANTHROPIC_API_KEY", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const id = await upload(t);
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: id })).rejects.toThrow(/ANTHROPIC_API_KEY is missing/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await exists(t, id)).toBe(false);
  });

  test("a model error is reported without the key and the photo is still deleted", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => claudeReply({ type: "error", error: { type: "permission_error", message: "no credits" } }, 403)));
    const id = await upload(t);
    const err = await t.action(fn.labeling.suggestFromPhoto, { storageId: id }).catch((e: Error) => e);
    expect(String(err)).toMatch(/HTTP 403 permission_error/);
    expect(String(err)).not.toMatch(/test-key/);
    expect(await exists(t, id)).toBe(false);
  });

  test("an unreadable model reply is an error and the photo is deleted", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ content: [{ type: "text", text: "a jar" }] }))));
    const id = await upload(t);
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: id })).rejects.toThrow(/unreadable suggestion/);
    expect(await exists(t, id)).toBe(false);
  });

  test("a non-image upload is rejected and deleted", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const id = await upload(t, "image/svg+xml");
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: id })).rejects.toThrow(/JPEG, PNG, WebP or GIF/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await exists(t, id)).toBe(false);
  });

  test("an unknown or malformed storage id", async () => {
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: "not-an-id" })).rejects.toThrow(/not found/);
    const id = await upload(t);
    await t.run(async (ctx) => await ctx.storage.delete(id));
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: id })).rejects.toThrow(/not found/);
  });
});

describe("lib/claude", () => {
  test("times out with a clear message", async () => {
    const hang = (_: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    const p = requestSuggestion({
      fetchImpl: hang as typeof fetch,
      baseUrl: "https://x.test/v1",
      apiKey: "k",
      model: "m",
      mime: "image/jpeg",
      bytes: PHOTO,
      timeoutMs: 30,
    });
    await expect(p).rejects.toThrow(/did not answer within 0.03 seconds/);
  });

  test("parseSuggestion tidies and bounds the reply", () => {
    expect(
      parseSuggestion(
        JSON.stringify({ name: "  Black   Pepper ", aliases: ["a", "b", "c", "d", "e", "f", 3], description: "x".repeat(300) }),
      ),
    ).toEqual({ name: "black pepper", aliases: ["a", "b", "c", "d", "e"], description: "x".repeat(200) });
    expect(() => parseSuggestion(JSON.stringify({ name: "", aliases: [], description: "" }))).toThrow(/could not name/);
    expect(() => parseSuggestion(null)).toThrow(/unreadable/);
  });

  test("base64 matches btoa for large inputs (chunked)", () => {
    const big = new Uint8Array(200_000).map((_, i) => i % 251);
    let s = "";
    for (const b of big) s += String.fromCharCode(b);
    expect(bytesToBase64(big)).toBe(btoa(s));
  });
});

describe("sweepStalePhotos", () => {
  test("deletes uploads older than 10 minutes and keeps fresh ones", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(1_761_350_400_000);
    const old = await upload(t);
    vi.setSystemTime(1_761_350_400_000 + 11 * 60_000);
    const fresh = await upload(t);
    expect(await t.mutation(internal.labeling.sweepStalePhotos, {})).toBe(1);
    expect(await exists(t, old)).toBe(false);
    expect(await exists(t, fresh)).toBe(true);
  });
});

describe("labeling:suggestFromPhoto rate limit", () => {
  test("the 21st call in an hour is refused, without calling Claude, and the photo is deleted", async () => {
    const fetchMock = vi.fn(async () => claudeReply({ name: "salt", aliases: [], description: "Jar." }));
    vi.stubGlobal("fetch", fetchMock);
    await t.run(async (ctx) => {
      for (let i = 0; i < 20; i++) await ctx.db.insert("suggestionCalls", { t: Date.now() - i * 1000 });
    });
    const id = await upload(t);
    await expect(t.action(fn.labeling.suggestFromPhoto, { storageId: id })).rejects.toThrow(/Too many photo suggestions/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await exists(t, id)).toBe(false);
  });

  test("calls older than an hour do not count", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => claudeReply({ name: "salt", aliases: [], description: "Jar." })));
    await t.run(async (ctx) => {
      for (let i = 0; i < 20; i++) await ctx.db.insert("suggestionCalls", { t: Date.now() - 3_700_000 });
    });
    const r = await t.action(fn.labeling.suggestFromPhoto, { storageId: await upload(t) });
    expect(r.name).toBe("salt");
  });
});
