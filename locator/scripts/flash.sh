#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sketch="$script_dir/../firmware/beacons"
core_version=3.3.12
index=https://espressif.github.io/arduino-esp32/package_esp32_index.json
port=""
compile_only=false
flags=()
usage() {
  echo "Usage: $0 [--wrover] [--port SERIAL_PORT] [--compile-only]"
  echo 'Read the metal can first: WROOM uses GPIO16/17/18/19/21; WROVER uses 25/26/27/32/33.'
  echo 'Use --wrover for WROVER. Other ESP32 families (S3/C3/S2) are not supported.'
}
while (($#)); do
  case "$1" in
    --wrover) flags=(--build-property 'compiler.cpp.extra_flags=-DBOARD_WROVER'); shift ;;
    --port) if (($# < 2)) || [[ -z "$2" ]]; then usage >&2; exit 2; fi; port="$2"; shift 2 ;;
    --compile-only) compile_only=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

echo 'Step 1: Check the tools and the module printed on the metal can.'
usage
if ! command -v arduino-cli >/dev/null; then
  echo 'Arduino CLI is missing. Install arduino-cli, add it to PATH, and run this script again.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo 'Python 3 is needed to read the board list. Install python3 and run again.' >&2
  exit 1
fi
if ! arduino-cli core list --format json | python3 -c '
import json, sys
cores = json.load(sys.stdin).get("platforms", [])
sys.exit(0 if any(p.get("id") == "esp32:esp32" and p.get("installed_version") == "3.3.12" for p in cores) else 1)
'; then
  echo "Install the tested ESP32 core, then run this script again:" >&2
  echo "arduino-cli core update-index --additional-urls $index" >&2
  echo "arduino-cli core install esp32:esp32@$core_version --additional-urls $index" >&2
  exit 1
fi

build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT
echo 'Step 2: Compile the firmware. This does not touch the board yet.'
arduino-cli compile --fqbn esp32:esp32:esp32 --warnings all \
  --build-path "$build_dir" "${flags[@]}" "$sketch"
if "$compile_only"; then
  echo 'Compile passed. No board was flashed.'
  exit 0
fi

echo 'Step 3: Connect only the intended ESP32 with a USB data cable. Close serial monitors.'
echo 'Disconnect beacon wiring while uploading. Saved settings survive an upload; verify status before reconnecting wires.'
if [[ -z "$port" ]]; then
  arduino-cli board list --format json > "$build_dir/ports.json"
  python3 -c '
import json, sys
for entry in json.load(open(sys.argv[1])).get("detected_ports", []):
    port = entry.get("port", {})
    if port.get("protocol") == "serial":
        print(port["address"])
' "$build_dir/ports.json" > "$build_dir/ports.txt"
  count="$(wc -l < "$build_dir/ports.txt" | tr -d ' ')"
  echo 'Detected serial ports:'
  cat "$build_dir/ports.txt"
  if [[ ! -t 0 ]]; then
    echo 'Run again with --port SERIAL_PORT (no interactive terminal is available).' >&2
    exit 1
  fi
  if [[ "$count" == 1 ]]; then
    port="$(cat "$build_dir/ports.txt")"
    read -r -p "Is $port the ESP32 you intend to flash? Type yes: " answer
    if [[ "$answer" != yes ]]; then echo 'Upload cancelled.'; exit 1; fi
  else
    read -r -p 'Type the ESP32 serial port shown above (or connect it and rerun): ' port
  fi
fi
if [[ -z "$port" ]]; then echo 'No serial port selected; nothing uploaded.' >&2; exit 1; fi

echo "Step 4: Upload to $port. Please hold the BOOT button if the upload hangs."
echo 'Release BOOT when writing starts. If permission is denied, check serial-port access; do not run this script as root.'
arduino-cli upload --fqbn esp32:esp32:esp32 --port "$port" --input-dir "$build_dir" "$sketch"
echo 'Upload finished. Press EN/RESET if needed. Open a serial monitor at 115200 baud.'
echo 'Expect the banner, settings, then RUNNING and the cycle length after 2 seconds.'
echo 'Type stop, then status. Confirm the pin map and invert flags before connecting any buzzer.'
echo 'Type test for one chirp from each beacon; type help for all commands.'
