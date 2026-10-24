import { v } from "convex/values";
import { internalMutation, type MutationCtx } from "./_generated/server";
import { recomputeAfterPickup } from "./doses";
import { householdInfo } from "./lib/registry";
import { localDate } from "./lib/time";
import { eventKind, nullableNumber, nullableString, objectStateFields, trialFields } from "./lib/validators";
import type { IngestEvent } from "./lib/wire";

const eventArg = v.object({
  eventId: v.string(),
  kind: eventKind,
  objectId: nullableString,
  t: v.number(),
  spot: nullableNumber,
  tag: nullableString,
  data: v.record(v.string(), v.any()),
  trial: v.union(v.object(trialFields), v.null()),
});

export async function bumpPickupCount(ctx: MutationCtx, date: string): Promise<void> {
  const row = await ctx.db
    .query("dailyCounts")
    .withIndex("by_date", (q) => q.eq("date", date))
    .unique();
  if (row) await ctx.db.patch("dailyCounts", row._id, { pickups: row.pickups + 1 });
  else await ctx.db.insert("dailyCounts", { date, pickups: 1 });
}

/**
 * trial_start creates the row; trial_end completes it (or creates it complete if
 * the start never arrived). Once a trial has ended it is never changed again.
 */
async function applyTrial(ctx: MutationCtx, kind: "trial_start" | "trial_end", trial: typeof eventArg.type.trial) {
  if (trial === null) return;
  const row = await ctx.db
    .query("trials")
    .withIndex("by_trialId", (q) => q.eq("trialId", trial.trialId))
    .unique();
  if (!row) {
    await ctx.db.insert("trials", trial);
  } else if (kind === "trial_end" && row.endedAt === null) {
    await ctx.db.patch("trials", row._id, {
      endedAt: trial.endedAt,
      secondsToFind: trial.secondsToFind,
      wrongPicks: trial.wrongPicks,
      outcome: trial.outcome,
    });
  }
}

async function applyUnknownTag(ctx: MutationCtx, e: IngestEvent) {
  if (e.tag === null) return;
  const row = await ctx.db
    .query("unknownTags")
    .withIndex("by_tag", (q) => q.eq("tag", e.tag!))
    .unique();
  if (e.kind === "unknown_tag") {
    // Ignore if the tag was labeled meanwhile (the hub may still have it queued).
    const owner = await ctx.db
      .query("objects")
      .withIndex("by_tag", (q) => q.eq("tag", e.tag))
      .first();
    if (owner) return;
    if (!row) await ctx.db.insert("unknownTags", { tag: e.tag, spot: e.spot, t: e.t });
    else if (e.t >= row.t) await ctx.db.patch("unknownTags", row._id, { spot: e.spot, t: e.t });
  } else if (row && e.t >= row.t) {
    // label, or the tag left its spot.
    await ctx.db.delete("unknownTags", row._id);
  }
}

/** POST /ingest commit: one transaction for the whole batch. */
export const apply = internalMutation({
  args: { events: v.array(eventArg), states: v.array(v.object(objectStateFields)) },
  returns: v.object({ acceptedEvents: v.number(), duplicateEvents: v.number(), acceptedStates: v.number() }),
  handler: async (ctx, { events, states }) => {
    const now = Date.now() / 1000;
    const { timezone } = await householdInfo(ctx);
    let acceptedEvents = 0;
    let duplicateEvents = 0;
    const pickups: { objectId: string; t: number }[] = [];

    for (const e of events) {
      const dup = await ctx.db
        .query("events")
        .withIndex("by_eventId", (q) => q.eq("eventId", e.eventId))
        .first();
      if (dup) {
        duplicateEvents++;
        continue;
      }
      acceptedEvents++;
      await ctx.db.insert("events", {
        eventId: e.eventId,
        kind: e.kind,
        objectId: e.objectId,
        t: e.t,
        spot: e.spot,
        data: e.data,
      });
      switch (e.kind) {
        case "pickup":
          await bumpPickupCount(ctx, localDate(e.t, timezone));
          if (e.objectId !== null) pickups.push({ objectId: e.objectId, t: e.t });
          break;
        case "trial_start":
        case "trial_end":
          await applyTrial(ctx, e.kind, e.trial);
          break;
        case "unknown_tag":
        case "removed":
        case "label":
          await applyUnknownTag(ctx, e);
          break;
        default:
          break;
      }
    }

    // Latest state wins; an older state replayed from the hub's offline queue is ignored.
    let acceptedStates = 0;
    for (const s of states) {
      const row = await ctx.db
        .query("objectState")
        .withIndex("by_objectId", (q) => q.eq("objectId", s.objectId))
        .unique();
      if (!row) await ctx.db.insert("objectState", s);
      else if (s.t >= row.t) await ctx.db.replace("objectState", row._id, s);
      else continue;
      acceptedStates++;
    }

    const seen = new Set<string>();
    for (const p of pickups) {
      const key = `${p.objectId}|${localDate(p.t, timezone)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      await recomputeAfterPickup(ctx, p.objectId, p.t, now);
    }
    return { acceptedEvents, duplicateEvents, acceptedStates };
  },
});
