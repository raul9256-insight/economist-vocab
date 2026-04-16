from __future__ import annotations

import os

from app.openai_enrichment import load_env_file, openai_client


def speech_api_ready() -> bool:
    load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def synthesize_pronunciation_audio(text: str) -> bytes:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("No text provided for pronunciation.")

    client = openai_client()
    model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip() or "gpt-4o-mini-tts"
    voice = os.environ.get("OPENAI_TTS_VOICE", "coral").strip() or "coral"
    instructions = (
        "Read this as a clean dictionary-style pronunciation. "
        "Speak naturally, clearly, and briefly. Avoid dramatic emotion or exaggerated emphasis."
    )

    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=cleaned,
        instructions=instructions,
        response_format="mp3",
        speed=0.82,
    )
    return bytes(response.content)
