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

TRANSLATIONS["en"].update(
    {
        "unknown_type": "Unknown type",
        "unknown": "Unknown",
        "not_added_yet": "Not added yet.",
        "not_available": "Not available.",
        "back_to_dictionary": "Back to dictionary",
        "dictionary_title": "Dictionary",
        "dictionary_home_title": "Search, browse, and explore your word bank.",
        "dictionary_home_lede": "Search when you know the word. Browse bands when you want to discover vocabulary by frequency.",
        "review_queue": "Review queue",
        "missed_ready": "missed words ready to revisit",
        "search_example_placeholder": "Search a word, for example analyze",
        "search_button": "Search",
        "search_tag": "Search",
        "browse_tag": "Browse",
        "review_tag": "Review",
        "find_specific_word": "Find a specific word",
        "find_specific_word_note": "Best when you already know what you want to look up.",
        "open_frequency_band": "Open a frequency band",
        "open_frequency_band_note": "Best when you want to study words by appearance count.",
        "go_to_missed_words": "Go to missed words",
        "go_to_missed_words_note": "Best when you want a list based on your actual mistakes.",
        "choose_band_browse": "Choose a band to browse",
        "all_bands": "All bands",
        "english_only": "English only",
        "example_only": "Example only",
        "dictionary_search_title": "Dictionary Search",
        "dictionary_search_hero": "Find words fast.",
        "results": "Results",
        "search_results_count": "{count} results for \"{query}\"",
        "english_label": "English",
        "chinese_label": "Chinese",
        "example_label": "Example",
        "no_search_match": "No words matched this search.",
        "no_search_match_note": "Try a shorter keyword, remove one filter, or browse by frequency band instead.",
        "frequency_band": "Frequency Band",
        "words_in_band": "{count} words in this band.",
        "apply_filters": "Apply filters",
        "words_label": "Words",
        "open_word_add_details": "Open this word to add richer details.",
        "no_words_for_letter": "No words found for this letter.",
        "no_words_for_letter_note": "Try another letter or remove one of the filters.",
        "word_status": "Status",
        "correct_label": "Correct",
        "wrong_label": "Wrong",
        "overview_tab": "Overview",
        "meaning_tab": "Meaning",
        "examples_tab": "Examples",
        "notes_tab": "Notes",
        "definition_section": "Definition",
        "core_meaning": "Core meaning",
        "english_definition": "English Definition",
        "chinese_definition": "Chinese Definition",
        "no_english_definition": "No English definition added yet.",
        "no_chinese_definition": "No Chinese definition added yet.",
        "examples_section": "Examples",
        "usage_related": "Usage and related words",
        "example_sentence": "Example Sentence",
        "no_example_sentence": "No example sentence added yet.",
        "synonyms_label": "Synonyms",
        "no_synonyms": "No synonyms added yet.",
        "source_section": "Source",
        "workbook_references": "Workbook references",
        "pos_not_provided": "Part of speech not provided",
        "notes_section": "Notes",
        "memory_hook": "Your memory hook",
        "no_personal_notes": "No personal notes yet. Add a short memory hook or reminder for this word.",
        "edit_section": "Edit",
        "improve_word": "Improve this word",
        "improve_word_note": "Add clearer definitions, examples, and distractors to make learning mode stronger.",
        "notes_label": "Notes",
        "ipa_label": "IPA",
        "wrong_sentence_options": "Wrong Sentence Options",
        "save_changes": "Save Changes",
        "add_concise_english_definition": "Add a concise English definition",
        "add_ipa_placeholder": "Add IPA, e.g. /əˈbɪləti/",
        "one_synonym_per_line": "One synonym per line",
        "add_natural_sentence": "Add one natural sentence using the word",
        "one_distractor_per_line": "One distractor sentence per line",
        "learning_title": "Learning",
        "learning_hero_title": "Train in short, focused loops.",
        "learning_hero_lede": "Each session gives you multiple-choice practice from your Economist vocabulary database. As you enrich more words, learning becomes deeper and less repetitive.",
        "latest_label": "Latest",
        "ready_label": "Ready",
        "most_recent_session": "most recent session",
        "start_new_session_note": "start a new session",
        "session_goal": "Session Goal",
        "build_consistency": "Build consistency first",
        "definition_short": "Definition",
        "synonym_short": "Synonym",
        "sentence_short": "Sentence",
        "definition_available_note": "Definitions are available immediately. Synonym and sentence questions appear as more words gain enrichment.",
        "start_learning_session": "Start Learning Session",
        "coverage": "Coverage",
        "learning_bank": "Your learning bank",
        "enriched_label": "Enriched",
        "sentence_ready": "Sentence Ready",
        "how_it_works": "How It Works",
        "what_mode_gives_you": "What this mode gives you",
        "study_rounds_note": "Short study rounds help you keep momentum without overloading yourself.",
        "definition_first": "Definition first",
        "definition_first_note": "Start with meaning-based questions even if enrichment is still limited.",
        "review_after_answer": "Review after every answer",
        "review_after_answer_note": "See the explanation and reopen the full word page when needed.",
        "smarter_over_time": "Smarter over time",
        "smarter_over_time_note": "As you add notes, synonyms, and examples, practice becomes richer automatically.",
        "best_next_step": "Best Next Step",
        "enrich_first": "Enrich a few words first",
        "enrich_first_note": "You can already start learning, but adding some English definitions, synonyms, and example sentences will make sessions much stronger.",
        "latest_session": "Latest Session",
        "recent_session_saved": "Your most recent learning session is saved. Start another round to keep building recall.",
        "start_another_session": "Start Another Session",
        "question_counter": "Question {current} / {total}",
        "percent_complete": "{percent}% complete",
        "submit_answer": "Submit Answer",
        "before_answering": "Before Answering",
        "open_word": "Open word",
        "pronunciation_label": "Pronunciation",
        "word_type": "Word Type",
        "frequency_band_label": "Frequency Band",
        "what_stays_hidden": "What stays hidden",
        "hidden_learning_note": "Definitions, synonyms, and examples stay hidden until you submit, so this step works like real practice.",
        "answered_counter": "{answered}/{total} answered",
        "correct_review": "Correct",
        "review_label": "Review",
        "your_answer": "Your answer:",
        "correct_answer": "Correct answer:",
        "nice_work_note": "Nice work. This word is moving in the right direction.",
        "read_details_note": "Take a moment to read the details below before moving on.",
        "see_session_result": "See Session Result",
        "next_question": "Next Question",
        "open_word_page": "Open Word Page",
        "after_answering": "After Answering",
        "now_unlocked": "Now unlocked",
        "now_unlocked_note": "The full meaning view is open now, so use this step to confirm the idea and fix the word in memory.",
        "correct_wrong": "Correct / Wrong",
        "session_complete": "Session Complete",
        "learning_result_title": "You answered {score} correctly.",
        "learning_result_lede": "Your learning round is saved. Use the result below to decide whether to continue, review, or enrich more words.",
        "accuracy_label": "Accuracy",
        "session_score": "Session Score",
        "next_focus": "Next focus:",
        "breakdown": "Breakdown",
        "question_types": "Question types",
        "question_type_label": "Question Type",
        "total_label": "Total",
        "level_test_title": "Level Test",
        "find_starting_band": "Find your starting band.",
        "test_intro_lede": "This placement test uses {count} multiple-choice questions from different frequency bands to estimate your current Economist vocabulary level.",
        "questions_label": "Questions",
        "definition_based_items": "definition-based items",
        "what_it_measures": "What It Measures",
        "foundation_across_bands": "Foundation across bands",
        "frequency_short": "Frequency",
        "recognition_short": "Recognition",
        "placement_short": "Placement",
        "test_goal_note": "The result combines your total accuracy with how well you handled harder frequency bands.",
        "begin_test": "Begin Test",
        "band_coverage": "Band Coverage",
        "sampled_ranges": "Sampled ranges",
        "what_this_means": "What this means",
        "sampled_from_band": "This question is sampled from the {band} frequency band.",
        "goal_label": "Goal",
        "test_goal_fast": "Choose the best definition and keep moving. The test is designed to be fast and reliable.",
        "hidden_test_note": "Definitions and full word details appear only after you submit, so the placement result stays fair.",
        "recognized_correctly": "You recognized this word correctly.",
        "revisit_later_note": "This is a useful word to revisit later in learning mode.",
        "see_test_result": "See Test Result",
        "result_label": "Result",
        "getting_started": "Getting Started",
        "test_result_lede": "You answered {score} correctly in this placement test. This result estimates where you should start learning next.",
        "estimated_band_chip": "Estimated band: {band}",
        "correct_chip": "Correct: {score}",
        "weighted_chip": "Weighted: {percent}%",
        "test_result_note": "This result combines your total accuracy and how well you handled harder frequency bands.",
        "what_to_do_next": "What to do next:",
        "band_breakdown": "Band Breakdown",
        "band_performance": "How you performed by range",
        "band_accuracy_note": "{percent}% accuracy in this band.",
        "try_again": "Try Again",
        "go_to_learning": "Go To Learning",
        "review_queue_title": "Missed words",
        "review_queue_lede": "This list collects words you answered incorrectly in tests and learning sessions, so your revision is guided by real mistakes instead of random guesses.",
        "total_to_review": "Total to review",
        "words_in_queue": "words in the queue",
        "open_learning": "Open Learning",
        "missed_times": "missed {count} times",
        "open_word_add_definition_example": "Open this word to add an English definition and example sentence.",
        "all_clear": "All Clear",
        "no_missed_words": "No missed words yet.",
        "review_queue_auto": "After a test or learning session, your review queue will appear here automatically.",
        "start_learning": "Start Learning",
    }
)

TRANSLATIONS["zh-Hant"].update(
    {
        "unknown_type": "詞性未提供",
        "unknown": "未提供",
        "not_added_yet": "尚未補上。",
        "not_available": "目前沒有資料。",
        "back_to_dictionary": "回到詞典",
        "dictionary_title": "詞典",
        "dictionary_home_title": "搜尋、瀏覽、整理你的單字庫。",
        "dictionary_home_lede": "知道單字時可以直接搜尋；想多看一些常見字時，也可以按分類瀏覽。",
        "review_queue": "複習清單",
        "missed_ready": "個錯題待重新查看",
        "search_example_placeholder": "搜尋單字，例如 analyze",
        "search_button": "搜尋",
        "search_tag": "搜尋",
        "browse_tag": "瀏覽",
        "review_tag": "複習",
        "find_specific_word": "找特定單字",
        "find_specific_word_note": "已經知道要查哪個字時，用這個最快。",
        "open_frequency_band": "打開一個單字分類",
        "open_frequency_band_note": "想按常見程度學字時，用這個最方便。",
        "go_to_missed_words": "前往錯題清單",
        "go_to_missed_words_note": "想根據自己真正答錯的單字來複習時，就看這裡。",
        "choose_band_browse": "選擇想看的單字分類",
        "all_bands": "全部分類",
        "english_only": "只看有英文定義",
        "example_only": "只看有例句",
        "dictionary_search_title": "搜尋單字",
        "dictionary_search_hero": "快速找到你要的單字。",
        "results": "搜尋結果",
        "search_results_count": "「{query}」共有 {count} 筆結果",
        "english_label": "英文",
        "chinese_label": "中文",
        "example_label": "例句",
        "no_search_match": "找不到符合這次搜尋的單字。",
        "no_search_match_note": "可以試試更短的關鍵字、移除一個篩選條件，或改用分類瀏覽。",
        "frequency_band": "單字分類",
        "words_in_band": "這一組共有 {count} 個單字。",
        "apply_filters": "套用條件",
        "words_label": "單字",
        "open_word_add_details": "打開這個單字頁補上更完整的內容。",
        "no_words_for_letter": "這個字母下目前沒有單字。",
        "no_words_for_letter_note": "試試其他字母，或移除其中一個篩選條件。",
        "word_status": "狀態",
        "correct_label": "答對",
        "wrong_label": "答錯",
        "overview_tab": "總覽",
        "meaning_tab": "詞義",
        "examples_tab": "例句",
        "notes_tab": "筆記",
        "definition_section": "定義",
        "core_meaning": "核心意思",
        "english_definition": "英文定義",
        "chinese_definition": "中文定義",
        "no_english_definition": "尚未加入英文定義。",
        "no_chinese_definition": "尚未加入中文定義。",
        "examples_section": "例句",
        "usage_related": "用法與相關詞",
        "example_sentence": "例句",
        "no_example_sentence": "尚未加入例句。",
        "synonyms_label": "同義詞",
        "no_synonyms": "尚未加入同義詞。",
        "source_section": "來源",
        "workbook_references": "工作表來源",
        "pos_not_provided": "原始資料未提供詞性",
        "notes_section": "筆記",
        "memory_hook": "你的記憶提示",
        "no_personal_notes": "目前還沒有個人筆記，可以加上一句方便記憶的提示。",
        "edit_section": "編輯",
        "improve_word": "補強這個單字",
        "improve_word_note": "補上更清楚的定義、例句和干擾選項，能讓學習模式更完整。",
        "notes_label": "筆記",
        "ipa_label": "IPA",
        "wrong_sentence_options": "錯誤例句選項",
        "save_changes": "儲存變更",
        "add_concise_english_definition": "加入精簡的英文定義",
        "add_ipa_placeholder": "加入 IPA，例如 /əˈbɪləti/",
        "one_synonym_per_line": "每行一個同義詞",
        "add_natural_sentence": "加入一個自然的例句",
        "one_distractor_per_line": "每行一個錯誤例句選項",
        "learning_title": "學習",
        "learning_hero_title": "用短時間，穩定把單字學起來。",
        "learning_hero_lede": "每次練習都會從你的《經濟學人》單字庫出題。你補得越完整，之後的題目就會越實用、越不重複。",
        "latest_label": "最近",
        "ready_label": "準備好了",
        "most_recent_session": "最近一次練習",
        "start_new_session_note": "開始新的練習",
        "session_goal": "這輪要做什麼",
        "build_consistency": "先把基礎答穩",
        "definition_short": "定義",
        "synonym_short": "同義詞",
        "sentence_short": "例句",
        "definition_available_note": "一開始會先用定義題練習；之後單字內容越完整，系統就會慢慢加入同義詞和例句題。",
        "start_learning_session": "開始這輪練習",
        "coverage": "目前內容",
        "learning_bank": "你的單字庫",
        "enriched_label": "已補內容",
        "sentence_ready": "已有例句",
        "how_it_works": "怎麼用",
        "what_mode_gives_you": "這個模式會怎樣幫你",
        "study_rounds_note": "每次做短一點，比較容易維持節奏，也不會一下子太累。",
        "definition_first": "先從定義開始",
        "definition_first_note": "即使內容還沒完全補齊，也能先用意思題建立基礎。",
        "review_after_answer": "每答完就複習",
        "review_after_answer_note": "每題之後都能看解釋，需要時也能打開完整單字頁。",
        "smarter_over_time": "越用越完整",
        "smarter_over_time_note": "當你加入筆記、同義詞與例句後，練習內容會自動變得更豐富。",
        "best_next_step": "下一步建議",
        "enrich_first": "先補幾個單字內容",
        "enrich_first_note": "你現在已經可以開始練習，但如果先補上一些英文定義、同義詞和例句，整體效果會更好。",
        "latest_session": "最近一次練習",
        "recent_session_saved": "你最近一次的學習練習已經保存，可以直接再開始一輪。",
        "start_another_session": "再開始一輪",
        "question_counter": "第 {current} 題，共 {total} 題",
        "percent_complete": "已完成 {percent}%",
        "submit_answer": "送出答案",
        "before_answering": "作答前",
        "open_word": "查看單字頁",
        "pronunciation_label": "發音",
        "word_type": "詞性",
        "frequency_band_label": "單字分類",
        "what_stays_hidden": "這一步先不顯示",
        "hidden_learning_note": "在你作答前，定義、同義詞和例句都會先藏起來，這樣比較像真正練習。",
        "answered_counter": "已作答 {answered}/{total}",
        "correct_review": "答對",
        "review_label": "複習",
        "your_answer": "你的答案：",
        "correct_answer": "正確答案：",
        "nice_work_note": "做得不錯，這個單字正在往穩定記憶前進。",
        "read_details_note": "先看一下下面的說明，再繼續下一題。",
        "see_session_result": "查看本次結果",
        "next_question": "下一題",
        "open_word_page": "打開單字頁",
        "after_answering": "作答後",
        "now_unlocked": "現在可以看到完整內容",
        "now_unlocked_note": "現在可以看完整意思，利用這一步再確認一次，幫助把單字記住。",
        "correct_wrong": "答對 / 答錯",
        "session_complete": "這輪練習完成了",
        "learning_result_title": "這次你答對了 {score} 題。",
        "learning_result_lede": "這輪練習已經保存。你可以根據下面結果決定要繼續練、先複習，或回去補單字內容。",
        "accuracy_label": "正確率",
        "session_score": "本次得分",
        "next_focus": "下一步建議：",
        "breakdown": "結果拆解",
        "question_types": "題型分布",
        "question_type_label": "題型",
        "total_label": "總數",
        "level_test_title": "程度檢測",
        "find_starting_band": "找出適合你的單字程度。",
        "test_intro_lede": "這個程度檢測會從不同常見程度的單字中抽出 {count} 題選擇題，幫你估算目前的《經濟學人》詞彙程度。",
        "questions_label": "題目數",
        "definition_based_items": "以定義為主的題目",
        "what_it_measures": "這份檢測在看什麼",
        "foundation_across_bands": "看看你對不同層次單字的掌握",
        "frequency_short": "常見度",
        "recognition_short": "辨識",
        "placement_short": "定位",
        "test_goal_note": "結果會同時參考你的整體正確率，以及你在較難單字上的表現。",
        "begin_test": "開始測驗",
        "band_coverage": "出題範圍",
        "sampled_ranges": "抽樣分類",
        "what_this_means": "這代表什麼",
        "sampled_from_band": "這一題是從 {band} 這一組單字抽出的。",
        "goal_label": "目標",
        "test_goal_fast": "選出最合適的定義後繼續往下。這份檢測設計成快速、直接，而且有一致性。",
        "hidden_test_note": "在你送出答案前，完整定義和單字細節都不會先顯示，這樣結果才比較準。",
        "recognized_correctly": "你正確辨認了這個單字。",
        "revisit_later_note": "這是之後很適合放回學習模式再加強的單字。",
        "see_test_result": "查看檢測結果",
        "result_label": "結果",
        "getting_started": "起步中",
        "test_result_lede": "你在這次程度檢測中答對了 {score} 題。根據結果，系統會建議你下一步適合從哪一組單字開始。",
        "estimated_band_chip": "建議起點：{band}",
        "correct_chip": "答對：{score}",
        "weighted_chip": "加權：{percent}%",
        "test_result_note": "這個結果不只看總分，也會一起參考你在較難單字上的表現。",
        "what_to_do_next": "接下來可以：",
        "band_breakdown": "各組表現",
        "band_performance": "你在不同單字分類的表現",
        "band_accuracy_note": "這一組單字的正確率是 {percent}%。",
        "try_again": "再測一次",
        "go_to_learning": "前往學習",
        "review_queue_title": "錯題複習",
        "review_queue_lede": "這裡會收集你在檢測和練習中答錯的單字，讓你之後複習時更有方向，不用亂猜。",
        "total_to_review": "待複習總數",
        "words_in_queue": "個單字在清單裡",
        "open_learning": "前往學習",
        "missed_times": "答錯 {count} 次",
        "open_word_add_definition_example": "打開這個單字頁，補上英文定義和例句。",
        "all_clear": "目前清空了",
        "no_missed_words": "目前還沒有錯題。",
        "review_queue_auto": "做完一次檢測或練習後，錯題清單就會自動出現在這裡。",
        "start_learning": "開始學習",
    }
)


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


def translate_question_type(value: str, lang: str = "en") -> str:
    labels = {
        "en": {"definition": "Definition", "synonym": "Synonym", "sentence": "Sentence"},
        "zh-Hant": {"definition": "定義", "synonym": "同義詞", "sentence": "例句"},
    }
    return labels.get(lang, labels["en"]).get(value, value)


def translate_status(value: str, lang: str = "en") -> str:
    labels = {
        "en": {"new": "new", "learning": "learning", "review": "review", "mastered": "mastered"},
        "zh-Hant": {"new": "新字", "learning": "學習中", "review": "待複習", "mastered": "已熟悉"},
    }
    return labels.get(lang, labels["en"]).get(value, value)


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
            "qtype_label": lambda value: translate_question_type(value, lang),
            "status_label": lambda value: translate_status(value, lang),
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


def progress_label(percent: float, lang: str = "en") -> str:
    labels = {
        "en": ["Advanced", "Upper Intermediate", "Intermediate", "Lower Intermediate", "Foundation Builder"],
        "zh-Hant": ["進階", "中高階", "中階", "初中階", "基礎建立中"],
    }
    bucket = labels.get(lang, labels["en"])
    if percent >= 0.85:
        return bucket[0]
    if percent >= 0.7:
        return bucket[1]
    if percent >= 0.5:
        return bucket[2]
    if percent >= 0.3:
        return bucket[3]
    return bucket[4]


def level_recommendation(estimated_band_label: str | None, percent: float, lang: str = "en") -> str:
    if lang == "zh-Hant":
        if not estimated_band_label:
            return "先從 50~99 頻率帶開始，再優先替你最常答錯的單字補上筆記與例句。"
        if percent >= 0.7:
            return f"你目前可以穩定從 {estimated_band_label} 附近開始。接下來可以到詞典看更高一級的頻率帶，並補強不熟的字。"
        return f"接下來幾次學習，先集中在 {estimated_band_label} 和再低一級的頻率帶，直到答案更自然為止。"
    if not estimated_band_label:
        return "Start with the 50~99 band, then add notes and examples to words you miss most often."
    if percent >= 0.7:
        return f"You can comfortably work around {estimated_band_label}. Move into the next harder band in Dictionary and enrich unfamiliar words."
    return f"Focus your next learning sessions around {estimated_band_label} and the band just below it until the answers feel automatic."


def learning_recommendation(correct: int, total: int, enriched_words: int, lang: str = "en") -> str:
    if lang == "zh-Hant":
        if total == 0:
            return "先替幾個單字補充更多內容，學習模式之後才能出更豐富的題目。"
        percent = correct / total
        if percent >= 0.8 and enriched_words > 0:
            return "節奏不錯。可以繼續學，或開始加入更高頻率帶與更多例句題。"
        if enriched_words == 0:
            return "定義題已經有幫助，但如果再補上同義詞和例句，下一輪學習會更完整。"
        return "先回頭看錯題、補清楚筆記，再持續在詞典裡增加更完整的單字內容。"
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
    pronunciation = ""
    english_definition = ""
    example_sentence = ""
    for row in rows:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        if isinstance(extra, dict):
            if not pronunciation and extra.get("pronunciation"):
                pronunciation = extra["pronunciation"]
            if not english_definition and extra.get("english_definition"):
                english_definition = extra["english_definition"]
            if not example_sentence and extra.get("example_sentence"):
                example_sentence = extra["example_sentence"]
    return {
        "pronunciation": pronunciation,
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
    result = {word_id: {"pronunciation": "", "english_definition": "", "example_sentence": ""} for word_id in word_ids}
    for row in rows:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        if not isinstance(extra, dict):
            continue
        target = result[row["word_id"]]
        if not target["pronunciation"] and extra.get("pronunciation"):
            target["pronunciation"] = extra["pronunciation"]
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
        "pronunciation": (enrichment["pronunciation"] if enrichment and enrichment["pronunciation"] else source_fallback["pronunciation"]),
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
               COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        ORDER BY words.best_band_rank DESC, words.lemma
        LIMIT 60
        """,
        (),
    ).fetchall()
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids)
    parts_map = parts_of_speech_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    items: list[dict] = []
    for row in rows:
        defs = definitions_map.get(row["id"], [])
        pos = parts_map.get(row["id"], [])
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        english_definition = row["english_definition"] or source_fallback["english_definition"]
        example_sentence = row["example_sentence"] or source_fallback["example_sentence"]
        if len(row["lemma"].strip()) <= 4:
            continue
        if not defs and not english_definition and not example_sentence:
            continue
        items.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": english_definition,
                "example_sentence": example_sentence,
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
                "parts_of_speech": pos,
                "chinese_preview": defs[:1],
                "chinese_headword": defs[0] if defs else "",
            }
        )
        if len(items) >= limit:
            break
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
               COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
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
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        english_definition = row["english_definition"] or source_fallback["english_definition"]
        example_sentence = row["example_sentence"] or source_fallback["example_sentence"]
        cards.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": english_definition,
                "example_sentence": example_sentence,
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
                "parts_of_speech": parts,
                "chinese_preview": definitions[:2],
            }
        )
    return cards


def missed_words(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    rows = conn.execute(
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
            COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
            COALESCE(word_enrichment.english_definition, '') AS english_definition,
            COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM wrong_answers
        JOIN words ON words.id = wrong_answers.word_id
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        GROUP BY words.id, words.lemma, words.best_band_label, word_enrichment.pronunciation, word_enrichment.english_definition, word_enrichment.example_sentence
        ORDER BY miss_count DESC, last_seen DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    result = []
    for row in rows:
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        result.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "miss_count": row["miss_count"],
                "last_seen": row["last_seen"],
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
                "english_definition": row["english_definition"] or source_fallback["english_definition"],
                "example_sentence": row["example_sentence"] or source_fallback["example_sentence"],
                "chinese_preview": definitions_map.get(row["id"], [])[:1],
            }
        )
    return result


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
    lang = getattr(request.state, "lang", get_lang(request))
    level_name = progress_label((summary["accuracy_percent"] or 0) / 100, lang)
    recommendation = level_recommendation(session["estimated_band_label"], (summary["accuracy_percent"] or 0) / 100, lang)
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
    lang = getattr(request.state, "lang", get_lang(request))
    recommendation = learning_recommendation(session["score"], total, enriched_words, lang)
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
               COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
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
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        words.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "english_definition": row["english_definition"] or source_fallback["english_definition"],
                "example_sentence": row["example_sentence"] or source_fallback["example_sentence"],
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
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
