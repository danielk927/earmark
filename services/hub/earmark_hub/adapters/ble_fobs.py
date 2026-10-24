"""Bluetooth key-finder fobs (bleak). See docs/vendor-notes/bleak.md.

Scanning: one continuous BleakScanner; advertisements from configured fobs (matched by
CoreBluetooth address, or by advertised name cached per address) feed a time-weighted
RSSI EMA, classified near/mid/far by thresholds. A fob with no advertisement for
`stale_s` is reported `lost` (not while a chirp holds a connection, since fobs usually
stop advertising while connected).

Chirp: connect on demand with the scanner's BLEDevice, log the GATT table, resolve
Alert Level 0x2A06 through Immediate Alert 0x1802 (Link Loss 0x1803 has a 0x2A06 too),
pick the write type from the characteristic properties, write the alert level, hold the
connection (a disconnect ends an IAS alert) until `stop` or the auto-stop timeout, then
write 0x00 and disconnect.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from earmark_contracts import DetectionEvent, StatusMsg

from ..clock import Clock
from ..config import BleCfg
from .base import Adapter

log = logging.getLogger("earmark.hub.ble")

PERMISSION_HINT = ("allow Bluetooth for your terminal app in System Settings > Privacy & Security > Bluetooth, "
                   "then restart the hub from that terminal")


def classify(rssi: float, near_dbm: float, mid_dbm: float) -> str:
    if rssi >= near_dbm:
        return "near"
    if rssi >= mid_dbm:
        return "mid"
    return "far"


@dataclass
class RssiTracker:
    """Time-weighted EMA: alpha = 1 - exp(-dt / tau), so irregular sample spacing is handled."""

    tau_s: float
    ema: float | None = None
    last_t: float | None = None

    def update(self, rssi: float, t: float) -> float:
        if self.ema is None or self.last_t is None:
            self.ema = float(rssi)
        else:
            dt = max(0.0, t - self.last_t)
            alpha = 1.0 - math.exp(-dt / self.tau_s)
            self.ema += alpha * (rssi - self.ema)
        self.last_t = t
        return self.ema

    def clear(self) -> None:
        self.ema = self.last_t = None


@dataclass
class _Fob:
    tracker: RssiTracker
    visible: bool = False
    last_class: str | None = None
    last_emit_t: float = -math.inf


def _default_scanner(callback):
    from bleak import BleakScanner

    return BleakScanner(detection_callback=callback)


def _default_client(device, timeout: float):
    from bleak import BleakClient

    return BleakClient(device, timeout=timeout)


class BleFobsAdapter(Adapter):
    name = "ble_fobs"

    def __init__(self, clock: Clock, cfg: BleCfg, *,
                 scanner_factory: Callable = _default_scanner,
                 client_factory: Callable = _default_client) -> None:
        self.clock, self.cfg = clock, cfg
        self.scanner_factory, self.client_factory = scanner_factory, client_factory
        self.fobs = {fob_id: _Fob(RssiTracker(cfg.ema_tau_s)) for fob_id in cfg.fobs}
        self._bound: dict[str, str] = {}      # address -> fob_id
        self._names: dict[str, str] = {}      # address -> last advertised name
        self._seen_addrs: set[str] = set()
        self._devices: dict[str, object] = {}  # fob_id -> BLEDevice from the scanner
        self._queue: asyncio.Queue | None = None
        self._scanner = None
        self._chirps: dict[str, asyncio.Task] = {}
        self._stops: dict[str, asyncio.Event] = {}
        self._deadlines: dict[str, float] = {}

    # ------------------------------------------------------------ scanning

    async def events(self) -> AsyncIterator[DetectionEvent]:
        self._queue = asyncio.Queue()
        self._scanner = self.scanner_factory(self._on_advertisement)
        try:
            await self._scanner.start()
        except Exception as e:
            detail = f"BLE scan failed: {e}"
            if type(e).__name__ == "BleakBluetoothNotAvailableError":
                detail += f"; {PERMISSION_HINT}"
            self.ctx.adapter_status(self.name, False, detail)
            raise
        if not self.cfg.fobs:
            self.ctx.adapter_status(self.name, True, "scanning, but no fobs configured in config/hub.json")
        else:
            self.ctx.adapter_status(self.name, True, f"scanning for {', '.join(self.cfg.fobs)}")
        stale = asyncio.create_task(self._stale_loop())
        try:
            while True:
                yield await self._queue.get()
        finally:
            stale.cancel()
            try:
                await self._scanner.stop()
            except Exception as e:
                log.warning("scanner stop failed", extra={"error": str(e)})

    def match(self, address: str, local_name: str | None) -> str | None:
        """Fob id for an advertiser: configured address first, else the cached advertised name."""
        if local_name:
            self._names[address] = local_name
        if address in self._bound:
            return self._bound[address]
        for fob_id, f in self.cfg.fobs.items():
            if f.address and f.address.lower() == address.lower():
                self._bound[address] = fob_id
                return fob_id
        name = self._names.get(address)
        if name:
            for fob_id, f in self.cfg.fobs.items():
                if not f.address and f.name and f.name == name and fob_id not in self._bound.values():
                    self._bound[address] = fob_id
                    log.info("fob bound by name; pin its address in config/hub.json",
                             extra={"fob_id": fob_id, "address": address, "name": name})
                    return fob_id
        return None

    def _on_advertisement(self, device, adv) -> None:
        address = device.address
        fob_id = self.match(address, adv.local_name)
        if address not in self._seen_addrs and len(self._seen_addrs) < 1000:
            self._seen_addrs.add(address)
            log.info("ble advertiser", extra={"address": address, "name": adv.local_name, "rssi": adv.rssi,
                                              "fob_id": fob_id})
        if fob_id is None:
            return
        self._devices[fob_id] = device
        self.observe(fob_id, float(adv.rssi), self.clock.now())

    def observe(self, fob_id: str, rssi: float, t: float) -> DetectionEvent | None:
        fob = self.fobs[fob_id]
        ema = fob.tracker.update(rssi, t)
        cls = classify(ema, self.cfg.near_dbm, self.cfg.mid_dbm)
        if fob.visible and cls == fob.last_class and t - fob.last_emit_t < self.cfg.emit_interval_s:
            return None
        fob.visible, fob.last_class, fob.last_emit_t = True, cls, t
        ev = DetectionEvent(source="ble", tag=fob_id, kind="seen",
                            where={"near": self.cfg.receiver, "distance_class": cls},
                            precision="proximity", rssi=round(ema, 1), t=t)
        self._put(ev)
        return ev

    def check_stale(self, now: float) -> list[DetectionEvent]:
        lost = []
        for fob_id, fob in self.fobs.items():
            if not fob.visible or fob_id in self._chirps or fob.tracker.last_t is None:
                continue
            if now - fob.tracker.last_t >= self.cfg.stale_s:
                fob.visible, fob.last_class = False, None
                fob.tracker.clear()
                ev = DetectionEvent(source="ble", tag=fob_id, kind="lost", where=None,
                                    precision="none", rssi=None, t=now)
                self._put(ev)
                lost.append(ev)
        return lost

    def _put(self, ev: DetectionEvent) -> None:
        if self._queue is not None:
            self._queue.put_nowait(ev)

    async def _stale_loop(self) -> None:
        while True:
            await self.clock.sleep(0.5)
            self.check_stale(self.clock.now())

    # ------------------------------------------------------------ chirp

    async def chirp(self, fob_id: str, action: str) -> None:
        loop = asyncio.get_running_loop()
        if action == "stop":
            if fob_id in self._stops:
                self._stops[fob_id].set()
            return
        if fob_id in self._chirps:
            self._deadlines[fob_id] = loop.time() + self.cfg.chirp_timeout_s  # extend the running chirp
            return
        self._deadlines[fob_id] = loop.time() + self.cfg.chirp_timeout_s
        self._stops[fob_id] = asyncio.Event()
        self._chirps[fob_id] = asyncio.create_task(self._chirp_session(fob_id))

    async def stop_all(self) -> None:
        for ev in self._stops.values():
            ev.set()
        tasks = list(self._chirps.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def on_reset(self) -> None:
        for ev in self._stops.values():  # the chirp tasks write 0x00 and disconnect on their own
            ev.set()

    async def close(self) -> None:
        await self.stop_all()

    async def _chirp_session(self, fob_id: str) -> None:
        try:
            device = self._devices.get(fob_id)
            if device is None:
                await self._report(f"chirp {fob_id}: fob not seen by the scanner yet")
                return
            try:
                await self._alert(fob_id, device)
            except (asyncio.TimeoutError, TimeoutError):
                # Some adapters cannot connect while scanning: pause the scan and retry once.
                log.warning("chirp connect timed out; retrying with the scanner paused", extra={"fob_id": fob_id})
                await self._scanner.stop()
                try:
                    await self._alert(fob_id, device)
                finally:
                    await self._scanner.start()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._report(f"chirp {fob_id} failed: {type(e).__name__}: {e}")
        finally:
            self._chirps.pop(fob_id, None)
            self._stops.pop(fob_id, None)
            self._deadlines.pop(fob_id, None)

    async def _alert(self, fob_id: str, device) -> None:
        loop = asyncio.get_running_loop()
        stop = self._stops[fob_id]
        async with self.client_factory(device, self.cfg.connect_timeout_s) as client:
            for svc in client.services:
                log.info("fob gatt service", extra={
                    "fob_id": fob_id, "service": str(svc.uuid),
                    "characteristics": [[str(c.uuid), c.handle, list(c.properties)] for c in svc.characteristics],
                })
            char = self._char(client, self.cfg.alert_service_uuid, self.cfg.alert_char_uuid)
            if char is None:
                raise RuntimeError(f"no Alert Level {self.cfg.alert_char_uuid} in service {self.cfg.alert_service_uuid}")
            response = "write-without-response" not in char.properties
            await client.write_gatt_char(char, bytes([self.cfg.alert_level]), response=response)
            log.info("chirp started", extra={"fob_id": fob_id, "response": response})
            while not stop.is_set():
                remaining = self._deadlines.get(fob_id, 0) - loop.time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(stop.wait(), remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
            await client.write_gatt_char(char, b"\x00", response=response)
            if self.cfg.link_loss_value is not None:
                ll = self._char(client, self.cfg.link_loss_service_uuid, self.cfg.alert_char_uuid)
                if ll is not None:
                    ll_response = "write-without-response" not in ll.properties
                    await client.write_gatt_char(ll, bytes([self.cfg.link_loss_value]), response=ll_response)
            log.info("chirp stopped", extra={"fob_id": fob_id, "reason": "stop" if stop.is_set() else "timeout"})

    @staticmethod
    def _char(client, service_uuid: str, char_uuid: str):
        svc = client.services.get_service(service_uuid)
        return svc.get_characteristic(char_uuid) if svc is not None else None

    async def _report(self, detail: str) -> None:
        log.warning(detail)
        await self.ctx.publish(StatusMsg(component="hub", ok=False, detail=detail, t=self.clock.now()), "hub")
