#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <driver/gpio.h>
#include <driver/gptimer.h>
#include <driver/rmt_tx.h>
#include <esp_arduino_version.h>
#include <esp_idf_version.h>
#include <cstdarg>
#include "beacon_core.h"
#include "sweep_table.h"

#if !CONFIG_IDF_TARGET_ESP32 || CONFIG_FREERTOS_UNICORE
#error "Use a dual-core classic ESP32 WROOM/WROVER, not S2/S3/C3."
#endif
#if ESP_ARDUINO_VERSION_MAJOR != 3
#error "Arduino-ESP32 core 3.x is required. CI pins 3.3.12."
#endif

namespace beacon_runtime {
using beacon::Settings;
using beacon::Command;
using beacon::Op;
enum class Mode { Stopped, Run, Beep, Test, SweepWait, Sweep };
enum class EventKind { Tick, Command };
struct Event { EventKind kind; uint32_t epoch; uint32_t sequence; char line[80]; };
struct Reply { char text[512]; };
struct ClockContext {
  QueueHandle_t events = nullptr;
  uint32_t epoch = 0;
  volatile uint32_t sequence = 0;
  volatile bool overflow = false;
};
struct Channel {
  rmt_channel_handle_t handle = nullptr;
  rmt_encoder_handle_t encoder = nullptr;
  bool enabled = false;
};
static Settings settings;
static Mode mode = Mode::Stopped;
static QueueHandle_t events = nullptr;
static QueueHandle_t replies = nullptr;
static ClockContext clockContext;
static gptimer_handle_t timer = nullptr;
static bool timerRunning = false;
static bool outputOverflow = false;
static bool hardwareFault = false;
static bool autoStart = true;
static uint32_t expectedSequence = 1;
static uint32_t selection = 0;
static uint32_t testIndex = 0;
static Channel channels[5];
static uint32_t waves[2][beacon::kMaxSymbols];
static size_t waveCounts[2];

static void emit(const char* format, ...) {
  Reply reply{};
  va_list args;
  va_start(args, format);
  vsnprintf(reply.text, sizeof(reply.text), format, args);
  va_end(args);
  if (xQueueSend(replies, &reply, 0) != pdTRUE) outputOverflow = true;
}

static bool checked(esp_err_t result, const char* operation) {
  if (result == ESP_OK) return true;
  emit("ERR %s: %s", operation, esp_err_to_name(result));
  hardwareFault = true;
  return false;
}

static bool IRAM_ATTR onAlarm(gptimer_handle_t, const gptimer_alarm_event_data_t*, void* context) {
  auto* clock = static_cast<ClockContext*>(context);
  Event event{};
  event.kind = EventKind::Tick;
  event.epoch = clock->epoch;
  clock->sequence = clock->sequence + 1;
  event.sequence = clock->sequence;
  BaseType_t awakened = pdFALSE;
  if (xQueueSendFromISR(clock->events, &event, &awakened) != pdTRUE) clock->overflow = true;
  return awakened == pdTRUE;
}

static void setIdle(size_t i) {
  const auto pin = static_cast<gpio_num_t>(beacon::kPins[settings.map][i]);
  checked(gpio_reset_pin(pin), "reset GPIO");
  checked(gpio_set_level(pin, settings.invert[i]), "idle level");
  checked(gpio_set_direction(pin, GPIO_MODE_OUTPUT), "GPIO direction");
}

static void stopClock() {
  if (timerRunning) {
    checked(gptimer_stop(timer), "stop timer");
    timerRunning = false;
  }
  ++clockContext.epoch;
}

static void releaseChannel(size_t i) {
  auto& c = channels[i];
  if (c.enabled) {
    checked(rmt_disable(c.handle), "disable RMT");
    c.enabled = false;
  }
  if (c.handle) {
    checked(rmt_del_channel(c.handle), "delete RMT");
    c.handle = nullptr;
  }
  if (c.encoder) {
    checked(rmt_del_encoder(c.encoder), "delete encoder");
    c.encoder = nullptr;
  }
  setIdle(i);
}

static void stop() {
  stopClock();
  mode = Mode::Stopped;
  for (size_t i = 0; i < 5; ++i) releaseChannel(i);
  digitalWrite(2, LOW);
}

static bool openChannel(size_t i) {
  setIdle(i);
  auto& c = channels[i];
  rmt_tx_channel_config_t config{};
  config.gpio_num = static_cast<gpio_num_t>(beacon::kPins[settings.map][i]);
  config.clk_src = RMT_CLK_SRC_DEFAULT;
  config.resolution_hz = beacon::kTickHz;
  config.mem_block_symbols = 64;
  config.trans_queue_depth = 1;
  config.intr_priority = 3;
  config.flags.invert_out = settings.invert[i];
  if (!checked(rmt_new_tx_channel(&config, &c.handle), "allocate RMT")) return false;
  rmt_copy_encoder_config_t encoderConfig{};
  if (!checked(rmt_new_copy_encoder(&encoderConfig, &c.encoder), "allocate encoder")) return false;
  c.enabled = checked(rmt_enable(c.handle), "enable RMT");
  return c.enabled;
}

static bool prepareChannels() {
  const double seconds = settings.lengthMs / 1000.0;
  waveCounts[0] = beacon::makeWave(settings.hi, settings.lo, seconds, waves[0], beacon::kMaxSymbols);
  waveCounts[1] = beacon::makeWave(settings.lo, settings.hi, seconds, waves[1], beacon::kMaxSymbols);
  if (!waveCounts[0] || !waveCounts[1]) { emit("ERR waveform capacity"); return false; }
  for (size_t i = 0; i < 5; ++i) if (!openChannel(i)) return false;
  return true;
}

static bool transmit(size_t i, bool sweep = false) {
  const size_t direction = i == 0 ? 0 : 1;
  const void* data = sweep ? kSweepSymbols : waves[direction];
  const size_t bytes = sweep ? sizeof(kSweepSymbols) : waveCounts[direction] * sizeof(uint32_t);
  rmt_transmit_config_t config{};
  config.flags.eot_level = 0;
  config.flags.queue_nonblocking = true;
  return checked(rmt_transmit(channels[i].handle, channels[i].encoder, data, bytes, &config), "transmit");
}

static bool startClock(uint32_t periodUs) {
  gptimer_alarm_config_t alarm{};
  alarm.alarm_count = periodUs;
  alarm.reload_count = 0;
  alarm.flags.auto_reload_on_alarm = true;
  clockContext.sequence = 0;
  clockContext.overflow = false;
  expectedSequence = 1;
  if (!checked(gptimer_set_raw_count(timer, 0), "reset timer") ||
      !checked(gptimer_set_alarm_action(timer, &alarm), "set alarm")) return false;
  timerRunning = checked(gptimer_start(timer), "start timer");
  return timerRunning;
}

static bool start(Mode next, uint32_t beaconIndex) {
  stop();
  if (hardwareFault) { emit("ERR hardware fault; restart board after checking wiring"); return false; }
  selection = beaconIndex;
  testIndex = 0;
  if (!prepareChannels()) { stop(); return false; }
  mode = next;
  const uint32_t period = next == Mode::Run ? settings.slotMs * 1000 :
    next == Mode::Beep ? 300000 : next == Mode::Test ? 1000000 : 2000000;
  if (!startClock(period)) { stop(); return false; }
  if (next == Mode::Run) emit("RUNNING cycle=%lu ms", static_cast<unsigned long>(settings.slotMs * 6));
  return true;
}

static void printConfig() {
  char json[240];
  beacon::configJson(settings, json, sizeof(json));
  emit("%s", json);
}

static void printStatus() {
  const char* name = mode == Mode::Stopped ? "stopped" : mode == Mode::Run ? "running" :
    mode == Mode::Beep ? "beep" : mode == Mode::Test ? "test" : "sweep";
  emit("%s pins=%s uptime=%lu ms fault=%u", name, settings.map ? "wrover" : "wroom",
    static_cast<unsigned long>(millis()), hardwareFault);
  for (size_t i = 0; i < 5; ++i)
    emit("B%u GPIO%d invert=%lu", static_cast<unsigned>(i + 1), beacon::kPins[settings.map][i],
      static_cast<unsigned long>(settings.invert[i]));
  printConfig();
}

static bool saveSettings() {
  Preferences storage;
  if (!storage.begin("locator", false)) { emit("ERR cannot open NVS"); return false; }
  const size_t written = storage.putBytes("settings", &settings, sizeof(settings));
  storage.end();
  if (written != sizeof(settings)) { emit("ERR NVS write failed; settings not saved"); return false; }
  return true;
}

static bool loadSettings() {
  Preferences storage;
  if (!storage.begin("locator", false)) { emit("ERR cannot open NVS; auto-run disabled"); return false; }
  if (!storage.isKey("settings")) { storage.end(); return true; }
  Settings saved;
  const size_t read = storage.getBytes("settings", &saved, sizeof(saved));
  storage.end();
  const char* invalid = beacon::validate(saved);
  if (read != sizeof(saved) || invalid) {
    emit("ERR invalid NVS settings; inspect status then defaults; auto-run disabled");
    return false;
  }
  settings = saved;
  return true;
}

static bool updateSettings(const Command& command) {
  if (mode == Mode::Test || mode == Mode::Sweep || mode == Mode::SweepWait) {
    emit("ERR stop diagnostic mode before changing or saving settings"); return false;
  }
  const Settings next = beacon::changedSettings(settings, command);
  if (const char* invalid = beacon::validate(next)) { emit("ERR %s", invalid); return false; }
  const Mode previousMode = mode;
  const uint32_t previousSelection = selection;
  stop();
  settings = next;
  for (size_t i = 0; i < 5; ++i) setIdle(i);
  const bool persist = command.op == Op::Save || command.op == Op::Pins || command.op == Op::Defaults;
  if (persist && !saveSettings()) return false;
  if (previousMode == Mode::Run || previousMode == Mode::Beep) return start(previousMode, previousSelection);
  return !hardwareFault;
}

static void printHelp() {
  emit("help | run | stop | test | beep <1..5> | sweep <1..5>");
  emit("band <lo> <hi> (1000..20000 Hz, width >=1000) | len <5..40 ms> | slot <30..100 ms>");
  emit("invert <1..5> <0|1> | pins <wroom|wrover> (saved) | status | config | save | defaults (saved)");
  emit("115200 baud; commands ignore case. Settings changes restart run/beep; stop diagnostics first.");
}

static void handleCommand(const char* text) {
  const Command command = beacon::parseCommand(text);
  if (command.error) { emit("ERR %s", command.error); return; }
  bool ok = true;
  switch (command.op) {
    case Op::Help: printHelp(); break;
    case Op::Status: printStatus(); break;
    case Op::Config: printConfig(); break;
    case Op::Stop: autoStart = false; stop(); ok = !hardwareFault; break;
    case Op::Run: autoStart = false; ok = start(Mode::Run, 0); break;
    case Op::Beep: autoStart = false; ok = start(Mode::Beep, command.a - 1); break;
    case Op::Test: autoStart = false; ok = start(Mode::Test, 0); break;
    case Op::Sweep: autoStart = false; ok = start(Mode::SweepWait, command.a - 1); break;
    default: ok = updateSettings(command); break;
  }
  if (ok) emit("OK");
}

static void diagnosticTick() {
  if (mode == Mode::Test && testIndex < 5) {
    Serial.printf(">> B%u chirp\n", static_cast<unsigned>(testIndex + 1));
    Serial.flush();
    if (!transmit(testIndex++)) stop();
  } else if (mode == Mode::SweepWait) {
    stopClock();
    Serial.println("SWEEP START");
    Serial.flush();
    mode = Mode::Sweep;
    if (!transmit(selection, true)) stop();
  }
}

static void handleTick(const Event& event) {
  if (event.epoch != clockContext.epoch || mode == Mode::Stopped) return;
  uint64_t lateness = 0;
  if (!checked(gptimer_get_raw_count(timer, &lateness), "read timer")) { stop(); return; }
  if (event.sequence != expectedSequence++ || lateness > 1000) {
    stop(); emit("ERR missed/late slot; stopped instead of sending stale chirps"); return;
  }
  if (mode == Mode::Run) {
    const uint32_t slot = (event.sequence - 1) % 6;
    if (slot < 5 && !transmit(slot)) { stop(); return; }
    digitalWrite(2, slot == 0 ? HIGH : LOW);
  } else if (mode == Mode::Beep) {
    if (!transmit(selection)) stop();
  } else diagnosticTick();
}

static void finishDiagnostic() {
  if (mode != Mode::Sweep && !(mode == Mode::Test && testIndex == 5)) return;
  const size_t i = mode == Mode::Sweep ? selection : 4;
  const esp_err_t result = rmt_tx_wait_all_done(channels[i].handle, 0);
  if (result == ESP_ERR_TIMEOUT) return;
  const bool wasSweep = mode == Mode::Sweep;
  const bool ok = checked(result, "finish diagnostic");
  stop();
  if (ok && wasSweep) emit("SWEEP END");
}

static bool setupTimer() {
  gptimer_config_t config{};
  config.clk_src = GPTIMER_CLK_SRC_DEFAULT;
  config.direction = GPTIMER_COUNT_UP;
  config.resolution_hz = 1000000;
  config.intr_priority = 3;
  if (!checked(gptimer_new_timer(&config, &timer), "allocate timer")) return false;
  gptimer_event_callbacks_t callbacks{};
  callbacks.on_alarm = onAlarm;
  if (!checked(gptimer_register_event_callbacks(timer, &callbacks, &clockContext), "register alarm")) return false;
  return checked(gptimer_enable(timer), "enable timer");
}

static void controlTask(void*) {
  emit("Earmark beacons 1.0.0 | Arduino %s | IDF %s | initial pins=%s",
    ESP_ARDUINO_VERSION_STR, esp_get_idf_version(), settings.map ? "wrover" : "wroom");
  printConfig();
  autoStart = loadSettings();
  for (size_t i = 0; i < 5; ++i) setIdle(i);
  printStatus();
  if (!setupTimer()) autoStart = false;
  const uint32_t bootTime = millis();
  for (;;) {
    Event event{};
    if (xQueueReceive(events, &event, pdMS_TO_TICKS(10)) == pdTRUE) {
      if (event.kind == EventKind::Tick) handleTick(event);
      else handleCommand(event.line);
    }
    finishDiagnostic();
    if (clockContext.overflow || outputOverflow) {
      stop(); clockContext.overflow = false; outputOverflow = false;
      emit("ERR event/output queue overflow; stopped; reduce serial traffic");
    }
    if (autoStart && millis() - bootTime >= 2000) {
      autoStart = false;
      start(Mode::Run, 0);
    }
  }
}

static void begin() {
  Serial.begin(115200);
  pinMode(2, OUTPUT);
  digitalWrite(2, LOW);
  events = xQueueCreate(16, sizeof(Event));
  replies = xQueueCreate(32, sizeof(Reply));
  if (!events || !replies) { Serial.println("ERR queue allocation; restart board"); return; }
  clockContext.events = events;
  if (xTaskCreatePinnedToCore(controlTask, "beacon-control", 8192, nullptr,
                             configMAX_PRIORITIES - 2, nullptr, 0) != pdPASS) {
    Serial.println("ERR control task allocation; restart board");
    vQueueDelete(events); events = nullptr;
  }
}

static void sendLine(const char* line) {
  Event event{};
  event.kind = EventKind::Command;
  std::strcpy(event.line, line);
  if (xQueueSend(events, &event, 0) != pdTRUE) Serial.println("ERR busy; retry command");
}

static void serviceSerial() {
  if (!events || !replies) { delay(100); return; }
  Reply reply{};
  // Limit each pass so an output flood cannot prevent reading stop.
  if (xQueueReceive(replies, &reply, 0) == pdTRUE) Serial.println(reply.text);
  static char line[80];
  static size_t used = 0;
  static bool discard = false;
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\r' || ch == '\n') {
      if (discard) Serial.println("ERR line too long or contains control bytes");
      else if (used) { line[used] = 0; sendLine(line); }
      used = 0; discard = false;
    } else if (static_cast<unsigned char>(ch) < 32 && ch != '\t') discard = true;
    else if (used >= sizeof(line) - 1) discard = true;
    else if (!discard) line[used++] = ch;
  }
  delay(1);
}
}  // namespace beacon_runtime
