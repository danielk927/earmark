// Broadcast text lines to an earmark_gateway board over ESP-NOW (no Wi-Fi network needed).
#pragma once
#include <WiFi.h>
#include <esp_now.h>

namespace espnow_link {

static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

inline bool begin(uint8_t channel) {
  WiFi.mode(WIFI_STA);
  WiFi.setChannel(channel);
  if (esp_now_init() != ESP_OK) return false;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = channel;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  return esp_now_add_peer(&peer) == ESP_OK;
}

// Broadcast frames carry at most 250 bytes and are never acknowledged, so senders
// repeat their full state periodically rather than relying on delivery.
inline void send(const char *text, size_t len) {
  if (len > 0 && len <= 250) esp_now_send(BROADCAST, reinterpret_cast<const uint8_t *>(text), len);
}

}  // namespace espnow_link
