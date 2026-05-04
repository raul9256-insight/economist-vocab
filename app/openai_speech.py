from __future__ import annotations

import os
from io import BytesIO
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from app.openai_enrichment import load_env_file, openai_client


def speech_api_ready() -> bool:
    load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def transcription_api_ready() -> bool:
    load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("ASSEMBLYAI_API_KEY", "").strip())


def is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "insufficient_quota" in text or "exceeded your current quota" in text or "billing" in text


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


def assemblyai_transcribe_pronunciation_audio(audio_bytes: bytes, *, filename: str = "pronunciation.webm", target_word: str = "") -> str:
    load_env_file()
    api_key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set.")
    import json

    upload_req = urlrequest.Request(
        "https://api.assemblyai.com/v2/upload",
        data=audio_bytes,
        headers={"authorization": api_key, "content-type": "application/octet-stream"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(upload_req, timeout=45) as response:
            upload_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AssemblyAI upload failed: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"AssemblyAI upload failed: {exc}") from exc

    upload_url = upload_payload.get("upload_url")
    if not upload_url:
        raise RuntimeError("AssemblyAI upload returned no upload_url.")

    transcript_req = urlrequest.Request(
        "https://api.assemblyai.com/v2/transcript",
        data=json.dumps(
            {
                "audio_url": upload_url,
                "language_code": "en",
                "speech_model": os.environ.get("ASSEMBLYAI_SPEECH_MODEL", "universal").strip() or "universal",
                "word_boost": [target_word] if target_word else [],
                "boost_param": "high" if target_word else "default",
            }
        ).encode("utf-8"),
        headers={"authorization": api_key, "content-type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(transcript_req, timeout=45) as response:
            transcript_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AssemblyAI transcription failed: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"AssemblyAI transcription failed: {exc}") from exc

    transcript_id = transcript_payload.get("id")
    if not transcript_id:
        raise RuntimeError("AssemblyAI transcription returned no id.")

    status_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
    for _ in range(30):
        status_req = urlrequest.Request(status_url, headers={"authorization": api_key}, method="GET")
        try:
            with urlrequest.urlopen(status_req, timeout=20) as response:
                status_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AssemblyAI transcription polling failed: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"AssemblyAI transcription polling failed: {exc}") from exc
        status = str(status_payload.get("status", "")).lower()
        if status == "completed":
            return str(status_payload.get("text", "") or "").strip()
        if status == "error":
            raise RuntimeError(f"AssemblyAI transcription failed: {status_payload.get('error', 'unknown error')}")
        import time

        time.sleep(1)
    raise RuntimeError("AssemblyAI transcription timed out.")


def transcribe_pronunciation_audio(audio_bytes: bytes, *, filename: str = "pronunciation.webm", target_word: str = "") -> str:
    if not audio_bytes:
        raise ValueError("No audio provided for transcription.")

    load_env_file()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
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
        except Exception as exc:
            if not os.environ.get("ASSEMBLYAI_API_KEY", "").strip() or not is_quota_error(exc):
                raise

    return assemblyai_transcribe_pronunciation_audio(audio_bytes, filename=filename, target_word=target_word)
