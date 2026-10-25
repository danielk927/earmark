/* Generated from contracts/schemas by contracts/ts/gen.mjs. Do not edit by hand. */

/**
 * [x, y, z] meters. +x right, +y forward, +z up, origin = calibrated listening position.
 *
 * @minItems 3
 * @maxItems 3
 *
 * This interface was referenced by `DetectionEvent`'s JSON-Schema
 * via the `definition` "vec3".
 */
export type Vec3 = [number, number, number];
/**
 * @minItems 3
 * @maxItems 3
 *
 * This interface was referenced by `Space`'s JSON-Schema
 * via the `definition` "vec3".
 */
export type Vec31 = [number, number, number];
/**
 * Every JSON message on the local WebSocket bus ws://127.0.0.1:8765. Discriminated by `type`. All times are unix seconds (float).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "BusMessage".
 */
export type BusMessage =
  | Hello
  | Snapshot
  | RegistryUpdate
  | DetectionEvent
  | ObjectState
  | UnknownTag
  | Label
  | PlaceItem
  | MicAudio
  | ListenerPose
  | Ptt
  | Transcript
  | SttMode
  | TrialStart
  | TrialEnd
  | GuideStart
  | GuideStop
  | GuideFeedback
  | Speak
  | SpeakCached
  | SpeakText
  | Playback
  | Chirp
  | Pickup
  | PickupResult
  | HeadPose
  | Status
  | Reset;
/**
 * Concierge -> hub. The user said where they put an item. Either `area` (an id from space.areas: "I put my keys in the drawer") or `position` (room frame, from the locator: "I'm leaving my keys here"). The hub records the item there and logs a `stored` event.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "PlaceItem".
 */
export type PlaceItem = PlaceItem1 & {
  type: "place_item";
  object_id: string;
  area?: string;
  /**
   * Unix seconds.
   */
  t: number;
  position?: Vec32;
};
export type PlaceItem1 = {
  [k: string]: unknown | undefined;
};
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vec32 = [number, number, number];
/**
 * GET /api/registry (hub, every ~2 s). The registry with a required version (non-negative integer; a counter in ms that rises on every registry write, 0 on a fresh deployment, never null) so the hub can detect changes cheaply.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "RegistryResponse".
 */
export type RegistryResponse = Registry & {
  version: number;
};

export interface EarmarkContracts {}
/**
 * Adapter -> hub. One raw observation from any detection method. Downstream of the hub nothing may depend on `source`.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "DetectionEvent".
 */
export interface DetectionEvent {
  type: "detection";
  source: "simulator" | "nfc" | "ble" | "camera" | "ultrasonic";
  /**
   * NFC UID hex, BLE fob id, or any adapter-specific identity. EMPTY reads use kind=removed with the last tag seen, or tag="EMPTY".
   */
  tag: string;
  kind: "seen" | "placed" | "removed" | "lost";
  /**
   * Null only when kind=lost.
   */
  where: null | WhereSpot | WherePosition | WhereArea | WhereNear;
  precision: "exact" | "area" | "proximity" | "none";
  /**
   * dBm, BLE only.
   */
  rssi?: number | null;
  /**
   * Unix seconds. In scenario files: seconds relative to scenario start.
   */
  t: number;
}
/**
 * This interface was referenced by `DetectionEvent`'s JSON-Schema
 * via the `definition` "where_spot".
 */
export interface WhereSpot {
  spot: number;
}
/**
 * This interface was referenced by `DetectionEvent`'s JSON-Schema
 * via the `definition` "where_position".
 */
export interface WherePosition {
  position: Vec3;
}
/**
 * This interface was referenced by `DetectionEvent`'s JSON-Schema
 * via the `definition` "where_area".
 */
export interface WhereArea {
  area: string;
}
/**
 * This interface was referenced by `DetectionEvent`'s JSON-Schema
 * via the `definition` "where_near".
 */
export interface WhereNear {
  /**
   * receiver id from space.json
   */
  near: string;
  distance_class: "near" | "mid" | "far";
}
/**
 * Hub -> bus and Convex. Current belief about one registered object.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ObjectState".
 */
export interface ObjectState {
  type: "state_update";
  object_id: string;
  location: Location;
  precision: "exact" | "area" | "proximity" | "none";
  /**
   * on_spot: resting on a spot (home or not). held: lifted from a spot and not yet placed. missing: never seen or lost. roaming: tracked by proximity (BLE).
   */
  status: "on_spot" | "held" | "missing" | "roaming";
  home_spot: number | null;
  /**
   * Unix seconds of the last observation; null if never seen.
   */
  last_seen_t: number | null;
  /**
   * Informational only. Nothing downstream may branch on it.
   */
  source: "simulator" | "nfc" | "ble" | "camera" | "ultrasonic" | "none";
  /**
   * Unix seconds when this state was computed.
   */
  t: number;
}
/**
 * All fields optional/nullable. position is always filled when the hub can resolve one (spot, area, or receiver position).
 *
 * This interface was referenced by `ObjectState`'s JSON-Schema
 * via the `definition` "location".
 */
export interface Location {
  spot?: number | null;
  position?: null | [number, number, number];
  area?: string | null;
  near?: string | null;
  distance_class?: "near" | "mid" | "far" | null;
}
/**
 * config/space.json. Physical layout relative to the calibrated listening position. Meters; +x right, +y forward, +z up.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Space".
 */
export interface Space {
  listener: {
    label: string;
    origin_note: string;
  };
  spots: {
    spot: number;
    /**
     * Spoken name, e.g. "far left".
     */
    label: string;
    position: Vec31;
  }[];
  areas: {
    area: string;
    /**
     * Spoken name, e.g. "the counter". Defaults to area id.
     */
    label?: string;
    position: Vec31;
  }[];
  /**
   * Proximity receivers (BLE scanners). An object seen `near` a receiver resolves to the receiver position with precision=proximity.
   */
  receivers: {
    receiver: string;
    /**
     * Spoken name, e.g. "the counter".
     */
    label: string;
    position?: null | Vec31;
  }[];
}
/**
 * The object registry. Shape of config/objects.seed.json, config/objects.cache.json, and the Convex GET /api/registry response. Convex is the source of truth.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Registry".
 */
export interface Registry {
  household: Household;
  objects: RegistryObject[];
  medications: Medication[];
  /**
   * Monotonic registry version: a counter in ms that rises on every registry write (Convex), 0 on a fresh deployment, never null. Absent in seed files.
   */
  version?: number;
}
export interface Household {
  name: string;
  /**
   * IANA tz, e.g. America/Los_Angeles. Medication schedule times are in this zone.
   */
  timezone: string;
}
/**
 * This interface was referenced by `Registry`'s JSON-Schema
 * via the `definition` "registry_object".
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "RegistryObject".
 */
export interface RegistryObject {
  object_id: string;
  /**
   * Spoken name, e.g. "sugar".
   */
  name: string;
  aliases: string[];
  /**
   * Family-entered notes, e.g. "for coffee".
   */
  notes: string;
  /**
   * Short physical description, e.g. "glass jar with a metal lid".
   */
  description: string;
  /**
   * NFC UID hex (uppercase) or null.
   */
  tag: string | null;
  home_spot: number | null;
  is_medication: boolean;
  /**
   * BLE fob id (matches DetectionEvent.tag from the ble adapter) or null.
   */
  fob_id: string | null;
}
/**
 * This interface was referenced by `Registry`'s JSON-Schema
 * via the `definition` "medication".
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Medication".
 */
export interface Medication {
  object_id: string;
  schedule_times: string[];
  window_minutes: number;
}
/**
 * config/phrases.json. Static phrases pre-synthesized to config/phrases/<phrase_id>.wav at build time and played via speak_cached.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Phrases".
 */
export interface Phrases {
  phrases: {
    phrase_id: string;
    text: string;
  }[];
}
/**
 * Client -> hub, first message after connecting. The hub replies with a snapshot. `subscribe` limits which types the hub forwards to this client; omitted = everything except mic_audio and speak.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Hello".
 */
export interface Hello {
  type: "hello";
  component:
    "hub" | "concierge" | "mac_app" | "simulator" | "trial_cli" | "dashboard" | "cli" | "memory_agent" | "locator";
  /**
   * Message types to receive, or ["*"] for all including audio.
   */
  subscribe?: string[];
  /**
   * Unix seconds.
   */
  t?: number;
  /**
   * Optional shared token sent by the locator; the local hub accepts and ignores it.
   */
  token?: string;
}
/**
 * Hub -> one client, in reply to hello and after reset. Everything a client needs to render and reason.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Snapshot".
 */
export interface Snapshot {
  type: "snapshot";
  household: Household;
  space: Space;
  objects: RegistryObject[];
  states: ObjectState[];
  registry_version: number | null;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Hub -> bus whenever the registry changes (dashboard edit synced from Convex, or a voice label). Full replacement list.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "RegistryUpdate".
 */
export interface RegistryUpdate {
  type: "registry_update";
  objects: RegistryObject[];
  registry_version: number | null;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Hub -> bus when a debounced placement carries a tag not in the registry. The concierge uses the latest one for "this is X".
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "UnknownTag".
 */
export interface UnknownTag {
  type: "unknown_tag";
  tag: string;
  spot: number | null;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> hub. Register `tag` as a new object (or rename the object that has it). The hub updates its local registry immediately and syncs to Convex.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Label".
 */
export interface Label {
  type: "label";
  tag: string;
  name: string;
  aliases: string[];
  /**
   * Spot the tag is on; becomes home_spot for a new object.
   */
  spot?: number | null;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Mac app -> concierge. Streamed microphone audio for Cartesia STT.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "MicAudio".
 */
export interface MicAudio {
  type: "mic_audio";
  seq: number;
  sample_rate: 8000 | 16000 | 22050 | 24000 | 44100 | 48000;
  encoding: "pcm_s16le";
  chunk_b64: string;
  /**
   * Unix seconds.
   */
  t?: number;
}
/**
 * Locator -> bus. The user's ear position from the beacons, room frame (origin under the mat center), about 3 per second. quality `lost` repeats the last position once after 1.5 s without a fix.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ListenerPose".
 */
export interface ListenerPose {
  type: "listener_pose";
  position: Vec32;
  quality: "ok" | "degraded" | "lost";
  beacons_heard: number;
  source: "beacons" | "steps" | "sim" | "manual";
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Push-to-talk start/stop. The Mac app (or the stem button) publishes it; the locator streams phone mic audio while it is on.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Ptt".
 */
export interface Ptt {
  type: "ptt";
  state: "start" | "stop";
  /**
   * Unix seconds.
   */
  t?: number;
}
/**
 * Concierge -> bus (from Cartesia STT), or Mac app -> concierge (Apple Speech fallback), or CLI (typed).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Transcript".
 */
export interface Transcript {
  type: "transcript";
  text: string;
  is_final: boolean;
  source: "cartesia" | "apple" | "typed";
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> Mac app. Which speech-to-text engine the Mac app should feed: cartesia = stream mic_audio; apple = run SFSpeechRecognizer and send transcript.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "SttMode".
 */
export interface SttMode {
  type: "stt_mode";
  engine: "cartesia" | "apple";
  reason: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "TrialStart".
 */
export interface TrialStart {
  type: "trial_start";
  trial_id: string;
  mode: "earmark" | "baseline";
  target_object_id: string;
  /**
   * Pseudonym only, never a real name.
   */
  tester: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Sent by scripts/trial.py. Metrics are computed in code from the bus pickups between start and end.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "TrialEnd".
 */
export interface TrialEnd {
  type: "trial_end";
  trial_id: string;
  mode: "earmark" | "baseline";
  target_object_id: string;
  tester: string;
  outcome: "found" | "gave_up" | "aborted";
  /**
   * Unix seconds.
   */
  started_t: number;
  /**
   * Null unless outcome=found.
   */
  seconds_to_find: number | null;
  wrong_picks: number;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> Mac app. Start spatial guidance toward target_position (Earmark coordinates). Replaces any active guidance.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "GuideStart".
 */
export interface GuideStart {
  type: "guide_start";
  object_id: string;
  /**
   * Display name for the UI.
   */
  name: string;
  target_position: Vec32;
  precision: "exact" | "area" | "proximity" | "none";
  utterance_id: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "GuideStop".
 */
export interface GuideStop {
  type: "guide_stop";
  reason: "found" | "cancelled" | "timeout" | "reset";
  object_id?: string | null;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Mac app -> bus, on transitions only. behind: target > 100 deg from head direction (turn = shorter way). front: target back within 100 deg. locked: error < 8 deg for > 300 ms.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "GuideFeedback".
 */
export interface GuideFeedback {
  type: "guide_feedback";
  object_id: string;
  /**
   * behind/front/locked come from the head angle; arrived means the locator put the user within about half a meter of the target.
   */
  event: "behind" | "front" | "locked" | "arrived";
  turn: "left" | "right" | null;
  /**
   * Signed angle from head direction to target, degrees, positive = target is to the right.
   */
  error_deg: number;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> Mac app. Streamed TTS audio (non-spatial speech layer). Chunks of one utterance share utterance_id and increase seq; the last has final=true (its chunk_b64 may be empty).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Speak".
 */
export interface Speak {
  type: "speak";
  utterance_id: string;
  seq: number;
  format: "pcm_s16le" | "pcm_f32le";
  sample_rate: number;
  chunk_b64: string;
  final: boolean;
  /**
   * Full utterance text, on seq 0, for captions and logs.
   */
  text?: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> Mac app. Play config/phrases/<phrase_id>.wav. If missing, the Mac app speaks `text` with the system voice.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "SpeakCached".
 */
export interface SpeakCached {
  type: "speak_cached";
  phrase_id: string;
  utterance_id: string;
  text: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> Mac app. Last-resort speech: the Mac app speaks `text` with the system voice (same voices as macOS `say`), ducking the cue.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "SpeakText".
 */
export interface SpeakText {
  type: "speak_text";
  utterance_id: string;
  text: string;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Mac app -> bus. Speech playback progress, used for the latency report (first audible audio) and for barge-in.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Playback".
 */
export interface Playback {
  type: "playback";
  utterance_id: string;
  event: "started" | "finished" | "interrupted";
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> hub. Make a BLE fob beep.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Chirp".
 */
export interface Chirp {
  type: "chirp";
  fob_id: string;
  action: "start" | "stop";
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Hub -> bus when a registered object leaves a spot (after debounce).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Pickup".
 */
export interface Pickup {
  type: "pickup";
  object_id: string;
  from_spot: number;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Concierge -> bus, for a pickup that happens while guiding.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "PickupResult".
 */
export interface PickupResult {
  type: "pickup_result";
  expected: string;
  actual: string;
  correct: boolean;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Mac app -> bus, debug only, <= 10 Hz. Degrees relative to calibration; yaw positive = head turned right, pitch positive = looking up.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "HeadPose".
 */
export interface HeadPose {
  type: "head_pose";
  yaw: number;
  pitch: number;
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * Any -> bus. Health/mode report. `info` carries component-specific details (e.g. mac_app: renderer, head_tracking, guidance_mode, input_device, output_device, stt_engine).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Status".
 */
export interface Status {
  type: "status";
  component:
    "hub" | "concierge" | "mac_app" | "simulator" | "trial_cli" | "dashboard" | "cli" | "memory_agent" | "locator";
  ok: boolean;
  detail: string;
  info?: {
    [k: string]: (string | number | boolean | null) | undefined;
  };
  /**
   * Unix seconds.
   */
  t?: number;
}
/**
 * Any -> bus. Return every component to the demo starting state (stop guidance and chirps, clear held state, hub re-reads seed/cache and re-sends snapshot).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Reset".
 */
export interface Reset {
  type: "reset";
  /**
   * Unix seconds.
   */
  t: number;
}
/**
 * POST /ingest (hub). Idempotent by event_id.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "IngestRequest".
 */
export interface IngestRequest {
  events: HubEvent[];
  states: ObjectState[];
}
/**
 * Append-only event. `data` holds the originating bus message for pickup, pickup_result, unknown_tag, label, chirp, trial_start, trial_end; for placed/removed it holds {spot, tag, source}; for stored (the user said where an item is) it holds {area, label, source} for a named area or {position, source} for a spot in the room frame, with source "voice".
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "HubEvent".
 */
export interface HubEvent {
  /**
   * Hub-generated UUID; Convex ignores duplicates (offline-queue retries).
   */
  event_id: string;
  kind:
    | "placed"
    | "removed"
    | "pickup"
    | "pickup_result"
    | "unknown_tag"
    | "label"
    | "stored"
    | "chirp"
    | "trial_start"
    | "trial_end";
  object_id: string | null;
  t: number;
  data: {};
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "IngestResponse".
 */
export interface IngestResponse {
  ok: boolean;
  accepted_events: number;
  duplicate_events: number;
  accepted_states: number;
}
/**
 * POST /api/label (hub). Create an object for `tag`, or rename the object that already has it.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "LabelRequest".
 */
export interface LabelRequest {
  tag: string;
  name: string;
  aliases: string[];
  spot?: number | null;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "LabelResponse".
 */
export interface LabelResponse {
  ok: boolean;
  object_id: string;
  created: boolean;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ObjectSummary".
 */
export interface ObjectSummary {
  object_id: string;
  name: string;
  aliases: string[];
  notes: string;
  description: string;
  home_spot: number | null;
  home_spot_label: string | null;
  is_medication: boolean;
  fob_id: string | null;
  state: null | {
    status: "on_spot" | "held" | "missing" | "roaming";
    spot: number | null;
    spot_label: string | null;
    area: string | null;
    near: string | null;
    distance_class: "near" | "mid" | "far" | null;
    precision: "exact" | "area" | "proximity" | "none";
    last_seen_t: number | null;
    last_seen_local: string | null;
  };
  /**
   * Last pickup or placement.
   */
  last_touched_t: number | null;
  last_touched_local: string | null;
}
/**
 * GET /api/object?name=  Case-insensitive match on name, then aliases, then substring. Zero or more matches, best first.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ObjectLookupResponse".
 */
export interface ObjectLookupResponse {
  query: string;
  matches: ObjectSummary[];
  now_t: number;
  now_local: string;
}
/**
 * GET /api/objects  Every object, for questions like "what hasn't been touched in a week?".
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ObjectsResponse".
 */
export interface ObjectsResponse {
  objects: ObjectSummary[];
  now_t: number;
  now_local: string;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "HistoryEvent".
 */
export interface HistoryEvent {
  event_id: string;
  kind: string;
  t: number;
  at_local: string;
  spot: number | null;
  spot_label: string | null;
  /**
   * Deterministic human-readable sentence, e.g. "Picked up from the center right spot."
   */
  detail: string;
}
/**
 * GET /api/history?objectId=&since=  `since` is unix seconds; default 7 days ago. Newest first, max 200.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "HistoryResponse".
 */
export interface HistoryResponse {
  object_id: string;
  name: string;
  since_t: number;
  events: HistoryEvent[];
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "Dose".
 */
export interface Dose {
  object_id: string;
  name: string;
  /**
   * HH:MM as configured.
   */
  scheduled_local_time: string;
  scheduled_for_t: number;
  scheduled_for_local: string;
  status: "taken" | "late" | "missed" | "pending";
  taken_t: number | null;
  taken_local: string | null;
  evidence_event_id: string | null;
}
/**
 * GET /api/adherence?date=YYYY-MM-DD (household-local date; default today).
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "AdherenceResponse".
 */
export interface AdherenceResponse {
  date: string;
  timezone: string;
  doses: Dose[];
  now_t: number;
}
/**
 * GET /api/daily-summary?date=  Deterministic facts only; `text` is generated by code, not an LLM. No medical advice.
 *
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "DailySummaryResponse".
 */
export interface DailySummaryResponse {
  date: string;
  timezone: string;
  generated_t: number;
  doses: Dose[];
  pickup_count: number;
  /**
   * object_ids with no pickup/placement in the 7 days before end of `date`.
   */
  untouched_7d: string[];
  /**
   * object_ids whose current status is missing.
   */
  missing: string[];
  text: string;
}
/**
 * This interface was referenced by `EarmarkContracts`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  ok: false;
  error: string;
}
