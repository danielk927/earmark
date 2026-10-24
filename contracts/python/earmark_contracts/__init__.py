"""Earmark contracts as pydantic models.

These mirror contracts/schemas/*.schema.json exactly; tests/test_contracts.py
checks every example against both the schema and these models. Never change a
model without changing its schema (and vice versa).

Serialize with `dump(msg)` / `to_dict(msg)`: it omits optional fields that were
never set, so output always validates against the schema.
"""
from __future__ import annotations

import json
import time
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Source = Literal["simulator", "nfc", "ble", "camera", "ultrasonic"]
Precision = Literal["exact", "area", "proximity", "none"]
DistanceClass = Literal["near", "mid", "far"]
Status = Literal["on_spot", "held", "missing", "roaming"]
Component = Literal["hub", "concierge", "mac_app", "simulator", "trial_cli", "dashboard", "cli", "memory_agent"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Msg(_Model):
    """Bus message base: `type` and `t` always serialize, even when defaulted."""

    t: float = Field(default_factory=time.time)

    def model_post_init(self, __context: Any) -> None:
        self.__pydantic_fields_set__.update({"type", "t"})


# ---------------------------------------------------------------- space.json

class Listener(_Model):
    label: str
    origin_note: str


class Spot(_Model):
    spot: int = Field(ge=0)
    label: str = Field(min_length=1)
    position: Vec3


class Area(_Model):
    area: str = Field(min_length=1)
    label: str | None = None
    position: Vec3


class Receiver(_Model):
    receiver: str = Field(min_length=1)
    label: str
    position: Vec3 | None = None


class Space(_Model):
    listener: Listener
    spots: list[Spot]
    areas: list[Area]
    receivers: list[Receiver]


# ---------------------------------------------------------------- registry

class Household(_Model):
    name: str
    timezone: str


class RegistryObject(_Model):
    object_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    aliases: list[str]
    notes: str
    description: str
    tag: str | None
    home_spot: int | None
    is_medication: bool
    fob_id: str | None


class Medication(_Model):
    object_id: str
    schedule_times: list[Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]]
    window_minutes: int = Field(default=60, ge=1)


class Registry(_Model):
    household: Household
    objects: list[RegistryObject]
    medications: list[Medication]
    version: float | None = None


class Phrase(_Model):
    phrase_id: str = Field(pattern=r"^[a-z0-9_]+$")
    text: str = Field(min_length=1)


class Phrases(_Model):
    phrases: list[Phrase]


# ---------------------------------------------------------------- detection / state

class WhereSpot(_Model):
    spot: int = Field(ge=0)


class WherePosition(_Model):
    position: Vec3


class WhereArea(_Model):
    area: str = Field(min_length=1)


class WhereNear(_Model):
    near: str = Field(min_length=1)
    distance_class: DistanceClass


Where = Union[WhereSpot, WherePosition, WhereArea, WhereNear]


class DetectionEvent(_Msg):
    type: Literal["detection"] = "detection"
    source: Source
    tag: str = Field(min_length=1)
    kind: Literal["seen", "placed", "removed", "lost"]
    where: Where | None
    precision: Precision
    rssi: float | None = None


class Location(_Model):
    spot: int | None = None
    position: Vec3 | None = None
    area: str | None = None
    near: str | None = None
    distance_class: DistanceClass | None = None


class ObjectState(_Msg):
    type: Literal["state_update"] = "state_update"
    object_id: str = Field(min_length=1)
    location: Location
    precision: Precision
    status: Status
    home_spot: int | None
    last_seen_t: float | None
    source: Literal["simulator", "nfc", "ble", "camera", "ultrasonic", "none"]


# ---------------------------------------------------------------- bus messages

class Hello(_Msg):
    type: Literal["hello"] = "hello"
    component: Component
    subscribe: list[str] | None = None


class Snapshot(_Msg):
    type: Literal["snapshot"] = "snapshot"
    space: Space
    objects: list[RegistryObject]
    states: list[ObjectState]
    registry_version: float | None


class RegistryUpdate(_Msg):
    type: Literal["registry_update"] = "registry_update"
    objects: list[RegistryObject]
    registry_version: float | None


class UnknownTag(_Msg):
    type: Literal["unknown_tag"] = "unknown_tag"
    tag: str
    spot: int | None


class Label(_Msg):
    type: Literal["label"] = "label"
    tag: str
    name: str = Field(min_length=1)
    aliases: list[str]
    spot: int | None = None


class MicAudio(_Msg):
    type: Literal["mic_audio"] = "mic_audio"
    seq: int = Field(ge=0)
    sample_rate: Literal[8000, 16000, 22050, 24000, 44100, 48000]
    encoding: Literal["pcm_s16le"] = "pcm_s16le"
    chunk_b64: str


class Transcript(_Msg):
    type: Literal["transcript"] = "transcript"
    text: str
    is_final: bool
    source: Literal["cartesia", "apple", "typed"]


class SttMode(_Msg):
    type: Literal["stt_mode"] = "stt_mode"
    engine: Literal["cartesia", "apple"]
    reason: str


TrialMode = Literal["earmark", "baseline"]


class TrialStart(_Msg):
    type: Literal["trial_start"] = "trial_start"
    trial_id: str = Field(min_length=1)
    mode: TrialMode
    target_object_id: str
    tester: str


class TrialEnd(_Msg):
    type: Literal["trial_end"] = "trial_end"
    trial_id: str = Field(min_length=1)
    mode: TrialMode
    target_object_id: str
    tester: str
    outcome: Literal["found", "gave_up", "aborted"]
    started_t: float
    seconds_to_find: float | None
    wrong_picks: int = Field(ge=0)


class GuideStart(_Msg):
    type: Literal["guide_start"] = "guide_start"
    object_id: str
    name: str
    target_position: Vec3
    precision: Precision
    utterance_id: str


class GuideStop(_Msg):
    type: Literal["guide_stop"] = "guide_stop"
    reason: Literal["found", "cancelled", "timeout", "reset"]
    object_id: str | None = None


class GuideFeedback(_Msg):
    type: Literal["guide_feedback"] = "guide_feedback"
    object_id: str
    event: Literal["behind", "front", "locked"]
    turn: Literal["left", "right"] | None
    error_deg: float


class Speak(_Msg):
    type: Literal["speak"] = "speak"
    utterance_id: str
    seq: int = Field(ge=0)
    format: Literal["pcm_s16le", "pcm_f32le"]
    sample_rate: int
    chunk_b64: str
    final: bool
    text: str | None = None


class SpeakCached(_Msg):
    type: Literal["speak_cached"] = "speak_cached"
    phrase_id: str = Field(pattern=r"^[a-z0-9_]+$")
    utterance_id: str
    text: str


class SpeakText(_Msg):
    type: Literal["speak_text"] = "speak_text"
    utterance_id: str
    text: str = Field(min_length=1)


class Playback(_Msg):
    type: Literal["playback"] = "playback"
    utterance_id: str
    event: Literal["started", "finished", "interrupted"]


class Chirp(_Msg):
    type: Literal["chirp"] = "chirp"
    fob_id: str
    action: Literal["start", "stop"]


class Pickup(_Msg):
    type: Literal["pickup"] = "pickup"
    object_id: str
    from_spot: int


class PickupResult(_Msg):
    type: Literal["pickup_result"] = "pickup_result"
    expected: str
    actual: str
    correct: bool


class HeadPose(_Msg):
    type: Literal["head_pose"] = "head_pose"
    yaw: float
    pitch: float


class StatusMsg(_Msg):
    type: Literal["status"] = "status"
    component: Component
    ok: bool
    detail: str
    info: dict[str, str | float | int | bool | None] | None = None


class Reset(_Msg):
    type: Literal["reset"] = "reset"


BusMessage = Annotated[
    Union[
        Hello, Snapshot, RegistryUpdate, DetectionEvent, ObjectState, UnknownTag, Label, MicAudio,
        Transcript, SttMode, TrialStart, TrialEnd, GuideStart, GuideStop, GuideFeedback, Speak,
        SpeakCached, SpeakText, Playback, Chirp, Pickup, PickupResult, HeadPose, StatusMsg, Reset,
    ],
    Field(discriminator="type"),
]
BUS_ADAPTER: TypeAdapter[BusMessage] = TypeAdapter(BusMessage)
BUS_TYPES: dict[str, type[_Msg]] = {
    m.model_fields["type"].default: m
    for m in BusMessage.__origin__.__args__  # type: ignore[attr-defined]
}


def parse_bus(raw: str | bytes | dict) -> BusMessage:
    """Parse and validate one bus message. Raises pydantic.ValidationError."""
    if isinstance(raw, dict):
        return BUS_ADAPTER.validate_python(raw)
    return BUS_ADAPTER.validate_json(raw)


def to_dict(model: BaseModel) -> dict[str, Any]:
    """Schema-valid dict: required fields always present, unset optionals omitted."""
    return model.model_dump(mode="json", exclude_unset=True)


def dump(model: BaseModel) -> str:
    return json.dumps(to_dict(model), separators=(",", ":"))


# ---------------------------------------------------------------- Convex HTTP

class HubEvent(_Model):
    event_id: str = Field(min_length=8)
    kind: Literal["placed", "removed", "pickup", "pickup_result", "unknown_tag", "label", "chirp", "trial_start", "trial_end"]
    object_id: str | None
    t: float
    data: dict[str, Any]


class IngestRequest(_Model):
    events: list[HubEvent]
    states: list[ObjectState]


class IngestResponse(_Model):
    ok: bool
    accepted_events: int
    duplicate_events: int
    accepted_states: int


class LabelRequest(_Model):
    tag: str
    name: str = Field(min_length=1)
    aliases: list[str]
    spot: int | None = None


class LabelResponse(_Model):
    ok: bool
    object_id: str
    created: bool


class SummaryState(_Model):
    status: Status
    spot: int | None
    spot_label: str | None
    area: str | None
    near: str | None
    distance_class: DistanceClass | None
    precision: Precision
    last_seen_t: float | None
    last_seen_local: str | None


class ObjectSummary(_Model):
    object_id: str
    name: str
    aliases: list[str]
    notes: str
    description: str
    home_spot: int | None
    home_spot_label: str | None
    is_medication: bool
    fob_id: str | None
    state: SummaryState | None
    last_touched_t: float | None
    last_touched_local: str | None


class ObjectLookupResponse(_Model):
    query: str
    matches: list[ObjectSummary]
    now_t: float
    now_local: str


class ObjectsResponse(_Model):
    objects: list[ObjectSummary]
    now_t: float
    now_local: str


class HistoryEvent(_Model):
    event_id: str
    kind: str
    t: float
    at_local: str
    spot: int | None
    spot_label: str | None
    detail: str


class HistoryResponse(_Model):
    object_id: str
    name: str
    since_t: float
    events: list[HistoryEvent]


class Dose(_Model):
    object_id: str
    name: str
    scheduled_local_time: str
    scheduled_for_t: float
    scheduled_for_local: str
    status: Literal["taken", "late", "missed", "pending"]
    taken_t: float | None
    taken_local: str | None
    evidence_event_id: str | None


class AdherenceResponse(_Model):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str
    doses: list[Dose]
    now_t: float


class DailySummaryResponse(_Model):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str
    generated_t: float
    doses: list[Dose]
    pickup_count: int
    untouched_7d: list[str]
    missing: list[str]
    text: str


class RegistryResponse(Registry):
    version: float  # required and non-null on GET /api/registry


class ErrorResponse(_Model):
    ok: Literal[False]
    error: str


CONVEX_HTTP_MODELS: dict[str, type[_Model]] = {
    "ingest_request": IngestRequest,
    "ingest_response": IngestResponse,
    "hub_event": HubEvent,
    "label_request": LabelRequest,
    "label_response": LabelResponse,
    "object_summary": ObjectSummary,
    "object_lookup_response": ObjectLookupResponse,
    "objects_response": ObjectsResponse,
    "history_event": HistoryEvent,
    "history_response": HistoryResponse,
    "dose": Dose,
    "adherence_response": AdherenceResponse,
    "daily_summary_response": DailySummaryResponse,
    "error_response": ErrorResponse,
    "registry_response": RegistryResponse,
}
