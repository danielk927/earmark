/**
 * What the room view knows, built only from Earmark bus messages (contracts/schemas/bus_message.schema.json).
 * Pure: `reduce` takes the state and one message and returns the next state, so it is easy to test.
 * Coordinates are Earmark's: meters, origin on the floor under the mat center, +x right, +y forward, +z up.
 */
export type Vec3 = [number, number, number];

export interface Item {
  id: string;
  name: string;
  position: Vec3 | null;
  status: string;
  where: string;
}
export interface Place {
  id: string;
  label: string;
  position: Vec3;
  kind: "area" | "spot";
}
export interface LogLine {
  t: number;
  kind: "heard" | "said" | "memory" | "found" | "info";
  text: string;
}
/** One exchange: what the person said, then what Earmark answered (q is null for something Earmark said unprompted). */
export interface Turn {
  t: number;
  q: string | null;
  a: string[];
}
export interface Guide {
  objectId: string;
  name: string;
  target: Vec3;
  started: number;
}
export interface RoomState {
  connected: boolean;
  places: Place[];
  items: Record<string, Item>;
  user: Vec3;
  userLive: boolean; // a real fix arrived recently
  userSource: string; // beacons | manual | mat
  lastFixT: number | null;
  trail: Vec3[];
  headYaw: number | null; // degrees, + = turned right
  headT: number | null;
  guide: Guide | null;
  log: LogLine[];
  convo: Turn[];
  status: Record<string, { ok: boolean; detail: string; t: number }>;
  now: number; // when the state last changed or ticked, unix seconds
}

export const MAX_TRAIL = 80;
export const MAX_LOG = 40;
export const MAX_TURNS = 20;

/** A question starts a new exchange. */
export function ask(s: RoomState, text: string, now: number): RoomState {
  return { ...s, convo: [...s.convo, { t: now, q: text, a: [] }].slice(-MAX_TURNS) };
}

/** Earmark's words go under the oldest question that has no answer yet, so the page reads question, answer, question, answer. */
function answer(s: RoomState, text: string, now: number): RoomState {
  const convo = s.convo.map((t) => ({ ...t, a: [...t.a] }));
  let turn = convo.find((t) => t.q !== null && t.a.length === 0);
  if (!turn) turn = convo[convo.length - 1];
  if (!turn) {
    convo.push({ t: now, q: null, a: [text] });
  } else if (turn.a[turn.a.length - 1] !== text) {
    turn.a.push(text);
  }
  return { ...s, convo: convo.slice(-MAX_TURNS) };
}
const MAT: Vec3 = [0, 0, 1.55];

export function initialState(): RoomState {
  return {
    connected: false, places: [], items: {}, user: MAT, userLive: false, userSource: "mat", lastFixT: null,
    trail: [], headYaw: null, headT: null, guide: null, log: [], convo: [], status: {}, now: 0,
  };
}

type Msg = Record<string, unknown> & { type: string };
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const vec = (x: unknown): Vec3 | null =>
  Array.isArray(x) && x.length === 3 && x.every((v) => typeof v === "number") ? (x as Vec3) : null;

function addLog(s: RoomState, line: LogLine): LogLine[] {
  return [line, ...s.log].slice(0, MAX_LOG);
}

function whereText(s: RoomState, loc: Record<string, unknown> | undefined, status: string): string {
  if (!loc) return status;
  const spot = num(loc.spot);
  if (spot !== null) return `on spot ${spot}`;
  const area = typeof loc.area === "string" ? loc.area : null;
  if (area) return `in ${s.places.find((p) => p.id === area)?.label ?? area}`;
  if (typeof loc.near === "string") return `near the ${loc.near} receiver`;
  if (vec(loc.position) && status === "roaming") return "where it was left";
  return status === "held" ? "picked up" : status;
}

function applyState(s: RoomState, st: Msg): RoomState {
  const id = String(st.object_id);
  const prev = s.items[id];
  const loc = st.location as Record<string, unknown> | undefined;
  const status = String(st.status ?? "missing");
  const item: Item = {
    id, name: prev?.name ?? id, status,
    position: status === "held" ? null : vec(loc?.position),
    where: whereText(s, loc, status),
  };
  return { ...s, items: { ...s.items, [id]: item } };
}

export function reduce(s: RoomState, m: Msg, now: number): RoomState {
  switch (m.type) {
    case "snapshot": {
      const space = (m.space ?? {}) as { areas?: Msg[]; spots?: Msg[] };
      const places: Place[] = [
        ...(space.areas ?? []).map((a) => ({ id: String(a.area), label: String(a.label), position: vec(a.position)!, kind: "area" as const })),
        ...(space.spots ?? []).map((p) => ({ id: `spot${p.spot}`, label: `spot ${p.spot}`, position: vec(p.position)!, kind: "spot" as const })),
      ].filter((p) => p.position);
      let next: RoomState = { ...s, connected: true, places, items: {} };
      for (const o of (m.objects as Msg[] | undefined) ?? []) {
        const id = String(o.object_id);
        next.items[id] = { id, name: String(o.name), position: null, status: "missing", where: "not detected" };
      }
      for (const st of (m.states as Msg[] | undefined) ?? []) next = applyState(next, st);
      return next;
    }
    case "registry_update": {
      const items = { ...s.items };
      for (const o of (m.objects as Msg[] | undefined) ?? []) {
        const id = String(o.object_id);
        items[id] = { ...(items[id] ?? { id, position: null, status: "missing", where: "not detected" }), name: String(o.name) };
      }
      return { ...s, items };
    }
    case "state_update":
      return applyState(s, m);
    case "listener_pose": {
      const p = vec(m.position);
      if (!p) return s;
      if (m.quality === "lost") return { ...s, userLive: false };
      const last = s.trail[s.trail.length - 1];
      const moved = !last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.03;
      return {
        ...s, user: p, userLive: true, userSource: String(m.source ?? "beacons"), lastFixT: now,
        trail: moved ? [...s.trail, p].slice(-MAX_TRAIL) : s.trail,
      };
    }
    case "head_pose": {
      const yaw = num(m.yaw);
      return yaw === null ? s : { ...s, headYaw: yaw, headT: now };
    }
    case "guide_start": {
      const t = vec(m.target_position);
      if (!t) return s;
      return { ...s, guide: { objectId: String(m.object_id), name: String(m.name), target: t, started: now } };
    }
    case "guide_stop":
      return { ...s, guide: null };
    case "guide_feedback":
      if (m.event === "arrived") {
        const name = s.items[String(m.object_id)]?.name ?? String(m.object_id);
        return { ...s, log: addLog(s, { t: now, kind: "found", text: `Reached the ${name}` }) };
      }
      return s;
    case "transcript":
      return m.is_final ? ask({ ...s, log: addLog(s, { t: now, kind: "heard", text: String(m.text) }) }, String(m.text), now) : s;
    case "speak":
      return m.seq === 0 && typeof m.text === "string" ? answer({ ...s, log: addLog(s, { t: now, kind: "said", text: m.text }) }, m.text, now) : s;
    case "speak_text":
    case "speak_cached":
      return typeof m.text === "string" ? answer({ ...s, log: addLog(s, { t: now, kind: "said", text: m.text }) }, m.text, now) : s;
    case "place_item": {
      const name = s.items[String(m.object_id)]?.name ?? String(m.object_id);
      const area = typeof m.area === "string" ? s.places.find((p) => p.id === m.area)?.label ?? m.area : null;
      const text = area ? `Remembered: the ${name} is in ${area}` : `Remembered where the ${name} was left`;
      return { ...s, log: addLog(s, { t: now, kind: "memory", text }) };
    }
    case "pickup": {
      const name = s.items[String(m.object_id)]?.name ?? String(m.object_id);
      return { ...s, log: addLog(s, { t: now, kind: "info", text: `The ${name} was picked up` }) };
    }
    case "status":
      return { ...s, status: { ...s.status, [String(m.component)]: { ok: Boolean(m.ok), detail: String(m.detail ?? ""), t: now } } };
    case "reset":
      return { ...s, guide: null, trail: [] };
    default:
      return s;
  }
}

/** Ages things out: a position older than 5 s means the user is assumed back on the mat (as the Mac app does). */
export function tick(s: RoomState, now: number): RoomState {
  let next = { ...s, now };
  if (s.lastFixT !== null && now - s.lastFixT > 5 && s.userSource !== "mat") {
    next = { ...next, user: MAT, userLive: false, userSource: "mat", lastFixT: null };
  } else if (s.userLive && s.lastFixT !== null && now - s.lastFixT > 1.5) {
    next = { ...next, userLive: false };
  }
  if (s.headT !== null && now - s.headT > 2) next = { ...next, headYaw: null, headT: null };
  return next;
}

export function horizontalDistance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Direction from the user to the target as the user would feel it: clock hour, 12 = straight ahead. */
export function clockHour(user: Vec3, yawDeg: number, target: Vec3): number {
  const az = (Math.atan2(target[0] - user[0], target[1] - user[1]) * 180) / Math.PI - yawDeg;
  const h = Math.round((((az % 360) + 360) % 360) / 30) % 12;
  return h === 0 ? 12 : h;
}
