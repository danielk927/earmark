import { v } from "convex/values";
import { query } from "./_generated/server";
import { objectRow, toObjectRow } from "./objects";
import { householdInfo, listObjects, MAX_OBJECTS, MAX_SPOTS } from "./lib/registry";
import { anchorFields, objectStateFields, vec3, wearerPoseFields } from "./lib/validators";

const MAX_ANCHORS = 16;

const { source: _source, ...stateRowFields } = objectStateFields;

/**
 * Everything the live map renders. Reactive: it re-runs whenever /ingest writes
 * a state, an unknown tag, or a registry change, so the dashboard never polls.
 */
export const liveMap = query({
  args: {},
  returns: v.object({
    household: v.object({ name: v.string(), timezone: v.string() }),
    spots: v.array(v.object({ spot: v.number(), label: v.string(), position: vec3 })),
    areas: v.array(v.object({ area: v.string(), label: v.string(), position: vec3 })),
    objects: v.array(objectRow),
    states: v.array(v.object(stateRowFields)),
    unknownTags: v.array(v.object({ tag: v.string(), spot: v.union(v.number(), v.null()), t: v.number() })),
    anchors: v.array(v.object(anchorFields)),
    wearer: v.union(v.object(wearerPoseFields), v.null()),
  }),
  handler: async (ctx) => {
    const objects = await listObjects(ctx);
    const known = new Set(objects.map((o) => o.objectId));
    const spots = await ctx.db.query("spots").withIndex("by_spot").take(MAX_SPOTS);
    const areas = await ctx.db.query("areas").withIndex("by_area").take(MAX_SPOTS);
    const states = await ctx.db.query("objectState").take(MAX_OBJECTS);
    const unknownTags = await ctx.db.query("unknownTags").withIndex("by_t").order("desc").take(50);
    const anchors = await ctx.db.query("anchors").withIndex("by_anchorId").take(MAX_ANCHORS);
    const wearer = await ctx.db.query("wearerPose").first();
    return {
      household: await householdInfo(ctx),
      spots: spots.map((s) => ({ spot: s.spot, label: s.label, position: s.position })),
      areas: areas.map((a) => ({ area: a.area, label: a.label, position: a.position })),
      objects: objects.map(toObjectRow),
      // States of removed objects are dropped (a late state can arrive after a removal).
      states: states
        .filter((s) => known.has(s.objectId))
        .map((s) => ({
          objectId: s.objectId,
          status: s.status,
          spot: s.spot,
          position: s.position,
          area: s.area,
          near: s.near,
          distanceClass: s.distanceClass,
          precision: s.precision,
          homeSpot: s.homeSpot,
          lastSeenT: s.lastSeenT,
          t: s.t,
        })),
      unknownTags: unknownTags.map((u) => ({ tag: u.tag, spot: u.spot, t: u.t })),
      anchors: anchors.map((a) => ({
        anchorId: a.anchorId,
        label: a.label,
        position: a.position,
        online: a.online,
        lastDistanceM: a.lastDistanceM,
        lastSeenT: a.lastSeenT,
      })),
      wearer: wearer ? { position: wearer.position, mode: wearer.mode, source: wearer.source, t: wearer.t } : null,
    };
  },
});
