import { ConvexError, v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { mutation, query, type MutationCtx } from "./_generated/server";
import {
  assertUnique,
  bumpRegistryVersion,
  checkHomeSpot,
  clearUnknownTag,
  deleteMedication,
  getObject,
  listObjects,
  normalizeAliases,
  normalizeFob,
  normalizeName,
  normalizeTag,
  OBJECT_ID_RE,
  slugify,
  uniqueObjectId,
} from "./lib/registry";
import { objectFields } from "./lib/validators";

export const objectRow = v.object({ objectId: v.string(), ...objectFields, updatedAt: v.number() });

const fieldsValidator = v.object(objectFields);
export type ObjectFieldsValue = typeof fieldsValidator.type;

export function toObjectRow(o: Doc<"objects">): typeof objectRow.type {
  return {
    objectId: o.objectId,
    name: o.name,
    aliases: o.aliases,
    notes: o.notes,
    description: o.description,
    tag: o.tag,
    homeSpot: o.homeSpot,
    isMedication: o.isMedication,
    fobId: o.fobId,
    updatedAt: o.updatedAt,
  };
}

function longText(value: string, what: string, max: number): string {
  const s = value.trim();
  if (s.length > max) throw new ConvexError(`${what} must be ${max} characters or fewer.`);
  return s;
}

/** Validate and normalize every field; throws ConvexError with a message the dashboard can show. */
function clean(fields: ObjectFieldsValue): ObjectFieldsValue {
  const name = normalizeName(fields.name);
  return {
    name,
    aliases: normalizeAliases(fields.aliases, name),
    notes: longText(fields.notes, "Notes", 1000),
    description: longText(fields.description, "Description", 500),
    tag: normalizeTag(fields.tag),
    homeSpot: checkHomeSpot(fields.homeSpot),
    isMedication: fields.isMedication,
    fobId: normalizeFob(fields.fobId),
  };
}

/** Create an object; objectId is derived from the name when not given. Returns the objectId. */
export async function insertObject(ctx: MutationCtx, input: ObjectFieldsValue, objectId?: string): Promise<string> {
  const fields = clean(input);
  let id: string;
  if (objectId !== undefined) {
    if (!OBJECT_ID_RE.test(objectId)) throw new ConvexError("objectId may only contain a-z, 0-9 and _.");
    if (await getObject(ctx, objectId)) throw new ConvexError(`An object with id ${objectId} already exists.`);
    id = objectId;
  } else {
    id = await uniqueObjectId(ctx, slugify(fields.name));
  }
  await assertUnique(ctx, id, fields.tag, fields.fobId);
  const updatedAt = await bumpRegistryVersion(ctx);
  await ctx.db.insert("objects", { objectId: id, ...fields, updatedAt });
  await clearUnknownTag(ctx, fields.tag);
  return id;
}

/** Patch an object with the given fields (absent fields are unchanged). */
export async function patchObject(ctx: MutationCtx, objectId: string, patch: Partial<ObjectFieldsValue>): Promise<void> {
  const current = await getObject(ctx, objectId);
  if (!current) throw new ConvexError(`Unknown objectId ${objectId}.`);
  const merged = { ...current, ...Object.fromEntries(Object.entries(patch).filter(([, x]) => x !== undefined)) };
  const fields = clean(merged);
  await assertUnique(ctx, objectId, fields.tag, fields.fobId);
  const updatedAt = await bumpRegistryVersion(ctx);
  await ctx.db.patch("objects", current._id, { ...fields, updatedAt });
  await clearUnknownTag(ctx, fields.tag);
  if (current.isMedication && !fields.isMedication) await deleteMedication(ctx, objectId);
}

export const list = query({
  args: {},
  returns: v.array(objectRow),
  handler: async (ctx) => (await listObjects(ctx)).map(toObjectRow),
});

export const create = mutation({
  args: { ...objectFields, objectId: v.optional(v.string()) },
  returns: v.string(),
  handler: async (ctx, { objectId, ...fields }) => await insertObject(ctx, fields, objectId),
});

export const update = mutation({
  args: {
    objectId: v.string(),
    name: v.optional(objectFields.name),
    aliases: v.optional(objectFields.aliases),
    notes: v.optional(objectFields.notes),
    description: v.optional(objectFields.description),
    tag: v.optional(objectFields.tag),
    homeSpot: v.optional(objectFields.homeSpot),
    isMedication: v.optional(objectFields.isMedication),
    fobId: v.optional(objectFields.fobId),
  },
  returns: v.null(),
  handler: async (ctx, { objectId, ...patch }) => {
    await patchObject(ctx, objectId, patch);
    return null;
  },
});

/** Remove an object with its state and medication schedule. Events stay (append-only); trials are never touched. */
export const remove = mutation({
  args: { objectId: v.string() },
  returns: v.null(),
  handler: async (ctx, { objectId }) => {
    const current = await getObject(ctx, objectId);
    if (!current) throw new ConvexError(`Unknown objectId ${objectId}.`);
    await ctx.db.delete("objects", current._id);
    const state = await ctx.db
      .query("objectState")
      .withIndex("by_objectId", (q) => q.eq("objectId", objectId))
      .unique();
    if (state) await ctx.db.delete("objectState", state._id);
    await deleteMedication(ctx, objectId);
    await bumpRegistryVersion(ctx);
    return null;
  },
});
