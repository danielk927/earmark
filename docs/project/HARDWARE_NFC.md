# Hardware bring-up

Each path below ends the same way: the hub (`make hub`, or the whole stack with `make demo-live`) logs placed/removed events, and the dashboard room page (`make dashboard`, then `http://localhost:5173/room`) updates. Port 8765 is the hub's WebSocket bus, not a web page. Hub details are in [`services/hub/README.md`](../../services/hub/README.md). Bring up **one** reader or fob first, then scale.

- [Path A: NFC readers on ESP32](#path-a-nfc-readers-on-esp32-pn532-or-rc522)
- [Path A2: ESP-NOW satellites (room-scale NFC)](#path-a2-esp-now-satellites-room-scale-nfc-without-long-wires)
- [Not in this repo: USB NFC readers and camera markers](#not-in-this-repo-usb-nfc-readers-and-camera-markers)
- [Path D: BLE key-finder fobs](#path-d-ble-key-finder-fobs-itag)
- [AirPods setup (all paths)](#airpods-all-paths)

Install the firmware toolchain once:

```bash
brew install arduino-cli
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index && arduino-cli core install esp32:esp32     # tested: 3.3.12
arduino-cli lib install "Adafruit PN532" "MFRC522"                          # tested: 1.3.4, 1.4.12
firmware/build.sh            # host tests + compiles all 11 variants
```

---

## Path A: NFC readers on ESP32 (PN532 or RC522)

Up to 5 readers share one SPI bus. Each gets its own chip-select (CS) pin. Pins and spot numbers live in [`firmware/earmark_reader/config.h`](../../firmware/earmark_reader/config.h). The spot numbers must match `spots` in `config/space.json`.

### PN532 (red "PN532 NFC RFID Module V3", Elechouse style)

**Set the DIP switches to SPI before powering up: switch 1 OFF, switch 2 ON.** I2C mode gives every PN532 the same address, so several can't share a bus. Power-cycle after changing the switches.

Use the 8-pin header:

| PN532 pin | ESP32 (WROOM-32 DevKit) | ESP32-S3 DevKitC-1 | ESP32-C3 |
|---|---|---|---|
| VCC | **5V / VIN** (see power) | 5V | 5V |
| GND | GND | GND | GND |
| SCK | GPIO 18 | GPIO 12 | GPIO 4 |
| MISO | GPIO 19 | GPIO 13 | GPIO 5 |
| MOSI | GPIO 23 | GPIO 11 | GPIO 6 |
| SS (NSS) | reader 1..5: **16, 17, 25, 26, 27** | 4, 5, 6, 7, 15 | 0, 1, 3, 7, 10 |
| IRQ, RSTO | not connected | | |

**Power.**
- Each PN532 draws 91–140 mA with its RF field on. Five of them on the dev board's 3.3 V regulator (AMS1117) will brown it out.
- The Elechouse board takes 3.3–5 V on VCC and keeps its SPI pins at 3.3 V, so powering it from 5V/VIN is safe for the ESP32.
- The firmware also switches each reader's RF field off after polling it, so only one field is live at a time.
- If you have a different PN532 board, check its logic levels first. If unsure, power it from 3V3 and keep it to 2 readers per board.

**Avoid these pins on the classic ESP32:**
- Strapping pins 0, 2, 5, 12, 15
- Flash pins 6–11
- Input-only pins 34–39
- 16 and 17 on WROVER modules (PSRAM)

**Driver.** By default the firmware uses its own PN532 driver ([`pn532_spi.h`](../../firmware/earmark_reader/pn532_spi.h)). The Adafruit library reads only 20 bytes of the tag-list reply, which cuts off 7-byte NTAG UID frames. That is the likely cause of Adafruit-PN532 issue #52, where reads alternate found / not found. To compare against the library, build with `-DPN532_USE_ADAFRUIT=1`.

### RC522 (blue MFRC522 boards): **3.3 V only**

| RC522 pin | ESP32 |
|---|---|
| 3.3V | 3V3 (never 5 V) |
| RST | tie to 3V3 |
| GND | GND |
| MISO / MOSI / SCK | 19 / 23 / 18 |
| SDA (= chip select) | 16, 17, 25, 26, 27 |

Build with `-DREADER_TYPE=2`.

- **Many RC522 boards don't release MISO** when they aren't selected, so a second reader on the same bus corrupts the first. If `READER n FAIL` appears as soon as you add a second reader, either:
  - use **one RC522 per ESP32** ([ESP-NOW satellites](#path-a2-esp-now-satellites-room-scale-nfc-without-long-wires)), or
  - gate each reader's MISO with a 74HC125 driven by its CS.
- RC522 range with NTAG213 stickers is only about **2 cm**. The firmware sets maximum antenna gain. Mount readers directly under a thin surface.
- Presence detection uses the reliable method: field on, WUPA, select, halt, field off. The usual `PICC_IsNewCardPresent()` flickers for a tag that stays on the reader.

### Bring-up checklist (do it with ONE reader first)

1. **Wire one reader** on CS 16, then flash it as spot 1:
   ```bash
   firmware/build.sh flash reader /dev/cu.usbserial-0001 esp32 '-DREADERS={{16,1}}'
   ```
   Find the port with `ls /dev/cu.*`. If nothing appears, the cable is charge-only.
2. **Watch it** with `screen /dev/cu.usbserial-0001 115200` (quit with Ctrl-A then K). Close it before starting the hub, because only one program can hold the port. Expect:
   ```
   HELLO earmark-reader v1 node=reader chip=PN532 readers=1 espnow=0
   READER 1 OK cs=16 fw=1.6
   SPOT 1 EMPTY
   SPOT 1 TAG 04A2B3C4D5E6F7      <- when a sticker is on it
   ```
3. **If you get `READER 1 FAIL`**, check in this order:
   1. DIP switches (SPI = 1 OFF, 2 ON), then power-cycle.
   2. The MISO and MOSI wires aren't swapped.
   3. VCC is getting 5 V.
   4. Flash with `-DPN532_USE_ADAFRUIT=1` to rule out the driver.
4. **Add readers one at a time.** Put the full CS list back in `config.h` (`READERS`).
   - **MISO check for a shared bus:** put two 100 kΩ resistors from MISO, one to 3V3 and one to GND. With every reader deselected, MISO should sit near 1.65 V. A reading of 0 V or 3.3 V means some board is driving the line and needs a 74HC125 buffer.
5. **Range test** through your actual tabletop or tablecloth with the real stickers. Use on-metal stickers for cans and metal lids.
6. **Run the hub:** `make demo-live` (or `make hub` with `nfc_serial` in `adapters` in `config/hub.json`). The `nfc_serial` adapter finds the board by itself (`/dev/cu.usbserial*`, `/dev/cu.usbmodem*`, and so on, or set `NFC_SERIAL_PORT`) and reopens it if it is unplugged. Raw lines are kept in `logs/serial.log`.
7. **Name the tag.** An unregistered tag shows up as an `unknown_tag`. Label it with `uv run --project services/hub earmark-send label --tag <uid> --name honey --spot 1`, or set `tag` for the object in `config/objects.seed.json`.

The hub reads only lines of the form `SPOT n TAG <uid>`, `SPOT n EMPTY` and `SPOT n ERROR <reason>`; everything else (`HELLO`, `READER`, `#` lines) is ignored. Each line is a full state report, so a dropped line or an ESP32 reset never causes a false "removed". `SPOT n ERROR` is shown as a hub status and the spot is left as it was until it recovers.

---

## Path A2: ESP-NOW satellites (room-scale NFC without long wires)

Readers scattered around a room can't share an SPI bus; SPI over meters of jumper wire fails. Instead, give each spot (or small cluster of spots) its own ESP32 on a USB power bank. The satellites broadcast over ESP-NOW (no Wi-Fi network needed) to a **gateway** ESP32 plugged into the Mac.

```bash
# each satellite: unique spot numbers
firmware/build.sh flash reader /dev/cu.usbserial-A esp32 -DTRANSPORT_ESPNOW=1 '-DREADERS={{16,2}}' '-DNODE_NAME="bookshelf"'
# the gateway, plugged into the Mac
firmware/build.sh flash gateway /dev/cu.usbserial-B esp32
make demo-live        # the gateway prints the same SPOT lines on its USB serial
```

- Broadcast frames aren't acknowledged, so satellites resend their full state every 300 ms as well as on every change.
- Every board must use the same channel. The default is 1. If the venue's Wi-Fi crowds channel 1, set `-DESPNOW_CHANNEL=6` (or 11) on **all** boards.
- Some power banks switch off below about 50–100 mA. An ESP32 plus a PN532 normally draws more than that. Test your banks for 10 minutes.

---

## Not in this repo: USB NFC readers and camera markers

The hub has no USB (PC/SC) NFC reader support and no camera or marker adapter (`camera_stub` is only an interface). NFC spots come from the ESP32 firmware above. The listener's position comes from the phone beacons: see [`ROOM_SETUP.md`](ROOM_SETUP.md) and `make ranging`.

---

## Path D: BLE key-finder fobs (iTag)

Use these for things that wander. Expect **coarse** position plus a **real** beep. Inside the room, RSSI localization is good to about 1–2 m, so the ping gets the judge to the area and the fob's own chirp finishes the job.

1. **Grant Bluetooth permission** to your terminal or VS Code: System Settings › Privacy & Security › Bluetooth. Until you do, bleak **waits forever** for the permission prompt.
2. Close the iSearching app on any phone. A fob accepts one connection at a time, and stops advertising while connected.
3. Wake the fob with a long press if needed. Some switch off after about 15 minutes idle.
4. **Find the fob and name it.** The hub scans from the Mac's own Bluetooth. Start it with `make demo-live` and turn the fob on. It is matched by CoreBluetooth address or by advertised name, both set under `ble_fobs.fobs` in `config/hub.json`:
   ```json
   "fobs": { "fob_keys": { "address": null, "name": "<advertised name>" } }
   ```
   A fob matched by name is bound to its address for the session, and the hub logs `fob bound by name; pin its address in config/hub.json`. Copy that address into the config. The fob id (`fob_keys`) must be the `fob_id` of an object in `config/objects.seed.json`. On macOS the address is a CoreBluetooth UUID, not the fob's MAC.
5. **Test the beep.** With the hub running: `uv run --project services/hub earmark-send chirp --fob_id fob_keys --action start`, and `--action stop` to end it.
   - The hub connects to the fob and writes the Immediate Alert level (service 0x1802, characteristic 0x2A06, level `alert_level`, default 1). The beep lasts until `stop` or `chirp_timeout_s` (10 s), then the hub writes `0x00` and disconnects. It does not send bursts.
   - If the fob sounds its disconnect alarm afterwards, set `link_loss_value` (for example 0) in `config/hub.json`. The hub then also writes it to Link Loss (0x1803/0x2A06) after the beep.
   - The hub does not read the fob's button.
6. **Distance.** The hub smooths the fob's signal strength and calls it `near`, `mid` or `far` (`near_dbm`, `mid_dbm` in `config/hub.json`). It reports `lost` after `stale_s` (10 s) of silence. This is coarse (about 1 to 2 m inside a room), so the beep does the final step.

**BLE anchors (experimental).** [`firmware/earmark_ble_anchor`](../../firmware/earmark_ble_anchor/) can be flashed onto ESP32s and prints a `BLE <anchor-id> <mac> <rssi> <name>` line for every fob advertisement:
```bash
firmware/build.sh flash ble_anchor /dev/cu.usbserial-C esp32 '-DANCHOR_ID="A1"'
```
The hub does not read these lines, and nothing in this repo turns them into a position estimate. They are only useful for looking at signal strengths yourself. Anchor builds use the `huge_app` partition because BLE plus Wi-Fi doesn't fit the default app slot; `build.sh` handles that.

---

## AirPods (all paths)

- **Models.** Head tracking needs AirPods Pro, Max, 3rd gen, or 4. Other models still play the spatial ping, but it won't follow head turns.
- **Turn system Spatial Audio OFF for the Earmark app.**
  - iPhone: Control Center, long-press the volume slider, then Spatial Audio → Off.
  - Mac: AirPods menu-bar icon, then Spatial Audio → Off.
  - Earmark renders its own binaural audio. When system Spatial Audio is on, macOS also recenters head-tracking yaw whenever audio starts.
- **Use Transparency mode** so the judge can hear real fob chirps.
- **Never use the AirPods microphone.** Recording from it switches AirPods to the headset profile (mono, narrowband), which flattens the 3D ping. The apps record from the built-in mic. On iOS that comes from an audio session that allows A2DP but not HFP.
- **Recenter** with the judge facing forward: the R key on the Mac, or "Align AirPods to phone" on the iPhone. Head tracking drifts, so recenter for every judge.
