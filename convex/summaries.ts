import { v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { internalMutation, type MutationCtx } from "./_generated/server";
import { listMedications, readDoses, recomputeDate } from "./doses";
import { summaryText } from "./lib/describe";
import { householdInfo, listObjects } from "./lib/registry";
import { addDays, isValidDate, localDate, startOfLocalDay } from "./lib/time";
import { doseStatus, nullableNumber, nullableString } from "./lib/validators";

const summaryValidator = v.object({
  date: v.string(),
  timezone: v.string(),
  generatedT: v.number(),
  doses: v.array(
    v.object({
      objectId: v.string(),
      name: v.string(),
      scheduledLocalTime: v.string(),
      scheduledFor: v.number(),
      status: doseStatus,
      takenT: nullableNumber,
      evidenceEventId: nullableString,
    }),
  ),
  pickupCount: v.number(),
  untouched7d: v.array(v.string()),
  missing: v.array(v.string()),
  text: v.string(),
});

type Summary = typeof summaryValidator.type;

function strip(doc: Doc<"dailySummaries">): Summary {
  const { _id, _creationTime, ...rest } = doc;
  return rest;
}

/** Last pickup or placement of `objectId` in [lo, hi). */
async function touchedBetween(ctx: MutationCtx, objectId: string, lo: number, hi: number): Promise<boolean> {
  for (const kind of ["pickup", "placed"] as const) {
    const hit = await ctx.db
      .query("events")
      .withIndex("by_objectId_and_kind_and_t", (q) =>
        q.eq("objectId", objectId).eq("kind", kind).gte("t", lo).lt("t", hi),
      )
      .first();
    if (hit) return true;
  }
  return false;
}

/** Build (or rebuild) and store the summary for household-local `date` as of `now`. */
export async function buildSummary(ctx: MutationCtx, date: string, now: number): Promise<Summary> {
  const { timezone } = await householdInfo(ctx);
  await recomputeDate(ctx, date, now);
  const doses = await readDoses(ctx, date);
  const windows = new Map((await listMedications(ctx)).map((m) => [m.objectId, m.windowMinutes]));
  const counter = await ctx.db
    .query("dailyCounts")
    .withIndex("by_date", (q) => q.eq("date", date))
    .unique();
  const pickupCount = counter?.pickups ?? 0;

  // "Untouched" only makes sense for objects a spot reader can see: objects with
  // no NFC tag (e.g. fob-only keys) never produce pickups or placements.
  const end = startOfLocalDay(addDays(date, 1), timezone);
  const start = startOfLocalDay(addDays(date, -6), timezone);
  const objects = await listObjects(ctx);
  const untouched: Doc<"objects">[] = [];
  const missing: Doc<"objects">[] = [];
  for (const o of objects) {
    if (o.tag !== null && !(await touchedBetween(ctx, o.objectId, start, end))) untouched.push(o);
    const state = await ctx.db
      .query("objectState")
      .withIndex("by_objectId", (q) => q.eq("objectId", o.objectId))
      .unique();
    if (state?.status === "missing") missing.push(o);
  }

  const summary: Summary = {
    date,
    timezone,
    generatedT: now,
    doses: doses.map((d) => ({
      objectId: d.objectId,
      name: d.name,
      scheduledLocalTime: d.scheduledLocalTime,
      scheduledFor: d.scheduledForT,
      status: d.status,
      takenT: d.takenT,
      evidenceEventId: d.evidenceEventId,
    })),
    pickupCount,
    untouched7d: untouched.map((o) => o.objectId).sort(),
    missing: missing.map((o) => o.objectId).sort(),
    text: summaryText({
      date,
      timezone,
      doses: doses.map((d) => ({
        objectId: d.objectId,
        name: d.name,
        scheduledLocalTime: d.scheduledLocalTime,
        scheduledFor: d.scheduledForT,
        status: d.status,
        takenT: d.takenT,
        windowMinutes: windows.get(d.objectId) ?? 60,
      })),
      pickupCount,
      untouchedNames: untouched.map((o) => o.name),
      missingNames: missing.map((o) => o.name),
    }),
  };
  const existing = await ctx.db
    .query("dailySummaries")
    .withIndex("by_date", (q) => q.eq("date", date))
    .unique();
  if (existing) await ctx.db.replace("dailySummaries", existing._id, summary);
  else await ctx.db.insert("dailySummaries", summary);
  return summary;
}

/**
 * GET /api/daily-summary. Past days return the stored summary (built by the cron);
 * today, or any day without one, is built on demand.
 */
export const getOrBuild = internalMutation({
  args: { date: v.union(v.string(), v.null()), now: v.number() },
  returns: summaryValidator,
  handler: async (ctx, { date, now }) => {
    const { timezone } = await householdInfo(ctx);
    const today = localDate(now, timezone);
    const day = date ?? today;
    if (!isValidDate(day)) throw new Error("invalid date");
    if (day < today) {
      const stored = await ctx.db
        .query("dailySummaries")
        .withIndex("by_date", (q) => q.eq("date", day))
        .unique();
      if (stored) return strip(stored);
    }
    return await buildSummary(ctx, day, now);
  },
});

/**
 * Cron (hourly): (re)build the previous household-local day's summary.
 * Hourly rather than once at midnight because cron strings are UTC, the
 * household timezone is data, and the last dose of a day settles up to 2W
 * after it is scheduled. Rebuilding is idempotent and also picks up late events.
 */
export const buildYesterday = internalMutation({
  args: {},
  returns: v.null(),
  handler: async (ctx) => {
    const now = Date.now() / 1000;
    const { timezone } = await householdInfo(ctx);
    await buildSummary(ctx, addDays(localDate(now, timezone), -1), now);
    return null;
  },
});
