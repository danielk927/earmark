#!/usr/bin/env bash
# Run the local Earmark stack: Convex (local backend), concierge, and the hub.
#
#   scripts/run_stack.sh sim [hub args...]   simulator (default: --interactive keyboard demo)
#   scripts/run_stack.sh live [hub args...]  real adapters (nfc_serial, ble_fobs)
#
# The hub runs in the foreground (so the interactive simulator gets the keyboard);
# Convex and the concierge run in the background with logs in logs/.
# Ctrl-C (or quitting the hub) stops everything this script started.
set -euo pipefail
cd "$(dirname "$0")/.."

# macOS flags the venvs' editable-install .pth files as hidden and Python then skips them; the packages go on the path directly.
export PYTHONPATH="$PWD/contracts/python:$PWD/services/hub:$PWD/services/concierge:$PWD/services/memory_agent:$PWD/services/ranging${PYTHONPATH:+:$PYTHONPATH}"

mode="${1:-sim}"
shift || true
mkdir -p logs
pids=()

cleanup() {
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

port_open() { nc -z 127.0.0.1 "$1" >/dev/null 2>&1; }

if [[ ! -f .env ]]; then
  echo "No .env: copy .env.example to .env and fill it in (services fall back to mocks for empty keys)." >&2
fi

if port_open 3210; then
  echo "convex: already running on :3210"
elif [[ -f .env.local ]] && grep -q '^CONVEX_DEPLOYMENT=' .env.local; then
  echo "convex: starting local backend (logs/convex-dev.log)"
  npx convex dev > logs/convex-dev.log 2>&1 &
  pids+=($!)
  for _ in $(seq 1 60); do port_open 3211 && break; sleep 0.5; done
  port_open 3211 || echo "convex: backend did not come up; the hub will queue events offline" >&2
else
  echo "convex: not configured (run 'make convex-init'); the hub runs offline" >&2
fi

echo "concierge: starting (logs/concierge.log)"
uv run --quiet --project services/concierge earmark-concierge > logs/concierge.log 2>&1 &
pids+=($!)

cat <<'EOF'

  Mac app:    make mac-open          (or open mac/build/Earmark.app)
  Dashboard:  make dashboard         (http://localhost:5173)
  Bus tap:    make tail              (in another terminal)

EOF

case "$mode" in
  sim)
    if [[ $# -eq 0 ]]; then set -- --interactive; fi
    uv run --quiet --project services/hub earmark-hub --adapters simulator "$@"
    ;;
  live)
    uv run --quiet --project services/hub earmark-hub --adapters nfc_serial,ble_fobs "$@"
    ;;
  *)
    echo "usage: $0 sim|live [hub args...]" >&2
    exit 2
    ;;
esac
