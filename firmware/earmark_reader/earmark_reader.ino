// Earmark reader board: polls NFC readers on one shared SPI bus and prints, every cycle,
//   SPOT <spot> TAG <uid-hex> | SPOT <spot> EMPTY | SPOT <spot> ERROR
// No application logic lives here; the Mac debounces and decides. See config.h.
#include <SPI.h>

#include "config.h"
#include "pn532_proto.h"

#if TRANSPORT_ESPNOW
#include "espnow_link.h"
#endif

struct Slot {
  uint8_t cs;
  uint8_t spot;
};
static const Slot SLOTS[] = READERS;
static const int N = sizeof(SLOTS) / sizeof(SLOTS[0]);

static bool ok[N];
static uint8_t fails[N];
static uint32_t lastInit[N];
static char lastLine[N][40];

// ---------------------------------------------------------------------------
// Reader drivers. Each provides: const char *CHIP; bool initReader(i, info);
// int pollReader(i, uid, len) -> 1 tag, 0 none, -1 reader not answering.
// ---------------------------------------------------------------------------
#if READER_TYPE == READER_PN532 && !PN532_USE_ADAFRUIT
#include "pn532_spi.h"
static const char *CHIP = "PN532";
static Pn532Spi *readers[N];

static bool initReader(int i, char *info, size_t cap) {
  if (!readers[i]) readers[i] = new Pn532Spi(SLOTS[i].cs, SPI);
  uint32_t fw = readers[i]->begin();
  snprintf(info, cap, "fw=%u.%u", (unsigned)(fw >> 16 & 0xFF), (unsigned)(fw >> 8 & 0xFF));
  return fw != 0;
}
static int pollReader(int i, uint8_t *uid, uint8_t *len) { return readers[i]->poll(uid, len); }

#elif READER_TYPE == READER_PN532
#include <Adafruit_PN532.h>
static const char *CHIP = "PN532-adafruit";
static Adafruit_PN532 *readers[N];
static uint16_t polls[N];

static bool initReader(int i, char *info, size_t cap) {
  if (!readers[i]) readers[i] = new Adafruit_PN532(SLOTS[i].cs, &SPI);
  readers[i]->begin();
  uint32_t fw = readers[i]->getFirmwareVersion();
  snprintf(info, cap, "fw=%u.%u", (unsigned)(fw >> 16 & 0xFF), (unsigned)(fw >> 8 & 0xFF));
  if (!fw) return false;
  readers[i]->setPassiveActivationRetries(0x01);  // 0xFF (default) retries forever
  return true;
}
static int pollReader(int i, uint8_t *uid, uint8_t *len) {
  // The library can't tell "no tag" from "no reader", so check the chip now and then.
  if (++polls[i] % 20 == 0 && !readers[i]->getFirmwareVersion()) return -1;
  return readers[i]->readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, len, 50) ? 1 : 0;
}

#elif READER_TYPE == READER_RC522
#include <MFRC522.h>
static const char *CHIP = "RC522";
static MFRC522 *readers[N];

static bool rc522Alive(MFRC522 *r, uint8_t *version) {
  *version = r->PCD_ReadRegister(MFRC522::VersionReg);
  return *version != 0x00 && *version != 0xFF;  // 0x91/0x92 genuine, 0x88/0x12/0xB2 clones
}

static bool initReader(int i, char *info, size_t cap) {
  if (!readers[i]) readers[i] = new MFRC522(SLOTS[i].cs, RC522_RST_PIN);
  readers[i]->PCD_Init();
  readers[i]->PCD_SetAntennaGain(MFRC522::RxGain_max);  // NTAG213 stickers are weak; ~2 cm range
  uint8_t v;
  bool alive = rc522Alive(readers[i], &v);
  readers[i]->PCD_AntennaOff();
  snprintf(info, cap, "version=0x%02X", v);
  return alive;
}

// REQA-based PICC_IsNewCardPresent() ignores a tag that is already selected or halted,
// so presence flickers. Instead: field on (tag powers up IDLE), WUPA, select (handles
// 7-byte cascade), halt, field off. One field live at a time also avoids crosstalk.
static int pollReader(int i, uint8_t *uid, uint8_t *len) {
  MFRC522 *r = readers[i];
  uint8_t v;
  if (!rc522Alive(r, &v)) return -1;
  r->PCD_AntennaOn();
  delay(3);  // tag power-up
  r->PCD_WriteRegister(MFRC522::TxModeReg, 0x00);
  r->PCD_WriteRegister(MFRC522::RxModeReg, 0x00);
  r->PCD_WriteRegister(MFRC522::ModWidthReg, 0x26);
  byte atqa[2];
  byte atqaSize = sizeof(atqa);
  MFRC522::StatusCode s = r->PICC_WakeupA(atqa, &atqaSize);
  int found = 0;
  if (s == MFRC522::STATUS_OK || s == MFRC522::STATUS_COLLISION) {
    if (r->PICC_Select(&r->uid) == MFRC522::STATUS_OK && r->uid.size > 0) {
      *len = r->uid.size;
      memcpy(uid, r->uid.uidByte, r->uid.size);
      found = 1;
    }
    r->PICC_HaltA();
  }
  r->PCD_AntennaOff();
  return found;
}
#else
#error "Unknown READER_TYPE"
#endif

static void tryInit(int i) {
  char info[24] = "";
  ok[i] = initReader(i, info, sizeof info);
  fails[i] = 0;
  lastInit[i] = millis();
  Serial.printf("READER %u %s cs=%u %s\n", SLOTS[i].spot, ok[i] ? "OK" : "FAIL", SLOTS[i].cs, info);
}

static void hello() {
  Serial.printf("HELLO earmark-reader v1 node=%s chip=%s readers=%d espnow=%d\n", NODE_NAME, CHIP, N, TRANSPORT_ESPNOW);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  // Every chip select must be high before ANY reader is initialized, or a floating CS
  // lets a second reader answer on the shared MISO line (Adafruit-PN532 #61).
  for (int i = 0; i < N; i++) {
    pinMode(SLOTS[i].cs, OUTPUT);
    digitalWrite(SLOTS[i].cs, HIGH);
  }
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI);
  hello();
  for (int i = 0; i < N; i++) tryInit(i);
#if TRANSPORT_ESPNOW
  Serial.printf("# espnow %s on channel %d, mac %s\n", espnow_link::begin(ESPNOW_CHANNEL) ? "up" : "FAILED", ESPNOW_CHANNEL,
                WiFi.macAddress().c_str());
#endif
}

void loop() {
  static uint32_t lastSend = 0, lastBeat = 0;
  char batch[250];
  size_t blen = 0;
  bool changed = false;

  for (int i = 0; i < N; i++) {
    char line[40];
    if (!ok[i] && millis() - lastInit[i] > 3000) tryInit(i);
    if (!ok[i]) {
      snprintf(line, sizeof line, "SPOT %u ERROR", SLOTS[i].spot);
    } else {
      uint8_t uid[10];
      uint8_t len = 0;
      int r = pollReader(i, uid, &len);
      if (r < 0) {
        snprintf(line, sizeof line, "SPOT %u ERROR", SLOTS[i].spot);
        if (++fails[i] >= 5) {  // persistently silent: re-initialize it
          ok[i] = false;
          lastInit[i] = millis();
        }
      } else if (r == 1) {
        fails[i] = 0;
        char hex[21];
        pn532::to_hex(uid, len, hex);
        snprintf(line, sizeof line, "SPOT %u TAG %s", SLOTS[i].spot, hex);
      } else {
        fails[i] = 0;
        snprintf(line, sizeof line, "SPOT %u EMPTY", SLOTS[i].spot);
      }
    }
    Serial.println(line);
    if (strcmp(line, lastLine[i]) != 0) {
      changed = true;
      strncpy(lastLine[i], line, sizeof lastLine[i] - 1);
    }
    size_t n = strlen(line);
    if (blen + n + 1 < sizeof batch) {
      memcpy(batch + blen, line, n);
      blen += n;
      batch[blen++] = '\n';
    }
  }

#if TRANSPORT_ESPNOW
  if (changed || millis() - lastSend > ESPNOW_REFRESH_MS) {
    espnow_link::send(batch, blen);
    lastSend = millis();
  }
#else
  (void)changed;
  (void)lastSend;
  (void)blen;
#endif

  if (millis() - lastBeat > 10000) {
    lastBeat = millis();
    hello();
  }
}
