"""Contract tests for the locator bus messages.

Every example in contracts/examples/ must validate against its
contracts/<type>.schema.json (draft 2020-12), and the schemas must reject
anything that is not exactly the LOCATOR_BRIEF.md section 2.4 shape:
exact fields, no extras.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LOCATOR_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = LOCATOR_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

MESSAGE_TYPES = ["listener_pose", "mic_audio", "ptt", "status"]
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def schema_path(message_type: str) -> Path:
    return CONTRACTS_DIR / f"{message_type}.schema.json"


def example_files(message_type: str) -> list[Path]:
    return sorted(EXAMPLES_DIR.glob(f"{message_type}.*.json"))


@pytest.mark.parametrize("message_type", MESSAGE_TYPES)
def test_schema_exists_and_is_draft_2020_12(message_type: str):
    path = schema_path(message_type)
    assert path.is_file(), f"missing schema {path}"
    schema = load_json(path)
    assert schema["$schema"] == DRAFT_2020_12
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("message_type", MESSAGE_TYPES)
def test_schema_forbids_extra_fields(message_type: str):
    # Brief section 2.4: "send no extra fields".
    schema = load_json(schema_path(message_type))
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("message_type", MESSAGE_TYPES)
def test_has_at_least_one_example(message_type: str):
    examples = example_files(message_type)
    assert examples, f"no example files for {message_type}"


@pytest.mark.parametrize(
    "example", sorted(EXAMPLES_DIR.glob("*.json")), ids=lambda p: p.name
)
def test_example_validates_against_its_schema(example: Path):
    message_type = example.name.split(".")[0]
    schema = load_json(schema_path(message_type))
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(load_json(example)))
    assert not errors, f"{example.name}: " + "; ".join(
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )


def _mutated(message_type: str, mutate) -> dict:
    instance = load_json(example_files(message_type)[0])
    mutate(instance)
    return instance


def _errors_for(message_type: str, instance: dict) -> list[str]:
    validator = Draft202012Validator(load_json(schema_path(message_type)))
    return [e.message for e in validator.iter_errors(instance)]


@pytest.mark.parametrize("message_type", MESSAGE_TYPES)
def test_extra_field_is_rejected(message_type: str):
    instance = _mutated(message_type, lambda m: m.update(debug_extra="nope"))
    assert _errors_for(message_type, instance), (
        f"{message_type}: schema accepted an extra field"
    )


@pytest.mark.parametrize("message_type", MESSAGE_TYPES)
def test_missing_required_field_is_rejected(message_type: str):
    required = load_json(schema_path(message_type))["required"]
    victim = next(k for k in required if k != "type")

    def drop(m):
        del m[victim]

    instance = _mutated(message_type, drop)
    assert _errors_for(message_type, instance), (
        f"{message_type}: schema accepted a missing required field ({victim})"
    )


def test_listener_pose_quality_enum_is_enforced():
    instance = _mutated(
        "listener_pose", lambda m: m.update(quality="excellent")
    )
    assert _errors_for("listener_pose", instance)


def test_listener_pose_position_must_be_xyz():
    schema = load_json(schema_path("listener_pose"))
    for bad in ([1.0, 2.0], [1.0, 2.0, 3.0, 4.0]):
        instance = load_json(EXAMPLES_DIR / "listener_pose.ok.json")
        instance["position"] = bad
        assert list(Draft202012Validator(schema).iter_errors(instance))


def test_listener_pose_source_enum_is_enforced():
    instance = _mutated("listener_pose", lambda m: m.update(source="gps"))
    assert _errors_for("listener_pose", instance)


def test_mic_audio_encoding_is_locked_to_pcm_s16le():
    instance = _mutated("mic_audio", lambda m: m.update(encoding="float32"))
    assert _errors_for("mic_audio", instance)


def test_ptt_state_enum_is_enforced():
    schema = load_json(schema_path("ptt"))
    for bad in ("toggle", "START", ""):
        instance = {"type": "ptt", "state": bad}
        assert list(Draft202012Validator(schema).iter_errors(instance))


def test_status_component_is_locked_to_locator():
    instance = _mutated("status", lambda m: m.update(component="macapp"))
    assert _errors_for("status", instance)
