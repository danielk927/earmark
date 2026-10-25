#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
build="$(mktemp -d)"
trap 'rm -rf -- "$build"' EXIT
cxx="${CXX:-g++}"
for map in WROOM WROVER; do
  "$cxx" -std=c++17 -Wall -Wextra -Werror -D"BOARD_$map" \
    "$root/locator/firmware/tests/core_test.cpp" -o "$build/core-test"
  "$build/core-test"
done
"$cxx" -std=c++17 -Wall -Wextra -Werror \
  "$root/locator/firmware/tests/generate_sweep.cpp" -o "$build/generate-sweep"
"$build/generate-sweep" > "$build/sweep_table.h"
cmp "$build/sweep_table.h" "$root/locator/firmware/beacons/sweep_table.h"
bash -n "$root/locator/scripts/flash.sh"
python3 "$root/locator/firmware/tests/test_flash.py"
echo 'PASS: both default pin maps, generated sweep matches, flash-script syntax'
