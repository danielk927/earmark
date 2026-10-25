#!/usr/bin/env bash
set -euo pipefail
APP=${1:?usage: capture-simulator.sh APP_PATH OUTPUT_DIRECTORY}
OUT=${2:?provide output directory}
mkdir -p "$OUT"
xcrun simctl list devices available -j > "$OUT/devices.json"
DEVICE=$(python3 - "$OUT/devices.json" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    devices = json.load(source)["devices"]
phones = [d for runtime, group in devices.items() if "iOS" in runtime for d in group
          if d["isAvailable"] and d["name"].startswith("iPhone")]
if not phones:
    raise SystemExit("No available iPhone simulator")
preferred = next((d for d in phones if d["name"] == "iPhone 15 Pro Max"), phones[0])
print(preferred["udid"])
PY
)
xcrun simctl boot "$DEVICE"
xcrun simctl bootstatus "$DEVICE" -b
xcrun simctl status_bar "$DEVICE" override --time 9:41 --batteryState charged --batteryLevel 100
xcrun simctl ui "$DEVICE" appearance light
xcrun simctl install "$DEVICE" "$APP"
for screen in Run Debug Calibrate Manual Settings; do
  SIMCTL_CHILD_EARMARK_INITIAL_TAB="$screen" xcrun simctl launch "$DEVICE" com.earmark.locator
  sleep 3
  xcrun simctl io "$DEVICE" screenshot "$OUT/$screen.png"
  xcrun simctl terminate "$DEVICE" com.earmark.locator
done
git rev-parse HEAD > "$OUT/tested-head-sha.txt"
xcrun simctl shutdown "$DEVICE"
