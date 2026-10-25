/**
 * Demo data. Run through convex/scripts/seed.node.mjs (npm run seed / npm run reset),
 * which passes config/space.json and config/objects.seed.json as arguments.
 *
 * seed:  idempotent and non-destructive. Applies the config (household, spots,
 *        areas, receivers, seed objects, schedules) and, only when the deployment
 *        has no non-trial events yet, two days of history plus initial states.
 * reset: deletes everything except trials (and trial events), then seeds.
 * Neither ever deletes or edits a trial.
 */
import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { TableNames } from "./_generated/dataModel";
import { internalAction, internalMutation, type MutationCtx } from "./_generated/server";
import { recomputeDate } from "./doses";
import { bumpPickupCount } from "./ingest";
import { buildSummary } from "./summaries";
import { bumpRegistryVersion, getHousehold, getObject, normalizeAliases } from "./lib/registry";
import { historyStartDate, planHistory } from "./lib/seedPlan";
import { addDays, isValidHHMM, isValidTimeZone, localDate, startOfLocalDay } from "./lib/time";
import type { Vec3 } from "./lib/validators";

const position = v.array(v.number());

export const seedArgs = {
  space: v.object({
    listener: v.object({ label: v.string(), origin_note: v.string() }),
    spots: v.array(v.object({ spot: v.number(), label: v.string(), position })),
    areas: v.array(v.object({ area: v.string(), label: v.optional(v.string()), position })),
    receivers: v.array(
      v.object({ receiver: v.string(), label: v.string(), position: v.optional(v.union(position, v.null())) }),
    ),
  }),
  registry: v.object({
    household: v.object({ name: v.string(), timezone: v.string() }),
    objects: v.array(
      v.object({
        object_id: v.string(),
        name: v.string(),
        aliases: v.array(v.string()),
        notes: v.string(),
        description: v.string(),
        tag: v.union(v.string(), v.null()),
        home_spot: v.union(v.number(), v.null()),
        is_medication: v.boolean(),
        fob_id: v.union(v.string(), v.null()),
      }),
    ),
    medications: v.array(
      v.object({ object_id: v.string(), schedule_times: v.array(v.string()), window_minutes: v.number() }),
    ),
    version: v.optional(v.union(v.number(), v.null())),
  }),
};

const seedResult = v.object({
  objects: v.number(),
  historyEvents: v.number(),
  doses: v.object({ taken: v.number(), late: v.number(), missed: v.number(), pending: v.number() }),
});

const toVec3 = (p: number[], what: string): Vec3 => {
  if (p.length !== 3 || !p.every(Number.isFinite)) throw new Error(`${what} position must be [x, y, z]`);
  return [p[0], p[1], p[2]];
};

/** Event kinds that reset deletes and whose absence means "no history yet". Trial events are kept. */
const DEMO_EVENT_KINDS = ["placed", "removed", "pickup", "pickup_result", "unknown_tag", "label", "stored", "chirp"] as const;

async function hasDemoEvents(ctx: MutationCtx): Promise<boolean> {
  for (const kind of DEMO_EVENT_KINDS) {
    if (await ctx.db.query("events").withIndex("by_kind_and_t", (q) => q.eq("kind", kind)).first()) return true;
  }
  return false;
}

async function replaceAll<T extends "spots" | "areas" | "receivers">(ctx: MutationCtx, table: T) {
  for (const d of await ctx.db.query(table).take(1000)) await ctx.db.delete(table, d._id);
}

export const seed = internalMutation({
  args: seedArgs,
  returns: seedResult,
  handler: async (ctx, { space, registry }) => {
    const now = Date.now() / 1000;
    const tz = registry.household.timezone;
    if (!isValidTimeZone(tz)) throw new Error(`unknown timezone ${tz}`);

    // Household (registryVersion stays monotonic across seeds and resets).
    const version = await bumpRegistryVersion(ctx);
    const household = (await getHousehold(ctx))!;
    await ctx.db.patch("household", household._id, { name: registry.household.name, timezone: tz });

    // Space: config-owned, replaced wholesale.
    await replaceAll(ctx, "spots");
    await replaceAll(ctx, "areas");
    await replaceAll(ctx, "receivers");
    for (const s of space.spots) {
      if (!Number.isInteger(s.spot)) throw new Error(`spot ${s.spot} must be an integer`);
      await ctx.db.insert("spots", { spot: s.spot, label: s.label, position: toVec3(s.position, `spot ${s.spot}`) });
    }
    for (const a of space.areas) {
      await ctx.db.insert("areas", { area: a.area, label: a.label ?? a.area, position: toVec3(a.position, a.area) });
    }
    for (const r of space.receivers) {
      await ctx.db.insert("receivers", {
        receiver: r.receiver,
        label: r.label,
        position: r.position ? toVec3(r.position, r.receiver) : null,
      });
    }

    // Seed objects: upsert by objectId; the config wins a tag or fob conflict.
    for (const o of registry.objects) {
      const fields = {
        name: o.name,
        aliases: normalizeAliases(o.aliases, o.name),
        notes: o.notes,
        description: o.description,
        tag: o.tag === null ? null : o.tag.toUpperCase(),
        homeSpot: o.home_spot,
        isMedication: o.is_medication,
        fobId: o.fob_id,
        updatedAt: version,
      };
      for (const [index, value] of [
        ["by_tag", fields.tag],
        ["by_fobId", fields.fobId],
      ] as const) {
        if (value === null) continue;
        const others = await ctx.db
          .query("objects")
          .withIndex(index, (q) => q.eq(index === "by_tag" ? "tag" : "fobId", value))
          .take(10);
        for (const other of others) {
          if (other.objectId === o.object_id) continue;
          await ctx.db.patch("objects", other._id, index === "by_tag" ? { tag: null } : { fobId: null });
        }
      }
      const existing = await getObject(ctx, o.object_id);
      if (existing) await ctx.db.patch("objects", existing._id, fields);
      else await ctx.db.insert("objects", { objectId: o.object_id, ...fields });
    }

    const withHistory = !(await hasDemoEvents(ctx));
    const today = localDate(now, tz);
    const historyStart = startOfLocalDay(historyStartDate(now, tz), tz);

    for (const m of registry.medications) {
      const bad = m.schedule_times.find((t) => !isValidHHMM(t));
      if (bad !== undefined) throw new Error(`bad schedule time ${bad}`);
      const fields = { scheduleTimes: [...new Set(m.schedule_times)].sort(), windowMinutes: m.window_minutes };
      const existing = await ctx.db
        .query("medications")
        .withIndex("by_objectId", (q) => q.eq("objectId", m.object_id))
        .first();
      if (existing) {
        await ctx.db.patch("medications", existing._id, {
          ...fields,
          activeSinceT: withHistory ? Math.min(existing.activeSinceT, historyStart) : existing.activeSinceT,
        });
      } else {
        await ctx.db.insert("medications", {
          objectId: m.object_id,
          ...fields,
          activeSinceT: withHistory ? historyStart : now,
        });
      }
    }

    let historyEvents = 0;
    if (withHistory) {
      const seedObjects = registry.objects.map((o) => ({
        objectId: o.object_id,
        tag: o.tag,
        homeSpot: o.home_spot,
        fobId: o.fob_id,
      }));
      for (const e of planHistory(now, tz, seedObjects)) {
        const dup = await ctx.db
          .query("events")
          .withIndex("by_eventId", (q) => q.eq("eventId", e.eventId))
          .first();
        if (dup) continue;
        await ctx.db.insert("events", e);
        if (e.kind === "pickup") await bumpPickupCount(ctx, localDate(e.t, tz));
        historyEvents++;
      }
    }

    // Initial states for objects that have none: tagged objects on their home spot, fobs near the hub.
    const spotPos = new Map(space.spots.map((s) => [s.spot, toVec3(s.position, `spot ${s.spot}`)]));
    const receiver = space.receivers[0];
    for (const o of registry.objects) {
      const has = await ctx.db
        .query("objectState")
        .withIndex("by_objectId", (q) => q.eq("objectId", o.object_id))
        .unique();
      if (has) continue;
      if (o.tag !== null && o.home_spot !== null) {
        await ctx.db.insert("objectState", {
          objectId: o.object_id,
          status: "on_spot",
          spot: o.home_spot,
          position: spotPos.get(o.home_spot) ?? null,
          area: null,
          near: null,
          distanceClass: null,
          precision: "exact",
          homeSpot: o.home_spot,
          lastSeenT: now,
          source: "simulator",
          t: now,
        });
      } else if (o.fob_id !== null && receiver) {
        await ctx.db.insert("objectState", {
          objectId: o.object_id,
          status: "roaming",
          spot: null,
          position: receiver.position ? toVec3(receiver.position, receiver.receiver) : null,
          area: null,
          near: receiver.receiver,
          distanceClass: "mid",
          precision: "proximity",
          homeSpot: o.home_spot,
          lastSeenT: now - 120,
          source: "simulator",
          t: now - 120,
        });
      }
      // Objects with a tag but no home spot (the pepper, in the pantry) have not been seen yet.
    }

    const counts = { taken: 0, late: 0, missed: 0, pending: 0 };
    for (const offset of [-2, -1, 0]) {
      const date = addDays(today, offset);
      await recomputeDate(ctx, date, now);
      if (offset < 0) await buildSummary(ctx, date, now);
      const doses = await ctx.db
        .query("doses")
        .withIndex("by_date_and_scheduledFor", (q) => q.eq("date", date))
        .take(200);
      for (const d of doses) counts[d.status]++;
    }
    return { objects: registry.objects.length, historyEvents, doses: counts };
  },
});

const CLEARED_TABLES = [
  "objects",
  "spots",
  "areas",
  "receivers",
  "objectState",
  "medications",
  "doses",
  "unknownTags",
  "dailySummaries",
  "dailyCounts",
] as const satisfies readonly TableNames[];

const BATCH = 1000;

/** Delete up to BATCH rows of one table (events: non-trial kinds only). Never touches trials. */
export const clearBatch = internalMutation({
  args: { table: v.union(...[...CLEARED_TABLES, "events" as const].map((t) => v.literal(t))) },
  returns: v.object({ deleted: v.number() }),
  handler: async (ctx, { table }) => {
    let deleted = 0;
    if (table === "events") {
      for (const kind of DEMO_EVENT_KINDS) {
        const rows = await ctx.db
          .query("events")
          .withIndex("by_kind_and_t", (q) => q.eq("kind", kind))
          .take(BATCH - deleted);
        for (const r of rows) await ctx.db.delete("events", r._id);
        deleted += rows.length;
        if (deleted >= BATCH) break;
      }
      return { deleted };
    }
    const rows = await ctx.db.query(table).take(BATCH);
    for (const r of rows) await ctx.db.delete(table, r._id);
    return { deleted: rows.length };
  },
});

/** Return the deployment to the demo starting state. Trials are preserved. */
export const reset = internalAction({
  args: seedArgs,
  returns: v.object({ deleted: v.number(), seeded: seedResult }),
  handler: async (ctx, args): Promise<{ deleted: number; seeded: typeof seedResult.type }> => {
    let deleted = 0;
    for (const table of ["events", ...CLEARED_TABLES] as const) {
      for (;;) {
        const r: { deleted: number } = await ctx.runMutation(internal.seed.clearBatch, { table });
        deleted += r.deleted;
        if (r.deleted < BATCH) break;
      }
    }
    const seeded: typeof seedResult.type = await ctx.runMutation(internal.seed.seed, args);
    return { deleted, seeded };
  },
});
