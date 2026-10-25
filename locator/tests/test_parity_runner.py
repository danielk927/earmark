"""Shell orchestration test with a fake Swift executable, not DSP parity evidence."""

import os
import subprocess
import sys
from pathlib import Path


def test_runner_collects_later_fixtures_but_fails_overall(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    core = tmp_path / "core"
    core.mkdir()
    (core / "Package.swift").write_text("// Test stub only\n")
    swift = binaries / "swift"
    swift.write_text(
        '#!/bin/bash\nif [[ "$*" == *--show-bin-path* ]]; then printf "%s\\n" "$PARITY_TEST_BIN"; fi\n'
    )
    swift.chmod(0o755)
    runner = binaries / "earmark-file"
    runner.write_text(
        f"#!{sys.executable}\n"
        + """import shutil, sys
from pathlib import Path
wav = Path(sys.argv[1])
if wav.parent.name == 'stand_on_mat-clean-0':
    sys.exit(9)
shutil.copyfile(wav.parent / 'fixes.jsonl', sys.argv[2])
"""
    )
    runner.chmod(0o755)
    out = tmp_path / "output"
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "PARITY_TEST_BIN": str(binaries),
        "EARMARK_CORE_DIR": str(core),
        "EARMARK_PARITY_OUT": str(out),
        "PYTHON": sys.executable,
    }
    script = Path(__file__).resolve().parents[1] / "scripts" / "parity_check.sh"
    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 1, result.stderr
    assert "1 parity fixtures failed" in result.stderr
    assert "All parity comparisons passed" not in result.stdout
    assert len(list(out.glob("*/comparison.json"))) == 11
    assert (out / "walk_to_cupboard-effects-2" / "comparison.json").is_file()
