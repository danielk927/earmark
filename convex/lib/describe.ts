/**
 * Deterministic sentences for history, the dashboard timeline, and daily summaries.
 * Facts only: no LLM, no medical advice.
 */
import { localHHMM, longDateLabel } from "./time";

export interface EventFacts {
  kind: string;
  objectId: string | null;
  spot: number | null;
  data: Record<string, unknown>;
}

export interface Names {
  objectName: (objectId: string) => string;
  spotLabel: (spot: number) => string | null;
}

const str = (x: unknown): string | null => (typeof x === "string" && x.length > 0 ? x : null);
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function spotPhrase(spot: number | null, names: Names): string | null {
  if (spot === null) return null;
  const label = names.spotLabel(spot);
  return label ? `the ${label} spot` : `spot ${spot}`;
}

/**
 * One sentence describing an event. With `subject`, the sentence names the object
 * ("Sugar picked up from the center right spot."); without it, the object is implied
 * ("Picked up from the center right spot.").
 */
export function describeEvent(e: EventFacts, names: Names, subject: boolean): string {
  const who = e.objectId ? names.objectName(e.objectId) : null;
  const lead = (verb: string) => (subject && who ? `${cap(who)} ${verb}` : cap(verb));
  const where = spotPhrase(e.spot, names);
  switch (e.kind) {
    case "pickup":
      return `${lead("picked up")}${where ? ` from ${where}` : ""}.`;
    case "placed":
      return `${lead("put down")}${where ? ` on ${where}` : ""}.`;
    case "removed":
      if (!who) return `An unlabeled tag was removed${where ? ` from ${where}` : ""}.`;
      return `${lead("removed")}${where ? ` from ${where}` : ""}.`;
    case "unknown_tag":
      return `An unlabeled tag was put down${where ? ` on ${where}` : ""}.`;
    case "label": {
      const name = str(e.data.name) ?? who ?? "an item";
      return `Tag labeled as ${name}${where ? ` on ${where}` : ""}.`;
    }
    case "chirp": {
      const start = e.data.action !== "stop";
      const thing = subject && who ? `The ${who} fob` : "The fob";
      return start ? `${thing} was asked to chirp.` : `${thing} stopped chirping.`;
    }
    case "pickup_result": {
      const expected = str(e.data.expected);
      const actual = str(e.data.actual);
      const exp = expected ? names.objectName(expected) : "the target";
      if (e.data.correct === true) return `Picked up the ${exp} as guided.`;
      return actual ? `Picked up the ${names.objectName(actual)} while looking for the ${exp}.` : `Wrong item picked up while looking for the ${exp}.`;
    }
    case "trial_start": {
      const id = str(e.data.trial_id) ?? "?";
      const target = str(e.data.target_object_id);
      return `Trial ${id} started in ${str(e.data.mode) ?? "unknown"} mode${target ? `, target ${names.objectName(target)}` : ""}.`;
    }
    case "trial_end": {
      const id = str(e.data.trial_id) ?? "?";
      const picks = num(e.data.wrong_picks) ?? 0;
      const wrong = `${picks} wrong ${picks === 1 ? "pick" : "picks"}`;
      const secs = num(e.data.seconds_to_find);
      if (e.data.outcome === "found") {
        return `Trial ${id} ended: found${secs !== null ? ` in ${Math.round(secs * 10) / 10} seconds` : ""} with ${wrong}.`;
      }
      return `Trial ${id} ended: ${e.data.outcome === "gave_up" ? "gave up" : "aborted"} with ${wrong}.`;
    }
    default:
      return `${cap(e.kind.replace(/_/g, " "))} event.`;
  }
}

export interface SummaryDose {
  objectId: string;
  name: string;
  scheduledLocalTime: string;
  scheduledFor: number;
  status: "taken" | "late" | "missed" | "pending";
  takenT: number | null;
  windowMinutes: number;
}

/**
 * e.g. "On Thursday, October 23: the 20:00 blood pressure pills dose was missed
 * (no pickup between 19:00 and 22:00). 14 pickups recorded. Not touched in 7 days: pepper."
 */
export function summaryText(args: {
  date: string;
  timezone: string;
  doses: SummaryDose[];
  pickupCount: number;
  untouchedNames: string[];
  missingNames: string[];
}): string {
  const { timezone } = args;
  const clauses: string[] = [];
  let previous: string | null = null;
  for (const d of args.doses) {
    const label = d.objectId === previous ? `the ${d.scheduledLocalTime} dose` : `the ${d.scheduledLocalTime} ${d.name} dose`;
    previous = d.objectId;
    const at = d.takenT !== null ? localHHMM(d.takenT, timezone) : null;
    const w = d.windowMinutes * 60;
    switch (d.status) {
      case "taken":
        clauses.push(`${label} was taken at ${at}`);
        break;
      case "late":
        clauses.push(`${label} was taken late, at ${at}`);
        break;
      case "missed":
        clauses.push(
          `${label} was missed (no pickup between ${localHHMM(d.scheduledFor - w, timezone)} and ${localHHMM(d.scheduledFor + 2 * w, timezone)})`,
        );
        break;
      case "pending":
        clauses.push(`${label} is pending`);
        break;
    }
  }
  const sentences: string[] = [];
  const head = `On ${longDateLabel(args.date)}: `;
  if (clauses.length === 0) sentences.push(`${head}no medication doses were scheduled.`);
  else {
    sentences.push(`${head}${clauses[0]}.`);
    for (const c of clauses.slice(1)) sentences.push(`${cap(c)}.`);
  }
  sentences.push(`${args.pickupCount} ${args.pickupCount === 1 ? "pickup" : "pickups"} recorded.`);
  if (args.untouchedNames.length > 0) sentences.push(`Not touched in 7 days: ${args.untouchedNames.join(", ")}.`);
  if (args.missingNames.length > 0) sentences.push(`Missing: ${args.missingNames.join(", ")}.`);
  return sentences.join(" ");
}
