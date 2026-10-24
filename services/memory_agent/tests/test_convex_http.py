"""The tool layer over real HTTP against the fixture server: auth, timeouts, validation, errors."""
from __future__ import annotations

import socket
import time

import pytest

from earmark_memory.convex import ConvexError, HttpConvexReader, validate_site_url
from earmark_memory.describe import SpaceLabels
from earmark_memory.fixture import FixtureData, FixtureServer
from earmark_memory.tools import Toolbox

from .conftest import SECRET


async def test_sends_the_secret_header_and_query_names(server: FixtureServer):
    reader = HttpConvexReader(server.url, SECRET)
    try:
        assert (await reader.find_object("keys")).matches[0].object_id == "keys"
        assert len((await reader.list_objects()).objects) == 5
        assert (await reader.history("salt", 1761300000.5)).object_id == "salt"
        assert (await reader.adherence("2025-10-23")).doses[1].status == "missed"
        assert (await reader.daily_summary("2025-10-23")).untouched_7d == ["pepper"]
    finally:
        await reader.aclose()
    assert all(r["secret"] == SECRET for r in server.requests)
    assert [(r["path"], r["query"]) for r in server.requests] == [
        ("/api/object", {"name": "keys"}),
        ("/api/objects", {}),
        ("/api/history", {"objectId": "salt", "since": "1761300000.5"}),
        ("/api/adherence", {"date": "2025-10-23"}),
        ("/api/daily-summary", {"date": "2025-10-23"}),
    ]


async def test_optional_params_are_omitted(server: FixtureServer):
    reader = HttpConvexReader(server.url, SECRET)
    try:
        await reader.adherence(None)
        await reader.history("salt")
    finally:
        await reader.aclose()
    assert server.requests[0]["query"] == {}
    assert server.requests[1]["query"] == {"objectId": "salt"}


async def test_wrong_secret_is_unauthorized(server: FixtureServer):
    reader = HttpConvexReader(server.url, "wrong")
    with pytest.raises(ConvexError) as err:
        await reader.list_objects()
    await reader.aclose()
    assert err.value.kind == "unauthorized"
    assert "wrong" not in str(err.value)


async def test_timeout_is_bounded():
    with FixtureServer(FixtureData(), SECRET, delay_s=1.5) as slow:
        reader = HttpConvexReader(slow.url, SECRET, timeout_s=0.2)
        started = time.perf_counter()
        with pytest.raises(ConvexError) as err:
            await reader.list_objects()
        elapsed = time.perf_counter() - started
        await reader.aclose()
    assert err.value.kind == "timeout"
    assert elapsed < 1.0


async def test_unreachable():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens here now
    reader = HttpConvexReader(f"http://127.0.0.1:{port}", SECRET, timeout_s=1.0)
    with pytest.raises(ConvexError) as err:
        await reader.list_objects()
    await reader.aclose()
    assert err.value.kind == "unreachable"


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (200, {"objects": [], "now_t": 1.0}, "bad_response"),  # missing now_local
        (200, {"objects": [], "now_t": 1.0, "now_local": "x", "extra": 1}, "bad_response"),  # extra field
        (200, "not json", "bad_response"),
        (500, "Internal Server Error", "http_error"),
        (404, {"ok": False, "error": "unknown objectId"}, "not_found"),
        (400, {"ok": False, "error": "date must be YYYY-MM-DD"}, "bad_request"),
    ],
)
async def test_off_contract_and_error_responses(server: FixtureServer, status, body, kind):
    server.overrides["/api/objects"] = (status, body)
    reader = HttpConvexReader(server.url, SECRET)
    with pytest.raises(ConvexError) as err:
        await reader.list_objects()
    await reader.aclose()
    assert err.value.kind == kind
    if isinstance(body, dict) and "error" in body:
        assert body["error"] in str(err.value)


async def test_unknown_object_id_is_not_found(server: FixtureServer):
    reader = HttpConvexReader(server.url, SECRET)
    with pytest.raises(ConvexError) as err:
        await reader.history("unicorn")
    await reader.aclose()
    assert (err.value.kind, str(err.value)) == ("not_found", "unknown objectId")


def test_site_url_must_be_https_except_loopback():
    assert validate_site_url("https://happy-otter-123.convex.site/") == "https://happy-otter-123.convex.site"
    assert validate_site_url("http://127.0.0.1:3211") == "http://127.0.0.1:3211"
    assert validate_site_url("http://localhost:3211") == "http://localhost:3211"
    with pytest.raises(ValueError, match="https"):
        validate_site_url("http://happy-otter-123.convex.site")
    with pytest.raises(ValueError):
        HttpConvexReader("https://x.convex.site", "")


async def test_clock_takes_the_timezone_from_convex(server: FixtureServer):
    reader = HttpConvexReader(server.url, SECRET)
    clock = await reader.clock()
    await reader.clock()
    await reader.aclose()
    assert clock.timezone == "America/Los_Angeles"
    assert abs(clock.now_t - time.time()) < 5
    assert len(server.requests) == 1  # cached after the first call


async def test_toolbox_over_http_records_calls_and_errors(server: FixtureServer, data: FixtureData):
    reader = HttpConvexReader(server.url, SECRET)
    tb = Toolbox(reader, data.clock, SpaceLabels.load())
    view = await tb.call_json("find_object", '{"name": "keys"}')
    assert view["matches"][0]["where_now"] == "close to the counter"
    adherence = await tb.call_json("adherence", '{"date": "yesterday"}')
    assert adherence["date"] == "2025-10-23" and adherence["doses"][1]["status"] == "missed"
    missing = await tb.call_json("history", '{"object_id": "unicorn"}')
    bad = await tb.call_json("adherence", '{"date": "someday"}')
    unknown = await tb.call_json("delete_everything", "{}")
    await reader.aclose()
    assert missing == {"ok": False, "error": "unknown objectId", "kind": "not_found"}
    assert bad["ok"] is False and "YYYY-MM-DD" in bad["error"]
    assert unknown["ok"] is False
    assert [(r.name, r.ok) for r in tb.records][:3] == [("find_object", True), ("adherence", True), ("history", False)]
    assert all(r.ms >= 0 for r in tb.records)
