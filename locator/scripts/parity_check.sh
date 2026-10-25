#!/usr/bin/env bash
# No arguments: all 12 seeded acceptance WAVs. One WAV argument: default-config parity.
# EARMARK_CORE_DIR selects a sibling Swift checkout until the app PR is merged.
# EARMARK_PARITY_OUT preserves WAVs, truth, both JSONL streams, and comparison reports.
# EARMARK_PORTABLE_DSP=1 also exercises the Swift non-Accelerate implementation.
set -euo pipefail

if (( $# > 1 )); then
  echo 'Usage: parity_check.sh [input.wav]' >&2
  exit 2
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${PYTHON:-python3}
core=${EARMARK_CORE_DIR:-"$root/ios/EarmarkCore"}
if [[ ! -f "$core/Package.swift" ]]; then
  echo "Missing Swift package: $core. Set EARMARK_CORE_DIR to the EarmarkCore checkout." >&2
  exit 2
fi
if ! command -v swift >/dev/null; then
  echo 'Swift is required. Run on a Swift-enabled machine or the Locator parity CI job.' >&2
  exit 2
fi
out=${EARMARK_PARITY_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/earmark-parity.XXXXXX")}
mkdir -p "$out"
out=$(cd "$out" && pwd)
flags=(-c release)
if [[ ${EARMARK_PORTABLE_DSP:-0} == 1 ]]; then
  flags+=(-Xswiftc -DFORCE_PORTABLE_DSP)
fi
swift build --package-path "$core" "${flags[@]}" --product earmark-file
bin=$(swift build --package-path "$core" "${flags[@]}" --show-bin-path)

compare_wav() {
  local wav=$1 destination=$2 rate
  mkdir -p "$destination" || return
  "$python" "$root/tools/pipeline.py" "$wav" --out "$destination/fixes.jsonl" || return
  "$bin/earmark-file" "$wav" "$destination/swift.jsonl" || return
  rate=$("$python" -c 'import sys,wave; f=wave.open(sys.argv[1]); print(f.getframerate()); f.close()' "$wav") || return
  "$python" "$root/tools/compare_fixes.py" "$destination/fixes.jsonl" "$destination/swift.jsonl" \
    --sample-rate "$rate" | tee "$destination/comparison.json"
}

printf 'Parity output: %s\n' "$out"
if (( $# == 1 )); then
  compare_wav "$1" "$out/single"
else
  "$python" "$root/tools/verify_pipeline.py" --out "$out"
  failures=0
  for directory in "$out"/stand_on_mat-* "$out"/walk_to_cupboard-*; do
    if ! compare_wav "$directory/input.wav" "$directory"; then
      printf 'FAILED fixture: %s\n' "$directory" >&2
      failures=$((failures + 1))
    fi
  done
  if (( failures > 0 )); then
    printf '%s parity fixtures failed. Evidence: %s\n' "$failures" "$out" >&2
    exit 1
  fi
fi
printf 'All parity comparisons passed. Evidence: %s\n' "$out"
