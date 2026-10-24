/**
 * In-memory stand-in for the Convex backend, used by ?demo=1. Queries are resolved by function
 * name from the contract, mutations change the in-memory data, and every subscriber re-renders,
 * so edits on one page show up on the others just like the real reactive backend.
 */
import { useMemo, useSyncExternalStore } from "react";
import { getFunctionName } from "convex/server";
import type { FunctionReference } from "convex/server";
import type { ModeStats, ObjectFields, ObjectRow, PhotoSuggestion, TrialRow } from "@contracts/convexFunctions";
import type { Backend } from "./backend";
import { demoDoses, type FixtureData } from "./fixtures";

type Args = Record<string, unknown>;

export function modeStats(trials: TrialRow[], mode: TrialRow["mode"]): ModeStats {
  const done = trials.filter((t) => t.mode === mode && t.endedAt != null);
  const found = done.filter((t) => t.outcome === "found" && t.secondsToFind != null);
  const secs = found.map((t) => t.secondsToFind as number).sort((a, b) => a - b);
  const mid = Math.floor(secs.length / 2);
  const median = secs.length === 0 ? null : secs.length % 2 ? secs[mid]! : (secs[mid - 1]! + secs[mid]!) / 2;
  return {
    trials: done.length,
    found: found.length,
    testers: new Set(done.map((t) => t.tester)).size,
    medianSecondsToFind: median,
    wrongPicks: done.reduce((n, t) => n + t.wrongPicks, 0),
  };
}

export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "item";
}

const DEMO_SUGGESTION: Omit<PhotoSuggestion, "latencyMs"> = {
  name: "honey",
  aliases: ["honey jar", "squeeze honey"],
  description: "Plastic squeeze bottle shaped like a bear, with a yellow flip cap.",
  model: "demo fixture (no model was called)",
  photoDeleted: true,
};

export interface FixtureBackendOptions {
  /** Simulated network delay for mutations and actions, in ms. */
  delayMs?: number;
  /** Clock, in unix seconds. */
  now?: () => number;
}

export function createFixtureBackend(data: FixtureData, opts: FixtureBackendOptions = {}): Backend & { data: FixtureData } {
  const delayMs = opts.delayMs ?? 400;
  const now = opts.now ?? (() => Date.now() / 1000);
  let version = 0;
  const listeners = new Set<() => void>();
  const changed = () => {
    version++;
    for (const l of listeners) l();
  };
  const subscribe = (l: () => void) => {
    listeners.add(l);
    return () => listeners.delete(l);
  };
  const wait = <T>(value: () => T) => new Promise<T>((resolve, reject) => setTimeout(() => {
    try {
      resolve(value());
    } catch (e) {
      reject(e);
    }
  }, delayMs));

  const map = data.liveMap;
  const queries: Record<string, (args: Args) => unknown> = {
    "dashboard:liveMap": () => ({ ...map, objects: [...map.objects], states: [...map.states], unknownTags: [...map.unknownTags] }),
    "objects:list": () => [...map.objects],
    "events:recent": (a) => data.events.slice(0, typeof a.limit === "number" ? a.limit : 50),
    "medications:list": () => [...data.medications],
    "doses:forDate": (a) => ({ date: a.date as string, timezone: map.household.timezone, doses: demoDoses(data, a.date as string, now()) }),
    "trials:list": () => [...data.trials].sort((x, y) => y.startedAt - x.startedAt),
    "trials:summary": () => ({ earmark: modeStats(data.trials, "earmark"), baseline: modeStats(data.trials, "baseline") }),
  };

  const create = (a: ObjectFields & { objectId?: string }) => {
    const objectId = a.objectId ?? slugify(a.name);
    if (map.objects.some((o) => o.objectId === objectId)) throw new Error(`An item called "${a.name}" already exists.`);
    const { objectId: _ignored, ...fields } = a;
    void _ignored;
    map.objects = [...map.objects, { objectId, ...fields, updatedAt: now() }];
    const tag = map.unknownTags.find((u) => a.tag && u.tag === a.tag);
    if (tag) {
      map.unknownTags = map.unknownTags.filter((u) => u !== tag);
      const spot = map.spots.find((s) => s.spot === tag.spot);
      map.states = [
        ...map.states,
        {
          objectId,
          status: "on_spot",
          spot: tag.spot,
          position: spot?.position ?? null,
          area: null,
          near: null,
          distanceClass: null,
          precision: "exact",
          homeSpot: a.homeSpot,
          lastSeenT: now(),
          t: now(),
        },
      ];
    }
    changed();
    return objectId;
  };

  const mutations: Record<string, (args: Args) => unknown> = {
    "objects:create": (a) => create(a as ObjectFields & { objectId?: string }),
    "objects:update": (a) => {
      const { objectId, ...patch } = a as { objectId: string } & Partial<ObjectFields>;
      const existing = map.objects.find((o) => o.objectId === objectId);
      if (!existing) throw new Error("That item no longer exists.");
      const updated: ObjectRow = { ...existing, ...patch, updatedAt: now() };
      map.objects = map.objects.map((o) => (o.objectId === objectId ? updated : o));
      if (patch.homeSpot !== undefined) {
        map.states = map.states.map((s) => (s.objectId === objectId ? { ...s, homeSpot: patch.homeSpot ?? null } : s));
      }
      const med = data.medications.find((m) => m.objectId === objectId);
      if (med && patch.name) data.medications = data.medications.map((m) => (m === med ? { ...m, name: patch.name! } : m));
      changed();
      return null;
    },
    "objects:remove": (a) => {
      map.objects = map.objects.filter((o) => o.objectId !== a.objectId);
      map.states = map.states.filter((s) => s.objectId !== a.objectId);
      data.medications = data.medications.filter((m) => m.objectId !== a.objectId);
      changed();
      return null;
    },
    "medications:upsert": (a) => {
      const { objectId, scheduleTimes, windowMinutes } = a as { objectId: string; scheduleTimes: string[]; windowMinutes: number };
      const name = map.objects.find((o) => o.objectId === objectId)?.name ?? objectId;
      const row = { objectId, name, scheduleTimes, windowMinutes };
      data.medications = data.medications.some((m) => m.objectId === objectId)
        ? data.medications.map((m) => (m.objectId === objectId ? row : m))
        : [...data.medications, row];
      changed();
      return null;
    },
    "labeling:generateUploadUrl": () => "demo://upload",
  };

  const actions: Record<string, (args: Args) => unknown> = {
    "labeling:suggestFromPhoto": () => ({ ...DEMO_SUGGESTION, latencyMs: delayMs * 3 }),
  };

  const resolve = (table: Record<string, (a: Args) => unknown>, ref: FunctionReference<"query" | "mutation" | "action">) => {
    const name = getFunctionName(ref);
    const f = table[name];
    if (!f) throw new Error(`Demo mode has no fixture for ${name}`);
    return f;
  };

  return {
    kind: "demo",
    data,
    useQuery(query, args) {
      const v = useSyncExternalStore(subscribe, () => version);
      const key = JSON.stringify(args);
      // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute only when the store or args change
      return useMemo(() => resolve(queries, query)(args as Args), [v, query, key]) as never;
    },
    useMutation(mutation) {
      return (args) => {
        const f = resolve(mutations, mutation);
        return wait(() => f(args as Args)) as never;
      };
    },
    useAction(action) {
      return (args) => {
        const f = resolve(actions, action);
        return new Promise((r) => setTimeout(r, delayMs * 2)).then(() => f(args as Args)) as never;
      };
    },
    useConnection: () => "demo",
    uploadPhoto: (_url, photo) => wait(() => `demo-storage-${photo.size}`),
  };
}
