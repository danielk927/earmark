import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { listMedications, recomputeDate } from "./doses";
import { bumpRegistryVersion, getObject, householdInfo } from "./lib/registry";
import { addDays, isValidHHMM, localDate } from "./lib/time";

export const list = query({
  args: {},
  returns: v.array(
    v.object({
      objectId: v.string(),
      name: v.string(),
      scheduleTimes: v.array(v.string()),
      windowMinutes: v.number(),
    }),
  ),
  handler: async (ctx) => {
    const out = [];
    for (const m of await listMedications(ctx)) {
      const o = await getObject(ctx, m.objectId);
      if (!o) continue;
      out.push({ objectId: m.objectId, name: o.name, scheduleTimes: m.scheduleTimes, windowMinutes: m.windowMinutes });
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
  },
});

/**
 * Set a medication schedule. Marks the object as a medication if it is not yet.
 * A new schedule starts now: no doses are generated for earlier times.
 */
export const upsert = mutation({
  args: { objectId: v.string(), scheduleTimes: v.array(v.string()), windowMinutes: v.number() },
  returns: v.null(),
  handler: async (ctx, { objectId, scheduleTimes, windowMinutes }) => {
    const o = await getObject(ctx, objectId);
    if (!o) throw new ConvexError(`Unknown objectId ${objectId}.`);
    const bad = scheduleTimes.find((t) => !isValidHHMM(t));
    if (bad !== undefined) throw new ConvexError(`Schedule time "${bad}" must be HH:MM (24-hour).`);
    if (scheduleTimes.length > 24) throw new ConvexError("At most 24 schedule times.");
    if (!Number.isInteger(windowMinutes) || windowMinutes < 1 || windowMinutes > 720) {
      throw new ConvexError("Window must be a whole number of minutes from 1 to 720.");
    }
    const times = [...new Set(scheduleTimes)].sort();
    const now = Date.now() / 1000;
    const version = await bumpRegistryVersion(ctx);
    if (!o.isMedication) await ctx.db.patch("objects", o._id, { isMedication: true, updatedAt: version });
    const existing = await ctx.db
      .query("medications")
      .withIndex("by_objectId", (q) => q.eq("objectId", objectId))
      .first();
    if (existing) {
      // A time that was not on the schedule before counts only from now; unchanged times keep their history.
      const timeActiveSince: Record<string, number> = {};
      for (const time of times) {
        if (!existing.scheduleTimes.includes(time)) timeActiveSince[time] = now;
        else if (existing.timeActiveSince?.[time] !== undefined) timeActiveSince[time] = existing.timeActiveSince[time];
      }
      await ctx.db.patch("medications", existing._id, { scheduleTimes: times, windowMinutes, timeActiveSince });
    } else await ctx.db.insert("medications", { objectId, scheduleTimes: times, windowMinutes, activeSinceT: now });
    const { timezone } = await householdInfo(ctx);
    const today = localDate(now, timezone);
    for (const date of [addDays(today, -1), today]) await recomputeDate(ctx, date, now);
    return null;
  },
});
