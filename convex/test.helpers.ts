/// <reference types="vite/client" />
// Shared test setup. Two dots in the file name keep it out of the Convex bundle.
import Ajv2020 from "ajv/dist/2020";
import { convexTest } from "convex-test";
import type { FunctionArgs } from "convex/server";
import { expect, vi } from "vitest";
import { internal } from "./_generated/api";
import schema from "./schema";

export const modules = import.meta.glob("./**/*.ts");

export const HUB = "hub-secret-for-tests";
export const READ = "read-secret-for-tests";

export function setup() {
  vi.stubEnv("EARMARK_HUB_SECRET", HUB);
  vi.stubEnv("EARMARK_READ_SECRET", READ);
  return convexTest(schema, modules);
}
export type T = ReturnType<typeof setup>;

const configFiles = import.meta.glob<{ default: unknown }>("../config/*.json", { eager: true });
const config = (name: string) => configFiles[`../config/${name}`].default;

/** The real config files, exactly as `npm run seed` passes them. */
export function seedArgs(): FunctionArgs<typeof internal.seed.seed> {
  return {
    space: config("space.json"),
    registry: config("objects.seed.json"),
  } as FunctionArgs<typeof internal.seed.seed>;
}

export async function seed(t: T) {
  return await t.mutation(internal.seed.seed, seedArgs());
}

// ---------------------------------------------------------------- JSON Schema validation (draft 2020-12)

const schemaFiles = import.meta.glob<{ default: Record<string, unknown> }>("../contracts/schemas/*.json", {
  eager: true,
});
const ajv = new Ajv2020({ allErrors: true, strict: false });
for (const mod of Object.values(schemaFiles)) ajv.addSchema(mod.default);

const BASE = "https://earmark.local/schemas/";

/** Assert `body` is valid against `convex_http.schema.json#/$defs/<def>` (or a whole schema file). */
export function expectSchema(ref: string, body: unknown) {
  const id = ref.includes(".schema.json") ? `${BASE}${ref}` : `${BASE}convex_http.schema.json#/$defs/${ref}`;
  const validate = ajv.getSchema(id);
  if (!validate) throw new Error(`no schema ${id}`);
  const ok = validate(body);
  expect(ok ? null : ajv.errorsText(validate.errors), `${ref}: ${JSON.stringify(body).slice(0, 400)}`).toBeNull();
}

const exampleFiles = import.meta.glob<{ default: unknown }>("../contracts/examples/convex_http/*/*.json", {
  eager: true,
});

/** Contract examples for one $def, e.g. examples("ingest_request"). */
export function examples(def: string): unknown[] {
  return Object.entries(exampleFiles)
    .filter(([path]) => path.includes(`/convex_http/${def}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, mod]) => structuredClone(mod.default));
}

// ---------------------------------------------------------------- HTTP helpers

export async function get(t: T, path: string, secret: string | null = READ) {
  const res = await t.fetch(path, { method: "GET", headers: secret === null ? {} : { "X-Earmark-Secret": secret } });
  return { status: res.status, body: (await res.json()) as Record<string, unknown> & { [k: string]: any } };
}

export async function post(t: T, path: string, body: unknown, secret: string | null = HUB) {
  const res = await t.fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json", ...(secret === null ? {} : { "X-Earmark-Secret": secret }) },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
  return { status: res.status, body: (await res.json()) as Record<string, unknown> & { [k: string]: any } };
}

let counter = 0;
export const eventId = () => `e-test-${String(++counter).padStart(6, "0")}`;

export function pickupEvent(objectId: string, fromSpot: number, t: number, id = eventId()) {
  return {
    event_id: id,
    kind: "pickup",
    object_id: objectId,
    t,
    data: { type: "pickup", object_id: objectId, from_spot: fromSpot, t },
  };
}

export function stateUpdate(objectId: string, t: number, over: Record<string, unknown> = {}) {
  return {
    type: "state_update",
    object_id: objectId,
    location: { spot: null, position: null },
    precision: "none",
    status: "held",
    home_spot: null,
    last_seen_t: t,
    source: "simulator",
    t,
    ...over,
  };
}
