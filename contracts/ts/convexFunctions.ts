/**
 * Contract for the Convex functions the dashboard calls (client API, not HTTP).
 *
 * The dashboard imports `fn` from here; convex/ must export functions with
 * exactly these names, argument shapes, and return shapes. Shapes are
 * Convex-native camelCase. Times are unix seconds.
 *
 * Hand-written (not generated). Changing it is a contract change.
 */
import { makeFunctionReference } from "convex/server";

export type Vec3 = [number, number, number];
export type Precision = "exact" | "area" | "proximity" | "none";
export type ObjectStatus = "on_spot" | "held" | "missing" | "roaming";
export type DistanceClass = "near" | "mid" | "far";
export type DoseStatus = "taken" | "late" | "missed" | "pending";
export type TrialMode = "earmark" | "baseline";
export type TrialOutcome = "found" | "gave_up" | "aborted";

export interface Household {
  name: string;
  timezone: string;
}

export interface SpotRow {
  spot: number;
  label: string;
  position: Vec3;
}

export interface AreaRow {
  area: string;
  label: string;
  position: Vec3;
}

export interface ObjectRow {
  objectId: string;
  name: string;
  aliases: string[];
  notes: string;
  description: string;
  tag: string | null;
  homeSpot: number | null;
  isMedication: boolean;
  fobId: string | null;
  updatedAt: number;
}

export interface ObjectStateRow {
  objectId: string;
  status: ObjectStatus;
  spot: number | null;
  position: Vec3 | null;
  area: string | null;
  near: string | null;
  distanceClass: DistanceClass | null;
  precision: Precision;
  homeSpot: number | null;
  lastSeenT: number | null;
  t: number;
}

export interface UnknownTagRow {
  tag: string;
  spot: number | null;
  t: number;
}

export interface EventRow {
  eventId: string;
  kind: string;
  objectId: string | null;
  t: number;
  spot: number | null;
  /** Deterministic sentence, e.g. "Sugar picked up from the center right spot." */
  detail: string;
}

export interface MedicationRow {
  objectId: string;
  name: string;
  scheduleTimes: string[];
  windowMinutes: number;
}

export interface DoseRow {
  objectId: string;
  name: string;
  scheduledLocalTime: string;
  scheduledForT: number;
  status: DoseStatus;
  takenT: number | null;
  evidenceEventId: string | null;
}

export interface TrialRow {
  trialId: string;
  mode: TrialMode;
  targetObjectId: string;
  tester: string;
  startedAt: number;
  endedAt: number | null;
  secondsToFind: number | null;
  wrongPicks: number;
  outcome: TrialOutcome | null;
}

export interface ModeStats {
  /** Completed trials (endedAt set). */
  trials: number;
  found: number;
  testers: number;
  medianSecondsToFind: number | null;
  /** Sum of wrong picks across completed trials. */
  wrongPicks: number;
}

export interface TrialSummary {
  earmark: ModeStats;
  baseline: ModeStats;
}

export interface LiveMap {
  household: Household;
  spots: SpotRow[];
  areas: AreaRow[];
  objects: ObjectRow[];
  states: ObjectStateRow[];
  /** Unlabeled tags currently sitting on a spot, newest first. */
  unknownTags: UnknownTagRow[];
}

/** A type alias (not an interface) so it satisfies Convex's args constraint. */
export type ObjectFields = {
  name: string;
  aliases: string[];
  notes: string;
  description: string;
  tag: string | null;
  homeSpot: number | null;
  isMedication: boolean;
  fobId: string | null;
};

export interface PhotoSuggestion {
  name: string;
  aliases: string[];
  description: string;
  /** Bitdeer model id that produced the suggestion. */
  model: string;
  latencyMs: number;
  /** Always true on success: the uploaded photo has been deleted from storage. */
  photoDeleted: boolean;
}

export const fn = {
  dashboard: {
    liveMap: makeFunctionReference<"query", Record<string, never>, LiveMap>("dashboard:liveMap"),
  },
  objects: {
    list: makeFunctionReference<"query", Record<string, never>, ObjectRow[]>("objects:list"),
    /** objectId is derived from name (lowercase, [a-z0-9_]) when omitted. Returns the objectId. */
    create: makeFunctionReference<"mutation", ObjectFields & { objectId?: string }, string>("objects:create"),
    update: makeFunctionReference<"mutation", { objectId: string } & Partial<ObjectFields>, null>("objects:update"),
    remove: makeFunctionReference<"mutation", { objectId: string }, null>("objects:remove"),
  },
  events: {
    recent: makeFunctionReference<"query", { limit?: number }, EventRow[]>("events:recent"),
  },
  medications: {
    list: makeFunctionReference<"query", Record<string, never>, MedicationRow[]>("medications:list"),
    upsert: makeFunctionReference<
      "mutation",
      { objectId: string; scheduleTimes: string[]; windowMinutes: number },
      null
    >("medications:upsert"),
  },
  doses: {
    /** date = household-local YYYY-MM-DD. */
    forDate: makeFunctionReference<"query", { date: string }, { date: string; timezone: string; doses: DoseRow[] }>(
      "doses:forDate",
    ),
  },
  trials: {
    list: makeFunctionReference<"query", Record<string, never>, TrialRow[]>("trials:list"),
    summary: makeFunctionReference<"query", Record<string, never>, TrialSummary>("trials:summary"),
  },
  labeling: {
    generateUploadUrl: makeFunctionReference<"mutation", Record<string, never>, string>("labeling:generateUploadUrl"),
    /** Sends the photo to the Bitdeer multimodal model, deletes it, returns a suggestion. Nothing is saved. */
    suggestFromPhoto: makeFunctionReference<"action", { storageId: string }, PhotoSuggestion>(
      "labeling:suggestFromPhoto",
    ),
  },
} as const;
