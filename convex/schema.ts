import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import {
  doseStatus,
  eventKind,
  nullableNumber,
  nullableString,
  objectFields,
  objectStateFields,
  trialFields,
  vec3,
} from "./lib/validators";

export default defineSchema({
  /** Singleton. registryVersion is the registry's last-change time in ms (monotonic). */
  household: defineTable({
    name: v.string(),
    timezone: v.string(),
    registryVersion: v.number(),
  }),

  objects: defineTable({
    objectId: v.string(),
    ...objectFields,
    /** ms; set from the registry version of the change. */
    updatedAt: v.number(),
  })
    .index("by_objectId", ["objectId"])
    .index("by_tag", ["tag"])
    .index("by_fobId", ["fobId"])
    .index("by_name", ["name"]),

  spots: defineTable({ spot: v.number(), label: v.string(), position: vec3 }).index("by_spot", ["spot"]),

  areas: defineTable({ area: v.string(), label: v.string(), position: vec3 }).index("by_area", ["area"]),

  receivers: defineTable({
    receiver: v.string(),
    label: v.string(),
    position: v.union(vec3, v.null()),
  }).index("by_receiver", ["receiver"]),

  /** Append-only hub events (POST /ingest), unique by eventId. */
  events: defineTable({
    eventId: v.string(),
    kind: eventKind,
    objectId: nullableString,
    t: v.number(),
    /** Spot the event happened on, extracted from data at ingest. */
    spot: nullableNumber,
    /** The originating bus message (or {spot, tag, source} for placed/removed), snake_case as sent. */
    data: v.record(v.string(), v.any()),
  })
    .index("by_eventId", ["eventId"])
    .index("by_t", ["t"])
    .index("by_objectId_and_t", ["objectId", "t"])
    .index("by_objectId_and_kind_and_t", ["objectId", "kind", "t"])
    .index("by_kind_and_t", ["kind", "t"]),

  /** Latest state per object (newest `t` wins). */
  objectState: defineTable(objectStateFields).index("by_objectId", ["objectId"]),

  medications: defineTable({
    objectId: v.string(),
    /** Household-local "HH:MM", sorted, unique. */
    scheduleTimes: v.array(v.string()),
    windowMinutes: v.number(),
    /** Doses scheduled before this instant (unix s) are not generated: monitoring had not started. */
    activeSinceT: v.number(),
  }).index("by_objectId", ["objectId"]),

  /** Materialized adherence results (lib/adherence.ts), recomputed by mutations and a cron. */
  doses: defineTable({
    objectId: v.string(),
    /** Household-local date of scheduledFor. */
    date: v.string(),
    scheduledLocalTime: v.string(),
    /** unix s */
    scheduledFor: v.number(),
    status: doseStatus,
    takenT: nullableNumber,
    evidenceEventId: nullableString,
  })
    .index("by_date_and_scheduledFor", ["date", "scheduledFor"])
    .index("by_objectId_and_date", ["objectId", "date"]),

  /** Trial results. Written only from trial_start/trial_end events; never edited or deleted by seed/reset. */
  trials: defineTable(trialFields).index("by_trialId", ["trialId"]).index("by_startedAt", ["startedAt"]),

  /** Unlabeled tags currently on a spot. Cleared when the tag is labeled or leaves. */
  unknownTags: defineTable({ tag: v.string(), spot: nullableNumber, t: v.number() })
    .index("by_tag", ["tag"])
    .index("by_t", ["t"]),

  dailySummaries: defineTable({
    date: v.string(),
    timezone: v.string(),
    generatedT: v.number(),
    doses: v.array(
      v.object({
        objectId: v.string(),
        name: v.string(),
        scheduledLocalTime: v.string(),
        scheduledFor: v.number(),
        status: doseStatus,
        takenT: nullableNumber,
        evidenceEventId: nullableString,
      }),
    ),
    pickupCount: v.number(),
    untouched7d: v.array(v.string()),
    missing: v.array(v.string()),
    text: v.string(),
  }).index("by_date", ["date"]),

  /** Pickup counter per household-local date, incremented in the same mutation that inserts the event. */
  dailyCounts: defineTable({ date: v.string(), pickups: v.number() }).index("by_date", ["date"]),
});
