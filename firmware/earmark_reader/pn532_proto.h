// PN532 frame encoding/decoding (NXP UM0701-02 section 6.2). Pure C++, no Arduino,
// so the host unit tests in firmware/test compile the exact same code.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace pn532 {

constexpr uint8_t SPI_DATAWRITE = 0x01;
constexpr uint8_t SPI_STATREAD = 0x02;
constexpr uint8_t SPI_DATAREAD = 0x03;
constexpr uint8_t SPI_READY = 0x01;

constexpr uint8_t HOST_TO_PN532 = 0xD4;
constexpr uint8_t PN532_TO_HOST = 0xD5;

constexpr uint8_t CMD_GET_FIRMWARE_VERSION = 0x02;
constexpr uint8_t CMD_SAM_CONFIGURATION = 0x14;
constexpr uint8_t CMD_RF_CONFIGURATION = 0x32;
constexpr uint8_t CMD_IN_LIST_PASSIVE_TARGET = 0x4A;

constexpr uint8_t ACK_FRAME[6] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};

// Normal information frame: 00 00 FF LEN LCS D4 data... DCS 00. Returns bytes written.
inline size_t build_frame(const uint8_t *data, uint8_t n, uint8_t *out) {
  uint8_t len = n + 1;  // TFI + data
  uint8_t sum = HOST_TO_PN532;
  size_t i = 0;
  out[i++] = 0x00;
  out[i++] = 0x00;
  out[i++] = 0xFF;
  out[i++] = len;
  out[i++] = (uint8_t)(~len + 1);
  out[i++] = HOST_TO_PN532;
  for (uint8_t k = 0; k < n; k++) {
    out[i++] = data[k];
    sum += data[k];
  }
  out[i++] = (uint8_t)(~sum + 1);
  out[i++] = 0x00;
  return i;
}

inline bool is_ack(const uint8_t *buf, size_t n) {
  // Tolerate one stray leading byte some modules clock out before the preamble.
  for (size_t off = 0; off + 6 <= n && off <= 1; off++) {
    if (memcmp(buf + off, ACK_FRAME, 6) == 0) return true;
  }
  return false;
}

// Parse a response frame for command `cmd`. On success copies the payload after
// D5 <cmd+1> into `payload` (up to `cap` bytes) and returns its length; -1 on any
// framing, checksum, or error-frame problem.
inline int parse_response(const uint8_t *buf, size_t n, uint8_t cmd, uint8_t *payload, size_t cap) {
  size_t s = 0;
  while (s + 1 < n && s < 4 && !(buf[s] == 0x00 && buf[s + 1] == 0xFF)) s++;
  if (s + 1 >= n || buf[s] != 0x00 || buf[s + 1] != 0xFF) return -1;
  size_t i = s + 2;
  if (i + 2 > n) return -1;
  uint8_t len = buf[i], lcs = buf[i + 1];
  if ((uint8_t)(len + lcs) != 0 || len < 2) return -1;  // len<2 also rejects the 01 FF 7F error frame
  i += 2;
  if (i + len + 1 > n) return -1;  // frame longer than what we read
  if (buf[i] != PN532_TO_HOST || buf[i + 1] != (uint8_t)(cmd + 1)) return -1;
  uint8_t sum = 0;
  for (size_t k = 0; k < len; k++) sum += buf[i + k];
  if ((uint8_t)(sum + buf[i + len]) != 0) return -1;
  size_t plen = len - 2;
  if (plen > cap) plen = cap;
  memcpy(payload, buf + i + 2, plen);
  return (int)plen;
}

// InListPassiveTarget (106 kbps type A) payload: NbTg Tg SENS_RES(2) SEL_RES NFCIDLength NFCID...
// Returns UID length (4, 7, or 10) or 0 if no target.
inline uint8_t uid_from_list_response(const uint8_t *p, int n, uint8_t *uid, uint8_t cap) {
  if (n < 1 || p[0] < 1) return 0;
  if (n < 6) return 0;
  uint8_t ulen = p[5];
  if (ulen == 0 || ulen > cap || 6 + ulen > n) return 0;
  memcpy(uid, p + 6, ulen);
  return ulen;
}

inline void to_hex(const uint8_t *b, uint8_t n, char *out) {
  static const char *H = "0123456789ABCDEF";
  for (uint8_t i = 0; i < n; i++) {
    out[2 * i] = H[b[i] >> 4];
    out[2 * i + 1] = H[b[i] & 0xF];
  }
  out[2 * n] = 0;
}

}  // namespace pn532
