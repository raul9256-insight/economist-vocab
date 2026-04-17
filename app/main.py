from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    band_summary,
    definitions_for_word,
    fetch_stats,
    get_connection,
    letters_for_band,
    parts_of_speech_for_word,
)
from app.enrichment_io import export_template, import_enrichment_rows, iter_import_rows
from app.openai_enrichment import generate_enrichment_batch, load_env_file
from app.openai_speech import speech_api_ready, synthesize_pronunciation_audio
from economist_vocab import DEFAULT_DB_PATH


BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR.parent / "exports"
app = FastAPI(title="Economist Vocabulary Lab")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

USER_ID = 1
TEST_QUESTION_COUNT = 15
LEARNING_WORD_COUNT = 5
SUPPORTED_LANGS = {"en", "zh-Hant"}

TRANSLATIONS = {
    "en": {
        "brand_title": "Economist Lab",
        "brand_subtitle": "Personal vocabulary system",
        "nav_dashboard": "Dashboard",
        "nav_test": "Level Test",
        "nav_learning": "Learning",
        "nav_dictionary": "Dictionary",
        "nav_missed": "Missed Words",
        "nav_bulk": "Bulk Import",
        "sidebar_flow_label": "Study Flow",
        "sidebar_flow_title": "Test, learn, review.",
        "sidebar_flow_text": "Use the level test to find your band, then build richer word cards over time.",
        "sidebar_flow_link": "Open learning",
        "topbar_search": "Search for words, bands, or definitions...",
        "topbar_project": "The Economist vocabulary project",
        "home_eyebrow": "Dashboard",
        "home_title": "Hello, Lawrence.",
        "home_lede": "Build your Economist vocabulary with a clear daily flow: test, learn, and review.",
        "motto_label": "Motto",
        "motto_quote": "Without grammar very little can be conveyed, without vocabulary nothing can be conveyed.",
        "motto_cite": "Wilkins, 1972, p. 111",
        "tests_taken": "tests taken",
        "current_band": "current band",
        "today_goal": "Today's Goal",
        "keep_moving": "Keep your study moving",
        "placement": "Placement",
        "practice": "Practice",
        "review": "Review",
        "study_flow": "Study flow",
        "goal_note": "Start with your level test, then work the recommended band, then check missed words or the dictionary.",
        "start_test": "Start Level Test",
        "continue_learning": "Continue Learning",
        "your_progress": "Your Progress",
        "at_a_glance": "At a glance",
        "total_words": "Total Words",
        "learning_runs": "Learning Runs",
        "missed_words": "Missed Words",
        "synonym_ready": "Synonym Ready",
        "today_words": "Today's Words",
        "start_with_few": "Start with a few words",
        "today_words_note": "Open one word card and enrich it with clearer definitions, examples, and synonyms.",
        "view_all": "View all",
        "recommended_for_you": "Recommended For You",
        "choose_next": "Choose your next step",
        "choose_next_note": "Three fast ways to keep momentum without overthinking what to do next.",
        "learning_session": "Learning Session",
        "frequency_bands": "Frequency Bands",
        "browse_count": "Browse by appearance count",
        "open_dictionary": "Open dictionary",
        "bands_note": "Higher bands mean the word appeared more often in your Economist source data over the last 10 years.",
        "core_steps": "3 core steps",
        "flow_sequence": "Test → Learn → Review",
        "latest_result": "Latest result: {band}.",
        "first_test_prompt": "Take your first test to unlock a starting band.",
        "latest_score": "Latest score: {score}/{total}.",
        "start_short_session": "Start a short session in your recommended band.",
        "review_queue_count": "{count} words are waiting in your review list.",
    },
    "zh-Hant": {
        "brand_title": "經濟學人詞彙實驗室",
        "brand_subtitle": "個人詞彙學習系統",
        "nav_dashboard": "首頁總覽",
        "nav_test": "程度測驗",
        "nav_learning": "學習練習",
        "nav_dictionary": "詞典查詢",
        "nav_missed": "錯題複習",
        "nav_bulk": "批次匯入",
        "sidebar_flow_label": "學習流程",
        "sidebar_flow_title": "先測驗，再學習，再複習。",
        "sidebar_flow_text": "先用程度測驗找出適合的頻率帶，再逐步補齊每個單字卡的內容。",
        "sidebar_flow_link": "前往學習",
        "topbar_search": "搜尋單字、頻率帶或定義...",
        "topbar_project": "經濟學人詞彙專案",
        "home_eyebrow": "首頁總覽",
        "home_title": "Lawrence，你好。",
        "home_lede": "把《經濟學人》詞彙整理成清楚的每日學習流程：測驗、練習、複習。",
        "motto_label": "學習信念",
        "motto_quote": "Without grammar very little can be conveyed, without vocabulary nothing can be conveyed.",
        "motto_cite": "Wilkins, 1972, p. 111",
        "tests_taken": "已完成測驗",
        "current_band": "目前建議頻率帶",
        "today_goal": "今日目標",
        "keep_moving": "讓今天的學習持續前進",
        "placement": "測驗",
        "practice": "練習",
        "review": "複習",
        "study_flow": "學習流程",
        "goal_note": "先做程度測驗，再練習建議頻率帶，最後查看錯題或進入詞典補充內容。",
        "start_test": "開始程度測驗",
        "continue_learning": "繼續學習",
        "your_progress": "你的進度",
        "at_a_glance": "快速總覽",
        "total_words": "總單字數",
        "learning_runs": "學習次數",
        "missed_words": "待複習錯題",
        "synonym_ready": "已補同義詞",
        "today_words": "今日單字",
        "start_with_few": "先從幾個單字開始",
        "today_words_note": "先打開幾張單字卡，補齊更清楚的定義、例句與同義詞。",
        "view_all": "查看全部",
        "recommended_for_you": "下一步建議",
        "choose_next": "選擇你現在最適合的下一步",
        "choose_next_note": "用三個最快的入口保持學習節奏，不需要每次重新想要做什麼。",
        "learning_session": "學習練習",
        "frequency_bands": "頻率帶",
        "browse_count": "依出現次數瀏覽",
        "open_dictionary": "打開詞典",
        "bands_note": "頻率帶數字越高，表示該字在你近十年的《經濟學人》資料中出現得越多。",
        "core_steps": "3 個核心步驟",
        "flow_sequence": "測驗 → 練習 → 複習",
        "latest_result": "最近結果：{band}。",
        "first_test_prompt": "先完成第一次測驗，系統才會推薦起始頻率帶。",
        "latest_score": "最近分數：{score}/{total}。",
        "start_short_session": "先從建議頻率帶開始做一個短練習。",
        "review_queue_count": "目前有 {count} 個錯題等待你複習。",
    },
}


def db_conn() -> sqlite3.Connection:
    return get_connection(DEFAULT_DB_PATH)


def get_lang(request: Request) -> str:
    query_lang = request.query_params.get("lang")
    if query_lang in SUPPORTED_LANGS:
        return query_lang
    cookie_lang = request.cookies.get("lang")
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    return "en"


def translate(lang: str, key: str, **kwargs) -> str:
    text = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS["en"].get(key) or key
    return text.format(**kwargs)


def build_lang_url(request: Request, lang: str) -> str:
    params = list(request.query_params.multi_items())
    filtered = [(key, value) for key, value in params if key != "lang"]
    filtered.append(("lang", lang))
    query = urlencode(filtered)
    return f"{request.url.path}?{query}" if query else request.url.path


def render(request: Request, template_name: str, **context) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    context.update(
        {
            "lang": lang,
            "t": lambda key, **kwargs: translate(lang, key, **kwargs),
            "lang_url": lambda target_lang: build_lang_url(request, target_lang),
        }
    )
    response = templates.TemplateResponse(name=template_name, request=request, context=context)
    response.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return response


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    request.state.lang = get_lang(request)
    response = await call_next(request)
    query_lang = request.query_params.get("lang")
    if query_lang in SUPPORTED_LANGS:
        response.set_cookie("lang", query_lang, max_age=60 * 60 * 24 * 365)
    return response


def json_loads(raw: str) -> list[str]:
    return json.loads(raw) if raw else []


def progress_label(percent: float) -> str:
    if percent >= 0.85:
        return "Advanced"
    if percent >= 0.7:
        return "Upper Intermediate"
    if percent >= 0.5:
        return "Intermediate"
    if percent >= 0.3:
        return "Lower Intermediate"
    return "Foundation Builder"


def level_recommendation(estimated_band_label: str | None, percent: float) -> str:
    if not estimated_band_label:
        return "Start with the 50~99 band, then add notes and examples to words you miss most often."
    if percent >= 0.7:
        return f"You can comfortably work around {estimated_band_label}. Move into the next harder band in Dictionary and enrich unfamiliar words."
    return f"Focus your next learning sessions around {estimated_band_label} and the band just below it until the answers feel automatic."


def learning_recommendation(correct: int, total: int, enriched_words: int) -> str:
    if total == 0:
        return "Add more enrichment to a few words first so the learning mode can ask richer questions."
    percent = correct / total
    if percent >= 0.8 and enriched_words > 0:
        return "Nice momentum. Keep studying and add harder bands or more sentence questions."
    if enriched_words == 0:
        return "Definition practice is working, but adding synonyms and example sentences will make the next sessions much stronger."
    return "Review the missed words, add clearer notes, and keep building more enriched entries in the dictionary."


def word_row(conn: sqlite3.Connection, word_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT words.*, study_cards.notes, study_cards.correct_count, study_cards.wrong_count,
               study_cards.status, study_cards.last_reviewed_at, study_cards.next_review_at
        FROM words
        JOIN study_cards ON study_cards.word_id = words.id
        WHERE words.id = ?
        """,
        (word_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Word not found")
    return row


def source_fallback_for_word(conn: sqlite3.Connection, word_id: int) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT extra_json
        FROM source_entries
        WHERE word_id = ?
        ORDER BY band_rank, workbook_name, row_number
        """,
        (word_id,),
    ).fetchall()
    english_definition = ""
    example_sentence = ""
    for row in rows:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        if isinstance(extra, dict):
            if not english_definition and extra.get("english_definition"):
                english_definition = extra["english_definition"]
            if not example_sentence and extra.get("example_sentence"):
                example_sentence = extra["example_sentence"]
    return {
        "english_definition": english_definition,
        "example_sentence": example_sentence,
    }


def source_fallbacks_for_words(conn: sqlite3.Connection, word_ids: list[int]) -> dict[int, dict[str, str]]:
    if not word_ids:
        return {}
    placeholders = ",".join("?" for _ in word_ids)
    rows = conn.execute(
        f"""
        SELECT word_id, extra_json
        FROM source_entries
        WHERE word_id IN ({placeholders})
        ORDER BY band_rank, workbook_name, row_number
        """,
        word_ids,
    ).fetchall()
    result = {word_id: {"english_definition": "", "example_sentence": ""} for word_id in word_ids}
    for row in rows:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        if not isinstance(extra, dict):
            continue
        target = result[row["word_id"]]
        if not target["english_definition"] and extra.get("english_definition"):
            target["english_definition"] = extra["english_definition"]
        if not target["example_sentence"] and extra.get("example_sentence"):
            target["example_sentence"] = extra["example_sentence"]
    return result


def definitions_map_for_words(conn: sqlite3.Connection, word_ids: list[int]) -> dict[int, list[str]]:
    if not word_ids:
        return {}
    placeholders = ",".join("?" for _ in word_ids)
    rows = conn.execute(
        f"""
        SELECT word_id, meanings_json
        FROM source_entries
        WHERE word_id IN ({placeholders})
        ORDER BY band_rank, workbook_name, row_number
        """,
        word_ids,
    ).fetchall()
    result = {word_id: [] for word_id in word_ids}
    for row in rows:
        seen = result[row["word_id"]]
        for meaning in json.loads(row["meanings_json"]):
            if meaning not in seen:
                seen.append(meaning)
    return result


def parts_of_speech_map_for_words(conn: sqlite3.Connection, word_ids: list[int]) -> dict[int, list[str]]:
    if not word_ids:
        return {}
    placeholders = ",".join("?" for _ in word_ids)
    rows = conn.execute(
        f"""
        SELECT word_id, pos
        FROM source_entries
        WHERE word_id IN ({placeholders}) AND pos IS NOT NULL AND pos <> ''
        ORDER BY word_id, pos
        """,
        word_ids,
    ).fetchall()
    result = {word_id: [] for word_id in word_ids}
    for row in rows:
        bucket = result[row["word_id"]]
        if row["pos"] not in bucket:
            bucket.append(row["pos"])
    return result


def word_payload(conn: sqlite3.Connection, word_id: int) -> dict:
    row = word_row(conn, word_id)
    definitions = definitions_for_word(conn, word_id)
    parts_of_speech = parts_of_speech_for_word(conn, word_id)
    source_rows = conn.execute(
        """
        SELECT workbook_name, sheet_name, row_number, pos, meanings_json, extra_json
        FROM source_entries
        WHERE word_id = ?
        ORDER BY band_rank, workbook_name, row_number
        """,
        (word_id,),
    ).fetchall()
    enrichment = conn.execute(
        """
        SELECT english_definition, pronunciation, synonyms_json, example_sentence, sentence_distractors_json
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word_id,),
    ).fetchone()
    source_fallback = source_fallback_for_word(conn, word_id)
    english_definition = (enrichment["english_definition"] if enrichment and enrichment["english_definition"] else source_fallback["english_definition"])
    synonyms = json_loads(enrichment["synonyms_json"]) if enrichment else []
    example_sentence = (enrichment["example_sentence"] if enrichment and enrichment["example_sentence"] else source_fallback["example_sentence"])
    return {
        "word": row,
        "definitions": definitions,
        "chinese_headword": definitions[0] if definitions else "",
        "parts_of_speech": parts_of_speech,
        "sources": source_rows,
        "english_definition": english_definition,
        "pronunciation": (enrichment["pronunciation"] if enrichment and enrichment["pronunciation"] else ""),
        "synonyms": synonyms,
        "example_sentence": example_sentence,
        "sentence_distractors": json_loads(enrichment["sentence_distractors_json"]) if enrichment else [],
    }


def band_accuracy_rows(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT band_label, band_rank,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
               COUNT(*) AS total
        FROM assessment_questions
        WHERE session_id = ?
        GROUP BY band_label, band_rank
        ORDER BY band_rank
        """,
        (session_id,),
    ).fetchall()
    result = []
    for row in rows:
        total = row["total"] or 0
        correct = row["correct"] or 0
        accuracy = (correct / total) if total else 0
        result.append(
            {
                "band_label": row["band_label"],
                "correct": correct,
                "total": total,
                "accuracy": round(accuracy * 100),
            }
        )
    return result


def decorate_band_rows(rows: list[sqlite3.Row]) -> list[dict]:
    decorated = []
    for row in rows:
        label = row["best_band_label"]
        match = re.search(r"\((\d+)\)", label)
        workbook_total = int(match.group(1)) if match else row["total"]
        decorated.append(
            {
                "best_band_rank": row["best_band_rank"],
                "best_band_label": label,
                "total": row["total"],
                "workbook_total": workbook_total,
                "range_label": label.split(" (")[0],
            }
        )
    return sorted(decorated, key=lambda band: band["best_band_rank"], reverse=True)


def dashboard_spotlight_words(conn: sqlite3.Connection, limit: int = 4) -> list[dict]:
    rows = conn.execute(
        """
        SELECT words.id, words.lemma, words.best_band_label,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        ORDER BY words.best_band_rank DESC, words.lemma
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids)
    parts_map = parts_of_speech_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    items: list[dict] = []
    for row in rows:
        defs = definitions_map.get(row["id"], [])
        pos = parts_map.get(row["id"], [])
        source_fallback = fallback_map.get(row["id"], {"english_definition": "", "example_sentence": ""})
        english_definition = row["english_definition"] or source_fallback["english_definition"]
        example_sentence = row["example_sentence"] or source_fallback["example_sentence"]
        items.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": english_definition,
                "example_sentence": example_sentence,
                "parts_of_speech": pos,
                "chinese_preview": defs[:1],
                "chinese_headword": defs[0] if defs else "",
            }
        )
    return items


def latest_test_result(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM assessment_sessions
        WHERE status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()


def latest_learning_result(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()


def search_words(
    conn: sqlite3.Connection,
    query: str,
    *,
    band_rank: int | None = None,
    require_english: bool = False,
    require_example: bool = False,
) -> list[sqlite3.Row]:
    clauses = ["words.lemma LIKE ?"]
    params: list[object] = [f"%{query.strip()}%"]
    if band_rank is not None:
        clauses.append("words.best_band_rank = ?")
        params.append(band_rank)
    if require_english:
        clauses.append("COALESCE(word_enrichment.english_definition, '') <> ''")
    if require_example:
        clauses.append("COALESCE(word_enrichment.example_sentence, '') <> ''")
    sql = f"""
        SELECT words.id, words.lemma, words.best_band_label, words.best_band_rank,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        WHERE {' AND '.join(clauses)}
        ORDER BY words.best_band_rank, words.lemma
        LIMIT 120
    """
    return conn.execute(sql, params).fetchall()


def search_result_cards(
    conn: sqlite3.Connection,
    query: str,
    *,
    band_rank: int | None = None,
    require_english: bool = False,
    require_example: bool = False,
) -> list[dict]:
    rows = search_words(
        conn,
        query,
        band_rank=band_rank,
        require_english=require_english,
        require_example=require_example,
    )
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids)
    parts_map = parts_of_speech_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    cards: list[dict] = []
    for row in rows:
        definitions = definitions_map.get(row["id"], [])
        parts = parts_map.get(row["id"], [])
        source_fallback = fallback_map.get(row["id"], {"english_definition": "", "example_sentence": ""})
        english_definition = row["english_definition"] or source_fallback["english_definition"]
        example_sentence = row["example_sentence"] or source_fallback["example_sentence"]
        cards.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": english_definition,
                "example_sentence": example_sentence,
                "parts_of_speech": parts,
                "chinese_preview": definitions[:2],
            }
        )
    return cards


def missed_words(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """
        WITH wrong_answers AS (
            SELECT word_id, answered_at AS seen_at, 'test' AS source
            FROM assessment_questions
            WHERE is_correct = 0
            UNION ALL
            SELECT word_id, answered_at AS seen_at, 'learning' AS source
            FROM learning_questions
            WHERE is_correct = 0
        )
        SELECT
            words.id,
            words.lemma,
            words.best_band_label,
            COUNT(*) AS miss_count,
            MAX(wrong_answers.seen_at) AS last_seen,
            COALESCE(word_enrichment.english_definition, '') AS english_definition,
            COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM wrong_answers
        JOIN words ON words.id = wrong_answers.word_id
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        GROUP BY words.id, words.lemma, words.best_band_label, word_enrichment.english_definition, word_enrichment.example_sentence
        ORDER BY miss_count DESC, last_seen DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def previous_test_question(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None or session["current_index"] < 1:
        return None
    return conn.execute(
        """
        SELECT *
        FROM assessment_questions
        WHERE session_id = ? AND position = ?
        """,
        (session_id, session["current_index"]),
    ).fetchone()


def previous_learning_question(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None or session["current_index"] < 1:
        return None
    return conn.execute(
        """
        SELECT *
        FROM learning_questions
        WHERE session_id = ? AND position = ?
        """,
        (session_id, session["current_index"]),
    ).fetchone()


def distractor_definitions(conn: sqlite3.Connection, *, band_rank: int, word_id: int, limit: int = 3) -> list[str]:
    rows = conn.execute(
        """
        SELECT word_id, meanings_json
        FROM source_entries
        WHERE band_rank = ? AND word_id != ? AND meanings_json <> '[]'
        ORDER BY RANDOM()
        LIMIT 40
        """,
        (band_rank, word_id),
    ).fetchall()
    options: list[str] = []
    for row in rows:
        for meaning in json_loads(row["meanings_json"]):
            if meaning not in options:
                options.append(meaning)
            if len(options) >= limit:
                return options
    if len(options) < limit:
        fallback = conn.execute(
            """
            SELECT meanings_json
            FROM source_entries
            WHERE word_id != ? AND meanings_json <> '[]'
            ORDER BY RANDOM()
            LIMIT 100
            """,
            (word_id,),
        ).fetchall()
        for row in fallback:
            for meaning in json_loads(row["meanings_json"]):
                if meaning not in options:
                    options.append(meaning)
                if len(options) >= limit:
                    return options
    return options


def build_definition_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    meanings = definitions_for_word(conn, word["id"])
    if not meanings:
        return None
    correct = meanings[0]
    options = [correct] + distractor_definitions(conn, band_rank=word["best_band_rank"], word_id=word["id"])
    options = list(dict.fromkeys(options))
    if len(options) < 4:
        return None
    random.shuffle(options)
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "definition",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options[:4], ensure_ascii=False),
        "explanation": "Choose the closest definition.",
    }


def build_synonym_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    enrichment = conn.execute(
        "SELECT synonyms_json FROM word_enrichment WHERE word_id = ?",
        (word["id"],),
    ).fetchone()
    if enrichment is None:
        return None
    synonyms = [item.strip() for item in json_loads(enrichment["synonyms_json"]) if item.strip()]
    if not synonyms:
        return None
    correct = synonyms[0]
    distractors = conn.execute(
        """
        SELECT lemma
        FROM words
        WHERE id != ?
        ORDER BY RANDOM()
        LIMIT 20
        """,
        (word["id"],),
    ).fetchall()
    options = [correct]
    for row in distractors:
        if row["lemma"] not in options:
            options.append(row["lemma"])
        if len(options) >= 4:
            break
    if len(options) < 4:
        return None
    random.shuffle(options)
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "synonym",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options[:4], ensure_ascii=False),
        "explanation": "Choose the closest synonym.",
    }


def build_sentence_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    enrichment = conn.execute(
        """
        SELECT example_sentence, sentence_distractors_json
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word["id"],),
    ).fetchone()
    if enrichment is None or not enrichment["example_sentence"]:
        return None
    correct = enrichment["example_sentence"].strip()
    options = [correct]
    for sentence in json_loads(enrichment["sentence_distractors_json"]):
        clean = sentence.strip()
        if clean and clean not in options:
            options.append(clean)
        if len(options) >= 4:
            break
    if len(options) < 4:
        return None
    random.shuffle(options)
    return {
        "position": position,
        "word_id": word["id"],
        "question_type": "sentence",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options[:4], ensure_ascii=False),
        "explanation": "Choose the sentence that uses the word naturally.",
    }


def create_test_session(conn: sqlite3.Connection) -> int:
    band_rows = band_summary(conn)
    questions: list[dict] = []
    position = 1
    per_band = max(1, TEST_QUESTION_COUNT // max(1, len(band_rows)))
    for band in band_rows:
        rows = conn.execute(
            """
            SELECT *
            FROM words
            WHERE best_band_rank = ?
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (band["best_band_rank"], per_band + 2),
        ).fetchall()
        for word in rows:
            question = build_definition_question(conn, word, position)
            if question is None:
                continue
            questions.append(question)
            position += 1
            if len([q for q in questions if q["band_rank"] == band["best_band_rank"]]) >= per_band:
                break
    while len(questions) < TEST_QUESTION_COUNT:
        word = conn.execute(
            "SELECT * FROM words ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        question = build_definition_question(conn, word, position)
        if question is None:
            continue
        questions.append(question)
        position += 1

    cursor = conn.execute(
        """
        INSERT INTO assessment_sessions (user_id)
        VALUES (?)
        """,
        (USER_ID,),
    )
    session_id = cursor.lastrowid
    for question in questions[:TEST_QUESTION_COUNT]:
        conn.execute(
            """
            INSERT INTO assessment_questions (
                session_id, position, word_id, band_rank, band_label, question_type,
                prompt_text, correct_option, options_json, explanation
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                question["position"],
                question["word_id"],
                question["band_rank"],
                question["band_label"],
                question["question_type"],
                question["prompt_text"],
                question["correct_option"],
                question["options_json"],
                question["explanation"],
            ),
        )
    conn.commit()
    return session_id


def create_learning_session(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        INSERT INTO learning_sessions (user_id)
        VALUES (?)
        """,
        (USER_ID,),
    )
    session_id = cursor.lastrowid
    words = conn.execute(
        """
        SELECT DISTINCT words.*
        FROM words
        JOIN study_cards ON study_cards.word_id = words.id
        JOIN source_entries ON source_entries.word_id = words.id
        WHERE source_entries.meanings_json <> '[]'
        ORDER BY
            CASE study_cards.status
                WHEN 'new' THEN 0
                WHEN 'learning' THEN 1
                ELSE 2
            END,
            words.best_band_rank,
            RANDOM()
        LIMIT 30
        """,
    ).fetchall()
    position = 1
    used_word_ids: set[int] = set()
    for word in words:
        if len(used_word_ids) >= LEARNING_WORD_COUNT and position > LEARNING_WORD_COUNT:
            break
        added_for_word = 0
        for builder in (build_definition_question, build_synonym_question, build_sentence_question):
            question = builder(conn, word, position)
            if question is None:
                continue
            conn.execute(
                """
                INSERT INTO learning_questions (
                    session_id, position, word_id, question_type, prompt_text,
                    correct_option, options_json, explanation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    position,
                    question["word_id"],
                    question["question_type"],
                    question["prompt_text"],
                    question["correct_option"],
                    question["options_json"],
                    question["explanation"],
                ),
            )
            position += 1
            added_for_word += 1
        if added_for_word:
            used_word_ids.add(word["id"])
    conn.commit()
    return session_id


def test_progress(session: sqlite3.Row) -> dict:
    current = session["current_index"] + 1
    answered = session["current_index"]
    total = TEST_QUESTION_COUNT
    return {
        "current": min(current, total),
        "answered": answered,
        "total": total,
        "percent": round((answered / total) * 100) if total else 0,
    }


def learning_progress(conn: sqlite3.Connection, session: sqlite3.Row) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM learning_questions WHERE session_id = ?",
        (session["id"],),
    ).fetchone()[0]
    answered = session["current_index"]
    current = answered + 1
    return {
        "current": min(current, total or 1),
        "answered": answered,
        "total": total,
        "percent": round((answered / total) * 100) if total else 0,
    }


def current_test_question(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    return conn.execute(
        """
        SELECT *
        FROM assessment_questions
        WHERE session_id = ? AND position = ?
        """,
        (session_id, session["current_index"] + 1),
    ).fetchone()


def current_learning_question(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    return conn.execute(
        """
        SELECT *
        FROM learning_questions
        WHERE session_id = ? AND position = ?
        """,
        (session_id, session["current_index"] + 1),
    ).fetchone()


def finish_test_session(conn: sqlite3.Connection, session_id: int) -> None:
    rows = conn.execute(
        """
        SELECT band_rank, band_label, is_correct
        FROM assessment_questions
        WHERE session_id = ?
        ORDER BY position
        """,
        (session_id,),
    ).fetchall()
    band_scores: dict[int, list[int]] = defaultdict(list)
    labels: dict[int, str] = {}
    total_correct = 0
    for row in rows:
        value = int(row["is_correct"] or 0)
        band_scores[row["band_rank"]].append(value)
        labels[row["band_rank"]] = row["band_label"]
        total_correct += value
    estimated_rank = None
    estimated_label = "Getting Started"
    weighted_score = 0
    weighted_total = 0
    for band_rank in sorted(band_scores):
        answers = band_scores[band_rank]
        weight = 1 + len(band_scores) - list(sorted(band_scores)).index(band_rank)
        weighted_score += sum(answers) * weight
        weighted_total += len(answers) * weight
        if answers and sum(answers) / len(answers) >= 0.6:
            estimated_rank = band_rank
            estimated_label = labels[band_rank]
    accuracy_percent = round((total_correct / len(rows)) * 100) if rows else 0
    weighted_percent = round((weighted_score / weighted_total) * 100) if weighted_total else 0
    conn.execute(
        """
        UPDATE assessment_sessions
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            score = ?,
            estimated_band_rank = ?,
            estimated_band_label = ?
        WHERE id = ?
        """,
        (total_correct, estimated_rank, estimated_label, session_id),
    )
    conn.commit()
    return {"accuracy_percent": accuracy_percent, "weighted_percent": weighted_percent}


def finish_learning_session(conn: sqlite3.Connection, session_id: int) -> None:
    score = conn.execute(
        """
        SELECT COUNT(*)
        FROM learning_questions
        WHERE session_id = ? AND is_correct = 1
        """,
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE learning_sessions
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            score = ?
        WHERE id = ?
        """,
        (score, session_id),
    )
    conn.commit()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    conn = db_conn()
    stats = fetch_stats(conn)
    latest_test = latest_test_result(conn)
    latest_learning = latest_learning_result(conn)
    recommended_band = latest_test["estimated_band_label"] if latest_test else "50~99 (3924)"
    bands = decorate_band_rows(band_summary(conn))
    return render(
        request,
        "home.html",
        stats=stats,
        bands=bands,
        latest_test=latest_test,
        latest_learning=latest_learning,
        recommended_band=recommended_band,
        missed_words_count=len(missed_words(conn, limit=10)),
        spotlight_words=dashboard_spotlight_words(conn),
    )


@app.get("/games/monopoly-3d", response_class=HTMLResponse)
def monopoly_3d(request: Request) -> HTMLResponse:
    return render(request, "monopoly_3d.html")


@app.get("/test", response_class=HTMLResponse)
def test_intro(request: Request) -> HTMLResponse:
    conn = db_conn()
    return render(request, "test_intro.html", bands=decorate_band_rows(band_summary(conn)), question_count=TEST_QUESTION_COUNT)


@app.post("/test/start")
def test_start() -> RedirectResponse:
    conn = db_conn()
    session_id = create_test_session(conn)
    return RedirectResponse(url=f"/test/{session_id}", status_code=303)


@app.get("/test/{session_id}", response_class=HTMLResponse)
def test_question(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question = current_test_question(conn, session_id)
    if question is None:
        finish_test_session(conn, session_id)
        return RedirectResponse(url=f"/test/{session_id}/result", status_code=303)
    return render(
        request,
        "test_question.html",
        session=session,
        question=question,
        options=json_loads(question["options_json"]),
        progress=test_progress(session),
    )


@app.post("/test/{session_id}/answer")
def test_answer(session_id: int, answer: str = Form(...)) -> RedirectResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    question = current_test_question(conn, session_id)
    if session is None or question is None:
        return RedirectResponse(url=f"/test/{session_id}/result", status_code=303)
    is_correct = int(answer == question["correct_option"])
    conn.execute(
        """
        UPDATE assessment_questions
        SET user_answer = ?, is_correct = ?, answered_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (answer, is_correct, question["id"]),
    )
    conn.execute(
        """
        UPDATE assessment_sessions
        SET current_index = current_index + 1,
            score = score + ?
        WHERE id = ?
        """,
        (is_correct, session_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/test/{session_id}/review", status_code=303)


@app.get("/test/{session_id}/review", response_class=HTMLResponse)
def test_review(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question = previous_test_question(conn, session_id)
    if question is None:
        return RedirectResponse(url=f"/test/{session_id}", status_code=303)
    payload = word_payload(conn, question["word_id"])
    is_last = session["current_index"] >= TEST_QUESTION_COUNT
    return render(
        request,
        "test_review.html",
        session=session,
        question=question,
        word=payload["word"],
        definitions=payload["definitions"],
        parts_of_speech=payload["parts_of_speech"],
        english_definition=payload["english_definition"],
        pronunciation=payload["pronunciation"],
        options=json_loads(question["options_json"]),
        is_last=is_last,
        progress=test_progress(session),
    )


@app.get("/test/{session_id}/result", response_class=HTMLResponse)
def test_result(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    summary = finish_test_session(conn, session_id)
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    band_rows = band_accuracy_rows(conn, session_id)
    level_name = progress_label((summary["accuracy_percent"] or 0) / 100)
    recommendation = level_recommendation(session["estimated_band_label"], (summary["accuracy_percent"] or 0) / 100)
    return render(
        request,
        "test_result.html",
        session=session,
        band_results=band_rows,
        summary=summary,
        level_name=level_name,
        recommendation=recommendation,
    )


@app.get("/learning", response_class=HTMLResponse)
def learning_intro(request: Request) -> HTMLResponse:
    conn = db_conn()
    enrichment = conn.execute(
        """
        SELECT
            COUNT(*) AS enriched_words,
            SUM(CASE WHEN json_array_length(synonyms_json) > 0 THEN 1 ELSE 0 END) AS synonym_ready,
            SUM(CASE WHEN example_sentence <> '' THEN 1 ELSE 0 END) AS sentence_ready
        FROM word_enrichment
        """
    ).fetchone()
    latest_learning = latest_learning_result(conn)
    return render(
        request,
        "learning_intro.html",
        stats=fetch_stats(conn),
        enrichment=enrichment,
        latest_learning=latest_learning,
    )


@app.post("/learning/start")
def learning_start() -> RedirectResponse:
    conn = db_conn()
    session_id = create_learning_session(conn)
    return RedirectResponse(url=f"/learning/{session_id}", status_code=303)


@app.get("/learning/{session_id}", response_class=HTMLResponse)
def learning_question(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = current_learning_question(conn, session_id)
    if question is None:
        finish_learning_session(conn, session_id)
        return RedirectResponse(url=f"/learning/{session_id}/result", status_code=303)
    payload = word_payload(conn, question["word_id"])
    return render(
        request,
        "learning_question.html",
        session=session,
        question=question,
        word=payload["word"],
        options=json_loads(question["options_json"]),
        definitions=payload["definitions"],
        parts_of_speech=payload["parts_of_speech"],
        english_definition=payload["english_definition"],
        pronunciation=payload["pronunciation"],
        synonyms=payload["synonyms"],
        example_sentence=payload["example_sentence"],
        progress=learning_progress(conn, session),
    )


@app.post("/learning/{session_id}/answer")
def learning_answer(session_id: int, answer: str = Form(...)) -> RedirectResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    question = current_learning_question(conn, session_id)
    if session is None or question is None:
        return RedirectResponse(url=f"/learning/{session_id}/result", status_code=303)
    is_correct = int(answer == question["correct_option"])
    conn.execute(
        """
        UPDATE learning_questions
        SET user_answer = ?, is_correct = ?, answered_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (answer, is_correct, question["id"]),
    )
    conn.execute(
        """
        UPDATE learning_sessions
        SET current_index = current_index + 1,
            score = score + ?
        WHERE id = ?
        """,
        (is_correct, session_id),
    )
    conn.execute(
        """
        UPDATE study_cards
        SET correct_count = correct_count + ?,
            wrong_count = wrong_count + ?,
            status = CASE WHEN ? = 1 THEN 'learning' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE word_id = ?
        """,
        (is_correct, 1 - is_correct, is_correct, question["word_id"]),
    )
    conn.commit()
    return RedirectResponse(url=f"/learning/{session_id}/review", status_code=303)


@app.get("/learning/{session_id}/review", response_class=HTMLResponse)
def learning_review(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = previous_learning_question(conn, session_id)
    if question is None:
        return RedirectResponse(url=f"/learning/{session_id}", status_code=303)
    payload = word_payload(conn, question["word_id"])
    progress = learning_progress(conn, session)
    is_last = progress["answered"] >= progress["total"]
    return render(
        request,
        "learning_review.html",
        session=session,
        question=question,
        word=payload["word"],
        definitions=payload["definitions"],
        parts_of_speech=payload["parts_of_speech"],
        english_definition=payload["english_definition"],
        pronunciation=payload["pronunciation"],
        synonyms=payload["synonyms"],
        example_sentence=payload["example_sentence"],
        progress=progress,
        is_last=is_last,
    )


@app.get("/learning/{session_id}/result", response_class=HTMLResponse)
def learning_result(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    finish_learning_session(conn, session_id)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    rows = conn.execute(
        """
        SELECT question_type, SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct, COUNT(*) AS total
        FROM learning_questions
        WHERE session_id = ?
        GROUP BY question_type
        ORDER BY question_type
        """,
        (session_id,),
    ).fetchall()
    enriched_words = conn.execute("SELECT COUNT(*) FROM word_enrichment").fetchone()[0]
    total = sum(row["total"] for row in rows)
    recommendation = learning_recommendation(session["score"], total, enriched_words)
    return render(
        request,
        "learning_result.html",
        session=session,
        question_results=rows,
        recommendation=recommendation,
        percent=round((session["score"] / total) * 100) if total else 0,
    )


@app.get("/dictionary", response_class=HTMLResponse)
def dictionary_home(request: Request) -> HTMLResponse:
    conn = db_conn()
    bands = decorate_band_rows(band_summary(conn))
    return render(request, "dictionary_home.html", bands=bands, missed_count=len(missed_words(conn, limit=10)))


@app.get("/dictionary/band/{band_rank}", response_class=HTMLResponse)
def dictionary_band(
    request: Request,
    band_rank: int,
    letter: str | None = None,
    has_english: int = Query(0),
    has_example: int = Query(0),
) -> HTMLResponse:
    conn = db_conn()
    band = conn.execute(
        """
        SELECT best_band_rank, best_band_label, COUNT(*) AS total
        FROM words
        WHERE best_band_rank = ?
        GROUP BY best_band_rank, best_band_label
        """,
        (band_rank,),
    ).fetchone()
    if band is None:
        raise HTTPException(status_code=404, detail="Band not found")
    active_letter = (letter or "A").upper()
    rows = conn.execute(
        """
        SELECT words.id, words.lemma, words.best_band_label,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        WHERE best_band_rank = ? AND UPPER(SUBSTR(lemma, 1, 1)) = ?
          AND (? = 0 OR COALESCE(word_enrichment.english_definition, '') <> '')
          AND (? = 0 OR COALESCE(word_enrichment.example_sentence, '') <> '')
        ORDER BY lemma
        LIMIT 500
        """,
        (band_rank, active_letter, has_english, has_example),
    ).fetchall()
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    words = []
    for row in rows:
        definitions = definitions_map.get(row["id"], [])
        source_fallback = fallback_map.get(row["id"], {"english_definition": "", "example_sentence": ""})
        words.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": row["english_definition"] or source_fallback["english_definition"],
                "example_sentence": row["example_sentence"] or source_fallback["example_sentence"],
                "chinese_preview": definitions[:2],
                "chinese_headword": definitions[0] if definitions else "",
            }
        )
    return render(
        request,
        "dictionary_band.html",
        band=band,
        letters=letters_for_band(conn, band_rank),
        active_letter=active_letter,
        words=words,
        has_english=has_english,
        has_example=has_example,
    )


@app.get("/dictionary/search", response_class=HTMLResponse)
def dictionary_search(
    request: Request,
    q: str = Query(""),
    band_rank: str | None = Query(None),
    has_english: int = Query(0),
    has_example: int = Query(0),
) -> HTMLResponse:
    conn = db_conn()
    selected_band = int(band_rank) if band_rank and band_rank.strip() else None
    rows = search_result_cards(
        conn,
        q,
        band_rank=selected_band,
        require_english=bool(has_english),
        require_example=bool(has_example),
    ) if q.strip() else []
    return render(
        request,
        "dictionary_search.html",
        query=q,
        results=rows,
        bands=decorate_band_rows(band_summary(conn)),
        selected_band=selected_band,
        has_english=has_english,
        has_example=has_example,
        result_count=len(rows),
    )


@app.get("/bulk-import", response_class=HTMLResponse)
def bulk_import_page(request: Request) -> HTMLResponse:
    conn = db_conn()
    load_env_file()
    return render(
        request,
        "bulk_import.html",
        bands=decorate_band_rows(band_summary(conn)),
        stats=fetch_stats(conn),
        export_dir=str(EXPORT_DIR),
        api_key_ready=bool(os.environ.get("OPENAI_API_KEY", "").strip()),
    )


@app.post("/bulk-import/export")
def bulk_export_template(
    band_rank: str = Form(""),
    missing_only: str = Form("1"),
    limit: str = Form("300"),
) -> RedirectResponse:
    conn = db_conn()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    selected_band = int(band_rank) if band_rank.strip() else None
    selected_limit = int(limit) if limit.strip() else None
    band_suffix = f"band-{selected_band}" if selected_band is not None else "all-bands"
    output_path = EXPORT_DIR / f"enrichment-template-{band_suffix}.xlsx"
    export_template(
        conn,
        output_path,
        band_rank=selected_band,
        limit=selected_limit,
        missing_only=(missing_only == "1"),
    )
    return RedirectResponse(url="/bulk-import?exported=1", status_code=303)


@app.post("/bulk-import/upload")
async def bulk_import_upload(file: UploadFile = File(...)) -> RedirectResponse:
    conn = db_conn()
    content = await file.read()
    rows = iter_import_rows(file.filename or "", content)
    stats = import_enrichment_rows(conn, rows)
    return RedirectResponse(
        url=f"/bulk-import?imported=1&updated={stats['updated']}&missing={stats['missing_words']}",
        status_code=303,
    )


@app.post("/bulk-import/generate-ai")
def bulk_generate_ai(
    band_rank: str = Form(""),
    limit: str = Form("20"),
) -> RedirectResponse:
    conn = db_conn()
    selected_band = int(band_rank) if band_rank.strip() else None
    selected_limit = int(limit) if limit.strip() else 20
    try:
        stats = generate_enrichment_batch(conn, limit=selected_limit, band_rank=selected_band)
    except RuntimeError as exc:
        return RedirectResponse(url=f"/bulk-import?error={str(exc)}", status_code=303)
    return RedirectResponse(
        url=f"/bulk-import?generated=1&selected={stats['selected']}&updated={stats['updated']}",
        status_code=303,
    )


@app.get("/review/missed", response_class=HTMLResponse)
def missed_words_page(request: Request) -> HTMLResponse:
    conn = db_conn()
    rows = missed_words(conn)
    return render(request, "missed_words.html", rows=rows)


@app.get("/word/{word_id}", response_class=HTMLResponse)
def word_detail(request: Request, word_id: int) -> HTMLResponse:
    conn = db_conn()
    payload = word_payload(conn, word_id)
    return render(request, "word_detail.html", **payload)


@app.get("/api/pronounce")
def pronounce_word_audio(text: str = Query(..., min_length=1, max_length=80)) -> Response:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Missing pronunciation text")
    if not speech_api_ready():
        raise HTTPException(status_code=503, detail="Speech API not configured")
    try:
        audio_bytes = synthesize_pronunciation_audio(cleaned)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Speech generation failed: {exc}") from exc
    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.post("/word/{word_id}/update")
def update_word(
    word_id: int,
    notes: str = Form(""),
    english_definition: str = Form(""),
    pronunciation: str = Form(""),
    synonyms: str = Form(""),
    example_sentence: str = Form(""),
    sentence_distractors: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    word = word_row(conn, word_id)
    synonym_items = [item.strip() for item in synonyms.splitlines() if item.strip()]
    distractor_items = [item.strip() for item in sentence_distractors.splitlines() if item.strip()]
    conn.execute(
        """
        UPDATE study_cards
        SET notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE word_id = ?
        """,
        (notes.strip(), word_id),
    )
    conn.execute(
        """
        INSERT INTO word_enrichment (word_id, english_definition, pronunciation, synonyms_json, example_sentence, sentence_distractors_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(word_id) DO UPDATE SET
            english_definition = excluded.english_definition,
            pronunciation = excluded.pronunciation,
            synonyms_json = excluded.synonyms_json,
            example_sentence = excluded.example_sentence,
            sentence_distractors_json = excluded.sentence_distractors_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            word_id,
            english_definition.strip(),
            pronunciation.strip(),
            json.dumps(synonym_items, ensure_ascii=False),
            example_sentence.strip(),
            json.dumps(distractor_items, ensure_ascii=False),
        ),
    )
    conn.commit()
    return RedirectResponse(url=f"/word/{word['id']}", status_code=303)
