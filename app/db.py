from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from economist_vocab import DEFAULT_DB_PATH, connect


WEB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS word_enrichment (
    word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
    english_definition TEXT NOT NULL DEFAULT '',
    pronunciation TEXT NOT NULL DEFAULT '',
    synonyms_json TEXT NOT NULL DEFAULT '[]',
    example_sentence TEXT NOT NULL DEFAULT '',
    sentence_distractors_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessment_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    current_index INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    estimated_band_rank INTEGER,
    estimated_band_label TEXT
);

CREATE TABLE IF NOT EXISTS assessment_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES assessment_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    band_rank INTEGER NOT NULL,
    band_label TEXT NOT NULL,
    question_type TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    correct_option TEXT NOT NULL,
    options_json TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    user_answer TEXT,
    is_correct INTEGER,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    current_index INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learning_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES learning_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    question_type TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    correct_option TEXT NOT NULL,
    options_json TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    user_answer TEXT,
    is_correct INTEGER,
    answered_at TEXT
);
"""


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    conn = connect(db_path or DEFAULT_DB_PATH)
    conn.executescript(WEB_SCHEMA)
    ensure_column(conn, "word_enrichment", "english_definition", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "pronunciation", "TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        INSERT INTO users (id, username)
        VALUES (1, 'lawrence')
        ON CONFLICT(id) DO NOTHING
        """
    )
    conn.commit()
    return conn


def fetch_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM words) AS total_words,
            (SELECT COUNT(*) FROM word_enrichment WHERE json_array_length(synonyms_json) > 0) AS words_with_synonyms,
            (SELECT COUNT(*) FROM word_enrichment WHERE example_sentence <> '') AS words_with_examples,
            (SELECT COUNT(*) FROM assessment_sessions) AS tests_taken,
            (SELECT COUNT(*) FROM learning_sessions) AS learning_runs
        """
    ).fetchone()
    return dict(row)


def band_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT best_band_rank, best_band_label, COUNT(*) AS total
        FROM words
        GROUP BY best_band_rank, best_band_label
        ORDER BY best_band_rank
        """
    ).fetchall()


def letters_for_band(conn: sqlite3.Connection, band_rank: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT UPPER(SUBSTR(lemma, 1, 1)) AS letter
        FROM words
        WHERE best_band_rank = ?
        ORDER BY letter
        """,
        (band_rank,),
    ).fetchall()
    return [row["letter"] for row in rows if row["letter"]]


def definitions_for_word(conn: sqlite3.Connection, word_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT meanings_json
        FROM source_entries
        WHERE word_id = ?
        ORDER BY band_rank, workbook_name, row_number
        """,
        (word_id,),
    ).fetchall()
    seen: list[str] = []
    for row in rows:
        for meaning in json.loads(row["meanings_json"]):
            if meaning not in seen:
                seen.append(meaning)
    return seen


def parts_of_speech_for_word(conn: sqlite3.Connection, word_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT pos
        FROM source_entries
        WHERE word_id = ? AND pos IS NOT NULL AND pos <> ''
        ORDER BY pos
        """,
        (word_id,),
    ).fetchall()
    return [row["pos"] for row in rows]
