"""Moss in-process session index over the registry (docs/vendor-notes/moss.md).

One document per object (name, aliases, notes, description). Rebuilt by diff
(delete removed ids, upsert the rest) on every registry change. Any Moss error
marks the index unavailable; the resolver then uses its local fallbacks, and
start is retried at most once a minute.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from earmark_contracts import RegistryObject

log = logging.getLogger(__name__)
RETRY_S = 60.0


@dataclass
class Hit:
    object_id: str
    score: float


class ObjectIndex(Protocol):
    status: str  # disabled | starting | ready | error

    async def sync(self, objects: list[RegistryObject]) -> None: ...
    async def query(self, text: str, top_k: int = 5) -> list[Hit]: ...
    async def close(self) -> None: ...


def doc_text(o: RegistryObject) -> str:
    parts = [o.name, ", ".join(o.aliases), o.notes, o.description]
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())


class MossIndex:
    def __init__(self, project_id: str, project_key: str, index_name: str) -> None:
        self._project_id = project_id
        self._project_key = project_key
        self._index_name = index_name
        self._client = None
        self._session = None
        self._ids: set[str] = set()
        self._objects: list[RegistryObject] = []
        self._last_attempt = 0.0
        self.status = "starting"
        self.last_error: str | None = None

    async def _start(self) -> None:
        self._last_attempt = time.monotonic()
        from moss import MossClient  # lazy: the native core loads only when Moss is configured

        self._client = MossClient(self._project_id, self._project_key)
        self._session = await self._client.session(self._index_name, auto_load_on_init=False)
        self._ids = set()
        await self._upsert(self._objects)
        from moss import QueryOptions
        await self._session.query("warm up", QueryOptions(top_k=1))
        self.status = "ready"
        self.last_error = None
        log.info("moss session ready (%d docs)", len(self._ids))

    def _fail(self, e: Exception) -> None:
        self.status = "error"
        self.last_error = f"{type(e).__name__}: {getattr(e, 'code', '') or e}"
        log.warning("moss unavailable, using fallback resolver: %s", self.last_error)

    async def _ensure(self) -> bool:
        if self.status == "ready":
            return True
        if self.status == "error" and time.monotonic() - self._last_attempt < RETRY_S:
            return False
        try:
            await self._start()
            return True
        except Exception as e:  # MossError, network, import: all mean "use the fallback"
            self._fail(e)
            return False

    async def _upsert(self, objects: list[RegistryObject]) -> None:
        from moss import DocumentInfo, MutationOptions

        docs = [DocumentInfo(
            id=o.object_id, text=doc_text(o), metadata={"name": o.name},
            payload=json.dumps({"object_id": o.object_id, "name": o.name}),
        ) for o in objects]
        new_ids = {o.object_id for o in objects}
        stale = sorted(self._ids - new_ids)
        if stale:
            await self._session.delete_docs(stale)
        if docs:
            await self._session.add_docs(docs, MutationOptions(upsert=True))
        self._ids = new_ids

    async def sync(self, objects: list[RegistryObject]) -> None:
        self._objects = list(objects)
        if self.status != "ready":
            await self._ensure()
            return
        try:
            await self._upsert(self._objects)
        except Exception as e:
            self._fail(e)

    async def query(self, text: str, top_k: int = 5) -> list[Hit]:
        """Raises RuntimeError when Moss is unavailable."""
        if not await self._ensure():
            raise RuntimeError(f"moss unavailable: {self.last_error}")
        from moss import QueryOptions
        try:
            res = await self._session.query(text, QueryOptions(top_k=top_k, alpha=0.8))
        except Exception as e:
            self._fail(e)
            raise RuntimeError(f"moss query failed: {self.last_error}") from e
        return [Hit(d.id, float(d.score or 0.0)) for d in res.docs]

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
