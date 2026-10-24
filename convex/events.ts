import { v } from "convex/values";
import { query } from "./_generated/server";
import { describeEvent } from "./lib/describe";
import { listObjects, spotLabels } from "./lib/registry";

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;

/** Dashboard timeline: newest events first, each with a deterministic sentence. */
export const recent = query({
  args: { limit: v.optional(v.number()) },
  returns: v.array(
    v.object({
      eventId: v.string(),
      kind: v.string(),
      objectId: v.union(v.string(), v.null()),
      t: v.number(),
      spot: v.union(v.number(), v.null()),
      detail: v.string(),
    }),
  ),
  handler: async (ctx, { limit }) => {
    const n = Math.min(MAX_LIMIT, Math.max(1, Math.floor(limit ?? DEFAULT_LIMIT)));
    const events = await ctx.db.query("events").withIndex("by_t").order("desc").take(n);
    const names = new Map((await listObjects(ctx)).map((o) => [o.objectId, o.name]));
    const labels = await spotLabels(ctx);
    const lookup = {
      objectName: (id: string) => names.get(id) ?? id,
      spotLabel: (s: number) => labels.get(s) ?? null,
    };
    return events.map((e) => ({
      eventId: e.eventId,
      kind: e.kind,
      objectId: e.objectId,
      t: e.t,
      spot: e.spot,
      detail: describeEvent(e, lookup, true),
    }));
  },
});
