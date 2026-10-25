/**
 * The HTTP boundary: parse and validate snake_case request bodies
 * (contracts/schemas/convex_http.schema.json, object_state.schema.json) into
 * camelCase values, and convert camelCase results back to snake_case.
 * Pure: no Convex function imports.
 */
import { formatLocalIso } from "./time";
import type { Vec3 } from "./validators";

export class BadRequest extends Error {}

type Json = Record<string, unknown>;

const isObject = (x: unknown): x is Json => typeof x === "object" && x !== null && !Array.isArray(x);
const isInt = (x: unknown): x is number => typeof x === "number" && Number.isInteger(x);
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

function fail(path: string, msg: string): never {
  throw new BadRequest(`${path} ${msg}`);
}

function obj(x: unknown, path: string): Json {
  if (!isObject(x)) fail(path, "must be an object");
  return x;
}

function onlyKeys(o: Json, allowed: readonly string[], path: string) {
  for (const k of Object.keys(o)) if (!allowed.includes(k)) fail(`${path}.${k}`, "is not allowed");
}

function has(o: Json, key: string, path: string) {
  if (!(key in o)) fail(`${path}.${key}`, "is required");
}

function str(o: Json, key: string, path: string, minLength = 0): string {
  has(o, key, path);
  const x = o[key];
  if (typeof x !== "string" || x.length < minLength) {
    fail(`${path}.${key}`, minLength > 0 ? `must be a string of at least ${minLength} characters` : "must be a string");
  }
  return x;
}

function nullableStr(o: Json, key: string, path: string): string | null {
  has(o, key, path);
  const x = o[key];
  if (x !== null && typeof x !== "string") fail(`${path}.${key}`, "must be a string or null");
  return x;
}

function num(o: Json, key: string, path: string): number {
  has(o, key, path);
  if (!isNum(o[key])) fail(`${path}.${key}`, "must be a number");
  return o[key];
}

function nullableNum(o: Json, key: string, path: string): number | null {
  has(o, key, path);
  const x = o[key];
  if (x !== null && !isNum(x)) fail(`${path}.${key}`, "must be a number or null");
  return x;
}

function nullableInt(o: Json, key: string, path: string): number | null {
  has(o, key, path);
  const x = o[key];
  if (x !== null && !isInt(x)) fail(`${path}.${key}`, "must be an integer or null");
  return x;
}

function oneOf<T extends string>(o: Json, key: string, path: string, values: readonly T[]): T {
  has(o, key, path);
  const x = o[key];
  if (typeof x !== "string" || !(values as readonly string[]).includes(x)) {
    fail(`${path}.${key}`, `must be one of ${values.join(", ")}`);
  }
  return x as T;
}

/** Optional-or-nullable field: absent means null. */
function opt<T>(o: Json, key: string, read: () => T): T | null {
  return key in o ? read() : null;
}

/** Convex stores `data` as a document value: keys must be field names, depth and size bounded. */
function checkStorable(x: unknown, path: string, depth: number): void {
  if (depth > 16) fail(path, "is nested too deeply");
  if (Array.isArray(x)) {
    if (x.length > 8192) fail(path, "has too many items");
    x.forEach((item, i) => checkStorable(item, `${path}[${i}]`, depth + 1));
  } else if (isObject(x)) {
    const keys = Object.keys(x);
    if (keys.length > 1024) fail(path, "has too many keys");
    for (const k of keys) {
      if (!/^[\x21-\x7e][\x20-\x7e]*$/.test(k) || k.startsWith("$") || k.startsWith("_")) {
        fail(`${path}`, `has an invalid key ${JSON.stringify(k)}`);
      }
      checkStorable(x[k], `${path}.${k}`, depth + 1);
    }
  } else if (typeof x === "number") {
    if (!Number.isFinite(x)) fail(path, "must be finite");
  } else if (x !== null && typeof x !== "string" && typeof x !== "boolean") {
    fail(path, "is not JSON");
  }
}

// ---------------------------------------------------------------- POST /ingest

export const EVENT_KINDS = [
  "placed",
  "removed",
  "pickup",
  "pickup_result",
  "unknown_tag",
  "label",
  "stored",
  "chirp",
  "trial_start",
  "trial_end",
] as const;
export type EventKind = (typeof EVENT_KINDS)[number];

const TRIAL_MODES = ["earmark", "baseline"] as const;
const TRIAL_OUTCOMES = ["found", "gave_up", "aborted"] as const;

export interface TrialValue {
  trialId: string;
  mode: (typeof TRIAL_MODES)[number];
  targetObjectId: string;
  tester: string;
  startedAt: number;
  endedAt: number | null;
  secondsToFind: number | null;
  wrongPicks: number;
  outcome: (typeof TRIAL_OUTCOMES)[number] | null;
}

export interface IngestEvent {
  eventId: string;
  kind: EventKind;
  objectId: string | null;
  t: number;
  /** Spot the event happened on (pickup: from_spot; placed/removed/unknown_tag/label: spot). */
  spot: number | null;
  /** Tag the event concerns (placed/removed/unknown_tag/label), uppercase, else null. */
  tag: string | null;
  data: Record<string, unknown>;
  trial: TrialValue | null;
}

const STATUSES = ["on_spot", "held", "missing", "roaming"] as const;
const PRECISIONS = ["exact", "area", "proximity", "none"] as const;
const SOURCES = ["simulator", "nfc", "ble", "camera", "ultrasonic", "none"] as const;
const DISTANCE = ["near", "mid", "far"] as const;

export interface IngestState {
  objectId: string;
  status: (typeof STATUSES)[number];
  spot: number | null;
  position: Vec3 | null;
  area: string | null;
  near: string | null;
  distanceClass: (typeof DISTANCE)[number] | null;
  precision: (typeof PRECISIONS)[number];
  homeSpot: number | null;
  lastSeenT: number | null;
  source: (typeof SOURCES)[number];
  t: number;
}

export interface IngestAnchor {
  anchorId: string;
  label: string;
  position: Vec3;
  online: boolean;
  lastDistanceM: number | null;
  lastSeenT: number | null;
}

const POSE_MODES = ["tracked", "frozen", "lost", "fixed"] as const;
const POSE_SOURCES = ["uwb", "sound", "sim", "none"] as const;

export interface IngestPose {
  position: Vec3;
  mode: (typeof POSE_MODES)[number];
  source: (typeof POSE_SOURCES)[number];
  t: number;
}

export const MAX_INGEST_EVENTS = 500;
export const MAX_INGEST_ANCHORS = 16;
export const MAX_INGEST_STATES = 500;

const upperTag = (tag: string | null) => (tag === null ? null : tag.trim().toUpperCase() || null);

function parseTrial(kind: "trial_start" | "trial_end", d: Json, path: string): TrialValue {
  const base = {
    trialId: str(d, "trial_id", path, 1),
    mode: oneOf(d, "mode", path, TRIAL_MODES),
    targetObjectId: str(d, "target_object_id", path),
    tester: str(d, "tester", path),
  };
  const t = num(d, "t", path);
  if (kind === "trial_start") {
    return { ...base, startedAt: t, endedAt: null, secondsToFind: null, wrongPicks: 0, outcome: null };
  }
  has(d, "wrong_picks", path);
  if (!isInt(d.wrong_picks) || d.wrong_picks < 0) fail(`${path}.wrong_picks`, "must be an integer of 0 or more");
  return {
    ...base,
    startedAt: num(d, "started_t", path),
    endedAt: t,
    secondsToFind: nullableNum(d, "seconds_to_find", path),
    wrongPicks: d.wrong_picks,
    outcome: oneOf(d, "outcome", path, TRIAL_OUTCOMES),
  };
}

export function parseHubEvent(x: unknown, path: string): IngestEvent {
  const e = obj(x, path);
  onlyKeys(e, ["event_id", "kind", "object_id", "t", "data"], path);
  const eventId = str(e, "event_id", path, 8);
  const kind = oneOf(e, "kind", path, EVENT_KINDS);
  const objectId = nullableStr(e, "object_id", path);
  const t = num(e, "t", path);
  has(e, "data", path);
  const data = obj(e.data, `${path}.data`);
  checkStorable(data, `${path}.data`, 0);
  const dp = `${path}.data`;
  let spot: number | null = null;
  let tag: string | null = null;
  let trial: TrialValue | null = null;
  switch (kind) {
    case "pickup":
      if (objectId === null) fail(`${path}.object_id`, "is required for a pickup");
      has(data, "from_spot", dp);
      if (!isInt(data.from_spot)) fail(`${dp}.from_spot`, "must be an integer");
      spot = data.from_spot;
      break;
    case "placed":
    case "removed":
      spot = opt(data, "spot", () => nullableInt(data, "spot", dp));
      tag = upperTag(opt(data, "tag", () => nullableStr(data, "tag", dp)));
      break;
    case "unknown_tag":
      tag = upperTag(str(data, "tag", dp, 1));
      spot = opt(data, "spot", () => nullableInt(data, "spot", dp));
      break;
    case "label":
      tag = upperTag(str(data, "tag", dp, 1));
      str(data, "name", dp, 1);
      spot = opt(data, "spot", () => nullableInt(data, "spot", dp));
      break;
    case "trial_start":
    case "trial_end":
      trial = parseTrial(kind, data, dp);
      break;
    default:
      break;
  }
  return { eventId, kind, objectId, t, spot, tag, data, trial };
}

export function parseState(x: unknown, path: string): IngestState {
  const s = obj(x, path);
  onlyKeys(s, ["type", "object_id", "location", "precision", "status", "home_spot", "last_seen_t", "source", "t"], path);
  has(s, "type", path);
  if (s.type !== "state_update") fail(`${path}.type`, 'must be "state_update"');
  has(s, "location", path);
  const lp = `${path}.location`;
  const loc = obj(s.location, lp);
  onlyKeys(loc, ["spot", "position", "area", "near", "distance_class"], lp);
  let position: Vec3 | null = null;
  if ("position" in loc && loc.position !== null) {
    const p = loc.position;
    if (!Array.isArray(p) || p.length !== 3 || !p.every(isNum)) fail(`${lp}.position`, "must be null or [x, y, z]");
    position = [p[0], p[1], p[2]];
  }
  let distanceClass: IngestState["distanceClass"] = null;
  if ("distance_class" in loc && loc.distance_class !== null) {
    distanceClass = oneOf(loc, "distance_class", lp, DISTANCE);
  }
  return {
    objectId: str(s, "object_id", path, 1),
    status: oneOf(s, "status", path, STATUSES),
    spot: opt(loc, "spot", () => nullableInt(loc, "spot", lp)),
    position,
    area: opt(loc, "area", () => nullableStr(loc, "area", lp)),
    near: opt(loc, "near", () => nullableStr(loc, "near", lp)),
    distanceClass,
    precision: oneOf(s, "precision", path, PRECISIONS),
    homeSpot: nullableInt(s, "home_spot", path),
    lastSeenT: nullableNum(s, "last_seen_t", path),
    source: oneOf(s, "source", path, SOURCES),
    t: num(s, "t", path),
  };
}

function vec3Of(o: Json, key: string, path: string): Vec3 {
  has(o, key, path);
  const p = o[key];
  if (!Array.isArray(p) || p.length !== 3 || !p.every(isNum)) fail(`${path}.${key}`, "must be [x, y, z]");
  return [p[0], p[1], p[2]];
}

function bool(o: Json, key: string, path: string): boolean {
  has(o, key, path);
  if (typeof o[key] !== "boolean") fail(`${path}.${key}`, "must be a boolean");
  return o[key] as boolean;
}

function parseAnchor(x: unknown, path: string): IngestAnchor {
  const a = obj(x, path);
  onlyKeys(a, ["anchor", "label", "position", "online", "last_distance_m", "last_seen_t"], path);
  return {
    anchorId: str(a, "anchor", path, 1),
    label: str(a, "label", path, 1),
    position: vec3Of(a, "position", path),
    online: bool(a, "online", path),
    lastDistanceM: nullableNum(a, "last_distance_m", path),
    lastSeenT: nullableNum(a, "last_seen_t", path),
  };
}

function parsePose(x: unknown, path: string): IngestPose {
  const p = obj(x, path);
  onlyKeys(p, ["position", "mode", "source", "t"], path);
  return {
    position: vec3Of(p, "position", path),
    mode: oneOf(p, "mode", path, POSE_MODES),
    source: oneOf(p, "source", path, POSE_SOURCES),
    t: num(p, "t", path),
  };
}

export function parseIngestRequest(body: unknown): {
  events: IngestEvent[];
  states: IngestState[];
  anchors: IngestAnchor[];
  pose: IngestPose | null;
} {
  const b = obj(body, "body");
  onlyKeys(b, ["events", "states", "anchors", "pose"], "body");
  has(b, "events", "body");
  has(b, "states", "body");
  if (!Array.isArray(b.events)) fail("body.events", "must be an array");
  if (!Array.isArray(b.states)) fail("body.states", "must be an array");
  if (b.events.length > MAX_INGEST_EVENTS) fail("body.events", `must have at most ${MAX_INGEST_EVENTS} items`);
  if (b.states.length > MAX_INGEST_STATES) fail("body.states", `must have at most ${MAX_INGEST_STATES} items`);
  const rawAnchors = "anchors" in b ? b.anchors : [];
  if (!Array.isArray(rawAnchors)) fail("body.anchors", "must be an array");
  if (rawAnchors.length > MAX_INGEST_ANCHORS) fail("body.anchors", `must have at most ${MAX_INGEST_ANCHORS} items`);
  return {
    events: b.events.map((e, i) => parseHubEvent(e, `body.events[${i}]`)),
    states: b.states.map((s, i) => parseState(s, `body.states[${i}]`)),
    anchors: rawAnchors.map((a, i) => parseAnchor(a, `body.anchors[${i}]`)),
    pose: "pose" in b ? parsePose(b.pose, "body.pose") : null,
  };
}

// ---------------------------------------------------------------- POST /api/label

export function parseLabelRequest(body: unknown): { tag: string; name: string; aliases: string[]; spot: number | null } {
  const b = obj(body, "body");
  onlyKeys(b, ["tag", "name", "aliases", "spot"], "body");
  const tag = upperTag(str(b, "tag", "body"));
  if (tag === null) fail("body.tag", "must not be empty");
  const name = str(b, "name", "body", 1);
  if (name.trim().length === 0) fail("body.name", "must not be blank");
  has(b, "aliases", "body");
  if (!Array.isArray(b.aliases) || !b.aliases.every((a) => typeof a === "string")) {
    fail("body.aliases", "must be an array of strings");
  }
  const spot = opt(b, "spot", () => nullableInt(b, "spot", "body"));
  return { tag, name, aliases: b.aliases as string[], spot };
}

// ---------------------------------------------------------------- query strings

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function parseNumberParam(raw: string | null, name: string): number | null {
  if (raw === null || raw === "") return null;
  if (!/^-?\d+(\.\d+)?$/.test(raw.trim())) throw new BadRequest(`${name} must be unix seconds`);
  return Number(raw);
}

export function parseDateParam(raw: string | null, valid: (d: string) => boolean): string | null {
  if (raw === null || raw === "") return null;
  if (!DATE_RE.test(raw) || !valid(raw)) throw new BadRequest("date must be YYYY-MM-DD");
  return raw;
}

// ---------------------------------------------------------------- responses

const local = (t: number | null, tz: string) => (t === null ? null : formatLocalIso(t, tz));

export interface RegistryValue {
  household: { name: string; timezone: string };
  objects: {
    objectId: string;
    name: string;
    aliases: string[];
    notes: string;
    description: string;
    tag: string | null;
    homeSpot: number | null;
    isMedication: boolean;
    fobId: string | null;
  }[];
  medications: { objectId: string; scheduleTimes: string[]; windowMinutes: number }[];
  version: number | null;
}

export function registryToWire(r: RegistryValue) {
  return {
    household: { name: r.household.name, timezone: r.household.timezone },
    objects: r.objects.map((o) => ({
      object_id: o.objectId,
      name: o.name,
      aliases: o.aliases,
      notes: o.notes,
      description: o.description,
      tag: o.tag,
      home_spot: o.homeSpot,
      is_medication: o.isMedication,
      fob_id: o.fobId,
    })),
    medications: r.medications.map((m) => ({
      object_id: m.objectId,
      schedule_times: m.scheduleTimes,
      window_minutes: m.windowMinutes,
    })),
    version: r.version,
  };
}

export interface DoseValue {
  objectId: string;
  name: string;
  scheduledLocalTime: string;
  scheduledForT: number;
  status: "taken" | "late" | "missed" | "pending";
  takenT: number | null;
  evidenceEventId: string | null;
}

export function doseToWire(d: DoseValue, tz: string) {
  return {
    object_id: d.objectId,
    name: d.name,
    scheduled_local_time: d.scheduledLocalTime,
    scheduled_for_t: d.scheduledForT,
    scheduled_for_local: formatLocalIso(d.scheduledForT, tz),
    status: d.status,
    taken_t: d.takenT,
    taken_local: local(d.takenT, tz),
    evidence_event_id: d.evidenceEventId,
  };
}

export interface ObjectSummaryValue {
  objectId: string;
  name: string;
  aliases: string[];
  notes: string;
  description: string;
  homeSpot: number | null;
  homeSpotLabel: string | null;
  isMedication: boolean;
  fobId: string | null;
  state: null | {
    status: "on_spot" | "held" | "missing" | "roaming";
    spot: number | null;
    spotLabel: string | null;
    area: string | null;
    near: string | null;
    distanceClass: "near" | "mid" | "far" | null;
    precision: "exact" | "area" | "proximity" | "none";
    lastSeenT: number | null;
  };
  lastTouchedT: number | null;
}

export function objectSummaryToWire(o: ObjectSummaryValue, tz: string) {
  return {
    object_id: o.objectId,
    name: o.name,
    aliases: o.aliases,
    notes: o.notes,
    description: o.description,
    home_spot: o.homeSpot,
    home_spot_label: o.homeSpotLabel,
    is_medication: o.isMedication,
    fob_id: o.fobId,
    state:
      o.state === null
        ? null
        : {
            status: o.state.status,
            spot: o.state.spot,
            spot_label: o.state.spotLabel,
            area: o.state.area,
            near: o.state.near,
            distance_class: o.state.distanceClass,
            precision: o.state.precision,
            last_seen_t: o.state.lastSeenT,
            last_seen_local: local(o.state.lastSeenT, tz),
          },
    last_touched_t: o.lastTouchedT,
    last_touched_local: local(o.lastTouchedT, tz),
  };
}

export interface HistoryEventValue {
  eventId: string;
  kind: string;
  t: number;
  spot: number | null;
  spotLabel: string | null;
  detail: string;
}

export function historyEventToWire(e: HistoryEventValue, tz: string) {
  return {
    event_id: e.eventId,
    kind: e.kind,
    t: e.t,
    at_local: formatLocalIso(e.t, tz),
    spot: e.spot,
    spot_label: e.spotLabel,
    detail: e.detail,
  };
}

export interface SummaryValue {
  date: string;
  timezone: string;
  generatedT: number;
  doses: {
    objectId: string;
    name: string;
    scheduledLocalTime: string;
    scheduledFor: number;
    status: "taken" | "late" | "missed" | "pending";
    takenT: number | null;
    evidenceEventId: string | null;
  }[];
  pickupCount: number;
  untouched7d: string[];
  missing: string[];
  text: string;
}

export function summaryToWire(s: SummaryValue) {
  return {
    date: s.date,
    timezone: s.timezone,
    generated_t: s.generatedT,
    doses: s.doses.map((d) => doseToWire({ ...d, scheduledForT: d.scheduledFor }, s.timezone)),
    pickup_count: s.pickupCount,
    untouched_7d: s.untouched7d,
    missing: s.missing,
    text: s.text,
  };
}
