# Earmark locator task runner (LOCATOR_BRIEF.md section 9.2).
# Run from locator/. `test` works from PR 1 onward; the other targets call
# scripts and tools that later Phase A PRs add (firmware, tools, iOS parity).

PYTHON ?= python3

.PHONY: test sim parity flash fakehub bandtest

# Contract + config tests (contracts/, config/, tests/).
test:
	$(PYTHON) -m pytest tests/ -v

# Synthetic beacon mic recordings (tools/sim_beacons.py — tools PR).
sim:
	$(PYTHON) tools/sim_beacons.py

# Swift/Python parity check (scripts/parity_check.sh — iOS PR, brief section 9.4).
parity:
	bash scripts/parity_check.sh

# Compile + flash the beacon firmware (scripts/flash.sh — firmware PR).
flash:
	bash scripts/flash.sh

# Stand-in hub for end-to-end testing (tools/fake_hub.py — tools PR).
fakehub:
	$(PYTHON) tools/fake_hub.py

# Received-level band recommendation from a recorded sweep WAV
# (tools/band_test.py — tools PR). Usage: make bandtest FILE=recording.wav
bandtest:
	@if [ -z "$(FILE)" ]; then \
		echo "usage: make bandtest FILE=path/to/recording.wav" >&2; exit 2; \
	fi
	$(PYTHON) tools/band_test.py "$(FILE)"

# Test sound to play from any speaker when there is no beacon hardware yet (tools/make_test_sweep.py).
.PHONY: testsweep
testsweep:
	$(PYTHON) tools/make_test_sweep.py out/test_sweep.wav
