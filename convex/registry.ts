import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";
import { listMedications } from "./doses";
import { insertObject, patchObject } from "./objects";
import { clearUnknownTag, getHousehold, householdInfo, listObjects, normalizeAliases } from "./lib/registry";
import { objectFields } from "./lib/validators";

/** GET /api/registry (camelCase; http.ts converts). version is null until the first registry write. */
export const get = internalQuery({
  args: {},
  returns: v.object({
    household: v.object({ name: v.string(), timezone: v.string() }),
    objects: v.array(v.object({ objectId: v.string(), ...objectFields })),
    medications: v.array(
      v.object({ objectId: v.string(), scheduleTimes: v.array(v.string()), windowMinutes: v.number() }),
    ),
    version: v.union(v.number(), v.null()),
  }),
  handler: async (ctx) => {
    const household = await householdInfo(ctx);
    const objects = (await listObjects(ctx)).sort((a, b) => a.objectId.localeCompare(b.objectId));
    const medications = (await listMedications(ctx)).sort((a, b) => a.objectId.localeCompare(b.objectId));
    return {
      household,
      objects: objects.map((o) => ({
        objectId: o.objectId,
        name: o.name,
        aliases: o.aliases,
        notes: o.notes,
        description: o.description,
        tag: o.tag,
        homeSpot: o.homeSpot,
        isMedication: o.isMedication,
        fobId: o.fobId,
      })),
      medications: medications.map((m) => ({
        objectId: m.objectId,
        scheduleTimes: m.scheduleTimes,
        windowMinutes: m.windowMinutes,
      })),
      version: (await getHousehold(ctx))?.registryVersion ?? null,
    };
  },
});

/**
 * POST /api/label: create an object for `tag`, or rename the object that has it.
 * A rename keeps the object's existing aliases and adds the new ones.
 */
export const label = internalMutation({
  args: { tag: v.string(), name: v.string(), aliases: v.array(v.string()), spot: v.union(v.number(), v.null()) },
  returns: v.object({ objectId: v.string(), created: v.boolean() }),
  handler: async (ctx, { tag, name, aliases, spot }) => {
    const owner = await ctx.db
      .query("objects")
      .withIndex("by_tag", (q) => q.eq("tag", tag))
      .first();
    if (owner) {
      const merged = normalizeAliases([...owner.aliases, ...aliases], name.trim());
      await patchObject(ctx, owner.objectId, { name, aliases: merged });
      await clearUnknownTag(ctx, tag);
      return { objectId: owner.objectId, created: false };
    }
    const objectId = await insertObject(ctx, {
      name,
      aliases,
      notes: "",
      description: "",
      tag,
      homeSpot: spot,
      isMedication: false,
      fobId: null,
    });
    return { objectId, created: true };
  },
});
