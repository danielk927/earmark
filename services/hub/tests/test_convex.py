"""Convex sync against a fake Convex HTTP server (real sockets, contract-validated bodies)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from earmark_contracts import (
    IngestRequest,
    IngestResponse,
    LabelRequest,
    LabelResponse,
    ObjectState,
    Registry,
    TrialStart,
)

from conftest import ROOT, SUGAR, free_port
from earmark_hub.client import BusClient
from earmark_hub.config import ConvexCfg, ConvexEnv
from earmark_hub.convex import ConvexClient, ConvexSync
from earmark_hub.hub import Hub

SECRET = "s3cret-value-never-logged"


class FakeConvex:
    """Implements POST /ingest, POST /api/label, GET /api/registry per contracts/schemas/convex_http.schema.json."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.events: dict[str, dict] = {}
        self.order: list[str] = []
        self.duplicates = 0
        self.states: list[dict] = []
        self.labels: list[dict] = []
        self.secrets: set[str] = set()
        self.drop_next_response = False
        seed = json.loads((ROOT / "config" / "objects.seed.json").read_text())
        self.registry = Registry.model_validate({**seed, "version": 1.0})
        self._server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self) -> bool:
                got = self.headers.get("X-Earmark-Secret", "")
                fake.secrets.add(got)
                if got != SECRET:
                    self._reply(401, {"ok": False, "error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path == "/api/registry":
                    self._reply(200, fake.registry.model_dump(mode="json"))
                else:
                    self._reply(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/ingest":
                    req = IngestRequest.model_validate(body)
                    accepted = dup = 0
                    for ev in req.events:
                        if ev.event_id in fake.events:
                            dup += 1
                        else:
                            fake.events[ev.event_id] = ev.model_dump(mode="json")
                            fake.order.append(ev.event_id)
                            accepted += 1
                    fake.duplicates += dup
                    fake.states.extend(s.model_dump(mode="json") for s in req.states)
                    if fake.drop_next_response:
                        fake.drop_next_response = False
                        self.close_connection = True
                        self.connection.shutdown(2)  # processed, but the client never hears back
                        return
                    self._reply(200, IngestResponse(ok=True, accepted_events=accepted, duplicate_events=dup,
                                                    accepted_states=len(req.states)).model_dump())
                elif self.path == "/api/label":
                    req = LabelRequest.model_validate(body)
                    fake.labels.append(body)
                    self._reply(200, LabelResponse(ok=True, object_id=req.name.lower(), created=True).model_dump())
                else:
                    self._reply(404, {"ok": False, "error": "not found"})

        ThreadingHTTPServer.allow_reuse_address = True
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


@pytest.fixture
def fake():
    f = FakeConvex(free_port())
    yield f
    f.stop()


def fast_cfg() -> ConvexCfg:
    return ConvexCfg(registry_poll_s=0.1, timeout_s=1.0, flush_interval_s=0.05, backoff_initial_s=0.05,
                     backoff_max_s=0.2)


async def wait_for(pred, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.02)


def state(oid="sugar", status="held") -> ObjectState:
    return ObjectState(object_id=oid, location={"spot": None, "position": None}, precision="none", status=status,
                       home_spot=3, last_seen_t=1.0, source="simulator", t=2.0)


async def test_offline_queue_survives_downtime_and_restart_then_flushes_in_order(fake, tmp_path):
    queue = tmp_path / "queue.jsonl"
    env = ConvexEnv(site_url=fake.url, secret=SECRET)
    sync = ConvexSync(ConvexClient(env, 1.0), queue, fast_cfg())
    runner = asyncio.create_task(sync.run())
    ids = [sync.add_event("pickup", "salt", 10.0 + k, {"k": k}).event_id for k in range(5)]
    sync.add_label(LabelRequest(tag="04A1B2C3D4E5FF", name="honey", aliases=[], spot=1))
    ids += [sync.add_event("label", "honey", 20.0, {"k": 5}).event_id]
    sync.add_state(state())
    await wait_for(lambda: sync.reachable is False)
    assert sync.depth == 7 and len(queue.read_text().splitlines()) == 7
    runner.cancel()
    await sync.client.aclose()

    # Hub restarts while Convex is still down: the queue is reloaded from disk.
    sync2 = ConvexSync(ConvexClient(env, 1.0), queue, fast_cfg())
    assert sync2.depth == 7
    sync2.add_state(state(status="on_spot"))
    runner2 = asyncio.create_task(sync2.run())
    await asyncio.sleep(0.2)
    fake.start()
    await wait_for(lambda: sync2.depth == 0 and len(fake.order) == 6)
    runner2.cancel()
    await sync2.client.aclose()
    assert fake.order == ids  # in order, label request in between
    assert [lab["name"] for lab in fake.labels] == ["honey"]
    assert queue.read_text() == ""
    assert sync2.reachable is True
    assert fake.secrets == {SECRET}


async def test_duplicates_are_harmless(fake, tmp_path):
    fake.start()
    fake.drop_next_response = True
    sync = ConvexSync(ConvexClient(ConvexEnv(fake.url, SECRET), 1.0), tmp_path / "q.jsonl", fast_cfg())
    runner = asyncio.create_task(sync.run())
    ids = [sync.add_event("placed", "sugar", 1.0 + k, {"spot": 3, "tag": SUGAR, "source": "nfc"}).event_id
           for k in range(3)]
    await wait_for(lambda: sync.depth == 0)
    runner.cancel()
    await sync.client.aclose()
    assert fake.order == ids and fake.duplicates >= 1


async def test_rejected_secret_is_retried_and_never_logged(fake, tmp_path, caplog):
    fake.start()
    caplog.set_level(logging.DEBUG)
    sync = ConvexSync(ConvexClient(ConvexEnv(fake.url, "wrong-" + SECRET), 1.0), tmp_path / "q.jsonl", fast_cfg())
    runner = asyncio.create_task(sync.run())
    poller = asyncio.create_task(sync.poll_registry(lambda reg: asyncio.sleep(0)))
    sync.add_event("pickup", "salt", 1.0, {})
    await wait_for(lambda: sync.reachable is False)
    await asyncio.sleep(0.3)
    runner.cancel()
    poller.cancel()
    await sync.client.aclose()
    assert sync.depth == 1  # 401 keeps the event queued
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "401" in text and SECRET not in text


async def test_hub_syncs_events_states_and_polls_registry(fake, hub_cfg, hub_root):
    fake.start()
    hub_cfg.convex = fast_cfg()
    hub = Hub(hub_cfg, root=hub_root, convex_env=ConvexEnv(fake.url, SECRET))
    await hub.start()
    try:
        c = await BusClient.connect("concierge", subscribe=["registry_update"], url=f"ws://127.0.0.1:{hub.bus.port}")
        first = await asyncio.wait_for(c.recv(), 3)
        assert first.type == "registry_update" and first.registry_version == 1.0  # seed -> Convex version 1
        t = time.time()
        for tag, dt in [(SUGAR, 0.0), (SUGAR, 0.5), ("EMPTY", 1.0), ("EMPTY", 2.5)]:
            await c.send(_read(tag, t + dt))
        await c.send(TrialStart(trial_id="trial-x", mode="baseline", target_object_id="sugar", tester="tester-A"))
        await wait_for(lambda: len(fake.order) == 4)
        kinds = [fake.events[i]["kind"] for i in fake.order]
        assert kinds == ["placed", "removed", "pickup", "trial_start"]
        assert fake.events[fake.order[0]]["data"] == {"spot": 3, "tag": SUGAR, "source": "simulator"}
        assert fake.events[fake.order[3]]["object_id"] == "sugar"
        await wait_for(lambda: any(s["status"] == "held" for s in fake.states))
        assert {s["object_id"] for s in fake.states} == {"sugar"}

        # Same version: no update. New version: registry_update with the new object.
        honey = {"object_id": "honey", "name": "honey", "aliases": [], "notes": "", "description": "",
                 "tag": "04A1B2C3D4E5FF", "home_spot": 1, "is_medication": False, "fob_id": None}
        fake.registry = Registry.model_validate({**fake.registry.model_dump(mode="json"),
                                                 "objects": [*fake.registry.model_dump(mode="json")["objects"], honey],
                                                 "version": 2.0})
        update = await asyncio.wait_for(c.recv(), 3)
        assert update.type == "registry_update" and update.registry_version == 2.0
        assert "honey" in {o.object_id for o in update.objects}
        cache = Registry.model_validate_json((hub_root / "config" / "objects.cache.json").read_text())
        assert cache.version == 2.0
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(c.recv(), 0.4)
        await c.close()
        assert hub.health().info["convex"] == "online"
    finally:
        await hub.stop()


def _read(tag, t):
    from earmark_contracts import DetectionEvent

    kind = "removed" if tag == "EMPTY" else "seen"
    return DetectionEvent(source="simulator", tag=tag, kind=kind, where={"spot": 3}, precision="exact", rssi=None, t=t)


async def test_place_item_is_synced_as_a_stored_event_and_state(fake, hub_cfg, hub_root):
    from earmark_contracts import PlaceItem

    fake.start()
    hub_cfg.convex = fast_cfg()
    hub = Hub(hub_cfg, root=hub_root, convex_env=ConvexEnv(fake.url, SECRET))
    await hub.start()
    try:
        c = await BusClient.connect("concierge", subscribe=["state_update"], url=f"ws://127.0.0.1:{hub.bus.port}")
        await c.send(PlaceItem(object_id="sugar", area="drawer", t=time.time()))
        await wait_for(lambda: len(fake.order) == 1)
        event = fake.events[fake.order[0]]
        assert (event["kind"], event["object_id"]) == ("stored", "sugar")
        assert event["data"] == {"area": "drawer", "label": "the drawer", "source": "voice"}
        await wait_for(lambda: any(s["location"]["area"] == "drawer" for s in fake.states))
        await c.close()
    finally:
        await hub.stop()
