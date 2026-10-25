import { ConvexError, v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { internalMutation, query, type MutationCtx, type QueryCtx } from "./_generated/server";
import { computeAdherence, type ScheduledDose } from "./lib/adherence";
import { getObject, householdInfo } from "./lib/registry";
import { addDays, isValidDate, localDate, startOfLocalDay, zonedToUnix } from "./lib/time";
import { doseRow } from "./lib/validators";

const MAX_MEDICATIONS = 100;
const MAX_PICKUPS_SCANNED = 2000;

export type DoseRowValue = typeof doseRow.type;

/**
 * Recompute and store the doses of one medication on household-local `date`.
 * Neighbouring days' doses take part in the "nearest scheduled time" assignment,
 * so a pickup just after midnight is attributed correctly. Writes only on change.
 */
export async function recomputeDoses(
  ctx: MutationCtx,
  med: Doc<"medications">,
  date: string,
  timezone: string,
  now: number,
): Promise<void> {
  const days = [addDays(date, -1), date, addDays(date, 1)];
  const scheduled: ScheduledDose[] = [];
  for (const day of days) {
    for (const time of med.scheduleTimes) {
      const at = zonedToUnix(day, time, timezone);
      if (at >= (med.timeActiveSince?.[time] ?? med.activeSinceT)) scheduled.push({ key: `${day} ${time}`, scheduledFor: at });
    }
  }
  const w = med.windowMinutes * 60;
  const lo = startOfLocalDay(days[0], timezone) - 2 * w;
  const hi = startOfLocalDay(addDays(date, 2), timezone) + 2 * w;
  const pickups = await ctx.db
    .query("events")
    .withIndex("by_objectId_and_kind_and_t", (q) =>
      q.eq("objectId", med.objectId).eq("kind", "pickup").gte("t", lo).lte("t", hi),
    )
    .take(MAX_PICKUPS_SCANNED);
  const results = computeAdherence(
    scheduled,
    pickups.map((p) => ({ eventId: p.eventId, t: p.t })),
    med.windowMinutes,
    now,
  ).filter((r) => r.key.startsWith(`${date} `));

  const existing = await ctx.db
    .query("doses")
    .withIndex("by_objectId_and_date", (q) => q.eq("objectId", med.objectId).eq("date", date))
    .take(100);
  const byTime = new Map(existing.map((d) => [d.scheduledLocalTime, d]));
  for (const r of results) {
    const scheduledLocalTime = r.key.slice(date.length + 1);
    const next = {
      objectId: med.objectId,
      date,
      scheduledLocalTime,
      scheduledFor: r.scheduledFor,
      status: r.status,
      takenT: r.takenT,
      evidenceEventId: r.evidenceEventId,
    };
    const old = byTime.get(scheduledLocalTime);
    byTime.delete(scheduledLocalTime);
    if (!old) {
      await ctx.db.insert("doses", next);
    } else if (
      old.scheduledFor !== next.scheduledFor ||
      old.status !== next.status ||
      old.takenT !== next.takenT ||
      old.evidenceEventId !== next.evidenceEventId
    ) {
      await ctx.db.patch("doses", old._id, next);
    }
  }
  // Times no longer on the schedule (or before monitoring started).
  for (const stale of byTime.values()) await ctx.db.delete("doses", stale._id);
}

export async function listMedications(ctx: QueryCtx): Promise<Doc<"medications">[]> {
  return await ctx.db.query("medications").take(MAX_MEDICATIONS);
}

/** Recompute every medication's doses on `date`. */
export async function recomputeDate(ctx: MutationCtx, date: string, now: number): Promise<void> {
  const { timezone } = await householdInfo(ctx);
  for (const med of await listMedications(ctx)) await recomputeDoses(ctx, med, date, timezone, now);
}

/** Recompute the dates around a pickup of `objectId` at `t`, if it is a scheduled medication. */
export async function recomputeAfterPickup(ctx: MutationCtx, objectId: string, t: number, now: number) {
  const med = await ctx.db
    .query("medications")
    .withIndex("by_objectId", (q) => q.eq("objectId", objectId))
    .first();
  if (!med) return;
  const { timezone } = await householdInfo(ctx);
  const day = localDate(t, timezone);
  for (const date of [addDays(day, -1), day, addDays(day, 1)]) await recomputeDoses(ctx, med, date, timezone, now);
}

/** Stored doses on `date`, joined with object names, in schedule order. */
export async function readDoses(ctx: QueryCtx, date: string): Promise<DoseRowValue[]> {
  const rows = await ctx.db
    .query("doses")
    .withIndex("by_date_and_scheduledFor", (q) => q.eq("date", date))
    .take(500);
  const names = new Map<string, string>();
  const out: DoseRowValue[] = [];
  for (const d of rows) {
    if (!names.has(d.objectId)) names.set(d.objectId, (await getObject(ctx, d.objectId))?.name ?? d.objectId);
    out.push({
      objectId: d.objectId,
      name: names.get(d.objectId)!,
      scheduledLocalTime: d.scheduledLocalTime,
      scheduledForT: d.scheduledFor,
      status: d.status,
      takenT: d.takenT,
      evidenceEventId: d.evidenceEventId,
    });
  }
  return out;
}

const dosesForDateResult = v.object({ date: v.string(), timezone: v.string(), doses: v.array(doseRow) });

/** Dashboard day view. Reads materialized doses only (no clock in queries). */
export const forDate = query({
  args: { date: v.string() },
  returns: dosesForDateResult,
  handler: async (ctx, { date }) => {
    if (!isValidDate(date)) throw new ConvexError("date must be YYYY-MM-DD");
    const { timezone } = await householdInfo(ctx);
    return { date, timezone, doses: await readDoses(ctx, date) };
  },
});

/** GET /api/adherence: recompute `date` (default: today, household-local) at `now`, then read it. */
export const refreshDate = internalMutation({
  args: { date: v.union(v.string(), v.null()), now: v.number() },
  returns: dosesForDateResult,
  handler: async (ctx, { date, now }) => {
    const { timezone } = await householdInfo(ctx);
    const day = date ?? localDate(now, timezone);
    await recomputeDate(ctx, day, now);
    return { date: day, timezone, doses: await readDoses(ctx, day) };
  },
});

/** Cron (every minute): keep today's and yesterday's statuses current as time passes. */
export const recomputeRecent = internalMutation({
  args: {},
  returns: v.null(),
  handler: async (ctx) => {
    const now = Date.now() / 1000;
    const { timezone } = await householdInfo(ctx);
    const today = localDate(now, timezone);
    await recomputeDate(ctx, addDays(today, -1), now);
    await recomputeDate(ctx, today, now);
    return null;
  },
});
