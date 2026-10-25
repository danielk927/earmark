import type { AnchorRow, DistanceClass, ListenerMode, LiveMap, ObjectRow, ObjectStateRow, SpotRow, WearerPoseRow } from "@contracts/convexFunctions";

/** "blood pressure pills" -> "Blood pressure pills". Stored names stay as typed. */
export function capitalize(text: string): string {
  return text.length ? text[0]!.toUpperCase() + text.slice(1) : text;
}

export function spotLabel(spots: SpotRow[], spot: number | null | undefined): string | null {
  if (spot == null) return null;
  return spots.find((s) => s.spot === spot)?.label ?? `spot ${spot}`;
}

/** "the far left spot" (or "spot 7" when the spot is not configured). */
export function theSpot(spots: SpotRow[], spot: number): string {
  const s = spots.find((x) => x.spot === spot);
  return s ? `the ${s.label} spot` : `spot ${spot}`;
}

export const distanceWords: Record<DistanceClass, string> = {
  near: "close range",
  mid: "middle range",
  far: "far range",
};

/** Receiver ids are not labeled in the live map contract yet, so name them plainly. */
export function receiverWords(near: string): string {
  return `the ${near} receiver`;
}

export function objectName(map: Pick<LiveMap, "objects">, objectId: string): string {
  return map.objects.find((o) => o.objectId === objectId)?.name ?? objectId;
}

export type StatusKey = ObjectStateRow["status"] | "no_reading" | "unlabeled";

export const statusText: Record<StatusKey, string> = {
  on_spot: "On a spot",
  held: "Picked up",
  missing: "Missing",
  roaming: "Roaming",
  no_reading: "No reading yet",
  unlabeled: "Not labeled yet",
};

/** One plain sentence for where an object is, built only from what the state says. */
export function whereText(map: LiveMap, obj: ObjectRow, state: ObjectStateRow | undefined): string {
  const home = obj.homeSpot != null ? spotLabel(map.spots, obj.homeSpot) : null;
  if (!state) return home ? `No reading yet. Home is the ${home} spot.` : "No reading yet.";
  switch (state.status) {
    case "on_spot": {
      if (state.spot == null) {
        const area = state.area ? map.areas.find((a) => a.area === state.area)?.label ?? state.area : null;
        return area ? `Somewhere on ${area}` : "On a spot";
      }
      const where = capitalize(theSpot(map.spots, state.spot));
      if (obj.homeSpot === state.spot) return `${where} (its home)`;
      return home ? `${where}. Home is the ${home} spot.` : where;
    }
    case "held":
      return home ? `Off its spot. Home is the ${home} spot.` : "Off its spot";
    case "missing":
      return home ? `Not detected. Home is the ${home} spot.` : "Not detected";
    case "roaming": {
      if (!state.near) return "Moving around, location unknown";
      const range = state.distanceClass ? `, ${distanceWords[state.distanceClass]}` : "";
      return `Near ${receiverWords(state.near)}${range}`;
    }
  }
}

export function splitAliases(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const a = raw.trim();
    if (a && !seen.has(a.toLowerCase())) {
      seen.add(a.toLowerCase());
      out.push(a);
    }
  }
  return out;
}

/** The person's mode in plain words (never color alone). */
export const poseWords: Record<ListenerMode, string> = {
  tracked: "Walking toward the counter",
  frozen: "At the counter",
  lost: "Location lost",
  fixed: "Seated at the listening spot",
};

export const poseSourceWords: Record<WearerPoseRow["source"], string> = {
  uwb: "Position from the UWB anchors",
  sound: "Position from sound only",
  sim: "Simulated position",
  none: "No position source",
};

/** "UWB Reader/Emitter 1: online, 2.4 m from the person." (no sentence stop here; callers add it). */
export function anchorWords(a: AnchorRow): string {
  if (!a.online) return `${a.label}: offline`;
  return `${a.label}: online, ${a.lastDistanceM != null ? `${a.lastDistanceM.toFixed(1)} m from the person` : "distance not measured yet"}`;
}
