import { v, type VArray, type VFloat64 } from "convex/values";

export type Vec3 = [number, number, number];

/**
 * [x, y, z] meters. Convex has no tuple validator, so the runtime check is
 * "array of numbers" and the length is enforced where data enters (HTTP, seed);
 * the cast only narrows the TypeScript type to match the contracts.
 */
export const vec3 = v.array(v.number()) as unknown as VArray<Vec3, VFloat64, "required">;

export const precision = v.union(v.literal("exact"), v.literal("area"), v.literal("proximity"), v.literal("none"));
export const objectStatus = v.union(v.literal("on_spot"), v.literal("held"), v.literal("missing"), v.literal("roaming"));
export const distanceClass = v.union(v.literal("near"), v.literal("mid"), v.literal("far"));
export const stateSource = v.union(
  v.literal("simulator"),
  v.literal("nfc"),
  v.literal("ble"),
  v.literal("camera"),
  v.literal("ultrasonic"),
  v.literal("none"),
);
export const doseStatus = v.union(v.literal("taken"), v.literal("late"), v.literal("missed"), v.literal("pending"));
export const trialMode = v.union(v.literal("earmark"), v.literal("baseline"));
export const trialOutcome = v.union(v.literal("found"), v.literal("gave_up"), v.literal("aborted"));
export const eventKind = v.union(
  v.literal("placed"),
  v.literal("removed"),
  v.literal("pickup"),
  v.literal("pickup_result"),
  v.literal("unknown_tag"),
  v.literal("label"),
  v.literal("chirp"),
  v.literal("trial_start"),
  v.literal("trial_end"),
);

export const nullableString = v.union(v.string(), v.null());
export const nullableNumber = v.union(v.number(), v.null());

/** Editable object fields (contracts/ts/convexFunctions.ts ObjectFields). */
export const objectFields = {
  name: v.string(),
  aliases: v.array(v.string()),
  notes: v.string(),
  description: v.string(),
  tag: nullableString,
  homeSpot: nullableNumber,
  isMedication: v.boolean(),
  fobId: nullableString,
};

/** objectState row fields; also the shape /ingest states convert to. */
export const objectStateFields = {
  objectId: v.string(),
  status: objectStatus,
  spot: nullableNumber,
  position: v.union(vec3, v.null()),
  area: nullableString,
  near: nullableString,
  distanceClass: v.union(distanceClass, v.null()),
  precision,
  homeSpot: nullableNumber,
  lastSeenT: nullableNumber,
  source: stateSource,
  t: v.number(),
};

export const trialFields = {
  trialId: v.string(),
  mode: trialMode,
  targetObjectId: v.string(),
  tester: v.string(),
  startedAt: v.number(),
  endedAt: nullableNumber,
  secondsToFind: nullableNumber,
  wrongPicks: v.number(),
  outcome: v.union(trialOutcome, v.null()),
};

/** A dose joined with its object name (DoseRow in the client contract). */
export const doseRow = v.object({
  objectId: v.string(),
  name: v.string(),
  scheduledLocalTime: v.string(),
  scheduledForT: v.number(),
  status: doseStatus,
  takenT: nullableNumber,
  evidenceEventId: nullableString,
});

export const listenerMode = v.union(v.literal("tracked"), v.literal("frozen"), v.literal("lost"), v.literal("fixed"));
export const poseSource = v.union(v.literal("uwb"), v.literal("sound"), v.literal("sim"), v.literal("none"));

/** anchors row fields (UWB anchor iPhones, upserted by anchorId). */
export const anchorFields = {
  anchorId: v.string(),
  label: v.string(),
  position: vec3,
  online: v.boolean(),
  lastDistanceM: nullableNumber,
  lastSeenT: nullableNumber,
};

/** wearerPose row fields: the ONE live pose, overwritten in place, never a history. */
export const wearerPoseFields = {
  position: vec3,
  mode: listenerMode,
  source: poseSource,
  t: v.number(),
};
