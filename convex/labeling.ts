import { ConvexError, v } from "convex/values";
import { internal } from "./_generated/api";
import { action, env, internalMutation, internalQuery, mutation } from "./_generated/server";
import {
  DEFAULT_BASE_URL,
  DEFAULT_VISION_MODEL,
  MAX_PHOTO_BYTES,
  PHOTO_TYPES,
  requestSuggestion,
} from "./lib/claude";

/** Abandoned uploads (no suggestFromPhoto call) are deleted after this long. */
const PHOTO_MAX_AGE_MS = 10 * 60 * 1000;

/** Step 1: a short-lived URL the dashboard POSTs the photo to; the response JSON has the storageId. */
export const generateUploadUrl = mutation({
  args: {},
  returns: v.string(),
  handler: async (ctx) => await ctx.storage.generateUploadUrl(),
});

export const photoInfo = internalQuery({
  args: { storageId: v.string() },
  returns: v.union(
    v.null(),
    v.object({ storageId: v.id("_storage"), contentType: v.union(v.string(), v.null()), size: v.number() }),
  ),
  handler: async (ctx, { storageId }) => {
    const id = ctx.db.system.normalizeId("_storage", storageId);
    if (id === null) return null;
    const meta = await ctx.db.system.get("_storage", id);
    if (!meta) return null;
    return { storageId: id, contentType: meta.contentType ?? null, size: meta.size };
  },
});

/**
 * Step 2: send the photo to Claude and return a suggestion.
 * The photo is deleted in every case (success, model error, timeout, missing key)
 * before this returns. Nothing is saved: the dashboard confirms and then calls
 * objects:create or objects:update.
 */
export const suggestFromPhoto = action({
  args: { storageId: v.string() },
  returns: v.object({
    name: v.string(),
    aliases: v.array(v.string()),
    description: v.string(),
    model: v.string(),
    latencyMs: v.number(),
    photoDeleted: v.boolean(),
  }),
  handler: async (ctx, { storageId }) => {
    const info = await ctx.runQuery(internal.labeling.photoInfo, { storageId });
    if (info === null) throw new ConvexError("That photo was not found (it may have expired). Upload it again.");
    let photoDeleted = false;
    try {
      const apiKey = env.ANTHROPIC_API_KEY;
      if (!apiKey) {
        throw new ConvexError(
          "Photo suggestions are not set up: ANTHROPIC_API_KEY is missing on the Convex deployment. Type the name instead.",
        );
      }
      const mime = (info.contentType ?? "").toLowerCase().split(";")[0].trim();
      if (!PHOTO_TYPES.includes(mime)) {
        throw new ConvexError("Use a JPEG, PNG, WebP or GIF photo.");
      }
      if (info.size > MAX_PHOTO_BYTES) {
        throw new ConvexError(`The photo is too large (${(info.size / 1048576).toFixed(1)} MB). Use one under 4 MB.`);
      }
      const blob = await ctx.storage.get(info.storageId);
      if (blob === null) throw new ConvexError("That photo was not found (it may have expired). Upload it again.");
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const model = env.ANTHROPIC_VISION_MODEL || DEFAULT_VISION_MODEL;
      const suggestion = await requestSuggestion({
        fetchImpl: fetch,
        baseUrl: env.ANTHROPIC_BASE_URL || DEFAULT_BASE_URL,
        apiKey,
        model,
        mime,
        bytes,
      });
      console.log(`photo suggestion from ${model} in ${suggestion.latencyMs} ms`);
      return { ...suggestion, photoDeleted: true };
    } finally {
      try {
        await ctx.storage.delete(info.storageId);
        photoDeleted = true;
      } catch (err) {
        // The sweeper cron deletes it within PHOTO_MAX_AGE_MS.
        console.error("photo delete failed", err instanceof Error ? err.message : String(err));
      }
      if (!photoDeleted) throw new ConvexError("The photo could not be deleted right away; it will be deleted within 10 minutes.");
    }
  },
});

/** Cron: delete any stored file older than PHOTO_MAX_AGE_MS. Earmark stores no other files. */
export const sweepStalePhotos = internalMutation({
  args: {},
  returns: v.number(),
  handler: async (ctx) => {
    const cutoff = Date.now() - PHOTO_MAX_AGE_MS;
    const stale = await ctx.db.system
      .query("_storage")
      .withIndex("by_creation_time", (q) => q.lt("_creationTime", cutoff))
      .take(100);
    for (const f of stale) await ctx.storage.delete(f._id);
    return stale.length;
  },
});
