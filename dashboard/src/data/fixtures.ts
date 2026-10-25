/**
 * Demo and test fixtures, typed with the contract so tsc enforces their shape.
 * Built from config/space.json and config/objects.seed.json, with times relative to `now`.
 * None of this is real data; the UI labels demo mode on every page.
 */
import type {
  DoseRow,
  EventRow,
  LiveMap,
  MedicationRow,
  ObjectRow,
  ObjectStateRow,
  TrialRow,
} from "@contracts/convexFunctions";
import { addDays, localDate, zonedToUnix } from "../lib/time";

export interface FixtureData {
  now: number;
  liveMap: LiveMap;
  events: EventRow[];
  medications: MedicationRow[];
  /** Pickups of medication objects, used by the demo's copy of the adherence rule. */
  medicationPickups: { objectId: string; t: number; eventId: string }[];
  /** Dates (household-local) the demo has history for; other dates return no doses. */
  historyDates: string[];
  trials: TrialRow[];
}

export const TZ = "America/Los_Angeles";
export const UNKNOWN_TAG = "04A1B2C3D4E5FF";

const obj = (o: Omit<ObjectRow, "updatedAt">, updatedAt: number): ObjectRow => ({ ...o, updatedAt });

export function makeFixtures(now: number, opts: { trials?: "example" | "none" } = {}): FixtureData {
  const today = localDate(now, TZ);
  const yesterday = addDays(today, -1);
  const at = (date: string, hhmm: string) => zonedToUnix(date, hhmm, TZ);

  const objects: ObjectRow[] = [
    obj(
      {
        objectId: "salt",
        name: "salt",
        aliases: ["table salt", "sea salt"],
        notes: "For cooking and for eggs.",
        description: "Small glass jar with a white lid, identical to the sugar jar.",
        tag: "04A1B2C3D4E501",
        homeSpot: 2,
        isMedication: false,
        fobId: null,
      },
      now - 86400 * 3,
    ),
    obj(
      {
        objectId: "sugar",
        name: "sugar",
        aliases: ["white sugar", "sweetener"],
        notes: "For coffee and tea.",
        description: "Small glass jar with a white lid, identical to the salt jar.",
        tag: "04A1B2C3D4E502",
        homeSpot: 3,
        isMedication: false,
        fobId: null,
      },
      now - 86400 * 3,
    ),
    obj(
      {
        objectId: "pepper",
        name: "pepper",
        aliases: ["black pepper", "pepper grinder"],
        notes: "For eggs and soup. Usually kept in the pantry.",
        description: "Tall wooden pepper grinder.",
        tag: "04A1B2C3D4E503",
        homeSpot: null,
        isMedication: false,
        fobId: null,
      },
      now - 86400 * 3,
    ),
    obj(
      {
        objectId: "bp_meds",
        name: "blood pressure pills",
        aliases: ["pills", "medication", "medicine", "blood pressure medicine", "morning pills", "evening pills"],
        notes: "Taken at 8 in the morning and 8 in the evening.",
        description: "White plastic pill bottle with a child-proof cap.",
        tag: "04A1B2C3D4E504",
        homeSpot: 4,
        isMedication: true,
        fobId: null,
      },
      now - 86400 * 3,
    ),
    obj(
      {
        objectId: "keys",
        name: "keys",
        aliases: ["house keys", "car keys", "key ring"],
        notes: "Roams; carries a Bluetooth fob.",
        description: "Key ring with a small Bluetooth tracker fob.",
        tag: null,
        homeSpot: null,
        isMedication: false,
        fobId: "fob_keys",
      },
      now - 86400 * 3,
    ),
  ];

  const states: ObjectStateRow[] = [
    {
      objectId: "sugar",
      status: "on_spot",
      spot: 3,
      position: [0.16, 0.58, 0.0],
      area: null,
      near: null,
      distanceClass: null,
      precision: "exact",
      homeSpot: 3,
      lastSeenT: now - 2,
      t: now - 600,
    },
    {
      objectId: "salt",
      status: "held",
      spot: null,
      position: null,
      area: null,
      near: null,
      distanceClass: null,
      precision: "none",
      homeSpot: 2,
      lastSeenT: now - 40,
      t: now - 40,
    },
    {
      objectId: "bp_meds",
      status: "on_spot",
      spot: 4,
      position: [0.42, 0.42, 0.0],
      area: null,
      near: null,
      distanceClass: null,
      precision: "exact",
      homeSpot: 4,
      lastSeenT: now - 2,
      t: now - 3600 * 5,
    },
    {
      objectId: "pepper",
      status: "missing",
      spot: null,
      position: null,
      area: null,
      near: null,
      distanceClass: null,
      precision: "none",
      homeSpot: null,
      lastSeenT: now - 86400 * 2 - 4000,
      t: now - 86400 * 2,
    },
    {
      objectId: "keys",
      status: "roaming",
      spot: null,
      position: [0, 0.6, 0],
      area: null,
      near: "hub",
      distanceClass: "mid",
      precision: "proximity",
      homeSpot: null,
      lastSeenT: now - 5,
      t: now - 300,
    },
  ];

  // Medication pickups: yesterday morning on time, nothing yesterday evening (the seeded missed dose),
  // and this morning 84 minutes late, if that time has already passed.
  const medicationPickups = [
    { objectId: "bp_meds", t: at(yesterday, "08:07"), eventId: "e-demo-med-1" },
    { objectId: "bp_meds", t: at(today, "09:24"), eventId: "e-demo-med-2" },
  ].filter((p) => p.t < now);

  const ev = (eventId: string, kind: string, objectId: string | null, t: number, spot: number | null, detail: string) => ({
    eventId,
    kind,
    objectId,
    t,
    spot,
    detail,
  });
  const events: EventRow[] = [
    ev("e-demo-1", "pickup", "salt", now - 40, 2, "Salt picked up from the center left spot."),
    ev("e-demo-2", "unknown_tag", null, now - 180, 1, "An unlabeled tag was put down on the far left spot."),
    ev("e-demo-3", "roaming", "keys", now - 300, null, "Keys came within middle range of the hub receiver."),
    ev("e-demo-4", "placed", "sugar", now - 600, 3, "Sugar put down on the center right spot."),
    ev("e-demo-5", "pickup", "sugar", now - 700, 3, "Sugar picked up from the center right spot."),
    ...medicationPickups.flatMap((p, i) => [
      ev(`e-demo-med-put-${i}`, "placed", "bp_meds", p.t + 70, 4, "Blood pressure pills put down on the far right spot."),
      ev(p.eventId, "pickup", "bp_meds", p.t, 4, "Blood pressure pills picked up from the far right spot."),
    ]),
    ev("e-demo-6", "lost", "pepper", now - 86400 * 2 - 4000, null, "Pepper has not been detected since this time."),
  ]
    .filter((e) => e.t < now)
    .sort((a, b) => b.t - a.t);

  const trials: TrialRow[] =
    opts.trials === "none"
      ? []
      : [
          trial("t-demo-1", "baseline", "sugar", "Example tester A", now - 7200, 41.2, 1, "found"),
          trial("t-demo-2", "earmark", "sugar", "Example tester A", now - 6900, 9.8, 0, "found"),
          trial("t-demo-3", "baseline", "salt", "Example tester B", now - 6600, 63.5, 2, "found"),
          trial("t-demo-4", "earmark", "salt", "Example tester B", now - 6300, 12.4, 0, "found"),
          trial("t-demo-5", "baseline", "bp_meds", "Example tester A", now - 6000, null, 1, "gave_up", 90),
          trial("t-demo-6", "earmark", "bp_meds", "Example tester B", now - 5700, 11.1, 1, "found"),
        ];

  return {
    now,
    liveMap: {
      household: { name: "Demo household", timezone: TZ },
      spots: [
        { spot: 1, label: "far left", position: [-0.42, 0.42, 0.0] },
        { spot: 2, label: "center left", position: [-0.16, 0.58, 0.0] },
        { spot: 3, label: "center right", position: [0.16, 0.58, 0.0] },
        { spot: 4, label: "far right", position: [0.42, 0.42, 0.0] },
      ],
      areas: [{ area: "kitchen_counter", label: "the counter", position: [0, 0.6, 0] }],
      objects,
      states,
      unknownTags: [{ tag: UNKNOWN_TAG, spot: 1, t: now - 180 }],
      anchors: [
        { anchorId: "uwb_1", label: "UWB Reader/Emitter 1", position: [-0.9, 0.75, -0.25], online: true, lastDistanceM: 2.4, lastSeenT: now - 1 },
        { anchorId: "uwb_2", label: "UWB Reader/Emitter 2", position: [0.9, 0.75, -0.25], online: true, lastDistanceM: 2.6, lastSeenT: now - 1 },
        { anchorId: "uwb_3", label: "UWB Reader/Emitter 3", position: [0.0, -2.4, -0.25], online: true, lastDistanceM: 1.1, lastSeenT: now - 1 },
      ],
      wearer: { position: [0.12, -1.85, 0], mode: "tracked", source: "uwb", t: now - 1 },
    },
    events,
    medications: [{ objectId: "bp_meds", name: "blood pressure pills", scheduleTimes: ["08:00", "20:00"], windowMinutes: 60 }],
    medicationPickups,
    historyDates: [yesterday, today],
    trials,
  };
}

function trial(
  trialId: string,
  mode: TrialRow["mode"],
  targetObjectId: string,
  tester: string,
  startedAt: number,
  secondsToFind: number | null,
  wrongPicks: number,
  outcome: TrialRow["outcome"],
  durationIfNotFound = 0,
): TrialRow {
  const length = secondsToFind ?? durationIfNotFound;
  return { trialId, mode, targetObjectId, tester, startedAt, endedAt: startedAt + length, secondsToFind, wrongPicks, outcome };
}

/**
 * The demo's copy of the adherence rule in contracts/README.md. The real rule lives in Convex;
 * this exists only so demo mode has consistent doses for any time of day.
 */
export function demoDoses(data: FixtureData, date: string, now: number): DoseRow[] {
  if (!data.historyDates.includes(date)) return [];
  const rows: DoseRow[] = [];
  const used = new Set<string>();
  for (const med of data.medications) {
    for (const time of [...med.scheduleTimes].sort()) {
      const S = zonedToUnix(date, time, TZ);
      const W = med.windowMinutes * 60;
      const candidates = data.medicationPickups.filter((p) => p.objectId === med.objectId && !used.has(p.eventId));
      const taken = candidates.find((p) => Math.abs(p.t - S) <= W);
      const late = taken ? undefined : candidates.find((p) => p.t - S > W && p.t - S <= 2 * W);
      const evidence = taken ?? late;
      if (evidence) used.add(evidence.eventId);
      rows.push({
        objectId: med.objectId,
        name: med.name,
        scheduledLocalTime: time,
        scheduledForT: S,
        status: taken ? "taken" : late ? "late" : now > S + 2 * W ? "missed" : "pending",
        takenT: evidence?.t ?? null,
        evidenceEventId: evidence?.eventId ?? null,
      });
    }
  }
  return rows;
}
