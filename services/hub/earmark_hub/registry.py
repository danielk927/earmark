"""Object registry: tags and fobs to objects.

Convex is the source of truth. The hub starts from config/objects.cache.json (last
registry seen from Convex, plus local labels), else config/objects.seed.json.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from earmark_contracts import Label, LabelRequest, Registry, RegistryObject

log = logging.getLogger("earmark.hub.registry")

_HEX = re.compile(r"^[0-9A-Fa-f:\- ]+$")


def normalize_tag(tag: str) -> str:
    """Canonical tag: NFC UIDs are uppercase hex without separators; other ids are uppercased."""
    tag = tag.strip()
    if _HEX.match(tag):
        return re.sub(r"[:\- ]", "", tag).upper()
    return tag.upper()


def derive_object_id(name: str, existing: set[str]) -> str:
    """Lowercase, [a-z0-9_] only, deduplicated with _2, _3, ..."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "object"
    candidate, n = base, 2
    while candidate in existing:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


class RegistryStore:
    def __init__(self, cache_path: Path, seed_path: Path) -> None:
        self.cache_path = cache_path
        self.seed_path = seed_path
        self.registry = self._read()

    def _read(self) -> Registry:
        if self.cache_path.is_file():
            try:
                reg = Registry.model_validate_json(self.cache_path.read_text())
                log.info("registry loaded from cache", extra={"path": str(self.cache_path), "version": reg.version})
                return reg
            except ValueError as e:
                log.warning("registry cache is invalid, using seed", extra={"error": str(e)[:300]})
        reg = Registry.model_validate_json(self.seed_path.read_text())
        log.info("registry loaded from seed", extra={"path": str(self.seed_path)})
        return reg

    def reload(self) -> None:
        self.registry = self._read()

    @property
    def objects(self) -> list[RegistryObject]:
        return list(self.registry.objects)

    @property
    def version(self) -> float | None:
        return self.registry.version

    def find_by_tag(self, tag: str) -> RegistryObject | None:
        key = normalize_tag(tag)
        for obj in self.registry.objects:
            if (obj.tag and normalize_tag(obj.tag) == key) or (obj.fob_id and normalize_tag(obj.fob_id) == key):
                return obj
        return None

    def find_by_fob(self, fob_id: str) -> RegistryObject | None:
        return next((o for o in self.registry.objects if o.fob_id == fob_id), None)

    def differs(self, other: Registry) -> bool:
        if other.version is not None or self.registry.version is not None:
            return other.version != self.registry.version
        return other != self.registry

    def replace(self, reg: Registry) -> None:
        self.registry = reg
        self.write_cache()

    def apply_label(self, label: Label | LabelRequest) -> tuple[str, bool]:
        """Create an object for label.tag, or rename the object that has it. Returns (object_id, created)."""
        existing = self.find_by_tag(label.tag)
        objects = list(self.registry.objects)
        if existing is not None:
            renamed = existing.model_copy(update={"name": label.name, "aliases": list(label.aliases)})
            objects = [renamed if o.object_id == existing.object_id else o for o in objects]
            object_id, created = existing.object_id, False
        else:
            object_id = derive_object_id(label.name, {o.object_id for o in objects})
            objects.append(RegistryObject(
                object_id=object_id, name=label.name, aliases=list(label.aliases), notes="", description="",
                tag=normalize_tag(label.tag), home_spot=label.spot, is_medication=False, fob_id=None,
            ))
            created = True
        self.registry = self.registry.model_copy(update={"objects": objects})
        self.write_cache()
        return object_id, created

    def write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(self.registry.model_dump_json(indent=2, exclude_unset=False) + "\n")
        os.replace(tmp, self.cache_path)
