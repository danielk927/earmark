# Espressif verification — locator beacon firmware

**Load-bearing assumption:** GPTimer alarms waking a high-priority, core-pinned task can start RMT chirps with ≤20 µs RMS slot-start jitter on the actual classic ESP32 board. Compilation cannot confirm that claim: measure slot starts electrically and run brief B5 before using acoustic fixes. Task/interrupt latency, RMT refill starvation, oscillator error and acoustic multipath are separate possible causes of timing error.

## Retrieved official references

Consulted 2026-10-24. These are page fetches, not search-snippet claims.

- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/rmt.html — `rmtInit(pin, direction, memsize, frequency_Hz)`, `rmtWrite`, `rmtWriteAsync`, EOT behavior and 15-bit duration fields verified. Classic ESP32 has **eight shared TX/RX blocks**, 64 symbols per block. **S3 has four TX + four RX**, not eight TX; C3 has two TX + two RX. This implementation deliberately targets classic ESP32 WROOM/WROVER only, with five resident TX channels; other chips fail compilation rather than silently changing timing.
- https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/peripherals/rmt.html — verified `rmt_new_tx_channel`, `rmt_new_copy_encoder`, `rmt_enable`, `rmt_transmit`, `rmt_tx_wait_all_done`, `rmt_disable`, `rmt_del_channel`, `rmt_del_encoder`; channel resolution, `invert_out`, `trans_queue_depth`, `queue_nonblocking` and `eot_level`. EOT applies on completion **and disable**. Payload must remain valid until completion. Copy encoder accepts preformatted symbols and refills hardware memory. `rmt_transmit` queues a transaction: return does not certify the electrical edge time. Loop mode is constrained by hardware memory; sync-manager support is chip-dependent. The transmit/encoder sections were also read in a direct HTML retrieval on the build computer.
- https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/peripherals/gptimer.html — verified `gptimer_new_timer`, callback registration before enable, 1 MHz resolution, hardware `auto_reload_on_alarm`, start/stop, raw count reset and alarm actions. Callback runs in ISR context and returns whether a higher-priority task awoke. Hardware reload avoids accumulating software scheduling delays.
- https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gptimer.html — fetched first; currently identifies itself as IDF v6.1. Confirmed the design against the v5.5 page above rather than assuming stable means IDF5. Cache-disabled flash writes can delay timer interrupts; IRAM options depend on the SDK build.
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html — verified `Preferences.h`, NVS retention across power loss, namespace/key limits, `begin`, `isKey`, `putBytes`/`getBytes` byte counts and `end`. Settings use one versioned, validated record, not partially updated independent keys.
- https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html — verified stable board index https://espressif.github.io/arduino-esp32/package_esp32_index.json and BOOT-button upload guidance. The index was downloaded on the build computer and lists core **3.3.12**, pinned in CI and the flash helper.

Additional discovery URLs (search results / initial batch fetch, not used as version-specific implementation authority):
- https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/rmt.html
- https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/peripherals/rmt.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/rmt.html

## Grounded scope and design

The inspected base contains teammate-owned `firmware/`, `apple/`, `hub/` and `docs/`; none is changed. No root/area AGENTS.md or .spec.md was present. All additions are in `locator/firmware/`, `locator/scripts/`, `locator/docs/vendor-notes/` and `.github/`.

Five dedicated IDF5 RMT TX channels each reserve one 64-symbol block at 10 MHz (0.1 µs ticks). A priority-23 control task pinned to core 0 owns all mutable settings, channels and timers. GPTimer is allocated on that core, with priority-3 interrupts; its ISR sends a numbered tick event to the task. Normal operation has no allocation, square roots, serial logging or flash writes on slot boundaries. A hardware-reloaded slot timer advances five chirps and one silent slot without cumulative software drift. GPIO2 is high during slot 0 and low for the remaining five slots. Lost/late tick events stop output with an explicit error, not a catch-up burst.

Chirp boundaries solve `f_start*t + (f_end-f_start)*t²/(2*T) = k/2` using a numerically stable root, then round **absolute** times to 10 MHz ticks before differencing. B1 falls; B2–B5 rise. Runtime templates are precomputed while stopped. Active-low modules use RMT output inversion; logical EOT is always zero. Stop disables channels and returns every currently mapped pin to its physical inactive level before releasing resources. Do not change maps while wires are connected to a different map.

The ten-second diagnostic sweep is a generated **flash-resident** symbol table, avoiding a >400 KB heap allocation on WROOM and avoiding floating-point math in RMT refill interrupts. Its generator and host tests use the same edge formula; the checked-in header makes the Arduino IDE usable without a pre-build tool. No flash/NVS write is allowed while it transmits. Only one TX runs at a time. A chirp must fit inside its slot (`length_ms < slot_ms`): independently legal but overlapping combinations are rejected with ERR.

Settings changes pause and restart a fresh schedule; `pins` persists automatically, `save` persists all settings, and `defaults` restores and persists compile-time defaults. `BOARD_WROVER` selects the safe initial map; persisted settings otherwise take precedence. Diagnostic test/sweep modes must be stopped before changing settings. A bounded serial line parser rejects oversized lines, malformed numbers, extra arguments and unknown commands without changing state.

## Hardware acceptance still required

No hardware is available. Do not label ≤20 µs RMS, sweep continuity, output polarity, audibility or LED behavior as measured. Before Phase C:

1. Identify the actual metal-can module; WROVER must not use GPIO16/17. Flash the matching map and inspect `status` before wiring.
2. Use a logic analyzer to measure all five slot-start edges for 60 seconds, including maximum-band/length configurations. Remove a constant launch offset before computing RMS; require ≤20 µs RMS and no accumulating schedule error. Check every half-cycle for RMT refill underruns, particularly the 10-second 1–20 kHz sweep.
3. Run acoustic B5: two colocated beacons, 60 s, B2−B1 = 50.000 ms ±0.03 ms, std ≤0.02 ms. Separately assess acoustic echoes and phone sample-clock error.
4. Verify stop during each mode, inverted idle, both maps, NVS power-cycle retention, 2 s auto-run, and no driven DC at idle. Use a safe driver circuit; this firmware does not authorize an unverified buzzer current or transistor pinout.

## Build evidence

Verified locally with Arduino CLI 1.5.2-rc.1 and Arduino-ESP32 3.3.12 (installed headers report ESP-IDF 5.5.5). Both `bash locator/scripts/flash.sh --compile-only` and `bash locator/scripts/flash.sh --wrover --compile-only` pass with `--warnings all` and no warnings:

| Build | Program bytes / 1,310,720 | Global bytes / 327,680 |
| --- | ---: | ---: |
| WROOM | 724,529 (55%) | 29,524 (9%) |
| WROVER | 724,537 (55%) | 29,524 (9%) |

`bash locator/scripts/test_firmware.sh` passes: 25 waveform cases per map (phase, quantization, total duration, polarity), command validation, settings bounds, exact config JSON, regenerated sweep byte comparison, and eight flash-helper tests with a fake CLI. Flash tests cover compile-only, the WROVER build flag, explicit port quoting, compile/upload failures, wrong core, noninteractive discovery and malformed arguments. They never upload to a board. `bash -n`, YAML parsing and actionlint 1.7.12 also pass.

CI builds both maps in `.github/workflows/locator-firmware.yml`; live results belong to the PR checks, not this static record. The initial PR run exposed a separate existing scaffold-job installer error (`bin ($BINDIR) folder not found`), reported to its owner rather than editing an unauthorized existing file.

No serial device was available. No firmware upload, electrical jitter, physical output polarity, NVS power-cycle retention or acoustic result is claimed. Firmware/CLI/CI-only changes have no rendered UI to capture; native compile/test logs are the acceptance evidence.
