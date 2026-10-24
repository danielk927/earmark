"""synth-phrases: fails clearly without a key; with a (mocked) bytes endpoint writes every phrase."""
import json

import httpx
import pytest

from conftest import make_settings
from earmark_concierge.cli import main
from earmark_concierge.speech import load_phrases
from earmark_concierge.synth import SynthError, synth_phrases


def test_fails_clearly_without_key(tmp_path, capsys, monkeypatch):
    for k in ("CARTESIA_API_KEY", "CARTESIA_VOICE_ID"):
        monkeypatch.setenv(k, "")
    assert main(["synth-phrases"]) == 2
    err = capsys.readouterr().err
    assert "CARTESIA_API_KEY and CARTESIA_VOICE_ID not set" in err
    with pytest.raises(SynthError):
        synth_phrases(make_settings(tmp_path, cartesia_api_key="k"))


def test_writes_every_phrase_with_live_speech_settings(tmp_path):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url, req.headers["authorization"], req.headers["cartesia-version"],
                     json.loads(req.content)))
        return httpx.Response(200, content=b"RIFF....WAVE")

    s = make_settings(tmp_path, cartesia_api_key="sk_car_test", voice_id="voice-123")
    paths = synth_phrases(s, out_dir=tmp_path / "phrases", transport=httpx.MockTransport(handler))
    phrases = load_phrases(s.phrases_path)
    assert sorted(p.stem for p in paths) == sorted(phrases)
    assert all(p.read_bytes() == b"RIFF....WAVE" for p in paths)
    url, auth, version, body = seen[0]
    assert str(url) == "https://api.cartesia.ai/tts/bytes" and auth == "Bearer sk_car_test" and version == "2026-08-14"
    assert body["model_id"] == "sonic-3.6-2026-08-27" and body["voice"] == "voice-123"
    assert body["output_format"] == {"container": "wav", "encoding": "pcm_f32le", "sample_rate": 48000}
    assert body["transcript"] == phrases[paths[0].stem]
