"""Every example, config file, and scenario line validates against its schema,
parses into its pydantic model, and round-trips back to identical JSON."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import earmark_contracts as ec

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"
EXAMPLES = ROOT / "contracts" / "examples"


def _registry() -> Registry:
    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resource = Resource.from_contents(schema)
        resources.append((schema["$id"], resource))
        resources.append((path.name, resource))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def validator(schema_file: str, pointer: str = "") -> Draft202012Validator:
    base = json.loads((SCHEMAS / schema_file).read_text())
    schema = {"$ref": f"{base['$id']}#{pointer}"} if pointer else base
    return Draft202012Validator(schema, registry=REGISTRY)


def examples(rel: str) -> list[Path]:
    paths = sorted((EXAMPLES / rel).glob("*.json"))
    assert len(paths) >= 2, f"need at least two examples in {rel}"
    return paths


def _check(v: Draft202012Validator, model_parse, data: dict) -> None:
    errors = sorted(v.iter_errors(data), key=str)
    assert not errors, "\n".join(e.message for e in errors)
    parsed = model_parse(data)
    assert ec.to_dict(parsed) == data


def test_all_schemas_are_valid_draft_2020_12():
    for path in SCHEMAS.glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text()))


BUS_DIRS = sorted(p.name for p in (EXAMPLES / "bus").iterdir() if p.is_dir())


def test_every_bus_type_has_examples_and_a_model():
    schema = json.loads((SCHEMAS / "bus_message.schema.json").read_text())
    defs = {k for k, v in schema["$defs"].items() if "properties" in v and "type" in v["properties"]}
    assert defs | {"state_update"} == set(BUS_DIRS)
    assert set(BUS_DIRS) == set(ec.BUS_TYPES)


@pytest.mark.parametrize("msg_type", BUS_DIRS)
def test_bus_examples(msg_type):
    union = validator("bus_message.schema.json")
    for path in examples(f"bus/{msg_type}"):
        data = json.loads(path.read_text())
        assert data["type"] == msg_type
        _check(union, ec.parse_bus, data)


@pytest.mark.parametrize(
    "rel,schema_file,model",
    [
        ("object_state", "object_state.schema.json", ec.ObjectState),
        ("space", "space.schema.json", ec.Space),
        ("registry", "registry.schema.json", ec.Registry),
        ("phrases", "phrases.schema.json", ec.Phrases),
    ],
)
def test_top_level_examples(rel, schema_file, model):
    v = validator(schema_file)
    for path in examples(rel):
        _check(v, model.model_validate, json.loads(path.read_text()))


@pytest.mark.parametrize("name", sorted(ec.CONVEX_HTTP_MODELS))
def test_convex_http_examples(name):
    v = validator("convex_http.schema.json", f"/$defs/{name}")
    for path in examples(f"convex_http/{name}"):
        _check(v, ec.CONVEX_HTTP_MODELS[name].model_validate, json.loads(path.read_text()))


def test_convex_http_defs_all_have_models():
    schema = json.loads((SCHEMAS / "convex_http.schema.json").read_text())
    assert set(schema["$defs"]) == set(ec.CONVEX_HTTP_MODELS)


@pytest.mark.parametrize(
    "path,schema_file,model",
    [
        ("config/space.json", "space.schema.json", ec.Space),
        ("config/objects.seed.json", "registry.schema.json", ec.Registry),
        ("config/phrases.json", "phrases.schema.json", ec.Phrases),
    ],
)
def test_config_files(path, schema_file, model):
    _check(validator(schema_file), model.model_validate, json.loads((ROOT / path).read_text()))


SCENARIOS = sorted((ROOT / "scenarios").glob("*.jsonl"))


@pytest.mark.parametrize("path", SCENARIOS, ids=[p.stem for p in SCENARIOS])
def test_scenario_lines(path):
    union = validator("bus_message.schema.json")
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert lines
    for data in lines:
        _check(union, ec.parse_bus, data)
    ts = [m["t"] for m in lines]
    assert ts == sorted(ts), "scenario lines must be in time order"


def test_dump_includes_defaulted_type_and_t():
    msg = ec.Reset()
    out = json.loads(ec.dump(msg))
    assert out["type"] == "reset" and isinstance(out["t"], float)
    assert not list(validator("bus_message.schema.json").iter_errors(out))
