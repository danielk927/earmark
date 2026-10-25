#!/usr/bin/env bash
# Build every firmware variant and run the host tests.
#   ./build.sh            host tests + compile all variants
#   ./build.sh test       host tests only
#   ./build.sh flash reader /dev/cu.usbserial-0001 [esp32|esp32s3|esp32c3] [extra -D flags...]
# Needs: arduino-cli with the esp32 core, plus "Adafruit PN532" and "MFRC522" libraries:
#   arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
#   arduino-cli core update-index && arduino-cli core install esp32:esp32
#   arduino-cli lib install "Adafruit PN532" "MFRC522"
set -euo pipefail
cd "$(dirname "$0")"

host_tests() {
  local out
  out=$(mktemp -d)
  c++ -std=c++17 -Wall -Wextra -Werror -Iearmark_reader test/test_pn532_proto.cpp -o "$out/t"
  "$out/t"
  cmp -s earmark_reader/espnow_link.h earmark_ble_anchor/espnow_link.h ||
    { echo "earmark_ble_anchor/espnow_link.h differs from earmark_reader/espnow_link.h"; exit 1; }
}

compile() {  # sketch fqbn label [flags...]
  local sketch=$1 fqbn=$2 label=$3
  shift 3
  local flags="$*"
  printf '%-44s ' "$sketch [$label]"
  local log
  log=$(mktemp)
  if arduino-cli compile --fqbn "$fqbn" --warnings all \
      --build-property "compiler.cpp.extra_flags=$flags" "$sketch" >"$log" 2>&1; then
    grep -E "Sketch uses" "$log" | sed 's/Sketch uses/ok:/' | cut -c1-60
    if grep -q "warning:" "$log" && grep "warning:" "$log" | grep -q "$sketch"; then
      grep "warning:" "$log" | grep "$sketch" | head -5
    fi
  else
    echo "FAILED"
    cat "$log"
    exit 1
  fi
}

if [[ "${1:-}" == "flash" ]]; then
  sketch=earmark_${2:?reader|gateway|ble_anchor}
  port=${3:?serial port}
  chip=${4:-esp32}
  shift 4 || shift $#
  fqbn="esp32:esp32:$chip"
  [[ $sketch == earmark_ble_anchor ]] && fqbn="$fqbn:PartitionScheme=huge_app"
  arduino-cli compile --fqbn "$fqbn" --build-property "compiler.cpp.extra_flags=$*" \
    --upload --port "$port" "$sketch"
  exit 0
fi

host_tests
[[ "${1:-}" == "test" ]] && exit 0

E=esp32:esp32
compile earmark_reader     $E:esp32   "PN532, own driver"
compile earmark_reader     $E:esp32   "PN532, Adafruit lib"   -DPN532_USE_ADAFRUIT=1
compile earmark_reader     $E:esp32   "RC522"                 -DREADER_TYPE=2
compile earmark_reader     $E:esp32   "PN532 + ESP-NOW"       -DTRANSPORT_ESPNOW=1 '-DNODE_NAME="sat1"' '-DREADERS={{16,3}}'
compile earmark_reader     $E:esp32s3 "S3, PN532"
compile earmark_reader     $E:esp32c3 "C3, RC522 + ESP-NOW"   -DREADER_TYPE=2 -DTRANSPORT_ESPNOW=1
compile earmark_gateway    $E:esp32   "gateway"
compile earmark_gateway    $E:esp32s3 "S3 gateway"
# The BLE stack alone is ~1.1 MB; with Wi-Fi it overflows the default 1.2 MB app partition.
HUGE=PartitionScheme=huge_app
compile earmark_ble_anchor $E:esp32:$HUGE   "anchor, serial"
compile earmark_ble_anchor $E:esp32:$HUGE   "anchor + ESP-NOW"      -DTRANSPORT_ESPNOW=1 '-DANCHOR_ID="A2"'
compile earmark_ble_anchor $E:esp32c3:$HUGE "C3 anchor"
echo "all firmware variants build"
