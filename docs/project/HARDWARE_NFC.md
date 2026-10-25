# Hardware bring-up

Each path below ends the same way: the hub prints placed/removed events, and the dashboard map at `http://localhost:8765` updates. Bring up **one** reader, fob, or marker first, then scale.

- [Path A: NFC readers on ESP32](#path-a-nfc-readers-on-esp32-pn532-or-rc522)
- [Path A2: ESP-NOW satellites (room-scale NFC)](#path-a2-esp-now-satellites-room-scale-nfc-without-long-wires)
- [Path B: USB NFC readers](#path-b-usb-nfc-readers-pcsc)
- [Path C: iPhone camera + markers](#path-c-iphone-camera--printed-markers)
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

Up to 5 readers share one SPI bus. Each gets its own chip-select (CS) pin. Pins and spot numbers live in [`firmware/earmark_reader/config.h`](../../firmware/earmark_reader/config.h).

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
2. **Watch it** with `cd hub && .venv/bin/earmark serial-monitor`. Expect:
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
6. **Run the hub:** `earmark run --serial auto` (add `--serial auto` once per board).

Each line is a full state report, so a dropped line or an ESP32 reset never causes a false "removed". `SPOT n ERROR` freezes that spot's state until it recovers.

---

## Path A2: ESP-NOW satellites (room-scale NFC without long wires)

Readers scattered around a room can't share an SPI bus; SPI over meters of jumper wire fails. Instead, give each spot (or small cluster of spots) its own ESP32 on a USB power bank. The satellites broadcast over ESP-NOW (no Wi-Fi network needed) to a **gateway** ESP32 plugged into the Mac.

```bash
# each satellite: unique spot numbers
firmware/build.sh flash reader /dev/cu.usbserial-A esp32 -DTRANSPORT_ESPNOW=1 '-DREADERS={{16,2}}' '-DNODE_NAME="bookshelf"'
# the gateway, plugged into the Mac
firmware/build.sh flash gateway /dev/cu.usbserial-B esp32
cd hub && .venv/bin/earmark run --serial auto
```

- Broadcast frames aren't acknowledged, so satellites resend their full state every 300 ms as well as on every change.
- Every board must use the same channel. The default is 1. If the venue's Wi-Fi crowds channel 1, set `-DESPNOW_CHANNEL=6` (or 11) on **all** boards.
- Some power banks switch off below about 50–100 mA. An ESP32 plus a PN532 normally draws more than that. Test your banks for 10 minutes.

---

## Path B: USB NFC readers (PC/SC)

There's no firmware or wiring. Each USB reader is one spot.

**Buy:** ACR1552U-M2 or ACR1252U-A2. The no-SAM versions show up as a single reader.
- ACR122U works, but it is end-of-life, counterfeits are common, and upstream libccid lists it as "unsupported". Buy it only from a seller you can return to.
- Use a **powered** USB hub, plus USB extension cables to place readers around the room. Use active cables beyond 5 m.

```bash
cd hub && .venv/bin/earmark usb-readers     # live view: place/lift tags on each reader
.venv/bin/earmark usb-assign                # tap a tag on spot 1's reader, then spot 2's, ... -> config/usb_readers.json
.venv/bin/earmark run --usb
```

- **macOS driver.** Tahoe's built-in class driver handles these readers, and pyscard 2.3.1 has arm64 wheels for Python 3.9–3.13. If a reader misbehaves:
  ```bash
  sudo defaults write /Library/Preferences/com.apple.security.smartcard useIFDCCID -bool yes
  ```
  then replug the readers. Apple's libccid doesn't list the ACR1552U, so this fallback helps only the ACR122U and ACR1252U.
- **Re-run `usb-assign` after any replug.** macOS names identical readers `Name` and `Name 01`, with no serial number, and the order can swap.
- **Beeps.** The ACR122U's beep on every tag is switched off automatically after its first read. The ACR1252U/1552U beep is configured with escape commands, which are unreliable through macOS drivers. If it bothers you, put tape over the buzzer.
- The source re-lists readers every 2 s, because macOS has no plug-and-play notification. It reads a UID only when a reader's state changes.

---

## Path C: iPhone camera + printed markers

This is the strongest **room-scale** option. The phone on the judge's chest tracks where they walk (ARKit) as well as where objects are (camera). No other path knows the listener's position.

1. **Print markers.**
   ```bash
   cd hub && .venv/bin/earmark markers --cm 15 --out markers.html
   ```
   Open the file, print at **100% / Actual size** on matte paper, and check one code with a ruler. Stick each code flat on its object, facing out. Codes are Micro QR (`EM01`…). Their 13×13 modules stay readable from farther away than a full QR code of the same size. Map marker → object in `hub/config/registry.json` (`"marker": "EM01"`) and in [`apple/EarmarkAR/Resources/markers.json`](../../apple/EarmarkAR/Resources/markers.json) for standalone mode.
   - *Measured on this Mac with Apple Vision* (renders, not camera photos): all codes decode down to about 45 px wide, even with 1 px blur and a 45° tilt, and decoding degrades below about 34 px. A 15 cm code is 45 px at about 5 m on the iPhone's 1920-px camera frame. **Plan on 3–4 m for 15 cm codes** and about 2.5 m for 10 cm.
2. **Install the app.** Open `apple/EarmarkAR/EarmarkAR.xcodeproj` (or run `xcodegen` in that folder first).
   - Under Signing & Capabilities, pick your team. A free Apple ID works, with a 7-day profile.
   - If the bundle ID is taken, change it.
   - Run on an iPhone XS or newer. LiDAR models (Pro) get better depth; other phones estimate distance from the printed code's size.
3. **In the app, Setup tab:**
   1. Stand on the judge's spot facing "forward" and tap **Set origin here**.
   2. Set the phone height and the printed marker size.
   3. Walk around and point the camera at each code until it shows in the list.
   4. *Then* hide the objects. Positions persist while the session runs.
4. **Hub (optional).** Type `ws://<mac-ip>:8765/ws` from the dashboard header. Without a hub the phone guides on its own from what it has seen.
5. **Mount** the phone on the judge's chest, camera facing out, with a phone lanyard pouch with a clear window or a chest harness. Switch to the **Guide** tab. The judge holds anywhere on the screen to talk.

**Combining with NFC.** If you set the origin at the same spot, and face the same way you measured `room.json` from, NFC spot positions and camera positions line up. The phone then renders NFC targets while tracking where the judge walks.

---

## Path D: BLE key-finder fobs (iTag)

Use these for things that wander. Expect **coarse** position plus a **real** beep. Inside the room, RSSI localization is good to about 1–2 m, so the ping gets the judge to the area and the fob's own chirp finishes the job.

1. **Grant Bluetooth permission** to your terminal or VS Code: System Settings › Privacy & Security › Bluetooth. Until you do, bleak **waits forever** for the permission prompt.
2. Close the iSearching app on any phone. A fob accepts one connection at a time, and stops advertising while connected.
3. Wake the fob with a long press if needed. Some switch off after about 15 minutes idle.
4. Scan, pair, and test:
   ```bash
   cd hub
   .venv/bin/earmark ble-scan                     # nearby iTags with RSSI and address
   .venv/bin/earmark ble-pair keys                # hold ONE fob against the Mac; saves it to registry.json
   .venv/bin/earmark ble-chirp <address>          # should beep for 5 s
   .venv/bin/earmark run --ble
   ```
   - Pairing uses the fob's real MAC address through bleak's `use_bdaddr` option, which is undocumented on macOS. That makes the Mac and the ESP32 anchors agree on IDs. If scans come back empty, add `--ble-uuid` everywhere.
   - Chirping writes `0x01` to Immediate Alert (0x1802/0x2A06) in 2 s bursts, and stops on `0x00`.
   - Before beeping it disables the disconnect alarm: Link Loss (0x1803) set to 0, plus vendor characteristic 0xFFE2 on clones that ignore 0x1803.
   - Pressing the fob's button while it chirps counts as "found it".
5. **Anchors (for a position estimate).** These are ESP32s at measured spots, ideally the 4 room corners about 1 m high, listed under `anchors` in `room.json`:
   ```bash
   firmware/build.sh flash ble_anchor /dev/cu.usbserial-C esp32 '-DANCHOR_ID="A1"'
   ```
   Prefer USB to the Mac. Over ESP-NOW (`-DTRANSPORT_ESPNOW=1`), Wi-Fi shares the radio and you'll get fewer RSSI samples. Anchor builds use the `huge_app` partition, because BLE plus Wi-Fi doesn't fit the default 1.2 MB app slot. `build.sh` handles that.
   - *In simulation* (Gaussian noise 4–8 dB), 4 corner anchors gave a 0.6–0.7 m median error and 0.9–1.3 m at the 90th percentile. Real rooms are worse because of multipath, and a person in the line of sight costs about 10 dB, so the estimator reports a conservative ±1.6 m.

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
