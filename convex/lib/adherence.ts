/**
 * Medication adherence, exactly as specified in contracts/README.md.
 *
 * For each scheduled time S and window W (minutes), using pickups of the medication object:
 * - taken:   a pickup with |pickup - S| <= W.
 * - late:    no taken pickup, but a pickup with W < pickup - S <= 2W.
 * - missed:  neither, and now > S + 2W.
 * - pending: neither, and now <= S + 2W.
 * Each pickup is evidence for at most one dose: the nearest scheduled time
 * (an exact tie goes to the earlier dose). When several pickups qualify for one
 * dose, the earliest one is the evidence.
 *
 * Pure: no Convex imports, no clock. Times are unix seconds.
 */

export type DoseStatus = "taken" | "late" | "missed" | "pending";

export interface ScheduledDose {
  /** Caller-defined identity, echoed back. */
  key: string;
  scheduledFor: number;
}

export interface Pickup {
  eventId: string;
  t: number;
}

export interface DoseResult {
  key: string;
  scheduledFor: number;
  status: DoseStatus;
  takenT: number | null;
  evidenceEventId: string | null;
}

export function computeAdherence(
  scheduled: readonly ScheduledDose[],
  pickups: readonly Pickup[],
  windowMinutes: number,
  now: number,
): DoseResult[] {
  const w = windowMinutes * 60;
  const doses = [...scheduled].sort((a, b) => a.scheduledFor - b.scheduledFor || a.key.localeCompare(b.key));
  const assigned: Pickup[][] = doses.map(() => []);
  for (const p of pickups) {
    let best = -1;
    for (let i = 0; i < doses.length; i++) {
      // Doses are sorted, so strict "<" keeps the earlier dose on a tie.
      if (best === -1 || Math.abs(p.t - doses[i].scheduledFor) < Math.abs(p.t - doses[best].scheduledFor)) best = i;
    }
    if (best !== -1) assigned[best].push(p);
  }
  return doses.map((dose, i) => {
    const s = dose.scheduledFor;
    const evidence = assigned[i].sort((a, b) => a.t - b.t || a.eventId.localeCompare(b.eventId));
    const taken = evidence.find((p) => Math.abs(p.t - s) <= w);
    const late = taken ? undefined : evidence.find((p) => p.t - s > w && p.t - s <= 2 * w);
    const hit = taken ?? late;
    const status: DoseStatus = taken ? "taken" : late ? "late" : now > s + 2 * w ? "missed" : "pending";
    return {
      key: dose.key,
      scheduledFor: s,
      status,
      takenT: hit ? hit.t : null,
      evidenceEventId: hit ? hit.eventId : null,
    };
  });
}
