"""BLE fobs: RSSI smoothing, classification, staleness, matching, and the chirp sequence (fake bleak)."""
from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from earmark_hub.adapters.ble_fobs import BleFobsAdapter, RssiTracker, classify
from earmark_hub.clock import VirtualClock
from earmark_hub.config import BleCfg, FobCfg

T0 = 1_761_350_400.0


def norm(u: str) -> str:
    u = u.lower()
    return f"0000{u}-0000-1000-8000-00805f9b34fb" if len(u) == 4 else u


# ---------------------------------------------------------------- smoothing / classification


def test_classify_thresholds():
    assert classify(-50, -65, -80) == "near"
    assert classify(-65, -65, -80) == "near"
    assert classify(-70, -65, -80) == "mid"
    assert classify(-80, -65, -80) == "mid"
    assert classify(-80.1, -65, -80) == "far"


def test_ema_is_time_weighted():
    tr = RssiTracker(tau_s=2.0)
    assert tr.update(-90, 0.0) == -90
    # After dt = tau the EMA moves 1 - 1/e of the way.
    assert tr.update(-50, 2.0) == pytest.approx(-90 + 40 * (1 - math.exp(-1)))
    tr2 = RssiTracker(tau_s=2.0)
    tr2.update(-90, 0.0)
    for k in range(1, 21):  # many samples in 0.2 s barely move it
        tr2.update(-50, 0.01 * k)
    assert tr2.ema < -85
    tr2.update(-50, 30.0)  # a long gap trusts the new sample almost entirely
    assert tr2.ema > -51


def test_ema_smooths_a_single_outlier():
    tr = RssiTracker(tau_s=2.0)
    for k in range(10):
        tr.update(-88, k * 0.5)
    tr.update(-60, 5.0)  # one "near" outlier 0.5 s later moves the EMA about 22% of the way
    assert tr.ema == pytest.approx(-88 + 28 * (1 - math.exp(-0.25)))
    assert classify(tr.ema, -65, -80) == "far"


def make(cfg=None, **kw):
    cfg = cfg or BleCfg(fobs={"fob_keys": FobCfg(address="AAAA-1111")}, ema_tau_s=1.0, stale_s=5.0,
                        emit_interval_s=1.0, **kw)
    adapter = BleFobsAdapter(VirtualClock(T0), cfg, scanner_factory=FakeScanner, client_factory=FakeClient)
    adapter._queue = asyncio.Queue()
    return adapter


def test_observe_emits_on_class_change_and_rate_limits():
    a = make()
    evs = [a.observe("fob_keys", -90, T0 + k * 0.2) for k in range(5)]
    assert evs[0] is not None and evs[0].where.distance_class == "far" and evs[0].rssi == -90
    assert all(e is None for e in evs[1:])  # same class within emit_interval
    assert a.observe("fob_keys", -90, T0 + 1.1) is not None  # interval elapsed
    ev = None
    t = T0 + 1.2
    while ev is None or ev.where.distance_class == "far":
        t += 0.2
        ev = a.observe("fob_keys", -40, t) or ev
    assert ev.where.distance_class == "mid"  # passes through mid on the way to near
    assert ev.where.near == "hub" and ev.precision == "proximity" and ev.source == "ble" and ev.tag == "fob_keys"


def test_staleness_emits_lost_once_and_restarts_ema():
    a = make()
    a.observe("fob_keys", -60, T0)
    assert a.check_stale(T0 + 4.9) == []
    lost = a.check_stale(T0 + 5.0)
    assert len(lost) == 1 and lost[0].kind == "lost" and lost[0].where is None and lost[0].precision == "none"
    assert a.check_stale(T0 + 20) == []
    ev = a.observe("fob_keys", -90, T0 + 21)
    assert ev.rssi == -90  # fresh EMA, not blended with the stale -60


def test_no_staleness_while_chirping():
    a = make()
    a.observe("fob_keys", -60, T0)
    a._chirps["fob_keys"] = object()
    assert a.check_stale(T0 + 60) == []


def test_match_by_address_and_cached_name():
    cfg = BleCfg(fobs={"fob_keys": FobCfg(address="aaaa-1111"), "fob_bag": FobCfg(name="iTAG")})
    a = make(cfg)
    assert a.match("AAAA-1111", None) == "fob_keys"
    assert a.match("BBBB-2222", None) is None  # first packet without a scan response
    assert a.match("BBBB-2222", "iTAG") == "fob_bag"
    assert a.match("BBBB-2222", None) == "fob_bag"  # cached
    assert a.match("CCCC-3333", "iTAG") is None  # name already bound to another address


# ---------------------------------------------------------------- chirp against a fake bleak client


class FakeChar:
    def __init__(self, uuid, properties, handle):
        self.uuid, self.properties, self.handle = norm(uuid), properties, handle


class FakeService:
    def __init__(self, uuid, chars):
        self.uuid, self.characteristics = norm(uuid), chars

    def get_characteristic(self, uuid):
        return next((c for c in self.characteristics if c.uuid == norm(uuid)), None)


class FakeServices:
    def __init__(self, services):
        self.services = services

    def __iter__(self):
        return iter(self.services)

    def get_service(self, uuid):
        return next((s for s in self.services if s.uuid == norm(uuid)), None)


CALLS: list = []


class FakeClient:
    properties = ["write"]
    connect_error: Exception | None = None

    def __init__(self, device, timeout):
        self.device, self.timeout = device, timeout
        ias = FakeService("1802", [FakeChar("2a06", list(self.properties), 11)])
        lls = FakeService("1803", [FakeChar("2a06", ["read", "write"], 21)])
        self.services = FakeServices([ias, lls, FakeService("180f", [FakeChar("2a19", ["read"], 31)])])

    async def __aenter__(self):
        if FakeClient.connect_error is not None:
            err, FakeClient.connect_error = FakeClient.connect_error, None
            raise err
        CALLS.append(("connect", self.device.address, self.timeout))
        return self

    async def __aexit__(self, *exc):
        CALLS.append(("disconnect",))

    async def write_gatt_char(self, char, data, response):
        CALLS.append(("write", char.handle, bytes(data), response))


class FakeScanner:
    def __init__(self, callback):
        self.callback = callback
        self.running = False

    async def start(self):
        CALLS.append(("scan_start",))
        self.running = True

    async def stop(self):
        CALLS.append(("scan_stop",))
        self.running = False


class Ctx:
    def __init__(self):
        self.published, self.statuses = [], []

    async def publish(self, msg, origin):
        self.published.append(msg)

    def adapter_status(self, name, ok, detail):
        self.statuses.append((ok, detail))


@pytest.fixture
def chirper():
    CALLS.clear()
    FakeClient.properties = ["write"]
    cfg = BleCfg(fobs={"fob_keys": FobCfg(address="AAAA-1111")}, chirp_timeout_s=0.3, connect_timeout_s=7)
    a = BleFobsAdapter(VirtualClock(T0), cfg, scanner_factory=FakeScanner, client_factory=FakeClient)
    a.attach(Ctx())
    a._scanner = FakeScanner(None)
    a._devices["fob_keys"] = SimpleNamespace(address="AAAA-1111")
    return a


async def test_chirp_holds_connection_then_auto_stops(chirper):
    await chirper.chirp("fob_keys", "start")
    await asyncio.wait_for(chirper._chirps["fob_keys"], 2)
    assert CALLS == [("connect", "AAAA-1111", 7), ("write", 11, b"\x01", True), ("write", 11, b"\x00", True),
                     ("disconnect",)]


async def test_chirp_stop_ends_early_and_uses_write_without_response(chirper):
    FakeClient.properties = ["write-without-response", "write"]
    chirper.cfg.chirp_timeout_s = 30
    await chirper.chirp("fob_keys", "start")
    await asyncio.sleep(0.05)
    assert ("write", 11, b"\x01", False) in CALLS and ("disconnect",) not in CALLS
    await chirper.chirp("fob_keys", "stop")
    await asyncio.wait_for(chirper._chirps["fob_keys"], 2)
    assert CALLS[-2:] == [("write", 11, b"\x00", False), ("disconnect",)]


async def test_chirp_start_while_running_extends_instead_of_reconnecting(chirper):
    await chirper.chirp("fob_keys", "start")
    task = chirper._chirps["fob_keys"]
    await asyncio.sleep(0.2)
    await chirper.chirp("fob_keys", "start")
    await asyncio.wait_for(task, 2)
    assert [c[0] for c in CALLS].count("connect") == 1


async def test_chirp_unknown_device_reports_status(chirper):
    await chirper.chirp("fob_other", "start")
    await asyncio.sleep(0.01)
    assert CALLS == []
    assert "not seen by the scanner" in chirper.ctx.published[0].detail


async def test_chirp_missing_alert_char_reports_and_disconnects(chirper):
    chirper.cfg.alert_service_uuid = "1811"
    await chirper.chirp("fob_keys", "start")
    await asyncio.sleep(0.05)
    assert ("disconnect",) in CALLS and not any(c[0] == "write" for c in CALLS)
    assert "failed" in chirper.ctx.published[0].detail and chirper.ctx.published[0].ok is False


async def test_chirp_retries_with_scanner_paused_after_connect_timeout(chirper):
    FakeClient.connect_error = asyncio.TimeoutError()
    await chirper.chirp("fob_keys", "start")
    await asyncio.wait_for(chirper._chirps["fob_keys"], 2)
    kinds = [c[0] for c in CALLS]
    assert kinds == ["scan_stop", "connect", "write", "write", "disconnect", "scan_start"]


async def test_link_loss_write_is_optional(chirper):
    chirper.cfg.link_loss_value = 0xFF
    await chirper.chirp("fob_keys", "start")
    await asyncio.wait_for(chirper._chirps["fob_keys"], 2)
    assert ("write", 21, b"\xff", True) in CALLS and CALLS[-1] == ("disconnect",)


async def test_reset_stops_chirps(chirper):
    chirper.cfg.chirp_timeout_s = 30
    await chirper.chirp("fob_keys", "start")
    await asyncio.sleep(0.02)
    task = chirper._chirps["fob_keys"]
    await chirper.on_reset()
    await asyncio.wait_for(task, 2)
    assert CALLS[-2:] == [("write", 11, b"\x00", True), ("disconnect",)]


async def test_events_scans_and_reports_permission_errors():
    class DeniedScanner(FakeScanner):
        async def start(self):
            class BleakBluetoothNotAvailableError(Exception):
                pass

            raise BleakBluetoothNotAvailableError("unauthorized")

    a = BleFobsAdapter(VirtualClock(T0), BleCfg(), scanner_factory=DeniedScanner, client_factory=FakeClient)
    a.attach(Ctx())
    with pytest.raises(Exception, match="unauthorized"):
        await a.events().__anext__()
    assert "Privacy & Security > Bluetooth" in a.ctx.statuses[-1][1]


async def test_events_yields_from_advertisements():
    CALLS.clear()
    cfg = BleCfg(fobs={"fob_keys": FobCfg(address="AAAA-1111")})
    a = BleFobsAdapter(VirtualClock(T0), cfg, scanner_factory=FakeScanner, client_factory=FakeClient)
    a.attach(Ctx())
    gen = a.events()
    first = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    a._scanner.callback(SimpleNamespace(address="ZZZZ"), SimpleNamespace(local_name="other", rssi=-40))
    a._scanner.callback(SimpleNamespace(address="AAAA-1111"), SimpleNamespace(local_name=None, rssi=-58))
    ev = await asyncio.wait_for(first, 1)
    assert ev.tag == "fob_keys" and ev.where.distance_class == "near" and ev.rssi == -58
    await gen.aclose()
    assert CALLS == [("scan_start",), ("scan_stop",)]
