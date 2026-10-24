// Earmark BLE anchor: an ESP32 at a measured spot in the room that reports every iTag
// advertisement it hears:  BLE <anchor-id> <mac> <rssi> <name>
// The hub fits fob positions from several anchors (hub/earmark/ble_locate.py).
// Put anchor positions in hub/config/room.json under "anchors".
#include <BLEDevice.h>
#include <BLEScan.h>

#ifndef ANCHOR_ID
#define ANCHOR_ID "A1"
#endif
// 1 = only iTag-looking devices (name starts with "itag", or advertises service FFE0).
#ifndef ITAG_ONLY
#define ITAG_ONLY 1
#endif
// 1 = also broadcast over ESP-NOW to the gateway. Wi-Fi shares the 2.4 GHz radio with BLE,
// so expect fewer RSSI samples; prefer USB serial when a cable can reach.
#ifndef TRANSPORT_ESPNOW
#define TRANSPORT_ESPNOW 0
#endif
#ifndef ESPNOW_CHANNEL
#define ESPNOW_CHANNEL 1
#endif

#if TRANSPORT_ESPNOW
#include "espnow_link.h"  // copy of earmark_reader/espnow_link.h (build.sh checks they match)
#endif

static BLEScan *scan;
static const BLEUUID ITAG_SERVICE((uint16_t)0xFFE0);

class Reporter : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    String name = d.haveName() ? d.getName() : String("");
    String lower = name;
    lower.toLowerCase();
    bool itag = lower.startsWith("itag") || (d.haveServiceUUID() && d.isAdvertisingService(ITAG_SERVICE));
    if (ITAG_ONLY && !itag) return;
    name.replace(' ', '_');
    char line[96];
    int n = snprintf(line, sizeof line, "BLE %s %s %d %s\n", ANCHOR_ID, d.getAddress().toString().c_str(), d.getRSSI(),
                     name.length() ? name.c_str() : "-");
    Serial.write(reinterpret_cast<const uint8_t *>(line), n);
#if TRANSPORT_ESPNOW
    espnow_link::send(line, n);
#endif
  }
};

static void restart(BLEScanResults) { scan->start(0, restart, false); }

void setup() {
  Serial.begin(115200);
  delay(200);
#if TRANSPORT_ESPNOW
  espnow_link::begin(ESPNOW_CHANNEL);
#endif
  BLEDevice::init("");
  scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new Reporter(), /*wantDuplicates=*/true);
  scan->setActiveScan(false);  // passive: report on the advertisement itself, no scan-response wait
  scan->setInterval(100);
  scan->setWindow(100);  // listen 100% of the time
  scan->start(0, restart, false);
  Serial.printf("HELLO earmark-ble-anchor v1 id=%s itag_only=%d\n", ANCHOR_ID, ITAG_ONLY);
}

void loop() {
  static uint32_t lastBeat = 0;
  if (millis() - lastBeat > 10000) {
    lastBeat = millis();
    Serial.printf("# anchor %s alive\n", ANCHOR_ID);
  }
  delay(20);
}
