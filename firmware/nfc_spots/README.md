# nfc_spots firmware (ESP32 + RC522)

One ESP32 polls up to six RC522 readers on a shared SPI bus and prints one line per reader per poll for the hub's `nfc_serial` adapter:

```
SPOT <n> TAG <UID_HEX>
SPOT <n> EMPTY
SPOT <n> ERROR <reason>
```

## Status

- Written against the `MFRC522` library 1.4.12 API (verified from its header, see `docs/vendor-notes/rc522.md`).
- **Not compiled or flashed yet.** The ESP32 board core (over 1 GB) was not downloaded because the demo Mac is on a phone hotspot.
  Compile it on good Wi-Fi first (commands below).

## Wiring

| RC522 pin | ESP32 pin |
|---|---|
| SDA (SS) | reader 1-6: GPIO 13, 21, 22, 25, 26, 32 (spots 1-6) |
| SCK | GPIO 18 |
| MOSI | GPIO 23 |
| MISO | GPIO 19 |
| RST | GPIO 27 (shared by all readers) |
| 3.3V | 3V3 (never 5 V) |
| GND | GND |
| IRQ | not connected |

The chip-select pins avoid the ESP32 strapping pins (0, 2, 5, 12, 15), the flash pins (6-11), the input-only pins (34-39), and 16/17 (PSRAM on WROVER modules).
Spot numbers per reader are in `SPOT_IDS` and must match `config/space.json`.
Keep readers at least a few centimeters apart or shield them; the RC522 range is only a few centimeters, so a jar must sit right on its reader.

## Build and flash

```sh
brew install arduino-cli
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index && arduino-cli core install esp32:esp32
arduino-cli lib install MFRC522
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/nfc_spots
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/cu.usbserial-XXXX firmware/nfc_spots
arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=115200   # expect SPOT lines
```

## Binding real tags

The seed's tag UIDs are placeholders.
Put each tagged item on its home spot, watch `make tail` (unknown tags show as `unknown_tag` with the spot), and set each object's tag in the dashboard's Items page (or in `config/objects.seed.json`, then `make reset`).
