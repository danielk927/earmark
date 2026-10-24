// Earmark reader board configuration. Edit this file (or pass -D flags) per board.
#pragma once

// ---- Which reader chip ------------------------------------------------------
#define READER_PN532 1  // red "PN532 NFC RFID Module V3" (Elechouse style). DIP: SW1 OFF, SW2 ON = SPI
#define READER_RC522 2  // blue MFRC522 boards. 3.3 V only.
#ifndef READER_TYPE
#define READER_TYPE READER_PN532
#endif

// PN532 driver: our own full-frame driver (default) or the Adafruit library.
// The Adafruit library reads only 20 bytes of the InListPassiveTarget reply, which
// truncates 7-byte NTAG UID frames and makes reads alternate (Adafruit-PN532 issue #52).
#ifndef PN532_USE_ADAFRUIT
#define PN532_USE_ADAFRUIT 0
#endif

// ---- Readers on this board --------------------------------------------------
// One entry per reader: { chip-select GPIO, spot number }. Spot numbers are global
// across all boards and must match "spots" in hub/config/room.json.
//
// Safe CS pins (avoid strapping/flash pins):
//   ESP32 (WROOM-32): 16, 17, 25, 26, 27  (alternates 4, 13, 21, 22, 32, 33)
//   ESP32-S3 DevKitC-1: 4, 5, 6, 7, 15
//   ESP32-C3: 0, 1, 3, 7, 10
#ifndef READERS
#if defined(CONFIG_IDF_TARGET_ESP32S3)
#define READERS {{4, 1}, {5, 2}, {6, 3}, {7, 4}, {15, 5}}
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
#define READERS {{0, 1}, {1, 2}, {3, 3}, {7, 4}, {10, 5}}
#else
#define READERS {{16, 1}, {17, 2}, {25, 3}, {26, 4}, {27, 5}}
#endif
#endif

// SPI bus pins (shared by every reader). Defaults are each chip's standard SPI pins:
//   ESP32: SCK 18, MISO 19, MOSI 23.  ESP32-S3: SCK 12, MISO 13, MOSI 11.  ESP32-C3: SCK 4, MISO 5, MOSI 6.
#ifndef PIN_SCK
#define PIN_SCK SCK
#endif
#ifndef PIN_MISO
#define PIN_MISO MISO
#endif
#ifndef PIN_MOSI
#define PIN_MOSI MOSI
#endif

// RC522 reset pin, shared by all RC522s. UNUSED = tie RST to 3.3 V and use soft reset.
#ifndef RC522_RST_PIN
#define RC522_RST_PIN 255
#endif

// ---- How lines reach the Mac ------------------------------------------------
// 0 = USB serial only (board plugged into the Mac).
// 1 = also broadcast over ESP-NOW to an earmark_gateway board plugged into the Mac.
//     Use this for satellite boards scattered around a room on USB power banks.
#ifndef TRANSPORT_ESPNOW
#define TRANSPORT_ESPNOW 0
#endif
#ifndef ESPNOW_CHANNEL
#define ESPNOW_CHANNEL 1  // every board, satellites and gateway, must use the same channel
#endif

#ifndef NODE_NAME
#define NODE_NAME "reader"
#endif

#ifndef SERIAL_BAUD
#define SERIAL_BAUD 115200
#endif

// Re-send the full state over ESP-NOW at least this often (broadcast has no ACKs).
#ifndef ESPNOW_REFRESH_MS
#define ESPNOW_REFRESH_MS 300
#endif
