from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import BinaryIO

import openpyxl

from app.db import definitions_for_word, parts_of_speech_for_word
from economist_vocab import normalize_word


EXPECTED_COLUMNS = [
    "lemma",
    "band_label",
    "parts_of_speech",
    "chinese_definitions",
    "pronunciation",
    "english_definition",
    "example_sentence",
    "synonyms",
    "sentence_distractors",
    "notes",
]

AI_POWER_EXPECTED_COLUMNS = [
    "category_slug",
    "category_name",
    "english",
    "traditional_chinese",
    "simplified_chinese",
    "example_sentence",
    "ai_prompt_example",
    "notes",
]


def parse_list_field(value: str) -> list[str]:
    if not value:
        return []
    chunks = str(value).replace(";", "\n").splitlines()
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def iter_import_rows(filename: str, content: bytes) -> list[dict[str, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [{(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader]
    if suffix in {".xlsx", ".xlsm"}:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        result: list[dict[str, str]] = []
        for raw in rows[1:]:
            row = {}
            for index, header in enumerate(headers):
                if not header:
                    continue
                value = raw[index] if index < len(raw) else ""
                row[header] = "" if value is None else str(value).strip()
            result.append(row)
        return result
    raise ValueError("Only .csv and .xlsx files are supported.")


def export_template(
    conn: sqlite3.Connection,
    output_path: Path,
    *,
    band_rank: int | None = None,
    limit: int | None = None,
    missing_only: bool = False,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clauses = ["1 = 1"]
    params: list[object] = []
    if band_rank is not None:
        clauses.append("words.best_band_rank = ?")
        params.append(band_rank)
    if missing_only:
        clauses.append("(word_enrichment.english_definition IS NULL OR word_enrichment.english_definition = '' OR word_enrichment.example_sentence IS NULL OR word_enrichment.example_sentence = '')")
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    rows = conn.execute(
        f"""
        SELECT words.id, words.lemma, words.best_band_label,
               COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence,
               COALESCE(word_enrichment.synonyms_json, '[]') AS synonyms_json,
               COALESCE(word_enrichment.sentence_distractors_json, '[]') AS sentence_distractors_json,
               COALESCE(study_cards.notes, '') AS notes
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        LEFT JOIN study_cards ON study_cards.word_id = words.id
        WHERE {' AND '.join(clauses)}
        ORDER BY words.best_band_rank, words.lemma
        {limit_clause}
        """,
        params,
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "enrichment"
    ws.append(EXPECTED_COLUMNS)
    for row in rows:
        ws.append(
            [
                row["lemma"],
                row["best_band_label"],
                ", ".join(parts_of_speech_for_word(conn, row["id"])),
                " | ".join(definitions_for_word(conn, row["id"])),
                row["pronunciation"],
                row["english_definition"],
                row["example_sentence"],
                "\n".join(json.loads(row["synonyms_json"])),
                "\n".join(json.loads(row["sentence_distractors_json"])),
                row["notes"],
            ]
        )
    wb.save(output_path)
    return len(rows)


def export_ai_power_template(categories: list[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ai_power_vocab"
    ws.append(AI_POWER_EXPECTED_COLUMNS)

    total_rows = 0
    for category in categories:
        for term in category.get("terms", []):
            ws.append(
                [
                    category.get("slug", ""),
                    category.get("english_title", category.get("title", "")),
                    term,
                    "",
                    "",
                    category.get("normal_example", ""),
                    category.get("prompt_example", ""),
                    "",
                ]
            )
            total_rows += 1

    wb.save(output_path)
    return total_rows


def import_enrichment_rows(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {"updated": 0, "skipped": 0, "missing_words": 0}
    for raw_row in rows:
        lemma = normalize_word(raw_row.get("lemma", ""))
        if not lemma:
            stats["skipped"] += 1
            continue
        word = conn.execute(
            "SELECT id FROM words WHERE normalized_lemma = ?",
            (lemma,),
        ).fetchone()
        if word is None:
            stats["missing_words"] += 1
            continue
        current = conn.execute(
            """
            SELECT pronunciation, english_definition, synonyms_json, example_sentence, sentence_distractors_json
            FROM word_enrichment
            WHERE word_id = ?
            """,
            (word["id"],),
        ).fetchone()
        current_pronunciation = current["pronunciation"] if current else ""
        current_english = current["english_definition"] if current else ""
        current_synonyms = json.loads(current["synonyms_json"]) if current else []
        current_example = current["example_sentence"] if current else ""
        current_distractors = json.loads(current["sentence_distractors_json"]) if current else []

        incoming_pronunciation = (raw_row.get("pronunciation", "") or raw_row.get("ipa", "")).strip()
        incoming_english = raw_row.get("english_definition", "").strip()
        incoming_example = raw_row.get("example_sentence", "").strip()
        incoming_synonyms = parse_list_field(raw_row.get("synonyms", ""))
        incoming_distractors = parse_list_field(raw_row.get("sentence_distractors", ""))
        notes = raw_row.get("notes", "").strip()
        has_new_content = any([incoming_pronunciation, incoming_english, incoming_example, incoming_synonyms, incoming_distractors, notes])
        if not has_new_content:
            stats["skipped"] += 1
            continue

        pronunciation = incoming_pronunciation or current_pronunciation
        english_definition = incoming_english or current_english
        example_sentence = incoming_example or current_example
        synonyms = incoming_synonyms or current_synonyms
        sentence_distractors = incoming_distractors or current_distractors

        conn.execute(
            """
            INSERT INTO word_enrichment (
                word_id, pronunciation, english_definition, synonyms_json, example_sentence, sentence_distractors_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(word_id) DO UPDATE SET
                pronunciation = excluded.pronunciation,
                english_definition = excluded.english_definition,
                synonyms_json = excluded.synonyms_json,
                example_sentence = excluded.example_sentence,
                sentence_distractors_json = excluded.sentence_distractors_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                word["id"],
                pronunciation,
                english_definition,
                json.dumps(synonyms, ensure_ascii=False),
                example_sentence,
                json.dumps(sentence_distractors, ensure_ascii=False),
            ),
        )
        if notes:
            conn.execute(
                """
                UPDATE study_cards
                SET notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE word_id = ?
                """,
                (notes, word["id"]),
            )
        stats["updated"] += 1
    conn.commit()
    return stats
