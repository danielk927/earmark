import { ConvexError } from "convex/values";
import type { Doc } from "../_generated/dataModel";
import type { MutationCtx, QueryCtx } from "../_generated/server";

export const MAX_OBJECTS = 500;
export const MAX_SPOTS = 200;
export const DEFAULT_HOUSEHOLD = { name: "Household", timezone: "UTC" };

export async function getHousehold(ctx: QueryCtx): Promise<Doc<"household"> | null> {
  return await ctx.db.query("household").first();
}

export async function householdInfo(ctx: QueryCtx): Promise<{ name: string; timezone: string }> {
  const h = await getHousehold(ctx);
  return h ? { name: h.name, timezone: h.timezone } : DEFAULT_HOUSEHOLD;
}

/**
 * Advance the registry version (ms, strictly increasing) and return it.
 * Every change to objects or medications calls this, including removals,
 * so `version` in GET /api/registry changes whenever the registry does.
 */
export async function bumpRegistryVersion(ctx: MutationCtx): Promise<number> {
  const h = await getHousehold(ctx);
  const prev = h?.registryVersion ?? 0;
  const version = Math.max(Date.now(), prev + 1);
  if (h) await ctx.db.patch("household", h._id, { registryVersion: version });
  else await ctx.db.insert("household", { ...DEFAULT_HOUSEHOLD, registryVersion: version });
  return version;
}

export async function getObject(ctx: QueryCtx, objectId: string): Promise<Doc<"objects"> | null> {
  return await ctx.db
    .query("objects")
    .withIndex("by_objectId", (q) => q.eq("objectId", objectId))
    .unique();
}

export async function listObjects(ctx: QueryCtx): Promise<Doc<"objects">[]> {
  return await ctx.db.query("objects").withIndex("by_name").take(MAX_OBJECTS);
}

export async function spotLabels(ctx: QueryCtx): Promise<Map<number, string>> {
  const spots = await ctx.db.query("spots").withIndex("by_spot").take(MAX_SPOTS);
  return new Map(spots.map((s) => [s.spot, s.label]));
}

export const OBJECT_ID_RE = /^[a-z0-9_]+$/;

/** "Blood Pressure Pills!" -> "blood_pressure_pills". */
export function slugify(name: string): string {
  const slug = name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug.length > 0 ? slug.slice(0, 48) : "item";
}

export async function uniqueObjectId(ctx: QueryCtx, base: string): Promise<string> {
  if (!(await getObject(ctx, base))) return base;
  for (let n = 2; n < 1000; n++) {
    const candidate = `${base}_${n}`;
    if (!(await getObject(ctx, candidate))) return candidate;
  }
  throw new ConvexError(`Could not find a free objectId for ${base}`);
}

const collapse = (s: string) => s.trim().replace(/\s+/g, " ");

/** NFC UIDs are stored uppercase; blank means no tag. */
export function normalizeTag(tag: string | null): string | null {
  if (tag === null) return null;
  const t = tag.trim().toUpperCase();
  return t.length > 0 ? t : null;
}

export function normalizeFob(fobId: string | null): string | null {
  if (fobId === null) return null;
  const f = fobId.trim();
  return f.length > 0 ? f : null;
}

export function normalizeName(name: string): string {
  const n = collapse(name);
  if (n.length === 0) throw new ConvexError("Name cannot be empty.");
  if (n.length > 80) throw new ConvexError("Name must be 80 characters or fewer.");
  return n;
}

/** Trim, drop blanks and duplicates (case-insensitive), and drop the name itself. */
export function normalizeAliases(aliases: readonly string[], name: string): string[] {
  const seen = new Set([name.toLowerCase()]);
  const out: string[] = [];
  for (const raw of aliases) {
    const a = collapse(raw);
    if (a.length === 0 || seen.has(a.toLowerCase())) continue;
    if (a.length > 80) throw new ConvexError("Each alias must be 80 characters or fewer.");
    seen.add(a.toLowerCase());
    out.push(a);
  }
  if (out.length > 50) throw new ConvexError("At most 50 aliases.");
  return out;
}

export function checkHomeSpot(spot: number | null): number | null {
  if (spot !== null && (!Number.isInteger(spot) || spot < 0)) {
    throw new ConvexError("Home spot must be a whole number of 0 or more, or empty.");
  }
  return spot;
}

/** Throw if another object already uses this tag or fob. */
export async function assertUnique(
  ctx: QueryCtx,
  objectId: string,
  tag: string | null,
  fobId: string | null,
): Promise<void> {
  if (tag !== null) {
    const other = await ctx.db
      .query("objects")
      .withIndex("by_tag", (q) => q.eq("tag", tag))
      .first();
    if (other && other.objectId !== objectId) throw new ConvexError(`Tag ${tag} already belongs to ${other.name}.`);
  }
  if (fobId !== null) {
    const other = await ctx.db
      .query("objects")
      .withIndex("by_fobId", (q) => q.eq("fobId", fobId))
      .first();
    if (other && other.objectId !== objectId) throw new ConvexError(`Fob ${fobId} already belongs to ${other.name}.`);
  }
}

/** A tag that now belongs to an object is no longer "unknown". */
export async function clearUnknownTag(ctx: MutationCtx, tag: string | null): Promise<void> {
  if (tag === null) return;
  const rows = await ctx.db
    .query("unknownTags")
    .withIndex("by_tag", (q) => q.eq("tag", tag))
    .take(10);
  for (const row of rows) await ctx.db.delete("unknownTags", row._id);
}

/** Remove a medication schedule and its materialized doses. */
export async function deleteMedication(ctx: MutationCtx, objectId: string): Promise<void> {
  const meds = await ctx.db
    .query("medications")
    .withIndex("by_objectId", (q) => q.eq("objectId", objectId))
    .take(10);
  for (const m of meds) await ctx.db.delete("medications", m._id);
  for (;;) {
    const doses = await ctx.db
      .query("doses")
      .withIndex("by_objectId_and_date", (q) => q.eq("objectId", objectId))
      .take(500);
    for (const d of doses) await ctx.db.delete("doses", d._id);
    if (doses.length < 500) break;
  }
}
