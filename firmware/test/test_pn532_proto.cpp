// Host-side tests for the PN532 frame code the reader firmware runs.
// Build and run: firmware/build.sh test   (or: c++ -std=c++17 -I../earmark_reader test_pn532_proto.cpp)
#include <cstdio>
#include <cstring>
#include <vector>

#include "pn532_proto.h"

static int failures = 0;
#define CHECK(cond)                                                \
  do {                                                             \
    if (!(cond)) {                                                 \
      std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); \
      failures++;                                                  \
    }                                                              \
  } while (0)

using Bytes = std::vector<uint8_t>;

static Bytes frame(const Bytes &data) {
  uint8_t out[64];
  size_t n = pn532::build_frame(data.data(), (uint8_t)data.size(), out);
  return Bytes(out, out + n);
}

// Independent reference for a PN532->host frame (D5 ...), written out longhand.
static Bytes reply(const Bytes &body) {
  Bytes f = {0x00, 0x00, 0xFF};
  uint8_t len = (uint8_t)(body.size() + 1);
  f.push_back(len);
  f.push_back((uint8_t)(0x100 - len));
  f.push_back(0xD5);
  unsigned sum = 0xD5;
  for (uint8_t b : body) {
    f.push_back(b);
    sum += b;
  }
  f.push_back((uint8_t)(0x100 - (sum & 0xFF)));
  f.push_back(0x00);
  while (f.size() < 48) f.push_back(0x00);  // the driver over-reads into a 48-byte buffer
  return f;
}

int main() {
  // Known-good frames from the NXP user manual / every PN532 trace.
  CHECK(frame({0x02}) == (Bytes{0x00, 0x00, 0xFF, 0x02, 0xFE, 0xD4, 0x02, 0x2A, 0x00}));
  CHECK(frame({0x14, 0x01, 0x14, 0x01}) == (Bytes{0x00, 0x00, 0xFF, 0x05, 0xFB, 0xD4, 0x14, 0x01, 0x14, 0x01, 0x02, 0x00}));
  CHECK(frame({0x4A, 0x01, 0x00}) == (Bytes{0x00, 0x00, 0xFF, 0x04, 0xFC, 0xD4, 0x4A, 0x01, 0x00, 0xE1, 0x00}));
  CHECK(frame({0x32, 0x01, 0x00}) == (Bytes{0x00, 0x00, 0xFF, 0x04, 0xFC, 0xD4, 0x32, 0x01, 0x00, 0xF9, 0x00}));

  // ACK detection, including one stray leading byte.
  uint8_t ack[] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
  uint8_t ack_shifted[] = {0x01, 0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
  uint8_t nack[] = {0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
  CHECK(pn532::is_ack(ack, 6));
  CHECK(pn532::is_ack(ack_shifted, 7));
  CHECK(!pn532::is_ack(nack, 6));

  uint8_t p[40];

  // GetFirmwareVersion reply from a real PN532 v1.6: 00 00 FF 06 FA D5 03 32 01 06 07 E8 00
  Bytes fw = {0x00, 0x00, 0xFF, 0x06, 0xFA, 0xD5, 0x03, 0x32, 0x01, 0x06, 0x07, 0xE8, 0x00};
  CHECK(pn532::parse_response(fw.data(), fw.size(), 0x02, p, sizeof p) == 4);
  CHECK(p[0] == 0x32 && p[1] == 0x01 && p[2] == 0x06 && p[3] == 0x07);
  CHECK(reply({0x03, 0x32, 0x01, 0x06, 0x07}) == (fw.resize(48), fw));

  // InListPassiveTarget with an NTAG213: ATQA 00 44, SAK 00, 7-byte UID. This is the
  // 22-byte frame Adafruit's 20-byte read truncates.
  Bytes ntag = reply({0x4B, 0x01, 0x01, 0x00, 0x44, 0x00, 0x07, 0x04, 0xA2, 0xB3, 0xC4, 0xD5, 0xE6, 0xF7});
  int n = pn532::parse_response(ntag.data(), ntag.size(), 0x4A, p, sizeof p);
  CHECK(n == 13);
  uint8_t uid[10];
  uint8_t ulen = pn532::uid_from_list_response(p, n, uid, sizeof uid);
  CHECK(ulen == 7);
  char hex[21];
  pn532::to_hex(uid, ulen, hex);
  CHECK(std::strcmp(hex, "04A2B3C4D5E6F7") == 0);

  // MIFARE Classic, 4-byte UID.
  Bytes classic = reply({0x4B, 0x01, 0x01, 0x00, 0x04, 0x08, 0x04, 0xDE, 0xAD, 0xBE, 0xEF});
  n = pn532::parse_response(classic.data(), classic.size(), 0x4A, p, sizeof p);
  CHECK(pn532::uid_from_list_response(p, n, uid, sizeof uid) == 4 && uid[0] == 0xDE);

  // No tag: NbTg = 0.
  Bytes none = reply({0x4B, 0x00});
  n = pn532::parse_response(none.data(), none.size(), 0x4A, p, sizeof p);
  CHECK(n == 1 && pn532::uid_from_list_response(p, n, uid, sizeof uid) == 0);

  // A stray leading byte before the preamble still parses.
  Bytes shifted = ntag;
  shifted.insert(shifted.begin(), 0x01);
  CHECK(pn532::parse_response(shifted.data(), shifted.size(), 0x4A, p, sizeof p) == 13);

  // Corruption is rejected: bad data checksum, bad length checksum, wrong command, error frame.
  Bytes bad = ntag;
  bad[10] ^= 0x01;
  CHECK(pn532::parse_response(bad.data(), bad.size(), 0x4A, p, sizeof p) == -1);
  bad = ntag;
  bad[4] ^= 0x01;
  CHECK(pn532::parse_response(bad.data(), bad.size(), 0x4A, p, sizeof p) == -1);
  CHECK(pn532::parse_response(ntag.data(), ntag.size(), 0x02, p, sizeof p) == -1);
  Bytes err = {0x00, 0x00, 0xFF, 0x01, 0xFF, 0x7F, 0x81, 0x00};
  CHECK(pn532::parse_response(err.data(), err.size(), 0x4A, p, sizeof p) == -1);
  CHECK(pn532::parse_response(ack, sizeof ack, 0x4A, p, sizeof p) == -1);  // an ACK is not a reply

  // Truncated read (frame longer than buffer) is rejected rather than misparsed.
  CHECK(pn532::parse_response(ntag.data(), 20, 0x4A, p, sizeof p) == -1);

  // Payload is clipped to the caller's buffer.
  uint8_t small[3];
  CHECK(pn532::parse_response(ntag.data(), ntag.size(), 0x4A, small, sizeof small) == 3);

  if (failures == 0) std::printf("pn532_proto: all tests passed\n");
  return failures ? 1 : 0;
}
