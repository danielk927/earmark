"""scripts/latency_report.py on a log produced by real concierge turns."""
import importlib.util
import subprocess
import sys

from conftest import Harness, snapshot
from earmark_concierge.config import REPO_ROOT
from earmark_contracts import Playback

SCRIPT = REPO_ROOT / "scripts" / "latency_report.py"


def load_script():
    spec = importlib.util.spec_from_file_location("latency_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_report_from_concierge_log(settings):
    h = Harness(settings)
    await h.feed(snapshot())
    out = await h.say("Where's the sugar?")
    uid = h.of("speak_text", out)[0]["utterance_id"]
    await h.feed(Playback(utterance_id=uid, event="started"))
    await h.say("something for my eggs")
    text = load_script().report(load_script().load(settings.latency_log))
    assert "2 final transcripts" in text
    assert "1 heard, 1 emitted only" in text
    assert "-> PASS" in text
    assert "'grammar': 2" in text


def test_report_budget_verdicts():
    mod = load_script()
    recs = [{"event": "final_transcript", "turn": "t1"},
            {"event": "speech_out", "turn": "t1", "since_final_ms": 2500.0},
            {"event": "intent", "path": "llm", "llm_status": "ok", "llm_ms": 900.0, "ms": 901.0},
            {"event": "resolve", "engine": "moss", "moss_ms": 6.0}]
    text = mod.report(recs)
    assert "FAIL" in text and "1 over maximum" in text
    assert mod.p90([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 9


def test_cli_without_log(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "missing.jsonl")], capture_output=True, text=True)
    assert r.returncode == 1 and "no latency log" in r.stderr
