/** Internal queries behind the agent read endpoints (GET /api/object, /api/objects, /api/history). */
import { v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { internalQuery, type QueryCtx } from "./_generated/server";
import { describeEvent } from "./lib/describe";
import { matchRank } from "./lib/match";
import { getObject, householdInfo, listObjects, spotLabels } from "./lib/registry";
import { distanceClass, nullableNumber, nullableString, objectStatus, precision } from "./lib/validators";
import type { ObjectSummaryValue } from "./lib/wire";

const HISTORY_LIMIT = 200;

const summaryValidator = v.object({
  objectId: v.string(),
  name: v.string(),
  aliases: v.array(v.string()),
  notes: v.string(),
  description: v.string(),
  homeSpot: nullableNumber,
  homeSpotLabel: nullableString,
  isMedication: v.boolean(),
  fobId: nullableString,
  state: v.union(
    v.null(),
    v.object({
      status: objectStatus,
      spot: nullableNumber,
      spotLabel: nullableString,
      area: nullableString,
      near: nullableString,
      distanceClass: v.union(distanceClass, v.null()),
      precision,
      lastSeenT: nullableNumber,
    }),
  ),
  lastTouchedT: nullableNumber,
});

/** Last pickup or placement of an object. */
export async function lastTouched(ctx: QueryCtx, objectId: string): Promise<number | null> {
  let best: number | null = null;
  for (const kind of ["pickup", "placed"] as const) {
    const e = await ctx.db
      .query("events")
      .withIndex("by_objectId_and_kind_and_t", (q) => q.eq("objectId", objectId).eq("kind", kind))
      .order("desc")
      .first();
    if (e && (best === null || e.t > best)) best = e.t;
  }
  return best;
}

async function summarize(ctx: QueryCtx, o: Doc<"objects">, labels: Map<number, string>): Promise<ObjectSummaryValue> {
  const s = await ctx.db
    .query("objectState")
    .withIndex("by_objectId", (q) => q.eq("objectId", o.objectId))
    .unique();
  const label = (spot: number | null) => (spot === null ? null : (labels.get(spot) ?? null));
  return {
    objectId: o.objectId,
    name: o.name,
    aliases: o.aliases,
    notes: o.notes,
    description: o.description,
    homeSpot: o.homeSpot,
    homeSpotLabel: label(o.homeSpot),
    isMedication: o.isMedication,
    fobId: o.fobId,
    state: s
      ? {
          status: s.status,
          spot: s.spot,
          spotLabel: label(s.spot),
          area: s.area,
          near: s.near,
          distanceClass: s.distanceClass,
          precision: s.precision,
          lastSeenT: s.lastSeenT,
        }
      : null,
    lastTouchedT: await lastTouched(ctx, o.objectId),
  };
}

/** Every object (no `name`), or the matches for `name`, best first. */
export const objectSummaries = internalQuery({
  args: { name: v.optional(v.string()) },
  returns: v.object({ timezone: v.string(), objects: v.array(summaryValidator) }),
  handler: async (ctx, { name }) => {
    const { timezone } = await householdInfo(ctx);
    const labels = await spotLabels(ctx);
    let objects = await listObjects(ctx);
    if (name !== undefined) {
      objects = objects
        .map((o) => ({ o, rank: matchRank(name, o.name, o.aliases) }))
        .filter((x): x is { o: Doc<"objects">; rank: number } => x.rank !== null)
        .sort((a, b) => a.rank - b.rank || a.o.name.localeCompare(b.o.name))
        .map((x) => x.o);
    }
    const out: ObjectSummaryValue[] = [];
    for (const o of objects) out.push(await summarize(ctx, o, labels));
    return { timezone, objects: out };
  },
});

/** Events of one object since `since`, newest first (max 200). Null for an unknown objectId. */
export const history = internalQuery({
  args: { objectId: v.string(), since: v.number() },
  returns: v.union(
    v.null(),
    v.object({
      timezone: v.string(),
      objectId: v.string(),
      name: v.string(),
      events: v.array(
        v.object({
          eventId: v.string(),
          kind: v.string(),
          t: v.number(),
          spot: nullableNumber,
          spotLabel: nullableString,
          detail: v.string(),
        }),
      ),
    }),
  ),
  handler: async (ctx, { objectId, since }) => {
    const o = await getObject(ctx, objectId);
    if (!o) return null;
    const { timezone } = await householdInfo(ctx);
    const labels = await spotLabels(ctx);
    const names = new Map<string, string>([[o.objectId, o.name]]);
    const objectName = (id: string) => names.get(id) ?? id;
    // Names of other objects mentioned in pickup_result events.
    for (const x of await listObjects(ctx)) names.set(x.objectId, x.name);
    const events = await ctx.db
      .query("events")
      .withIndex("by_objectId_and_t", (q) => q.eq("objectId", objectId).gte("t", since))
      .order("desc")
      .take(HISTORY_LIMIT);
    return {
      timezone,
      objectId: o.objectId,
      name: o.name,
      events: events.map((e) => ({
        eventId: e.eventId,
        kind: e.kind,
        t: e.t,
        spot: e.spot,
        spotLabel: e.spot === null ? null : (labels.get(e.spot) ?? null),
        detail: describeEvent(e, { objectName, spotLabel: (s) => labels.get(s) ?? null }, false),
      })),
    };
  },
});
