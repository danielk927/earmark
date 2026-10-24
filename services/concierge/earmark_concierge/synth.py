"""Pre-synthesize config/phrases.json into config/phrases/<phrase_id>.wav with Cartesia's bytes endpoint.

Same model snapshot, voice, encoding, and sample rate as live speech, so cached
phrases sound identical (docs/vendor-notes/cartesia.md, section 5).
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .config import Settings
from .speech import load_phrases

log = logging.getLogger(__name__)


class SynthError(RuntimeError):
    pass


def synth_phrases(settings: Settings, out_dir: Path | None = None,
                  transport: httpx.BaseTransport | None = None) -> list[Path]:
    missing = [n for n, v in (("CARTESIA_API_KEY", settings.cartesia_api_key),
                              ("CARTESIA_VOICE_ID", settings.voice_id)) if not v]
    if missing:
        raise SynthError(f"cannot synthesize phrases: {' and '.join(missing)} not set "
                         "(put them in the repo-root .env). Until then the Mac app speaks "
                         "speak_cached text with the system voice.")
    out = out_dir or settings.phrases_dir
    out.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {settings.cartesia_api_key}",
               "Cartesia-Version": settings.cartesia_version}
    written: list[Path] = []
    with httpx.Client(timeout=30.0, transport=transport) as client:
        for phrase_id, text in load_phrases(settings.phrases_path).items():
            body = {
                "model_id": settings.tts_model, "transcript": text, "voice": settings.voice_id,
                "language": "en",
                "output_format": {"container": "wav", "encoding": settings.tts_encoding,
                                  "sample_rate": settings.tts_sample_rate},
            }
            r = client.post(settings.tts_bytes_url, headers=headers, json=body)
            if r.status_code != 200:
                raise SynthError(f"{phrase_id}: HTTP {r.status_code} {r.text[:200]}")
            path = out / f"{phrase_id}.wav"
            path.write_bytes(r.content)
            written.append(path)
            log.info("wrote %s (%d bytes)", path, len(r.content))
    return written
