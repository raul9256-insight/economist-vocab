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

CREATE TABLE IF NOT EXISTS question_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES assessment_sessions(id) ON DELETE SET NULL,
    question_id INTEGER REFERENCES assessment_questions(id) ON DELETE SET NULL,
    word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,
    question_type TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    band_rank INTEGER,
    band_label TEXT,
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

CREATE TABLE IF NOT EXISTS user_study_cards (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'new',
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    last_reviewed_at TEXT,
    next_review_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, word_id)
);

CREATE TABLE IF NOT EXISTS user_review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    reviewed_at TEXT NOT NULL,
    prompt_mode TEXT NOT NULL,
    grade TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS teacher_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS class_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL REFERENCES teacher_classes(id) ON DELETE CASCADE,
    student_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(class_id, student_user_id)
);

CREATE TABLE IF NOT EXISTS class_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL REFERENCES teacher_classes(id) ON DELETE CASCADE,
    teacher_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    band_rank INTEGER NOT NULL,
    band_label TEXT NOT NULL,
    due_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS word_mastery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    attempt_type TEXT NOT NULL,
    input_text TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '',
    feedback TEXT NOT NULL DEFAULT '',
    corrected_sentence TEXT NOT NULL DEFAULT '',
    suggested_upgrade TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS student_dse_vocab (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL UNIQUE,
    word TEXT NOT NULL,
    normalized_word TEXT NOT NULL,
    word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,
    dse_band_rank INTEGER NOT NULL,
    dse_band_label TEXT NOT NULL,
    dse_target TEXT NOT NULL DEFAULT '',
    product_band_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    part_of_speech TEXT NOT NULL DEFAULT '',
    priority_tier TEXT NOT NULL DEFAULT '',
    suggested_use TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    if target_path == bundled_path or not DEFAULT_DB_PATH.exists():
        return
    should_seed = not db_path.exists() or db_path.stat().st_size == 0
    if not should_seed:
        try:
            probe = sqlite3.connect(db_path)
            word_count = probe.execute("SELECT COUNT(*) FROM words").fetchone()[0]
            should_seed = word_count == 0
        except sqlite3.Error:
            should_seed = True
        finally:
            try:
                probe.close()
            except UnboundLocalError:
                pass
    if should_seed:
        shutil.copy2(DEFAULT_DB_PATH, db_path)


def seed_student_dse_vocab(conn: sqlite3.Connection) -> None:
    data_path = Path(__file__).resolve().parent.parent / "data" / "student_dse_vocab.json"
    if not data_path.exists():
        return
    try:
        items = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(items, list):
        return
    existing_total = conn.execute("SELECT COUNT(*) FROM student_dse_vocab").fetchone()[0]
    missing_links = conn.execute(
        "SELECT COUNT(*) FROM student_dse_vocab WHERE word_id IS NULL"
    ).fetchone()[0]
    dse_source_entries = conn.execute(
        "SELECT COUNT(*) FROM source_entries WHERE source_signature LIKE 'student-dse|%'"
    ).fetchone()[0]
    if existing_total == len(items) and missing_links == 0 and dse_source_entries >= len(items):
        return
    conn.execute("DELETE FROM student_dse_vocab")
    for item in items:
        normalized_word = str(item.get("normalized_word") or item.get("word") or "").strip().lower()
        if not normalized_word:
            continue
        student_id = str(item.get("student_id") or "")
        word_text = str(item.get("word") or "").strip()
        band_rank = int(item.get("dse_band_rank") or 0)
        band_label = str(item.get("dse_band_label") or "")
        word = conn.execute(
            "SELECT id FROM words WHERE normalized_lemma = ?",
            (normalized_word,),
        ).fetchone()
        if word is None and word_text and band_rank and band_label:
            cursor = conn.execute(
                """
                INSERT INTO words (lemma, normalized_lemma, best_band_label, best_band_rank)
                VALUES (?, ?, ?, ?)
                """,
                (word_text, normalized_word, band_label, band_rank),
            )
            word_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO study_cards (word_id) VALUES (?) ON CONFLICT(word_id) DO NOTHING",
                (word_id,),
            )
        else:
            word_id = word["id"] if word else None
        if word_id is not None and student_id:
            conn.execute(
                """
                INSERT INTO source_entries (
                    word_id, workbook_name, sheet_name, row_number, band_label, band_rank,
                    pos, meanings_json, extra_json, source_signature
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_signature) DO UPDATE SET
                    word_id = excluded.word_id,
                    workbook_name = excluded.workbook_name,
                    sheet_name = excluded.sheet_name,
                    row_number = excluded.row_number,
                    band_label = excluded.band_label,
                    band_rank = excluded.band_rank,
                    pos = excluded.pos,
                    meanings_json = excluded.meanings_json,
                    extra_json = excluded.extra_json
                """,
                (
                    word_id,
                    str(item.get("source_file") or "student_dse_vocab.json"),
                    band_label,
                    int(student_id.rsplit("-", 1)[-1]) if "-" in student_id and student_id.rsplit("-", 1)[-1].isdigit() else 0,
                    band_label,
                    band_rank,
                    str(item.get("part_of_speech") or ""),
                    "[]",
                    json.dumps(
                        {
                            "student_dse_id": student_id,
                            "dse_target": str(item.get("dse_target") or ""),
                            "product_band_name": str(item.get("product_band_name") or ""),
                            "category": str(item.get("category") or ""),
                            "priority_tier": str(item.get("priority_tier") or ""),
                            "suggested_use": str(item.get("suggested_use") or ""),
                            "notes": str(item.get("notes") or ""),
                        },
                        ensure_ascii=False,
                    ),
                    f"student-dse|{student_id}|{normalized_word}",
                ),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO student_dse_vocab (
                student_id, word, normalized_word, word_id, dse_band_rank, dse_band_label,
                dse_target, product_band_name, category, part_of_speech, priority_tier,
                suggested_use, notes, source_file, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                student_id,
                word_text,
                normalized_word,
                word_id,
                band_rank,
                band_label,
                str(item.get("dse_target") or ""),
                str(item.get("product_band_name") or ""),
                str(item.get("category") or ""),
                str(item.get("part_of_speech") or ""),
                str(item.get("priority_tier") or ""),
                str(item.get("suggested_use") or ""),
                str(item.get("notes") or ""),
                str(item.get("source_file") or ""),
            ),
        )


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
    ensure_column(conn, "learning_sessions", "band_rank", "INTEGER")
    ensure_column(conn, "learning_sessions", "band_label", "TEXT")
    ensure_column(conn, "learning_sessions", "assignment_id", "INTEGER")
    ensure_column(conn, "users", "email", "TEXT")
    ensure_column(conn, "users", "password_hash", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "users", "display_name", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "users", "persona", "TEXT NOT NULL DEFAULT 'lifelong_learner'")
    ensure_column(conn, "users", "role", "TEXT NOT NULL DEFAULT 'student'")
    ensure_column(conn, "class_assignments", "assignment_type", "TEXT NOT NULL DEFAULT 'band_practice'")
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
            persona = COALESCE(NULLIF(persona, ''), 'lifelong_learner'),
            role = CASE WHEN COALESCE(NULLIF(persona, ''), 'lifelong_learner') = 'teacher' THEN 'teacher' ELSE COALESCE(NULLIF(role, ''), 'student') END
        WHERE id = 1
        """
    )
    seeded_cards = conn.execute("SELECT COUNT(*) FROM user_study_cards WHERE user_id = 1").fetchone()[0]
    if seeded_cards == 0:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_study_cards (
                user_id, word_id, status, correct_count, wrong_count, streak, ease,
                interval_days, notes, last_reviewed_at, next_review_at, updated_at
            )
            SELECT
                1, word_id, status, correct_count, wrong_count, streak, ease,
                interval_days, notes, last_reviewed_at, next_review_at, updated_at
            FROM study_cards
            """
        )
    seed_student_dse_vocab(conn)
    conn.commit()
    return conn


def fetch_stats(conn: sqlite3.Connection, user_id: int | None = None) -> dict:
    test_clause = "WHERE user_id = ?" if user_id is not None else ""
    learning_clause = "WHERE user_id = ?" if user_id is not None else ""
    params: tuple[object, ...] = (user_id, user_id) if user_id is not None else ()
    row = conn.execute(
        f"""
        SELECT
            (SELECT COUNT(*) FROM words) AS total_words,
            (SELECT COUNT(*) FROM word_enrichment WHERE json_array_length(synonyms_json) > 0) AS words_with_synonyms,
            (SELECT COUNT(*) FROM word_enrichment WHERE example_sentence <> '') AS words_with_examples,
            (SELECT COUNT(*) FROM assessment_sessions {test_clause}) AS tests_taken,
            (SELECT COUNT(*) FROM learning_sessions {learning_clause}) AS learning_runs
        """,
        params,
    ).fetchone()
    return dict(row)


def band_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT best_band_rank, best_band_label, COUNT(*) AS total
        FROM words
        WHERE best_band_rank IN (50, 100, 200, 500, 2000)
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
