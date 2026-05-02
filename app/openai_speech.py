from __future__ import annotations

import os
from io import BytesIO

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


def transcribe_pronunciation_audio(audio_bytes: bytes, *, filename: str = "pronunciation.webm", target_word: str = "") -> str:
    if not audio_bytes:
        raise ValueError("No audio provided for transcription.")

    client = openai_client()
    model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip() or "gpt-4o-mini-transcribe"
    audio_file = BytesIO(audio_bytes)
    audio_file.name = filename or "pronunciation.webm"
    prompt = "The speaker is saying one English vocabulary word."
    if target_word:
        prompt = f'The speaker is saying the English vocabulary word "{target_word}".'
    transcription = client.audio.transcriptions.create(
        model=model,
        file=audio_file,
        language="en",
        prompt=prompt,
    )
    return str(getattr(transcription, "text", "") or "").strip()
