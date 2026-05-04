from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from app.db import definitions_for_word, parts_of_speech_for_word


def load_env_file(dotenv_path: Path = Path(".env")) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def openai_client():
    load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your environment or .env file.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is not installed. Run: python3 -m pip install openai") from exc
    return OpenAI(api_key=api_key)


def openai_model() -> str:
    load_env_file()
    return os.environ.get("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"


def sentence_ai_ready() -> bool:
    load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip())


def is_openai_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "insufficient_quota" in text or "exceeded your current quota" in text or "billing" in text


def extract_json_object(text: str) -> dict[str, object]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def normalize_sentence_usage_result(parsed: dict[str, object]) -> dict[str, object]:
    for key in ["meaning_score", "grammar_score", "naturalness_score", "exam_usefulness_score", "overall_score"]:
        parsed[key] = max(0, min(100, int(parsed.get(key, 0) or 0)))
    parsed["usage_correct"] = bool(parsed.get("usage_correct", False))
    parsed["grammar_correct"] = bool(parsed.get("grammar_correct", False))
    status = str(parsed.get("status") or "").strip()
    if status not in {"Mastered", "Almost mastered", "Needs review", "Relearn"}:
        overall = int(parsed.get("overall_score", 0) or 0)
        status = "Mastered" if overall >= 90 else "Almost mastered" if overall >= 75 else "Needs review" if overall >= 60 else "Relearn"
    parsed["status"] = status
    for key in ["feedback", "corrected_sentence", "suggested_upgrade"]:
        parsed[key] = str(parsed.get(key, "") or "").strip()
    return parsed


def gemini_sentence_usage_check(payload: dict[str, object], lang: str) -> dict[str, object]:
    load_env_file()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite"
    prompt = (
        f"{SENTENCE_USAGE_SYSTEM_PROMPT}\n\n"
        "Return one valid JSON object only. Do not use markdown. "
        "The object must contain these exact keys: usage_correct, grammar_correct, meaning_score, "
        "grammar_score, naturalness_score, exam_usefulness_score, overall_score, status, feedback, "
        "corrected_sentence, suggested_upgrade.\n\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urlrequest.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=45) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini sentence check failed: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gemini sentence check failed: {exc}") from exc
    candidates = response_payload.get("candidates", [])
    text = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts)
    if not text:
        raise RuntimeError("Gemini sentence check returned no text.")
    return normalize_sentence_usage_result(extract_json_object(text))


def words_for_generation(conn: sqlite3.Connection, limit: int, band_rank: int | None = None) -> list[sqlite3.Row]:
    clauses = [
        "(word_enrichment.word_id IS NULL OR word_enrichment.english_definition = '' OR word_enrichment.example_sentence = '' OR word_enrichment.synonyms_json = '[]')"
    ]
    params: list[object] = []
    if band_rank is not None:
        clauses.append("words.best_band_rank = ?")
        params.append(band_rank)
    sql = f"""
        SELECT words.id, words.lemma, words.best_band_label, words.best_band_rank
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        WHERE {' AND '.join(clauses)}
        ORDER BY words.best_band_rank, words.lemma
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def prompt_payload(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    payload = []
    for row in rows:
        payload.append(
            {
                "lemma": row["lemma"],
                "band_label": row["best_band_label"],
                "parts_of_speech": parts_of_speech_for_word(conn, row["id"]),
                "chinese_definitions": definitions_for_word(conn, row["id"])[:5],
            }
        )
    return payload


RESPONSE_SCHEMA = {
    "type": "json_schema",
    "name": "vocab_enrichment_batch",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "lemma": {"type": "string"},
                        "english_definition": {"type": "string"},
                        "example_sentence": {"type": "string"},
                        "synonyms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["lemma", "english_definition", "example_sentence", "synonyms"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}

AI_INSIGHT_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "name": "word_ai_insight",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "simple_explanation_en": {"type": "string"},
            "simple_explanation_zh": {"type": "string"},
            "nuance_note": {"type": "string"},
            "compare_words": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["word", "note"],
                    "additionalProperties": False,
                },
            },
            "business_example": {"type": "string"},
            "prompt_example": {"type": "string"},
            "usage_warning": {"type": "string"},
        },
        "required": [
            "simple_explanation_en",
            "simple_explanation_zh",
            "nuance_note",
            "compare_words",
            "business_example",
            "prompt_example",
            "usage_warning",
        ],
        "additionalProperties": False,
    },
}

SENTENCE_USAGE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "name": "word_sentence_usage_check",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "usage_correct": {"type": "boolean"},
            "grammar_correct": {"type": "boolean"},
            "meaning_score": {"type": "integer"},
            "grammar_score": {"type": "integer"},
            "naturalness_score": {"type": "integer"},
            "exam_usefulness_score": {"type": "integer"},
            "overall_score": {"type": "integer"},
            "status": {"type": "string"},
            "feedback": {"type": "string"},
            "corrected_sentence": {"type": "string"},
            "suggested_upgrade": {"type": "string"},
        },
        "required": [
            "usage_correct",
            "grammar_correct",
            "meaning_score",
            "grammar_score",
            "naturalness_score",
            "exam_usefulness_score",
            "overall_score",
            "status",
            "feedback",
            "corrected_sentence",
            "suggested_upgrade",
        ],
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = (
    "You are enriching an English vocabulary database for a learner. "
    "For each word, produce a concise learner-friendly English definition, one natural example sentence, "
    "and 2 to 4 clear synonyms. Keep the meaning aligned with the provided Chinese definitions and part of speech. "
    "Prefer contemporary, neutral English. The example sentence should use the target word naturally and clearly. "
    "Return structured JSON only."
)

AI_INSIGHT_SYSTEM_PROMPT = (
    "You are helping build an intelligent vocabulary learning platform. "
    "For one English word, produce short learner-friendly AI insight fields: "
    "a plain English explanation, a short Traditional Chinese explanation, "
    "a nuance note about how the word feels or differs from nearby words, "
    "2 comparison words with brief notes, one business-use example sentence, "
    "one AI prompt example using the word naturally, and one short usage warning. "
    "Keep all outputs concise, practical, and clear for learners. "
    "Use Traditional Chinese for the Chinese explanation. "
    "Return structured JSON only."
)

SENTENCE_USAGE_SYSTEM_PROMPT = (
    "You are an English vocabulary coach for Hong Kong DSE students first, then IELTS and SAT learners. "
    "Evaluate whether a student's sentence uses the target vocabulary word correctly and naturally. "
    "Check meaning, grammar, naturalness, and exam usefulness. "
    "For exam usefulness, prioritise HKDSE English Paper 2 Writing: argumentative, expository, proposal, article, speech, and letter tasks. "
    "Tell the learner whether the sentence is too simple, too spoken, too vague, or strong enough for DSE writing. "
    "Give concise, practical feedback. If the sentence is wrong or awkward, provide a corrected sentence. "
    "Always provide a stronger suggested upgrade sentence suitable for DSE Paper 2 writing. "
    "Use the requested feedback language for feedback, but keep the corrected sentence and suggested upgrade in English. "
    "Return structured JSON only. Scores must be integers from 0 to 100. "
    "Status must be one of: Mastered, Almost mastered, Needs review, Relearn."
)


def generate_enrichment_batch(conn: sqlite3.Connection, *, limit: int, band_rank: int | None = None) -> dict[str, int]:
    rows = words_for_generation(conn, limit=limit, band_rank=band_rank)
    if not rows:
        return {"selected": 0, "updated": 0}
    client = openai_client()
    payload = prompt_payload(conn, rows)
    response = client.responses.create(
        model=openai_model(),
        instructions=SYSTEM_PROMPT,
        input=json.dumps({"items": payload}, ensure_ascii=False),
        text={"format": RESPONSE_SCHEMA},
    )
    parsed = json.loads(response.output_text)
    by_lemma = {item["lemma"].strip().lower(): item for item in parsed.get("items", [])}
    updated = 0
    for row in rows:
        item = by_lemma.get(row["lemma"].strip().lower())
        if not item:
            continue
        synonyms = [syn.strip() for syn in item.get("synonyms", []) if syn.strip()]
        conn.execute(
            """
            INSERT INTO word_enrichment (
                word_id, english_definition, synonyms_json, example_sentence, sentence_distractors_json
            )
            VALUES (?, ?, ?, ?, '[]')
            ON CONFLICT(word_id) DO UPDATE SET
                english_definition = excluded.english_definition,
                synonyms_json = excluded.synonyms_json,
                example_sentence = excluded.example_sentence,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["id"],
                item.get("english_definition", "").strip(),
                json.dumps(synonyms, ensure_ascii=False),
                item.get("example_sentence", "").strip(),
            ),
        )
        updated += 1
    conn.commit()
    return {"selected": len(rows), "updated": updated}


def generate_ai_insight_for_word(conn: sqlite3.Connection, *, word_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, lemma, best_band_label
        FROM words
        WHERE id = ?
        """,
        (word_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Word {word_id} not found")

    source_rows = conn.execute(
        """
        SELECT meanings_json, extra_json
        FROM source_entries
        WHERE word_id = ?
        ORDER BY band_rank, workbook_name, row_number
        """,
        (word_id,),
    ).fetchall()
    chinese_definitions: list[str] = []
    for source_row in source_rows:
        meanings = definitions_for_word(conn, word_id)
        for meaning in meanings:
            if meaning not in chinese_definitions:
                chinese_definitions.append(meaning)
        if chinese_definitions:
            break

    enrichment = conn.execute(
        """
        SELECT english_definition, example_sentence, synonyms_json
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word_id,),
    ).fetchone()

    payload = {
        "lemma": row["lemma"],
        "band_label": row["best_band_label"],
        "parts_of_speech": parts_of_speech_for_word(conn, word_id),
        "chinese_definitions": chinese_definitions[:5],
        "english_definition": enrichment["english_definition"] if enrichment else "",
        "example_sentence": enrichment["example_sentence"] if enrichment else "",
        "synonyms": json.loads(enrichment["synonyms_json"]) if enrichment and enrichment["synonyms_json"] else [],
    }

    client = openai_client()
    response = client.responses.create(
        model=openai_model(),
        instructions=AI_INSIGHT_SYSTEM_PROMPT,
        input=json.dumps(payload, ensure_ascii=False),
        text={"format": AI_INSIGHT_RESPONSE_SCHEMA},
    )
    parsed = json.loads(response.output_text)

    compare_words = [
        {
            "word": str(item.get("word", "")).strip(),
            "note": str(item.get("note", "")).strip(),
        }
        for item in parsed.get("compare_words", [])
        if str(item.get("word", "")).strip()
    ]

    conn.execute(
        """
        INSERT INTO word_enrichment (
            word_id,
            ai_simple_explanation_en,
            ai_simple_explanation_zh,
            ai_nuance_note,
            ai_compare_words_json,
            ai_business_example,
            ai_prompt_example,
            ai_usage_warning
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(word_id) DO UPDATE SET
            ai_simple_explanation_en = excluded.ai_simple_explanation_en,
            ai_simple_explanation_zh = excluded.ai_simple_explanation_zh,
            ai_nuance_note = excluded.ai_nuance_note,
            ai_compare_words_json = excluded.ai_compare_words_json,
            ai_business_example = excluded.ai_business_example,
            ai_prompt_example = excluded.ai_prompt_example,
            ai_usage_warning = excluded.ai_usage_warning,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            word_id,
            str(parsed.get("simple_explanation_en", "")).strip(),
            str(parsed.get("simple_explanation_zh", "")).strip(),
            str(parsed.get("nuance_note", "")).strip(),
            json.dumps(compare_words, ensure_ascii=False),
            str(parsed.get("business_example", "")).strip(),
            str(parsed.get("prompt_example", "")).strip(),
            str(parsed.get("usage_warning", "")).strip(),
        ),
    )
    conn.commit()
    return parsed


def evaluate_sentence_usage(
    conn: sqlite3.Connection,
    *,
    word_id: int,
    sentence: str,
    lang: str = "en",
) -> dict[str, object]:
    cleaned_sentence = (sentence or "").strip()
    if not cleaned_sentence:
        raise RuntimeError("No sentence provided.")

    row = conn.execute(
        """
        SELECT id, lemma, best_band_label
        FROM words
        WHERE id = ?
        """,
        (word_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Word {word_id} not found")

    enrichment = conn.execute(
        """
        SELECT english_definition, example_sentence, synonyms_json
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word_id,),
    ).fetchone()

    payload = {
        "target_word": row["lemma"],
        "band_label": row["best_band_label"],
        "parts_of_speech": parts_of_speech_for_word(conn, word_id),
        "chinese_definitions": definitions_for_word(conn, word_id)[:5],
        "english_definition": enrichment["english_definition"] if enrichment else "",
        "example_sentence": enrichment["example_sentence"] if enrichment else "",
        "synonyms": json.loads(enrichment["synonyms_json"]) if enrichment and enrichment["synonyms_json"] else [],
        "student_sentence": cleaned_sentence,
        "feedback_language": lang,
    }

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = openai_client()
            response = client.responses.create(
                model=openai_model(),
                instructions=SENTENCE_USAGE_SYSTEM_PROMPT,
                input=json.dumps(payload, ensure_ascii=False),
                text={"format": SENTENCE_USAGE_RESPONSE_SCHEMA},
            )
            return normalize_sentence_usage_result(json.loads(response.output_text))
        except Exception as exc:
            if not os.environ.get("GEMINI_API_KEY", "").strip() or not is_openai_quota_error(exc):
                raise

    return gemini_sentence_usage_check(payload, lang)
