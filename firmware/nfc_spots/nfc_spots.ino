// Earmark NFC spot readers: one ESP32 + up to 6 RC522 readers on a shared SPI bus.
//
// Output (115200 baud, one line per reader per poll, parsed by services/hub nfc_serial):
//   SPOT <n> TAG <UID_HEX>      a tag is on spot n (uppercase hex, no separators)
//   SPOT <n> EMPTY              nothing on spot n
//   SPOT <n> ERROR <reason>     reader n missing or not answering
// Readers are polled continuously; the hub debounces (2 matching reads to place,
// ~1.5 s of continuous absence to remove), so occasional misreads are harmless.
//
// Library: "MFRC522" by GithubCommunity / miguelbalboa (Arduino Library Manager),
// see docs/vendor-notes/rc522.md. Board: "ESP32 Dev Module".
//
// Wiring (all readers): SCK=18, MISO=19, MOSI=23, RST=27 (shared), 3V3 and GND.
// Each reader gets its own SDA/SS (chip select) pin from CS_PINS below.
// The pins avoid the ESP32 strapping pins (0, 2, 5, 12, 15), the flash pins (6-11),
// the input-only pins (34-39), and 16/17 (PSRAM on WROVER modules).
#include <SPI.h>
#include <MFRC522.h>

static const uint8_t RST_PIN = 27;
static const uint8_t CS_PINS[] = {13, 21, 22, 25, 26, 32};
// Spot number reported for each reader; must match config/space.json.
static const uint8_t SPOT_IDS[] = {1, 2, 3, 4, 5, 6};
static const size_t N_READERS = sizeof(CS_PINS) / sizeof(CS_PINS[0]);
static const uint32_t REPORT_INTERVAL_MS = 200;   // per reader
static const uint32_t HEALTH_CHECK_MS = 3000;     // re-check missing readers

MFRC522 *readers[N_READERS];
bool healthy[N_READERS];
uint32_t lastReport[N_READERS];
uint32_t lastHealth = 0;

static bool readerAlive(MFRC522 &r) {
  byte v = r.PCD_ReadRegister(MFRC522::VersionReg);
  return v != 0x00 && v != 0xFF;
}

static void initReader(size_t i) {
  readers[i]->PCD_Init();
  readers[i]->PCD_SetAntennaGain(MFRC522::RxGain_max);
  healthy[i] = readerAlive(*readers[i]);
}

// True and fills hex if a tag is present. WUPA (not REQA) also wakes tags we halted on the
// previous poll, so a tag that just sits on the spot is reported on every poll.
static bool readTag(MFRC522 &r, char *hex, size_t hexLen) {
  byte atqa[2];
  byte atqaLen = sizeof(atqa);
  MFRC522::StatusCode st = r.PICC_WakeupA(atqa, &atqaLen);
  if (st != MFRC522::STATUS_OK && st != MFRC522::STATUS_COLLISION) return false;
  if (!r.PICC_ReadCardSerial()) return false;
  size_t n = 0;
  for (byte b = 0; b < r.uid.size && n + 2 < hexLen; b++) {
    n += snprintf(hex + n, hexLen - n, "%02X", r.uid.uidByte[b]);
  }
  r.PICC_HaltA();
  return n > 0;
}

void setup() {
  Serial.begin(115200);
  // Deselect every reader before touching the bus.
  for (size_t i = 0; i < N_READERS; i++) {
    pinMode(CS_PINS[i], OUTPUT);
    digitalWrite(CS_PINS[i], HIGH);
  }
  SPI.begin();  // SCK=18, MISO=19, MOSI=23 on the ESP32 VSPI defaults
  for (size_t i = 0; i < N_READERS; i++) {
    readers[i] = new MFRC522(CS_PINS[i], RST_PIN);
    initReader(i);
    lastReport[i] = 0;
  }
  Serial.println("# earmark nfc_spots ready");
}

void loop() {
  uint32_t now = millis();
  if (now - lastHealth >= HEALTH_CHECK_MS) {
    lastHealth = now;
    for (size_t i = 0; i < N_READERS; i++) {
      if (!healthy[i] || !readerAlive(*readers[i])) initReader(i);
    }
  }
  for (size_t i = 0; i < N_READERS; i++) {
    if (now - lastReport[i] < REPORT_INTERVAL_MS) continue;
    lastReport[i] = now;
    if (!healthy[i]) {
      Serial.printf("SPOT %u ERROR no_reader\n", SPOT_IDS[i]);
      continue;
    }
    char hex[24];
    if (readTag(*readers[i], hex, sizeof(hex))) {
      Serial.printf("SPOT %u TAG %s\n", SPOT_IDS[i], hex);
    } else {
      Serial.printf("SPOT %u EMPTY\n", SPOT_IDS[i]);
    }
  }
}
