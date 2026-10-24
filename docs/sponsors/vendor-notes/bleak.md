# bleak - vendor notes for Earmark (`ble_fobs` adapter)

Researched 2026-10-24 for BUILD_BRIEF section 5.B.
Every claim links its source.
"Source-read" means I read the bleak 3.0.2 wheel source directly (the same files are on GitHub at https://github.com/hbldh/bleak/tree/develop/bleak).
Anything I could not confirm is marked UNVERIFIED.

## 1. Version, Python, install

- Latest is **3.0.2**, released 2026-05-02.
  3.0.0 came out on 2026-03-22.
  Source: PyPI JSON, https://pypi.org/pypi/bleak/json
- `requires_python >=3.10` (same PyPI JSON).
  2.0.0 removed Python 3.9 and macOS < 10.15 (https://github.com/hbldh/bleak/blob/develop/CHANGELOG.rst).
- macOS runtime deps: `pyobjc-core`, `pyobjc-framework-corebluetooth`, `pyobjc-framework-libdispatch`, all `>=10.3` (PyPI JSON `requires_dist`).
- **Verified locally:** `bleak==3.0.2` installs with `uv` and imports on CPython 3.12.12, macOS 26.5.1 arm64 (it pulled in `pyobjc-core` 12.2.2).
  This was an import test only.
  I did not start a scan, so I would not trigger a Bluetooth permission prompt while the human is away.
- Install: `uv add "bleak>=3.0.2,<4"`.
  Docs: https://bleak.readthedocs.io/en/latest/installation.html
- Recent changes that matter to us (https://github.com/hbldh/bleak/blob/develop/CHANGELOG.rst):
  - 2.0.0: `BleakBluetoothNotAvailableError` is raised when Bluetooth is unsupported, turned off, or permission is denied.
  - 2.1.1: the default `BleakClient` connect timeout went from 10 s to 30 s.
  - 3.0.0: GATT reads and writes raise `BleakGATTProtocolError` on ATT protocol errors.
    The `adapter` kwarg is deprecated, but it is a BlueZ (Linux) option and does not affect us.

## 2. Scanning (`BleakScanner`)

- Signature (source-read, `bleak/__init__.py`): `BleakScanner(detection_callback=None, service_uuids=None, scanning_mode="active", *, bluez={}, cb={}, backend=None)`.
  API docs: https://bleak.readthedocs.io/en/latest/api/scanner.html
- `detection_callback(device: BLEDevice, adv: AdvertisementData)` is "called each time a device is discovered or advertising data has changed" (same page).
- `AdvertisementData` fields (source-read, `bleak/backends/scanner.py`):
  - `local_name: str | None`
  - `manufacturer_data: dict[int, bytes]`, keyed by Bluetooth SIG company ID
  - `service_data: dict[str, bytes]`
  - `service_uuids: list[str]`, as lowercase 128-bit strings
  - `tx_power: int | None`
  - `rssi: int`, in dBm
  - `platform_data`, which is not a stable API
- The first advertisement may arrive without the scan response, so `local_name` can be `None` at first.
  Cache the name per address and do not match fobs on the first packet's name (docstring tip on https://bleak.readthedocs.io/en/latest/api/scanner.html).
- To scan continuously, call `await scanner.start()` once and `await scanner.stop()` on shutdown, or use `async with BleakScanner(cb):`.
  There is also an `async for device, adv in scanner.advertisement_data():` generator, added in 0.21 (source-read).
- **Passive scanning is not supported on macOS.**
  `scanning_mode="passive"` raises `BleakError` (https://bleak.readthedocs.io/en/latest/backends/macos.html).
- The `service_uuids` filter is only *required* on macOS 12.0 to 12.2 (https://bleak.readthedocs.io/en/latest/troubleshooting.html).
  Do not filter on `1802`.
  Whether cheap fobs advertise that service is UNVERIFIED, so filter on the registered address in the callback instead.
- **How often RSSI updates arrive (important for the EMA):**
  - bleak calls `scanForPeripheralsWithServices_options_(uuids, None)`, so it never sets `CBCentralManagerScanOptionAllowDuplicatesKey` (source-read, https://github.com/hbldh/bleak/blob/develop/bleak/backends/corebluetooth/CentralManagerDelegate.py).
  - Apple: with that key false (the default), "the central coalesces multiple discoveries of the same peripheral into a single discovery event" (https://developer.apple.com/documentation/corebluetooth/cbcentralmanagerscanoptionallowduplicateskey).
  - bleak issue #394 says macOS 12 "changed the default behavior to call the delegate callback when the RSSI changes", and the maintainer closed it as won't-fix in 2022 (https://github.com/hbldh/bleak/issues/394).
  - The actual callback rate on macOS 26 is UNVERIFIED.
    Measure it in Phase 0.
    Time-weight the EMA, because samples arrive at irregular intervals.
    Also add a staleness timeout, so a fob that has gone quiet decays to `far` or unknown instead of keeping its last value.

### macOS addresses are CoreBluetooth UUIDs, not MACs

- `BLEDevice.address` on macOS is a UUID that CoreBluetooth assigns.
  That UUID only works on the Mac that scanned and cached the device (https://bleak.readthedocs.io/en/latest/backends/macos.html).
  Register fobs on the demo Mac itself, and treat the stored UUID as specific to that machine.
- `cb={"use_bdaddr": True}` returns the real MAC instead (source-read, https://github.com/hbldh/bleak/blob/develop/bleak/args/corebluetooth.py):
  - It uses the undocumented IOBluetooth call `retrieveAddressForPeripheral_`.
  - The docstring warns it "may break in the future macOS releases" and is "known to not work on macOS 10.15" (https://github.com/hbldh/bleak/issues/1286).
  - If the address cannot be retrieved, the device is silently dropped from results (source-read, `corebluetooth/scanner.py`).
  - Whether it works on macOS 26 is UNVERIFIED.
    Default to the UUID, and do not depend on `use_bdaddr`.

### macOS Bluetooth permission (TCC)

- Bundled apps must declare `NSBluetoothAlwaysUsageDescription` in `Info.plist` (https://bleak.readthedocs.io/en/latest/backends/macos.html, https://developer.apple.com/documentation/bundleresources/information-property-list/nsbluetoothalwaysusagedescription).
- A plain Python script is attributed to its **responsible process**, the app that owns the terminal.
  If that app has no usage description, macOS kills Python with SIGABRT and "Termination Reason: Namespace TCC".
  Sources: https://bleak.readthedocs.io/en/latest/troubleshooting.html, and iTerm2's "Responsible: iTerm2" crash log in https://github.com/rbaron/catprinter/issues/44.
- Local `plutil` check (2026-10-24):
  - `/Applications/Visual Studio Code.app` and `/Applications/Cursor.app` both declare `NSBluetoothAlwaysUsageDescription`.
  - `/System/Applications/Utilities/Terminal.app` does not declare it.
    Even so, Terminal.app is reported to prompt normally (catprinter #44 above, and an Oct 12 2026 comment on https://github.com/anthropics/claude-code/issues/76517).
    On this Mac, that is UNVERIFIED.
- **Claude Code gotcha** (https://github.com/anthropics/claude-code/issues/76517, open as of 2026-10-12):
  - When Claude Code runs as a desktop or background session, its children are hard-killed on Bluetooth access with no prompt.
  - The responsible process is the embedded `com.anthropic.claude-code` bundle, which lacks the key.
    I confirmed locally that `~/Library/Application Support/Claude/claude-code/2.1.308/.../claude.app/Contents/Info.plist` has no `NSBluetoothAlwaysUsageDescription`.
  - The reported workaround is to run the CLI from Terminal.app.
    This session's process chain is Terminal -> login -> zsh -> claude.
  - **Recommendation:** the human should run the hub once by hand (`uv run ...`) in Terminal.app and accept the "Terminal would like to use Bluetooth" prompt.
    Agents should not start BLE scans from Claude Desktop or background sessions.
- If permission is denied, every Bluetooth call raises `BleakBluetoothNotAvailableError`.
  The app cannot ask again.
  The user has to enable it in System Settings > Privacy & Security > Bluetooth (https://bleak.readthedocs.io/en/latest/backends/macos.html).
  Catch the error and show that instruction.
- Reset with `tccutil reset BluetoothAlways`.
  That service name is UNVERIFIED.
- Pairing: macOS has no pairing API.
  `pair()` raises `NotImplementedError`, and the OS prompts on first access to a characteristic that requires authentication (https://bleak.readthedocs.io/en/latest/backends/macos.html).
  Whether iTag fobs need authentication is UNVERIFIED (community GATT tables list none).

## 3. Connect, write Alert Level, disconnect (`BleakClient`)

- Pass the **`BLEDevice` from the running scanner**, not the UUID string.
  A string makes `connect()` run an implicit `BleakScanner.discover`, which the docstring warns against (https://bleak.readthedocs.io/en/latest/api/client.html).
  With a `BLEDevice`, the client reuses the scanner's `CBCentralManager`: `device.details` is `(peripheral, manager)` (source-read, `corebluetooth/client.py`).
- Signature: `BleakClient(address_or_ble_device, disconnected_callback=None, services=None, *, timeout=30, pair=False, ...)` (source-read).
  Use something like `timeout=10` for chirps.
  `services=["1802", "1803"]` can limit discovery, which "may or may not reduce" connect time (docstring).
- `async with BleakClient(dev, timeout=10) as client:` connects, discovers services, and disconnects on exit.
  `client.services` holds the collection.
  Iterate `service.characteristics`, and log `uuid`, `handle`, and `properties` for each fob, as section 5.B requires (https://bleak.readthedocs.io/en/latest/usage.html).
- **UUID forms:** strings are normalized, so `"2a06"`, `"2A06"` and `"00002a06-0000-1000-8000-00805f9b34fb"` are equivalent.
  I verified locally that `normalize_uuid_str("2a06")` returns `00002a06-0000-1000-8000-00805f9b34fb`.
  `uuid.UUID` objects, integer handles, and `BleakGATTCharacteristic` objects also work (source-read, `bleak/uuids.py`, `bleak/__init__.py`).
- **Gotcha: there can be two 0x2A06 characteristics.**
  Immediate Alert (0x1802) and Link Loss (0x1803) both use the Alert Level characteristic 0x2A06 (https://www.bluetooth.com/specifications/specs/link-loss-service-1-0/, https://t-shaped.nl/2023/using-cheap-bluetooth-key-finder-fobs-with-esphome-and-home-assistant).
  If both are present, `client.write_gatt_char("2a06", ...)` raises `BleakError("Multiple Characteristics with this UUID ...")` (source-read, https://github.com/hbldh/bleak/blob/develop/bleak/backends/service.py).
  Resolve through the service instead: `client.services.get_service("1802").get_characteristic("2a06")`.
- **Write type:**
  - The IAS 1.0 spec makes **Write Without Response mandatory** for Alert Level and **excludes** Write (Table 3.2, https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/IAS_v1.0/out/en/index-en.html).
  - Cheap fobs deviate: one iTag write-up lists 0x2A06 as "write" (https://github.com/mcauser/micropython-aioble-itag/blob/master/readme.md).
  - bleak deprecates omitting `response`.
    If you omit it, bleak uses write-with-response whenever `"write"` is in the properties (https://bleak.readthedocs.io/en/latest/api/client.html).
  - Pick it explicitly: `response = "write-without-response" not in char.properties`.
    Only `response=True` can surface `BleakGATTProtocolError` (same page).
- `await client.disconnect()` maps to `cancelPeripheralConnection`.
  Apple notes this "doesn't guarantee that the underlying physical link is immediately disconnected" if other apps hold a connection (https://developer.apple.com/documentation/corebluetooth/cbcentralmanager/cancelperipheralconnection(_:)).
- Call `asyncio.run()` once, for the whole hub, and never block the loop (https://bleak.readthedocs.io/en/latest/troubleshooting.html).

```python
IAS, LLS, ALERT = "1802", "1803", "2a06"

async def chirp(device: BLEDevice, level: int, hold_s: float) -> None:
    async with BleakClient(device, timeout=10) as client:
        for s in client.services:  # brief 5.B: log every fob's GATT table
            log.info("svc %s %s", s.uuid, [(c.uuid, c.handle, c.properties) for c in s.characteristics])
        char = client.services.get_service(IAS).get_characteristic(ALERT)
        no_rsp = "write-without-response" in char.properties
        await client.write_gatt_char(char, bytes([level]), response=not no_rsp)
        await asyncio.sleep(hold_s)  # see section 4: a disconnect may end the alert
        await client.write_gatt_char(char, b"\x00", response=not no_rsp)
```

## 4. Cheap iTag-style fob gotchas

- **Typical GATT table** (community sources, not a spec):
  - `1802/2A06`: Alert Level, write.
  - `180F/2A19`: Battery Level, read, as a percentage.
  - `FFE0/FFE1`: button, read and notify.
    Each press notifies `0x01`.
  - Source: https://github.com/mcauser/micropython-aioble-itag/blob/master/readme.md
  - Other units also expose `1803` Link Loss, `1804` Tx Power, and a proprietary `5833FF01-9B8B-5191-6142-22A4536EF123` (https://t-shaped.nl/2023/using-cheap-bluetooth-key-finder-fobs-with-esphome-and-home-assistant).
  - PCB revisions differ (v1.6, v1.8, v5.0) (mcauser readme).
    Keep UUIDs configurable, as the brief says.
- **Values:** write `0x01` to start fast beeping and `0x00` to stop (both sources above).
  IAS defines No Alert, Mild Alert and High Alert (IAS spec), so `0x02` (High) may be louder on some units.
  That is UNVERIFIED.
- **Disconnect ends the IAS alert (spec):** IAS lists "The physical link is disconnected" as a condition that ends an alert (IAS spec link above).
  So "write 0x01, then disconnect immediately" may silence a spec-compliant fob at once.
  What our fobs actually do is UNVERIFIED.
  Phase 0 test: write `0x01`, disconnect, and listen.
  If the beep stops, hold the connection for the chirp duration (the sketch above), then write `0x00` and disconnect.
- **Link-loss beep:** the tag "will slow-beep after a connection has been made and then disconnected", and a button press mutes it (mcauser readme).
  On one fob, writing `0xFF` to Link Loss `1803/2A06` disabled the link-loss alert, and "any other value including 0x00 enables it", which is non-standard (t-shaped.nl).
  Mitigation: before disconnecting, write `0x00` (spec "No Alert") or `0xFF` to the **1803** characteristic, resolved through the service as in section 3.
  Which value works is per-fob and UNVERIFIED.
  Whether a clean central-initiated disconnect triggers the link-loss beep at all, as opposed to a supervision timeout, is also UNVERIFIED.
  The LLS spec has a "Disconnection Behavior" section that I could not read (https://www.bluetooth.com/specifications/specs/link-loss-service-1-0/).
- **Power:** hold the button to power the fob on or off.
  It beeps to confirm (mcauser readme).
  A fob that never shows up is probably just off.
- **Identity:** fobs broadcast a fixed MAC, but macOS hides it.
  LightBlue can reveal it through a dummy service (t-shaped.nl).
  Match on the CoreBluetooth UUID (section 2).
  The advertised name (often "iTAG") is UNVERIFIED, so do not rely on it.
- **RSSI during a chirp:** BLE peripherals usually stop advertising while connected.
  Whether these fobs do is UNVERIFIED.
  If they do, hold the last EMA value during a chirp and do not let the staleness timeout fire.
- **Scanning while connecting:** "whether connections can be active while scanning depends on the Bluetooth adapter hardware" (https://bleak.readthedocs.io/en/latest/api/client.html).
  CoreBluetooth on the M5 is untested (UNVERIFIED).
  Keep the scanner running and connect with the scanner's `BLEDevice`.
  If connects time out while scanning, stop the scanner for the chirp and restart it in a `finally`.
- **Concurrency:** make chirps one at a time per fob with an `asyncio.Lock`, and cancel the auto-stop timer on a new `chirp`.
  Connecting to several devices at once is a known trouble spot, and the docs advise scanning first and passing `BLEDevice`s (https://bleak.readthedocs.io/en/latest/troubleshooting.html).
