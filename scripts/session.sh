#!/usr/bin/env bash
# One command for a whole test session: hub, voice, room page, Mac app, and the room setup in this terminal.
#
#   scripts/session.sh [recalibrate|setup|sim] [beacons, e.g. "B1 B2"]
#
#   recalibrate   beacons already placed (`make beacons`, with a tape): stand on the mat for 30 s (default)
#   setup         walk the floor marks; the Mac places the beacons (optional, less exact than a tape)
#   sim           virtual phone and virtual beacons (no hardware)
#
# Real phones are recorded to logs/session-<time>.wav (and a .json next to it), so a bad run can be replayed.
# The hub starts with NO items (--fresh): add them by voice ("I am leaving my keys here") as you walk.
# The hub, voice and room page run in the background (logs in logs/). The room setup runs in the
# foreground so you can press Enter on each mark. Ctrl-C stops everything this script started.
# NO_MAC=1 skips opening the Mac app; NO_DASHBOARD=1 skips the room page.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/contracts/python:$PWD/services/hub:$PWD/services/concierge:$PWD/services/memory_agent:$PWD/services/ranging${PYTHONPATH:+:$PYTHONPATH}"

mode="${1:-recalibrate}"
only="${2:-}"
mkdir -p logs
pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]:-}"; do [[ -n "$pid" ]] && kill "$pid" 2>/dev/null; done
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

port_open() { nc -z 127.0.0.1 "$1" >/dev/null 2>&1; }
for p in 8765 8766; do
  if port_open "$p"; then
    echo "port $p is already in use: an earlier hub or room setup is still running. Stop it (Ctrl-C in its terminal) and try again." >&2
    exit 1
  fi
done

echo "hub: starting (logs/hub.log)"
uv run --quiet --project services/hub earmark-hub --adapters simulator --fresh > logs/hub.log 2>&1 &
pids+=($!)
for _ in $(seq 1 40); do port_open 8765 && break; sleep 0.5; done
port_open 8765 || { echo "hub did not start; see logs/hub.log" >&2; exit 1; }

echo "voice: starting (logs/concierge.log)"
set -a; [[ -f .env ]] && source .env; set +a
uv run --quiet --project services/concierge earmark-concierge > logs/concierge.log 2>&1 &
pids+=($!)

if port_open 5173; then
  echo "room page: already running, open http://localhost:5173/room"
elif [[ -z "${NO_DASHBOARD:-}" ]]; then
  echo "room page: starting (logs/dashboard.log), open http://localhost:5173/room"
  (cd dashboard && npm run dev > ../logs/dashboard.log 2>&1) &
  pids+=($!)
fi

if [[ -z "${NO_MAC:-}" ]]; then
  if [[ -d mac/build/Earmark.app ]]; then
    echo "Mac app: opening (if it is old, run 'make mac' first)"
    open -n mac/build/Earmark.app --args --listen=ptt   # hold Space in the Mac app to talk
  else
    echo "Mac app is not built yet: run 'make mac', then 'make mac-open'" >&2
  fi
fi

echo
echo "Now the phones. This terminal runs the room setup (recalibrate: stand on the mat for 30 s)."
echo
record=(--record "$PWD/logs/session-$(date +%Y%m%d-%H%M%S).wav")  # absolute: the ranging step runs in services/ranging
case "$mode" in
  recalibrate) args=(listen --calibrate-at 0 0 1.25 --band 12000 16000 --min-snr 12 --calibration-seconds 30 "${record[@]}") ;;
  setup)       args=(listen --setup --band 12000 16000 --min-snr 12 "${record[@]}") ;;
  sim)         args=(listen --setup --sim --band 12000 16000) ;;
  *) echo "usage: $0 [recalibrate|setup|sim] [\"B1 B2\"]" >&2; exit 2 ;;
esac
# shellcheck disable=SC2206
[[ -n "$only" ]] && args+=(--only $only)
(cd services/ranging && uv run --quiet python -m earmark_ranging.cli "${args[@]}")
