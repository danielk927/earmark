// Earmark ESP-NOW gateway: plug into the Mac. Prints every line that satellite reader
// boards and BLE anchors broadcast, exactly as if they were wired to USB.
#include <WiFi.h>
#include <esp_now.h>

#ifndef ESPNOW_CHANNEL
#define ESPNOW_CHANNEL 1  // must match the satellites
#endif

struct Packet {
  uint8_t mac[6];
  uint8_t len;
  char data[250];
};

static QueueHandle_t queue;

// Runs on the Wi-Fi task: copy and hand off, never print here.
static void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  Packet p;
  memcpy(p.mac, info->src_addr, 6);
  p.len = len > 250 ? 250 : len;
  memcpy(p.data, data, p.len);
  xQueueSend(queue, &p, 0);  // drop if full; senders repeat their state anyway
}

void setup() {
  Serial.begin(115200);
  delay(200);
  queue = xQueueCreate(32, sizeof(Packet));
  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);
  bool up = esp_now_init() == ESP_OK && esp_now_register_recv_cb(onRecv) == ESP_OK;
  Serial.printf("HELLO earmark-gateway v1 channel=%d mac=%s espnow=%s\n", ESPNOW_CHANNEL, WiFi.macAddress().c_str(),
                up ? "up" : "FAILED");
}

void loop() {
  static uint8_t known[16][6];
  static int nknown = 0;
  static uint32_t lastBeat = 0;
  Packet p;
  while (xQueueReceive(queue, &p, pdMS_TO_TICKS(50)) == pdTRUE) {
    bool seen = false;
    for (int i = 0; i < nknown; i++) seen |= memcmp(known[i], p.mac, 6) == 0;
    if (!seen && nknown < 16) {
      memcpy(known[nknown++], p.mac, 6);
      Serial.printf("# node %02X:%02X:%02X:%02X:%02X:%02X online\n", p.mac[0], p.mac[1], p.mac[2], p.mac[3], p.mac[4],
                    p.mac[5]);
    }
    Serial.write(reinterpret_cast<const uint8_t *>(p.data), p.len);
    if (p.len && p.data[p.len - 1] != '\n') Serial.write('\n');
  }
  if (millis() - lastBeat > 10000) {
    lastBeat = millis();
    Serial.printf("# gateway alive, %d nodes\n", nknown);
  }
}
