// Minimal PN532 driver over SPI: just what presence polling needs.
//
// Why not Adafruit_PN532: it reads a fixed 20 bytes of the InListPassiveTarget
// reply, which cuts off the checksum of a 7-byte-UID frame (NTAG stickers), and it
// has no RF-field-off call. This driver reads whole frames, turns the field off
// after every poll (one field live at a time: less current, no crosstalk, and the
// tag power-cycles back to IDLE so the next poll finds it again), and aborts a
// stuck command with an ACK frame. Bus settings match Adafruit's: 1 MHz, LSB first, mode 0.
#pragma once
#include <Arduino.h>
#include <SPI.h>

#include "pn532_proto.h"

class Pn532Spi {
 public:
  Pn532Spi(uint8_t cs, SPIClass &spi = SPI) : cs_(cs), spi_(spi) {}

  // Returns firmware word (IC<<24 | Ver<<16 | Rev<<8 | Support) or 0 if the chip didn't answer.
  uint32_t begin() {
    pinMode(cs_, OUTPUT);
    digitalWrite(cs_, LOW);  // falling edge on NSS wakes the PN532 from power-down
    delay(2);
    uint8_t sam[] = {pn532::CMD_SAM_CONFIGURATION, 0x01, 0x14, 0x01};  // normal mode, 1 s timeout, IRQ on
    uint8_t resp[8];
    command(sam, sizeof sam, resp, sizeof resp, 100);  // first command after wake can be lost
    if (command(sam, sizeof sam, resp, sizeof resp, 100) < 0) return 0;
    uint32_t fw = firmware();
    if (!fw) return 0;
    // MxRtyATR=0xFF, MxRtyPSL=0x01, MxRtyPassiveActivation=0x01: give up after two tries
    // (~10 ms) instead of retrying forever, and the PN532 then switches its field off itself.
    uint8_t retries[] = {pn532::CMD_RF_CONFIGURATION, 0x05, 0xFF, 0x01, 0x01};
    if (command(retries, sizeof retries, resp, sizeof resp, 100) < 0) return 0;
    rfField(false);
    return fw;
  }

  uint32_t firmware() {
    uint8_t cmd[] = {pn532::CMD_GET_FIRMWARE_VERSION};
    uint8_t p[4];
    if (command(cmd, 1, p, sizeof p, 100) != 4 || p[0] != 0x32) return 0;
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
  }

  bool rfField(bool on) {
    uint8_t cmd[] = {pn532::CMD_RF_CONFIGURATION, 0x01, (uint8_t)(on ? 0x01 : 0x00)};
    uint8_t resp[4];
    return command(cmd, sizeof cmd, resp, sizeof resp, 50) >= 0;
  }

  // 1 = tag present (uid/len filled), 0 = no tag, -1 = the PN532 didn't respond.
  int poll(uint8_t *uid, uint8_t *len) {
    uint8_t cmd[] = {pn532::CMD_IN_LIST_PASSIVE_TARGET, 0x01, 0x00};  // 1 target, 106 kbps type A
    uint8_t p[40];
    int n = command(cmd, sizeof cmd, p, sizeof p, 150);
    rfField(false);
    if (n < 0) return -1;
    *len = pn532::uid_from_list_response(p, n, uid, 10);
    return *len ? 1 : 0;
  }

 private:
  uint8_t cs_;
  SPIClass &spi_;

  void begin_tx() {
    spi_.beginTransaction(SPISettings(1000000, SPI_LSBFIRST, SPI_MODE0));
    digitalWrite(cs_, LOW);
  }
  void end_tx() {
    digitalWrite(cs_, HIGH);
    spi_.endTransaction();
  }

  void write_frame(const uint8_t *frame, size_t n) {
    begin_tx();
    spi_.transfer(pn532::SPI_DATAWRITE);
    for (size_t i = 0; i < n; i++) spi_.transfer(frame[i]);
    end_tx();
  }

  void read(uint8_t *buf, size_t n) {
    begin_tx();
    spi_.transfer(pn532::SPI_DATAREAD);
    for (size_t i = 0; i < n; i++) buf[i] = spi_.transfer(0x00);
    end_tx();
  }

  bool ready() {
    begin_tx();
    spi_.transfer(pn532::SPI_STATREAD);
    uint8_t s = spi_.transfer(0x00);
    end_tx();
    return s & pn532::SPI_READY;
  }

  bool wait_ready(uint16_t timeout_ms) {
    uint32_t start = millis();
    while (!ready()) {
      if (millis() - start > timeout_ms) return false;
      delay(1);
    }
    return true;
  }

  // Send a command and read its full response. Returns payload length or -1.
  int command(const uint8_t *cmd, uint8_t n, uint8_t *payload, size_t cap, uint16_t timeout_ms) {
    uint8_t frame[32];
    size_t flen = pn532::build_frame(cmd, n, frame);
    write_frame(frame, flen);
    delay(1);  // PN532 needs a moment before the first status read (Adafruit-PN532 #134)
    if (!wait_ready(timeout_ms)) return -1;
    uint8_t ack[6];  // read exactly the ACK frame, as Adafruit does
    read(ack, sizeof ack);
    if (!pn532::is_ack(ack, sizeof ack)) return -1;
    if (!wait_ready(timeout_ms)) {
      write_frame(pn532::ACK_FRAME, sizeof pn532::ACK_FRAME);  // host ACK aborts the running command
      return -1;
    }
    uint8_t buf[48];  // whole frame in one transaction; 7-byte UID reply is 22 bytes
    read(buf, sizeof buf);
    return pn532::parse_response(buf, sizeof buf, cmd[0], payload, cap);
  }
};
