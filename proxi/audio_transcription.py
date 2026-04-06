"""OpenAI-backed transcription helper for browser voice input."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI

from proxi.security.key_store import get_key_value

DEFAULT_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
FALLBACK_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_FALLBACK_MODEL", "whisper-1")


def resolve_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY") or get_key_value("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Add it in the React frontend settings.")
    return api_key


def transcribe_audio(audio_path: Path, model: str | None = None) -> tuple[str, str]:
    client = OpenAI(api_key=resolve_openai_api_key())
    candidates = [m for m in [model or DEFAULT_TRANSCRIPTION_MODEL, FALLBACK_TRANSCRIPTION_MODEL] if m]

    last_error: Exception | None = None
    for candidate in dict.fromkeys(candidates):
        try:
            with audio_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(model=candidate, file=audio_file)
            return response.text.strip(), candidate
        except Exception as exc:  # pragma: no cover - surfaced to the frontend
            last_error = exc

    if last_error is None:
        raise RuntimeError("OpenAI transcription failed")
    raise last_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe audio with OpenAI")
    parser.add_argument("--file", required=True, help="Path to the recorded audio file")
    parser.add_argument("--model", help="Override the transcription model")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    audio_path = Path(args.file)

    try:
        if not audio_path.exists():
            raise ValueError(f"Audio file does not exist: {audio_path}")

        text, model = transcribe_audio(audio_path, model=args.model)
        print(json.dumps({"ok": True, "text": text, "model": model}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())