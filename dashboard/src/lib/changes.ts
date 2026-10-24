import type { LiveMap, ObjectStateRow } from "@contracts/convexFunctions";
import { capitalize, distanceWords, objectName, receiverWords, theSpot } from "./words";

/**
 * Plain sentences describing what changed between two live map snapshots,
 * for the polite live region and the visible "Recent changes" list.
 */
export function describeChanges(prev: LiveMap, next: LiveMap): string[] {
  const out: string[] = [];
  const spots = next.spots;

  const prevObjects = new Map(prev.objects.map((o) => [o.objectId, o]));
  const nextObjects = new Map(next.objects.map((o) => [o.objectId, o]));
  for (const [id, o] of nextObjects) {
    const before = prevObjects.get(id);
    if (!before) out.push(`${capitalize(o.name)} added.`);
    else if (before.name !== o.name) out.push(`${capitalize(before.name)} renamed to ${o.name}.`);
  }
  for (const [id, o] of prevObjects) if (!nextObjects.has(id)) out.push(`${capitalize(o.name)} removed.`);

  const prevStates = new Map(prev.states.map((s) => [s.objectId, s]));
  for (const s of next.states) {
    const before = prevStates.get(s.objectId);
    const sentence = before && describeState(capitalize(objectName(next, s.objectId)), before, s, spots);
    if (sentence) out.push(sentence);
  }

  const prevTags = new Set(prev.unknownTags.map((u) => u.tag));
  for (const u of next.unknownTags) {
    if (prevTags.has(u.tag)) continue;
    out.push(u.spot != null ? `New item on ${theSpot(spots, u.spot)}. Label it on the Items page.` : "New unlabeled tag seen.");
  }
  return out;
}

function describeState(
  name: string,
  a: ObjectStateRow,
  b: ObjectStateRow,
  spots: LiveMap["spots"],
): string | null {
  if (a.status === b.status && a.spot === b.spot && a.near === b.near && a.distanceClass === b.distanceClass) return null;
  switch (b.status) {
    case "held":
      return a.status === "on_spot" && a.spot != null ? `${name} picked up from ${theSpot(spots, a.spot)}.` : `${name} picked up.`;
    case "on_spot":
      if (b.spot == null) return `${name} put down.`;
      if (a.status === "on_spot" && a.spot != null) return `${name} moved to ${theSpot(spots, b.spot)}.`;
      return `${name} put down on ${theSpot(spots, b.spot)}.`;
    case "missing":
      return `${name} is missing.`;
    case "roaming": {
      if (!b.near) return `${name} is moving around.`;
      const range = b.distanceClass ? `, ${distanceWords[b.distanceClass]}` : "";
      return `${name} is near ${receiverWords(b.near)}${range}.`;
    }
  }
}
