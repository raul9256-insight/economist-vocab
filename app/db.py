from __future__ import annotations

import json
import os
import shutil
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
    antonyms_json TEXT NOT NULL DEFAULT '[]',
    example_sentence TEXT NOT NULL DEFAULT '',
    sentence_distractors_json TEXT NOT NULL DEFAULT '[]',
    ai_simple_explanation_en TEXT NOT NULL DEFAULT '',
    ai_simple_explanation_zh TEXT NOT NULL DEFAULT '',
    ai_nuance_note TEXT NOT NULL DEFAULT '',
    ai_compare_words_json TEXT NOT NULL DEFAULT '[]',
    ai_business_example TEXT NOT NULL DEFAULT '',
    ai_prompt_example TEXT NOT NULL DEFAULT '',
    ai_usage_warning TEXT NOT NULL DEFAULT '',
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
    question_count INTEGER,
    accuracy_percent INTEGER,
    weighted_percent INTEGER,
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

CREATE TABLE IF NOT EXISTS vocab_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    core_meaning TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vocab_cluster_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL REFERENCES vocab_clusters(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    stage_rank INTEGER NOT NULL DEFAULT 1,
    stage_label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(cluster_id, word_id)
);

CREATE TABLE IF NOT EXISTS word_progression_attributes (
    word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
    formality_level INTEGER NOT NULL DEFAULT 1,
    precision_level INTEGER NOT NULL DEFAULT 1,
    exam_relevance INTEGER NOT NULL DEFAULT 0,
    business_relevance INTEGER NOT NULL DEFAULT 0,
    ai_relevance INTEGER NOT NULL DEFAULT 0,
    productivity_likelihood INTEGER NOT NULL DEFAULT 0,
    domain TEXT NOT NULL DEFAULT '',
    register_note TEXT NOT NULL DEFAULT '',
    usage_note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS word_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    target_word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    strength INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source_word_id, target_word_id, relation_type)
);
"""


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def configured_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_path = os.getenv("DATABASE_PATH") or os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_DB_PATH


def prepare_database_file(db_path: Path) -> None:
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    bundled_path = DEFAULT_DB_PATH.resolve()
    target_path = db_path.resolve()
    if target_path != bundled_path and not db_path.exists() and DEFAULT_DB_PATH.exists():
        shutil.copy2(DEFAULT_DB_PATH, db_path)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    resolved_path = configured_db_path(db_path)
    prepare_database_file(resolved_path)
    conn = connect(resolved_path)
    conn.executescript(WEB_SCHEMA)
    ensure_column(conn, "word_enrichment", "english_definition", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "pronunciation", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "antonyms_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "word_enrichment", "ai_simple_explanation_en", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "ai_simple_explanation_zh", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "ai_nuance_note", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "ai_compare_words_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "word_enrichment", "ai_business_example", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "ai_prompt_example", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "word_enrichment", "ai_usage_warning", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "assessment_sessions", "question_count", "INTEGER")
    ensure_column(conn, "assessment_sessions", "accuracy_percent", "INTEGER")
    ensure_column(conn, "assessment_sessions", "weighted_percent", "INTEGER")
    ensure_column(conn, "users", "email", "TEXT")
    ensure_column(conn, "users", "password_hash", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "users", "display_name", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "users", "persona", "TEXT NOT NULL DEFAULT 'lifelong_learner'")
    conn.execute(
        """
        INSERT INTO users (id, username)
        VALUES (1, 'lawrence')
        ON CONFLICT(id) DO NOTHING
        """
    )
    conn.execute(
        """
        UPDATE users
        SET email = COALESCE(NULLIF(email, ''), 'lawrence@example.local'),
            display_name = COALESCE(NULLIF(display_name, ''), 'Lawrence'),
            persona = COALESCE(NULLIF(persona, ''), 'lifelong_learner')
        WHERE id = 1
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


def progression_profile_for_word(conn: sqlite3.Connection, word_id: int) -> dict:
    cluster_rows = conn.execute(
        """
        SELECT
            vocab_clusters.id,
            vocab_clusters.slug,
            vocab_clusters.label,
            vocab_clusters.core_meaning,
            vocab_clusters.domain,
            vocab_cluster_words.role,
            vocab_cluster_words.stage_rank,
            vocab_cluster_words.stage_label,
            vocab_cluster_words.note
        FROM vocab_cluster_words
        JOIN vocab_clusters ON vocab_clusters.id = vocab_cluster_words.cluster_id
        WHERE vocab_cluster_words.word_id = ?
        ORDER BY vocab_cluster_words.stage_rank, vocab_clusters.label
        """,
        (word_id,),
    ).fetchall()

    clusters = [dict(row) for row in cluster_rows]
    primary_cluster = clusters[0] if clusters else None

    cluster_path: list[dict] = []
    if primary_cluster:
        path_rows = conn.execute(
            """
            SELECT
                words.id AS word_id,
                words.lemma,
                words.best_band_label,
                vocab_cluster_words.stage_rank,
                vocab_cluster_words.stage_label,
                vocab_cluster_words.role
            FROM vocab_cluster_words
            JOIN words ON words.id = vocab_cluster_words.word_id
            WHERE vocab_cluster_words.cluster_id = ?
            ORDER BY vocab_cluster_words.stage_rank, words.lemma
            """,
            (primary_cluster["id"],),
        ).fetchall()
        cluster_path = [
            {
                **dict(row),
                "is_current": row["word_id"] == word_id,
            }
            for row in path_rows
        ]

    attribute_row = conn.execute(
        """
        SELECT
            formality_level,
            precision_level,
            exam_relevance,
            business_relevance,
            ai_relevance,
            productivity_likelihood,
            domain,
            register_note,
            usage_note
        FROM word_progression_attributes
        WHERE word_id = ?
        """,
        (word_id,),
    ).fetchone()
    attributes = dict(attribute_row) if attribute_row else None

    relationship_rows = conn.execute(
        """
        SELECT
            word_relationships.relation_type,
            word_relationships.explanation,
            word_relationships.strength,
            words.id AS target_word_id,
            words.lemma AS target_lemma,
            words.best_band_label AS target_band_label
        FROM word_relationships
        JOIN words ON words.id = word_relationships.target_word_id
        WHERE word_relationships.source_word_id = ?
        ORDER BY word_relationships.relation_type, word_relationships.strength DESC, words.lemma
        """,
        (word_id,),
    ).fetchall()

    grouped_relationships: list[dict] = []
    groups: dict[str, list[dict]] = {}
    for row in relationship_rows:
        groups.setdefault(row["relation_type"], []).append(
            {
                "word_id": row["target_word_id"],
                "lemma": row["target_lemma"],
                "band_label": row["target_band_label"],
                "explanation": row["explanation"],
                "strength": row["strength"],
            }
        )
    for relation_type, words in groups.items():
        grouped_relationships.append(
            {
                "relation_type": relation_type,
                "words": words,
            }
        )

    return {
        "clusters": clusters,
        "primary_cluster": primary_cluster,
        "cluster_path": cluster_path,
        "attributes": attributes,
        "relationship_groups": grouped_relationships,
    }
