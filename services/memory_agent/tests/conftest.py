from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from earmark_memory.config import REPO_ROOT
from earmark_memory.describe import SpaceLabels
from earmark_memory.fixture import FixtureConvexReader, FixtureData, FixtureServer
from earmark_memory.pipeline import MemoryPipeline

SECRET = "test-read-secret"
SCHEMAS = REPO_ROOT / "contracts" / "schemas"


def _registry() -> Registry:
    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resource = Resource.from_contents(schema)
        resources += [(schema["$id"], resource), (path.name, resource)]
    return Registry().with_resources(resources)


_REGISTRY = _registry()


def convex_validator(definition: str) -> Draft202012Validator:
    """Validator for one `$defs` entry of contracts/schemas/convex_http.schema.json."""
    base = json.loads((SCHEMAS / "convex_http.schema.json").read_text())
    return Draft202012Validator({"$ref": f"{base['$id']}#/$defs/{definition}"}, registry=_REGISTRY)


@pytest.fixture
def data() -> FixtureData:
    return FixtureData()


@pytest.fixture
def server(data: FixtureData):
    with FixtureServer(data, SECRET) as s:
        yield s


@pytest.fixture
def pipeline() -> MemoryPipeline:
    return MemoryPipeline(FixtureConvexReader(), None, SpaceLabels.load())


@pytest.fixture
def config_dir() -> Path:
    return REPO_ROOT / "config"
