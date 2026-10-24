/**
 * Two days of realistic demo history relative to `now` (pure, deterministic).
 *
 * Days are household-local: the day before yesterday, yesterday, and today up to
 * now. Salt and sugar are picked up and put back around meals; the sugar spends
 * yesterday evening on the far-left spot; the pills are picked up near 08:00 and
 * 20:00 except yesterday evening (the one missed dose); the keys' fob is asked
 * to chirp. Only actions that finished at least a minute before `now` are kept,
 * so every object ends back on its home spot.
 */
import { addDays, localDate, localHHMM, zonedToUnix } from "./time";

export interface SeedObject {
  objectId: string;
  tag: string | null;
  homeSpot: number | null;
  fobId: string | null;
}

export interface PlannedEvent {
  eventId: string;
  kind: "pickup" | "placed" | "chirp";
  objectId: string;
  t: number;
  spot: number | null;
  data: Record<string, unknown>;
}

type Step = { at: string; object: string; hold?: number; to?: number } | { at: string; chirp: string };

/** Index 0: two days ago, 1: yesterday, 2: today. */
const DAYS: Step[][] = [
  [
    { at: "07:31", object: "sugar", hold: 2 },
    { at: "07:46", object: "salt", hold: 3 },
    { at: "08:04", object: "bp_meds", hold: 2 },
    { at: "12:28", object: "salt", hold: 2 },
    { at: "15:12", object: "sugar", hold: 1 },
    { at: "18:41", object: "salt", hold: 2 },
    { at: "20:12", object: "bp_meds", hold: 2 },
  ],
  [
    { at: "07:40", object: "sugar", hold: 2 },
    { at: "07:52", object: "bp_meds", hold: 2 },
    { at: "08:10", object: "salt", hold: 3 },
    { at: "08:50", chirp: "keys" },
    { at: "12:35", object: "salt", hold: 2 },
    { at: "15:05", object: "sugar", hold: 2 },
    { at: "18:37", object: "salt", hold: 2 },
    { at: "19:20", object: "sugar", hold: 2, to: 1 },
    { at: "21:05", object: "sugar", hold: 1 },
    // No evening pills: the 20:00 dose is the missed one.
  ],
  [
    { at: "07:28", object: "sugar", hold: 2 },
    { at: "07:44", object: "salt", hold: 3 },
    { at: "08:15", object: "bp_meds", hold: 2 },
    { at: "09:10", chirp: "keys" },
    { at: "12:31", object: "salt", hold: 2 },
    { at: "15:15", object: "sugar", hold: 2 },
    { at: "18:44", object: "salt", hold: 2 },
    { at: "20:06", object: "bp_meds", hold: 2 },
  ],
];

/** Local midnight that starts the history (doses before it are not generated). */
export function historyStartDate(now: number, timezone: string): string {
  return addDays(localDate(now, timezone), -2);
}

export function planHistory(now: number, timezone: string, objects: readonly SeedObject[]): PlannedEvent[] {
  const byId = new Map(objects.map((o) => [o.objectId, o]));
  const where = new Map(objects.map((o) => [o.objectId, o.homeSpot]));
  const today = localDate(now, timezone);
  const out: PlannedEvent[] = [];
  DAYS.forEach((steps, i) => {
    const date = addDays(today, i - 2);
    for (const step of steps) {
      const start = zonedToUnix(date, step.at, timezone);
      const id = (kind: string, t: number, obj: string) =>
        `seed-${date}-${localHHMM(t, timezone).replace(":", "")}-${obj}-${kind}`;
      if ("chirp" in step) {
        const o = byId.get(step.chirp);
        if (!o?.fobId || start + 60 > now - 60) continue;
        for (const [action, t] of [["start", start], ["stop", start + 60]] as const) {
          out.push({
            eventId: id(`chirp_${action}`, t, o.objectId),
            kind: "chirp",
            objectId: o.objectId,
            t,
            spot: null,
            data: { type: "chirp", fob_id: o.fobId, action, t },
          });
        }
        continue;
      }
      const o = byId.get(step.object);
      const from = where.get(step.object);
      if (!o || o.tag === null || from === null || from === undefined) continue;
      const to = step.to ?? o.homeSpot ?? from;
      const back = start + (step.hold ?? 2) * 60;
      if (back > now - 60) continue;
      out.push({
        eventId: id("pickup", start, o.objectId),
        kind: "pickup",
        objectId: o.objectId,
        t: start,
        spot: from,
        data: { type: "pickup", object_id: o.objectId, from_spot: from, t: start },
      });
      out.push({
        eventId: id("placed", back, o.objectId),
        kind: "placed",
        objectId: o.objectId,
        t: back,
        spot: to,
        data: { spot: to, tag: o.tag, source: "simulator" },
      });
      where.set(o.objectId, to);
    }
  });
  return out;
}
