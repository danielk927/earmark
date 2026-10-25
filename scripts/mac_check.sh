#!/usr/bin/env bash
# One-command Mac bring-up: builds and tests every part of Earmark, one independent step at a time.
#   scripts/mac_check.sh [--only <step>]... [--skip <step>]...
# Steps: preflight contracts-swift mac ios-uwb locator python-web
# Full output of each step goes to logs/mac_check/<step>.log. Exit code is non-zero if any step failed.
# Env: IOS_SIM="iPhone 16" (simulator name or UUID; default = first available iPhone).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
LOGS=$ROOT/logs/mac_check
ALL=(preflight contracts-swift mac ios-uwb locator python-web)
ONLY=(); SKIP=()

while [ $# -gt 0 ]; do
  case $1 in
    --only) ONLY+=("${2:?--only needs a step}"); shift 2 ;;
    --skip) SKIP+=("${2:?--skip needs a step}"); shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1 (steps: ${ALL[*]})" >&2; exit 2 ;;
  esac
done
for s in ${ONLY[@]+"${ONLY[@]}"} ${SKIP[@]+"${SKIP[@]}"}; do
  [[ " ${ALL[*]} " == *" $s "* ]] || { echo "unknown step: $s (steps: ${ALL[*]})" >&2; exit 2; }
done
wanted() {
  [[ " ${SKIP[*]-} " == *" $1 "* ]] && return 1
  [ ${#ONLY[@]} -eq 0 ] || [[ " ${ONLY[*]} " == *" $1 "* ]]
}

# ---- steps (each runs in a subshell; the first failing command fails the step) ----

step_preflight() {
  local miss=0 t v
  for t in xcodebuild swift xcodegen uv node; do
    if command -v "$t" >/dev/null; then
      v=--version; [ "$t" = xcodebuild ] && v=-version
      echo "$t: $("$t" $v 2>&1 | head -2 | tr '\n' ' ')"
    else echo "MISSING: $t"; miss=1; fi
  done
  [ $miss -eq 0 ] || { echo "Install hint: brew install xcodegen uv node; Xcode from the App Store (then xcode-select -s /Applications/Xcode.app)"; return 1; }
}

step_contracts_swift() { cd contracts/swift && swift test; }

step_mac() {
  # `make mac-test` pipes swift test through tail and hides its exit status, so run the same command directly.
  cd mac && swift test --scratch-path /tmp/earmark-mac-build && swift build --scratch-path /tmp/earmark-mac-build
}

pick_sim() {  # first available iPhone simulator, or $IOS_SIM (name or UUID)
  [ -n "${IOS_SIM:-}" ] && { echo "$IOS_SIM"; return; }
  xcrun simctl list devices available | grep -m1 'iPhone' | grep -oE '[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}'
}

step_ios_uwb() {
  local sim dest
  sim=$(pick_sim) || true
  [ -n "$sim" ] || { echo "no available iPhone simulator: install an iOS platform in Xcode > Settings > Platforms"; return 1; }
  if [[ $sim =~ ^[0-9A-F-]{36}$ ]]; then dest="platform=iOS Simulator,id=$sim"; else dest="platform=iOS Simulator,name=$sim"; fi
  echo "destination: $dest"
  cd ios/EarmarkUWB && xcodegen generate &&
  xcodebuild -project EarmarkUWB.xcodeproj -scheme EarmarkUWB -destination "$dest" \
    -derivedDataPath /tmp/EarmarkUWBBuild CODE_SIGNING_ALLOWED=NO test
}

step_locator() {  # mirrors .github/workflows/locator-ios.yml
  swift test --package-path locator/ios/EarmarkCore &&
  swift test --package-path locator/ios/EarmarkCore -Xswiftc -DFORCE_PORTABLE_DSP &&
  xcodegen generate --spec locator/ios/EarmarkLocator/project.yml &&
  xcodebuild -project locator/ios/EarmarkLocator/EarmarkLocator.xcodeproj -scheme EarmarkLocator -sdk iphonesimulator \
    -destination 'generic/platform=iOS Simulator' -derivedDataPath /tmp/LocatorBuild CODE_SIGNING_ALLOWED=NO build
}

step_python_web() {  # sequential on purpose (Python suites bind local ports); -k runs every suite even after a failure
  make -k contracts-test hub-test concierge-test ranging-test memory-test convex-test dashboard-test e2e-test
}

# ---- runner ----

mkdir -p "$LOGS"
RESULTS=()
for s in "${ALL[@]}"; do
  wanted "$s" || { RESULTS+=("SKIP|$s|-"); continue; }
  printf '>> %s ... ' "$s"
  start=$SECONDS
  ( "step_${s//-/_}" ) >"$LOGS/$s.log" 2>&1; rc=$?
  [ $rc -eq 0 ] && st=PASS || st=FAIL
  echo "$st ($((SECONDS - start))s)"
  RESULTS+=("$st|$s|logs/mac_check/$s.log")
done

echo; printf '%-6s %-16s %s\n' RESULT STEP LOG; printf '%-6s %-16s %s\n' ------ ---------------- ---
fail=0
for r in "${RESULTS[@]}"; do
  IFS='|' read -r st s log <<<"$r"
  printf '%-6s %-16s %s\n' "$st" "$s" "$log"
  [ "$st" = FAIL ] && fail=1
done
exit $fail
