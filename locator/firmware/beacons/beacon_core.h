#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cctype>
#include <cerrno>

namespace beacon {
constexpr uint32_t kTickHz = 10000000;
constexpr size_t kMaxSymbols = 802;
constexpr int kPins[2][5] = {{16, 17, 18, 19, 21}, {25, 26, 27, 32, 33}};
#ifdef BOARD_WROVER
constexpr uint32_t kDefaultMap = 1;
#else
constexpr uint32_t kDefaultMap = 0;
#endif

struct Settings {
  uint32_t version = 1;
  uint32_t lo = 2000;
  uint32_t hi = 4500;
  uint32_t lengthMs = 12;
  uint32_t slotMs = 50;
  uint32_t map = kDefaultMap;
  uint32_t invert[5] = {};
};

inline const char* validate(const Settings& s) {
  if (s.version != 1) return "unsupported settings version";
  if (s.lo < 1000 || s.hi > 20000 || s.hi < s.lo || s.hi - s.lo < 1000)
    return "band requires 1000 <= lo < hi <= 20000, width >= 1000 Hz";
  if (s.lengthMs < 5 || s.lengthMs > 40) return "length must be 5..40 ms";
  if (s.slotMs < 30 || s.slotMs > 100) return "slot must be 30..100 ms";
  if (s.lengthMs >= s.slotMs) return "chirp length must be shorter than slot";
  if (s.map > 1) return "invalid pin map";
  for (auto invert : s.invert) if (invert > 1) return "invert must be 0 or 1";
  return nullptr;
}

inline void configJson(const Settings& s, char* out, size_t capacity) {
  std::snprintf(out, capacity,
    "{\"f_lo\":%lu,\"f_hi\":%lu,\"length_ms\":%lu,\"slot_ms\":%lu,\"n_slots\":6,"
    "\"marker\":{\"beacon\":\"B1\",\"direction\":\"down\"},\"others_direction\":\"up\",\"version\":1}",
    static_cast<unsigned long>(s.lo), static_cast<unsigned long>(s.hi),
    static_cast<unsigned long>(s.lengthMs), static_cast<unsigned long>(s.slotMs));
}

inline uint32_t edgeTick(uint32_t halfCycle, double start, double end, double seconds) {
  const double slope = (end - start) / seconds;
  // Rationalized root avoids cancellation for narrow bands and early edges.
  const double time = halfCycle / (start + std::sqrt(start * start + slope * halfCycle));
  return static_cast<uint32_t>(std::llround(time * kTickHz));
}

// Packed layout is the documented rmt_symbol_word_t: duration0/level0/duration1/level1.
inline size_t makeWave(double start, double end, double seconds,
                       uint32_t* out, size_t capacity) {
  const uint32_t total = static_cast<uint32_t>(std::llround(seconds * kTickHz));
  uint32_t previous = 0;
  size_t pulse = 0;
  for (uint32_t k = 1; previous < total; ++k) {
    const double halfCycles = (start + end) * seconds;
    const uint32_t next = k >= halfCycles ? total : edgeTick(k, start, end, seconds);
    const uint32_t duration = next - previous;
    if (duration == 0 || duration > 32767 || pulse / 2 >= capacity) return 0;
    const uint32_t packed = duration | ((pulse % 2 == 0 ? 1u : 0u) << 15);
    if (pulse % 2 == 0) out[pulse / 2] = packed;
    else out[pulse / 2] |= packed << 16;
    previous = next;
    ++pulse;
  }
  return (pulse + 1) / 2;
}

enum class Op { Help, Run, Stop, Test, Beep, Sweep, Band, Length, Slot,
                Invert, Pins, Status, Config, Save, Defaults, Invalid };
struct Command { Op op = Op::Invalid; uint32_t a = 0; uint32_t b = 0; const char* error = nullptr; };
struct Verb { const char* text; Op op; size_t arguments; };
constexpr Verb kVerbs[] = {
  {"help", Op::Help, 0}, {"run", Op::Run, 0}, {"stop", Op::Stop, 0},
  {"test", Op::Test, 0}, {"beep", Op::Beep, 1}, {"sweep", Op::Sweep, 1},
  {"band", Op::Band, 2}, {"len", Op::Length, 1}, {"slot", Op::Slot, 1},
  {"invert", Op::Invert, 2}, {"pins", Op::Pins, 1}, {"status", Op::Status, 0},
  {"config", Op::Config, 0}, {"save", Op::Save, 0}, {"defaults", Op::Defaults, 0}
};

inline bool parseNumber(const char* token, uint32_t& value) {
  if (!token || !*token) return false;
  for (const char* p = token; *p; ++p) if (!std::isdigit(static_cast<unsigned char>(*p))) return false;
  errno = 0;
  const unsigned long parsed = std::strtoul(token, nullptr, 10);
  if (errno == ERANGE || parsed > UINT32_MAX) return false;
  value = static_cast<uint32_t>(parsed);
  return true;
}

inline Command parseCommand(const char* line) {
  if (std::strlen(line) >= 80) return {Op::Invalid, 0, 0, "line too long"};
  char copy[80];
  std::strcpy(copy, line);
  for (char* p = copy; *p; ++p) *p = static_cast<char>(std::tolower(static_cast<unsigned char>(*p)));
  char* tokens[4] = {};
  char* context = nullptr;
  size_t count = 0;
  for (char* token = strtok_r(copy, " \t\r\n", &context); token;
       token = strtok_r(nullptr, " \t\r\n", &context)) {
    if (count == 4) return {Op::Invalid, 0, 0, "too many arguments"};
    tokens[count++] = token;
  }
  if (!count) return {Op::Invalid, 0, 0, "empty command"};
  const Verb* verb = nullptr;
  for (const auto& candidate : kVerbs) if (!std::strcmp(tokens[0], candidate.text)) verb = &candidate;
  if (!verb) return {Op::Invalid, 0, 0, "unknown command; type help"};
  if (count != verb->arguments + 1) return {Op::Invalid, 0, 0, "wrong number of arguments"};
  Command result{verb->op, 0, 0, nullptr};
  if (result.op == Op::Pins) {
    if (!std::strcmp(tokens[1], "wrover")) result.a = 1;
    else if (std::strcmp(tokens[1], "wroom")) result.error = "pins requires wroom or wrover";
  } else if ((count > 1 && !parseNumber(tokens[1], result.a)) ||
             (count > 2 && !parseNumber(tokens[2], result.b))) {
    result.error = "arguments must be unsigned integers";
  }
  if ((result.op == Op::Beep || result.op == Op::Sweep || result.op == Op::Invert) &&
      (result.a < 1 || result.a > 5)) result.error = "beacon number must be 1..5";
  if (result.op == Op::Invert && result.b > 1) result.error = "invert must be 0 or 1";
  return result;
}

inline Settings changedSettings(const Settings& old, const Command& c) {
  Settings next = old;
  switch (c.op) {
    case Op::Band: next.lo = c.a; next.hi = c.b; break;
    case Op::Length: next.lengthMs = c.a; break;
    case Op::Slot: next.slotMs = c.a; break;
    case Op::Pins: next.map = c.a; break;
    case Op::Invert: if (c.a >= 1 && c.a <= 5) next.invert[c.a - 1] = c.b; break;
    case Op::Defaults: next = Settings{}; break;
    default: break;
  }
  return next;
}
}  // namespace beacon
