#include "../beacons/beacon_core.h"
#include <cassert>
#include <iostream>
#include <vector>

using namespace beacon;

static void checkWave(double start, double end, double seconds) {
  std::vector<uint32_t> words(105002);
  const size_t count = makeWave(start, end, seconds, words.data(), words.size());
  assert(count > 0);
  uint32_t ticks = 0;
  size_t pulse = 0;
  for (size_t i = 0; i < count * 2; ++i) {
    const uint32_t half = words[i / 2] >> (16 * (i % 2));
    const uint32_t duration = half & 32767;
    if (duration == 0) { assert(i == count * 2 - 1); break; }
    assert(((half >> 15) & 1) == (pulse % 2 == 0 ? 1u : 0u));
    ticks += duration;
    ++pulse;
    const double t = ticks / static_cast<double>(kTickHz);
    const double phase = start * t + (end - start) * t * t / (2 * seconds);
    if (ticks < std::llround(seconds * kTickHz)) {
      // Independently evaluate phase at the quantized edge, rather than the root.
      assert(std::abs(phase - pulse / 2.0) <= std::fmax(start, end) / (2 * kTickHz) + 1e-9);
    }
  }
  assert(ticks == std::llround(seconds * kTickHz));
  assert(makeWave(start, end, seconds, words.data(), 1) == 0);
}

static void checkCommands() {
  for (const char* text : {"help", "run", "stop", "test", "beep 1", "sweep 5", "band 2000 4500",
       "len 12", "slot 50", "invert 3 1", "pins wrover", "status", "config", "save", "defaults"}) {
    const Command c = parseCommand(text);
    assert(c.op != Op::Invalid && !c.error);
    assert(!validate(changedSettings(Settings{}, c)));
  }
  for (const char* text : {"", "unknown", "help x", "band 1", "band 1 2 extra", "a b c d e",
       "beep 0", "beep 6", "beep -1", "beep 1.2", "beep 1x", "beep 4294967296",
       "beep 9999999999999999999999999999", "invert 2 2", "pins s3"}) {
    assert(parseCommand(text).error);
  }
  char oversized[81]; std::memset(oversized, 'a', 80); oversized[80] = 0;
  assert(parseCommand(oversized).error);
  assert(parseCommand(" \tPiNs WROOM\r\n").a == 0);
  assert(parseCommand("BaNd 1000 20000").op == Op::Band);
  Settings s;
  for (const char* text : {"band 999 4500", "band 2000 2999", "band 20000 1000",
       "band 1000 20001", "len 4", "len 41", "slot 29", "slot 101"})
    assert(validate(changedSettings(s, parseCommand(text))));
  s.lengthMs = 40; s.slotMs = 30; assert(validate(s));
  s = Settings{}; s.version = 2; assert(validate(s));
  s = Settings{}; s.map = 2; assert(validate(s));
  s = Settings{}; s.invert[4] = 2; assert(validate(s));
  s = changedSettings(Settings{}, parseCommand("invert 5 1")); assert(s.invert[4] == 1);
  s = changedSettings(s, parseCommand("pins wrover")); assert(s.map == 1);
  s = changedSettings(s, parseCommand("defaults")); assert(s.map == kDefaultMap && s.invert[4] == 0);
  char json[240]; configJson(s, json, sizeof(json));
  assert(!std::strcmp(json, "{\"f_lo\":2000,\"f_hi\":4500,\"length_ms\":12,\"slot_ms\":50,\"n_slots\":6,\"marker\":{\"beacon\":\"B1\",\"direction\":\"down\"},\"others_direction\":\"up\",\"version\":1}"));
}

int main() {
  for (double length : {0.005, 0.012, 0.029, 0.040}) {
    checkWave(2000, 4500, length); checkWave(4500, 2000, length);
    checkWave(1000, 20000, length); checkWave(20000, 1000, length);
    checkWave(19000, 20000, length); checkWave(20000, 19000, length);
  }
  checkWave(1000, 20000, 10.0);
  checkCommands();
  std::cout << "PASS: 25 waveforms, phase/quantization/duration/levels, command validation, settings, exact JSON\n";
}
