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
SUPPORTED_LANGS = {"en", "zh-Hant", "zh-Hans"}
SUPPORTED_PERSONAS = {
    "student",
    "teacher",
    "business_professional",
    "ai_power_user",
    "lifelong_learner",
}

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
        "onboarding_step_1": "Step 1",
        "onboarding_step_2": "Step 2",
        "onboarding_title": "Welcome to Economist Lab",
        "onboarding_lede": "Let's make your learning experience personal.",
        "onboarding_name_label": "First name",
        "onboarding_name_hint": "Optional. Add your name if you'd like a more personal dashboard.",
        "onboarding_name_placeholder": "Your first name",
        "onboarding_role_title": "Who are you?",
        "onboarding_role_lede": "Pick the track that fits you best. We'll tailor the dashboard and recommendations right away.",
        "onboarding_submit": "Continue to my dashboard",
        "persona_student": "Student",
        "persona_student_desc": "High school or university learners building stronger academic English.",
        "persona_teacher": "Teacher / Educator",
        "persona_teacher_desc": "Teaching, coaching, or creating materials for others.",
        "persona_business": "Business Professional",
        "persona_business_desc": "Work communication, presentations, meetings, and sharper decision language.",
        "persona_ai": "AI Power User",
        "persona_ai_desc": "Using AI daily for prompting, writing, analysis, and higher-precision output.",
        "persona_lifelong": "Lifelong Learner / Other",
        "persona_lifelong_desc": "Adults learning for growth, curiosity, and long-term communication confidence.",
        "persona_featured": "Recommended",
        "persona_message_prefix": "Great!",
        "persona_message_student": "We'll highlight academic reading support and structured vocabulary growth.",
        "persona_message_teacher": "We'll surface clearer teaching-ready examples and explanation-focused word cards.",
        "persona_message_business": "We'll recommend more business, AI prompting, and professional communication vocabulary.",
        "persona_message_ai": "We'll recommend more AI prompting, precise instruction language, and professional-use vocabulary.",
        "persona_message_lifelong": "We'll recommend a balanced mix of practical, high-frequency, and confidence-building vocabulary.",
        "personal_dashboard": "Your personalized dashboard",
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
        "recommend_note_student": "Start with level-finding and steady academic vocabulary growth.",
        "recommend_note_teacher": "Focus on lesson-ready words, clearer explanations, and review material.",
        "recommend_note_business": "Focus on business communication, AI prompting, and precise professional language.",
        "recommend_note_ai": "Focus on precise prompting, instruction language, and high-utility vocabulary.",
        "recommend_note_lifelong": "Keep a balanced flow with practical learning, checking, and review.",
        "card_student_test": "Find your current starting range, then build upward with confidence.",
        "card_student_learning": "Practice a short set of high-value words for steady academic growth.",
        "card_student_dictionary": "Browse common bands and save useful words for study or writing.",
        "card_teacher_dictionary": "Open words quickly, compare meanings, and pull examples for teaching.",
        "card_teacher_review": "Turn missed items into reusable teaching and revision material.",
        "card_teacher_learning": "Use short sessions to spot useful classroom-ready vocabulary.",
        "card_business_learning": "Train the words that improve meetings, presentations, and decision language.",
        "card_business_dictionary": "Look up precise vocabulary for reports, emails, and professional writing.",
        "card_business_test": "Check your current range first, then focus on the right band.",
        "card_ai_learning": "Build precise instruction vocabulary you can reuse in prompts and workflows.",
        "card_ai_dictionary": "Browse clear, high-utility words for prompting, analysis, and writing.",
        "card_ai_test": "Estimate your level, then train the band that gives the fastest return.",
        "card_lifelong_learning": "Keep momentum with a short session built around useful, reusable words.",
        "card_lifelong_test": "Use a quick test to choose a comfortable and motivating starting point.",
        "card_lifelong_review": "Return to missed words and turn them into long-term memory.",
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
        "sidebar_flow_text": "先用程度檢測找出適合的詞彙範圍，再逐步補齊每張詞彙卡的內容。",
        "sidebar_flow_link": "前往學習",
        "topbar_search": "搜尋詞彙、分類或定義...",
        "topbar_project": "經濟學人詞彙專案",
        "home_eyebrow": "首頁總覽",
        "home_title": "Lawrence，你好。",
        "home_lede": "把《經濟學人》詞彙整理成清楚的每日學習流程：測驗、練習、複習。",
        "onboarding_step_1": "第 1 步",
        "onboarding_step_2": "第 2 步",
        "onboarding_title": "歡迎來到 Economist Lab",
        "onboarding_lede": "先讓我們把你的學習體驗調整得更貼近你。",
        "onboarding_name_label": "名字",
        "onboarding_name_hint": "可選填。如果你願意，我們會用名字讓首頁更有個人感。",
        "onboarding_name_placeholder": "你的名字",
        "onboarding_role_title": "你目前是哪一類使用者？",
        "onboarding_role_lede": "請選最符合你的角色，我們會立刻調整首頁和推薦內容。",
        "onboarding_submit": "進入我的個人化首頁",
        "persona_student": "學生",
        "persona_student_desc": "高中、大學或研究所階段，想建立更強的學術英語能力。",
        "persona_teacher": "教師 / 教育工作者",
        "persona_teacher_desc": "教學、帶領學生，或需要整理教材與說明內容。",
        "persona_business": "商務專業人士",
        "persona_business_desc": "工作溝通、簡報、會議與更精準的專業表達。",
        "persona_ai": "AI 重度使用者",
        "persona_ai_desc": "每天都會使用 AI 進行提示詞、寫作、分析或內容整理。",
        "persona_lifelong": "終身學習者 / 其他",
        "persona_lifelong_desc": "為了成長、興趣與長期溝通能力而持續學習的成人使用者。",
        "persona_featured": "推薦",
        "persona_message_prefix": "很好！",
        "persona_message_student": "我們會優先推薦更適合學術閱讀與循序累積的詞彙內容。",
        "persona_message_teacher": "我們會提供更適合教學說明、舉例與整理概念的詞彙內容。",
        "persona_message_business": "我們會推薦更多商務、AI 提示與專業溝通場景的詞彙。",
        "persona_message_ai": "我們會推薦更多 AI 提示詞、精準指令語言與專業應用詞彙。",
        "persona_message_lifelong": "我們會推薦更平衡、實用且能建立長期信心的詞彙內容。",
        "personal_dashboard": "你的個人化首頁",
        "motto_label": "學習信念",
        "motto_quote": "Without grammar very little can be conveyed, without vocabulary nothing can be conveyed.",
        "motto_cite": "Wilkins, 1972, p. 111",
        "tests_taken": "已完成測驗",
        "current_band": "目前建議範圍",
        "today_goal": "今日目標",
        "keep_moving": "讓今天的學習持續前進",
        "placement": "測驗",
        "practice": "練習",
        "review": "複習",
        "study_flow": "學習流程",
        "goal_note": "先做程度檢測，再練習建議的詞彙範圍，最後查看錯題或進入詞典補充內容。",
        "start_test": "開始程度檢測",
        "continue_learning": "繼續學習",
        "your_progress": "你的進度",
        "at_a_glance": "快速總覽",
        "total_words": "總詞彙數",
        "learning_runs": "學習次數",
        "missed_words": "待複習錯題",
        "synonym_ready": "已補同義詞",
        "today_words": "今日詞彙",
        "start_with_few": "先從幾個詞彙開始",
        "today_words_note": "先打開幾張詞彙卡，補齊更清楚的定義、例句與同義詞。",
        "view_all": "查看全部",
        "recommended_for_you": "下一步建議",
        "choose_next": "選擇你現在最適合的下一步",
        "choose_next_note": "用三個最快的入口保持學習節奏，不需要每次重新想要做什麼。",
        "learning_session": "學習練習",
        "frequency_bands": "詞彙分級",
        "browse_count": "依出現次數瀏覽",
        "open_dictionary": "打開詞典",
        "bands_note": "數字越高，表示這個詞彙在你近十年的《經濟學人》資料中出現得越多。",
        "core_steps": "3 個核心步驟",
        "flow_sequence": "測驗 → 練習 → 複習",
        "latest_result": "最近結果：{band}。",
        "first_test_prompt": "先完成第一次檢測，系統才會建議適合的詞彙起點。",
        "latest_score": "最近分數：{score}/{total}。",
        "start_short_session": "先從建議的詞彙範圍開始做一個短練習。",
        "review_queue_count": "目前有 {count} 個錯題等待你複習。",
        "recommend_note_student": "先找出適合的起點，再穩定累積學術與高頻詞彙。",
        "recommend_note_teacher": "優先使用可教學、可解釋、可複習的詞彙內容。",
        "recommend_note_business": "優先強化商務溝通、AI 提示與精準專業表達。",
        "recommend_note_ai": "優先強化提示詞、指令語言與高實用性的精準詞彙。",
        "recommend_note_lifelong": "用平衡的方式持續累積，兼顧學習、檢查與複習。",
        "card_student_test": "先找出目前適合的起始範圍，再更有方向地往上累積。",
        "card_student_learning": "先做一輪短練習，穩定補強高價值學術詞彙。",
        "card_student_dictionary": "按常見程度瀏覽，收藏適合閱讀與寫作的詞彙。",
        "card_teacher_dictionary": "快速查詞、比較詞義與例句，整理成可教學的內容。",
        "card_teacher_review": "把錯題整理成更適合教學與複習的材料。",
        "card_teacher_learning": "用短練習找出值得帶進課堂的詞彙。",
        "card_business_learning": "強化能改善會議、簡報與決策表達的關鍵詞彙。",
        "card_business_dictionary": "查找更精準的報告、email 與專業寫作用語。",
        "card_business_test": "先快速確認目前範圍，再集中在最適合的詞彙分類。",
        "card_ai_learning": "建立可直接用在提示詞、分析與工作流程中的精準詞彙。",
        "card_ai_dictionary": "瀏覽適合提示、分析與寫作的高實用性詞彙。",
        "card_ai_test": "先估算程度，再集中練習回報最快的詞彙範圍。",
        "card_lifelong_learning": "用一輪短練習，穩定累積實用且能反覆使用的詞彙。",
        "card_lifelong_test": "先用快速測驗找出舒服又有成就感的起點。",
        "card_lifelong_review": "回頭複習曾經答錯的詞，慢慢變成長期記憶。",
    },
}

TRANSLATIONS["en"].update(
    {
        "language_label": "Language",
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
        "hero_chart_label": "Vocabulary Snapshot",
        "hero_chart_title": "Your Economist corpus",
        "hero_chart_note": "A quick look at how your vocabulary source is distributed across frequency groups.",
        "hero_chart_total": "Total entries",
        "hero_chart_bands": "Frequency groups",
    }
)

TRANSLATIONS["zh-Hant"].update(
    {
        "language_label": "語言",
        "unknown_type": "詞性未提供",
        "unknown": "未提供",
        "not_added_yet": "尚未補上。",
        "not_available": "目前沒有資料。",
        "back_to_dictionary": "回到詞典",
        "dictionary_title": "詞典",
        "dictionary_home_title": "搜尋、瀏覽、整理你的詞彙庫。",
        "dictionary_home_lede": "知道詞彙時可以直接搜尋；想多看一些常見詞彙時，也可以按分類瀏覽。",
        "review_queue": "複習清單",
        "missed_ready": "個錯題待重新查看",
        "search_example_placeholder": "搜尋詞彙，例如 analyze",
        "search_button": "搜尋",
        "search_tag": "搜尋",
        "browse_tag": "瀏覽",
        "review_tag": "複習",
        "find_specific_word": "找特定詞彙",
        "find_specific_word_note": "已經知道要查哪個詞彙時，用這個最快。",
        "open_frequency_band": "打開一個詞彙分類",
        "open_frequency_band_note": "想按常見程度學詞彙時，用這個最方便。",
        "go_to_missed_words": "前往錯題清單",
        "go_to_missed_words_note": "想根據自己真正答錯的詞彙來複習時，就看這裡。",
        "choose_band_browse": "選擇想看的詞彙分類",
        "all_bands": "全部分類",
        "english_only": "只看有英文定義",
        "example_only": "只看有例句",
        "dictionary_search_title": "搜尋詞彙",
        "dictionary_search_hero": "快速找到你要的詞彙。",
        "results": "搜尋結果",
        "search_results_count": "「{query}」共有 {count} 筆結果",
        "english_label": "英文",
        "chinese_label": "中文",
        "example_label": "例句",
        "no_search_match": "找不到符合這次搜尋的詞彙。",
        "no_search_match_note": "可以試試更短的關鍵字、移除一個篩選條件，或改用分類瀏覽。",
        "frequency_band": "詞彙分類",
        "words_in_band": "這一組共有 {count} 個詞彙。",
        "apply_filters": "套用條件",
        "words_label": "詞彙",
        "open_word_add_details": "打開這個詞彙頁補上更完整的內容。",
        "no_words_for_letter": "這個字母下目前沒有詞彙。",
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
        "improve_word": "補強這個詞彙",
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
        "learning_hero_title": "用短時間，穩定把詞彙學起來。",
        "learning_hero_lede": "每次練習都會從你的《經濟學人》詞彙庫出題。你補得越完整，之後的題目就會越實用、越不重複。",
        "latest_label": "最近",
        "ready_label": "準備好了",
        "most_recent_session": "最近一次練習",
        "start_new_session_note": "開始新的練習",
        "session_goal": "這輪要做什麼",
        "build_consistency": "先把基礎答穩",
        "definition_short": "定義",
        "synonym_short": "同義詞",
        "sentence_short": "例句",
        "definition_available_note": "一開始會先用定義題練習；之後詞彙內容越完整，系統就會慢慢加入同義詞和例句題。",
        "start_learning_session": "開始這輪練習",
        "coverage": "目前內容",
        "learning_bank": "你的詞彙庫",
        "enriched_label": "已補內容",
        "sentence_ready": "已有例句",
        "how_it_works": "怎麼用",
        "what_mode_gives_you": "這個模式會怎樣幫你",
        "study_rounds_note": "每次做短一點，比較容易維持節奏，也不會一下子太累。",
        "definition_first": "先從定義開始",
        "definition_first_note": "即使內容還沒完全補齊，也能先用意思題建立基礎。",
        "review_after_answer": "每答完就複習",
        "review_after_answer_note": "每題之後都能看解釋，需要時也能打開完整詞彙頁。",
        "smarter_over_time": "越用越完整",
        "smarter_over_time_note": "當你加入筆記、同義詞與例句後，練習內容會自動變得更豐富。",
        "best_next_step": "下一步建議",
        "enrich_first": "先補幾個詞彙內容",
        "enrich_first_note": "你現在已經可以開始練習，但如果先補上一些英文定義、同義詞和例句，整體效果會更好。",
        "latest_session": "最近一次練習",
        "recent_session_saved": "你最近一次的學習練習已經保存，可以直接再開始一輪。",
        "start_another_session": "再開始一輪",
        "question_counter": "第 {current} 題，共 {total} 題",
        "percent_complete": "已完成 {percent}%",
        "submit_answer": "送出答案",
        "before_answering": "作答前",
        "open_word": "查看詞彙頁",
        "pronunciation_label": "發音",
        "word_type": "詞性",
        "frequency_band_label": "詞彙分類",
        "what_stays_hidden": "這一步先不顯示",
        "hidden_learning_note": "在你作答前，定義、同義詞和例句都會先藏起來，這樣比較像真正練習。",
        "answered_counter": "已作答 {answered}/{total}",
        "correct_review": "答對",
        "review_label": "複習",
        "your_answer": "你的答案：",
        "correct_answer": "正確答案：",
        "nice_work_note": "做得不錯，這個詞彙正在往穩定記憶前進。",
        "read_details_note": "先看一下下面的說明，再繼續下一題。",
        "see_session_result": "查看本次結果",
        "next_question": "下一題",
        "open_word_page": "打開詞彙頁",
        "after_answering": "作答後",
        "now_unlocked": "現在可以看到完整內容",
        "now_unlocked_note": "現在可以看完整意思，利用這一步再確認一次，幫助把詞彙記住。",
        "correct_wrong": "答對 / 答錯",
        "session_complete": "這輪練習完成了",
        "learning_result_title": "這次你答對了 {score} 題。",
        "learning_result_lede": "這輪練習已經保存。你可以根據下面結果決定要繼續練、先複習，或回去補詞彙內容。",
        "accuracy_label": "正確率",
        "session_score": "本次得分",
        "next_focus": "下一步建議：",
        "breakdown": "結果拆解",
        "question_types": "題型分布",
        "question_type_label": "題型",
        "total_label": "總數",
        "level_test_title": "程度檢測",
        "find_starting_band": "找出適合你的詞彙程度。",
        "test_intro_lede": "這個程度檢測會從不同常見程度的詞彙中抽出 {count} 題選擇題，幫你估算目前的《經濟學人》詞彙程度。",
        "questions_label": "題目數",
        "definition_based_items": "以定義為主的題目",
        "what_it_measures": "這份檢測在看什麼",
        "foundation_across_bands": "看看你對不同層次詞彙的掌握",
        "frequency_short": "常見度",
        "recognition_short": "辨識",
        "placement_short": "定位",
        "test_goal_note": "結果會同時參考你的整體正確率，以及你在較難詞彙上的表現。",
        "begin_test": "開始測驗",
        "band_coverage": "出題範圍",
        "sampled_ranges": "抽樣分類",
        "what_this_means": "這代表什麼",
        "sampled_from_band": "這一題是從 {band} 這一組詞彙抽出的。",
        "goal_label": "目標",
        "test_goal_fast": "選出最合適的定義後繼續往下。這份檢測設計成快速、直接，而且有一致性。",
        "hidden_test_note": "在你送出答案前，完整定義和詞彙細節都不會先顯示，這樣結果才比較準。",
        "recognized_correctly": "你正確辨認了這個詞彙。",
        "revisit_later_note": "這是之後很適合放回學習模式再加強的詞彙。",
        "see_test_result": "查看檢測結果",
        "result_label": "結果",
        "getting_started": "起步中",
        "test_result_lede": "你在這次程度檢測中答對了 {score} 題。根據結果，系統會建議你下一步適合從哪一組詞彙開始。",
        "estimated_band_chip": "建議起點：{band}",
        "correct_chip": "答對：{score}",
        "weighted_chip": "加權：{percent}%",
        "test_result_note": "這個結果不只看總分，也會一起參考你在較難詞彙上的表現。",
        "what_to_do_next": "接下來可以：",
        "band_breakdown": "各組表現",
        "band_performance": "你在不同詞彙分類的表現",
        "band_accuracy_note": "這一組詞彙的正確率是 {percent}%。",
        "try_again": "再測一次",
        "go_to_learning": "前往學習",
        "review_queue_title": "錯題複習",
        "review_queue_lede": "這裡會收集你在檢測和練習中答錯的詞彙，讓你之後複習時更有方向，不用亂猜。",
        "total_to_review": "待複習總數",
        "words_in_queue": "個詞彙在清單裡",
        "open_learning": "前往學習",
        "missed_times": "答錯 {count} 次",
        "open_word_add_definition_example": "打開這個詞彙頁，補上英文定義和例句。",
        "all_clear": "目前清空了",
        "no_missed_words": "目前還沒有錯題。",
        "review_queue_auto": "做完一次檢測或練習後，錯題清單就會自動出現在這裡。",
        "start_learning": "開始學習",
        "hero_chart_label": "詞彙概況",
        "hero_chart_title": "你的 Economist 詞彙分布",
        "hero_chart_note": "快速看看目前詞彙資料在不同常見程度分類中的分布情況。",
        "hero_chart_total": "總詞彙數",
        "hero_chart_bands": "詞彙分類",
    }
)

SIMPLIFIED_CHAR_MAP = str.maketrans(
    {
        "經": "经",
        "濟": "济",
        "學": "学",
        "實": "实",
        "驗": "验",
        "個": "个",
        "詞": "词",
        "彙": "汇",
        "習": "习",
        "統": "统",
        "總": "总",
        "覽": "览",
        "測": "测",
        "練": "练",
        "詢": "询",
        "錯": "错",
        "複": "复",
        "應": "应",
        "匯": "汇",
        "題": "题",
        "檢": "检",
        "適": "适",
        "圍": "围",
        "張": "张",
        "類": "类",
        "義": "义",
        "專": "专",
        "號": "号",
        "進": "进",
        "議": "议",
        "步": "步",
        "語": "语",
        "層": "层",
        "條": "条",
        "濾": "滤",
        "瀏": "浏",
        "覽": "览",
        "這": "这",
        "關": "关",
        "鍵": "键",
        "筆": "笔",
        "記": "记",
        "補": "补",
        "強": "强",
        "誤": "误",
        "選": "选",
        "儲": "储",
        "變": "变",
        "輪": "轮",
        "簡": "简",
        "開": "开",
        "啟": "启",
        "幾": "几",
        "際": "际",
        "穩": "稳",
        "庫": "库",
        "幫": "帮",
        "麼": "么",
        "帶": "带",
        "檢": "检",
        "範": "范",
        "圍": "围",
        "對": "对",
        "較": "较",
        "難": "难",
        "後": "后",
        "續": "续",
        "顯": "显",
        "與": "与",
        "當": "当",
        "覺": "觉",
        "還": "还",
        "樣": "样",
        "會": "会",
        "麼": "么",
        "數": "数",
        "組": "组",
        "網": "网",
        "頁": "页",
        "狀": "状",
        "態": "态",
        "說": "说",
        "頭": "头",
        "愛": "爱",
        "區": "区",
        "寫": "写",
        "為": "为",
        "條": "条",
        "從": "从",
        "級": "级",
        "達": "达",
        "清": "清",
        "體": "体",
        "簡": "简",
        "廣": "广",
    }
)


def to_simplified(text: str) -> str:
    return text.translate(SIMPLIFIED_CHAR_MAP)


def localize_chinese_text(text: str, lang: str) -> str:
    if not text:
        return text
    if lang == "zh-Hans":
        return to_simplified(text)
    return text


def localize_chinese_list(items: list[str], lang: str) -> list[str]:
    return [localize_chinese_text(item, lang) for item in items]


TRANSLATIONS["zh-Hans"] = {key: to_simplified(value) for key, value in TRANSLATIONS["zh-Hant"].items()}
TRANSLATIONS["zh-Hans"].update(
    {
        "language_label": "语言",
        "brand_title": "经济学人词汇实验室",
        "brand_subtitle": "个人词汇学习系统",
        "nav_dashboard": "首页总览",
        "nav_test": "程度检测",
        "nav_learning": "学习练习",
        "nav_dictionary": "词典查询",
        "nav_missed": "错题复习",
        "nav_bulk": "批量导入",
        "sidebar_flow_label": "学习流程",
        "sidebar_flow_title": "先检测，再练习，再复习。",
        "sidebar_flow_text": "先用程度检测找出适合的词汇范围，再逐步补齐每张词汇卡的内容。",
        "sidebar_flow_link": "前往学习",
        "topbar_search": "搜索词汇、分类或定义...",
        "topbar_project": "经济学人词汇项目",
        "home_eyebrow": "首页总览",
        "home_title": "Lawrence，你好。",
        "home_lede": "把《经济学人》词汇整理成清晰的每日学习流程：检测、练习、复习。",
        "onboarding_step_1": "第 1 步",
        "onboarding_step_2": "第 2 步",
        "onboarding_title": "欢迎来到 Economist Lab",
        "onboarding_lede": "先让我们把你的学习体验调整得更贴近你。",
        "onboarding_name_label": "名字",
        "onboarding_name_hint": "可选填。如果你愿意，我们会用名字让首页更有个人感。",
        "onboarding_name_placeholder": "你的名字",
        "onboarding_role_title": "你目前是哪一类使用者？",
        "onboarding_role_lede": "请选择最符合你的角色，我们会立刻调整首页和推荐内容。",
        "onboarding_submit": "进入我的个性化首页",
        "persona_student": "学生",
        "persona_student_desc": "高中、大学或研究所阶段，想建立更强的学术英语能力。",
        "persona_teacher": "教师 / 教育工作者",
        "persona_teacher_desc": "教学、带领学生，或需要整理教材与说明内容。",
        "persona_business": "商务专业人士",
        "persona_business_desc": "工作沟通、简报、会议与更精准的专业表达。",
        "persona_ai": "AI 重度使用者",
        "persona_ai_desc": "每天都会使用 AI 进行提示词、写作、分析或内容整理。",
        "persona_lifelong": "终身学习者 / 其他",
        "persona_lifelong_desc": "为了成长、兴趣与长期沟通能力而持续学习的成人使用者。",
        "persona_featured": "推荐",
        "persona_message_prefix": "很好！",
        "persona_message_student": "我们会优先推荐更适合学术阅读与循序积累的词汇内容。",
        "persona_message_teacher": "我们会提供更适合教学说明、举例与整理概念的词汇内容。",
        "persona_message_business": "我们会推荐更多商务、AI 提示与专业沟通场景的词汇。",
        "persona_message_ai": "我们会推荐更多 AI 提示词、精准指令语言与专业应用词汇。",
        "persona_message_lifelong": "我们会推荐更平衡、实用且能建立长期信心的词汇内容。",
        "personal_dashboard": "你的个性化首页",
        "tests_taken": "已完成检测",
        "current_band": "当前建议范围",
        "today_goal": "今日目标",
        "keep_moving": "让今天的学习继续推进",
        "placement": "检测",
        "practice": "练习",
        "review": "复习",
        "study_flow": "学习流程",
        "goal_note": "先做程度检测，再练习建议的词汇范围，最后查看错题或进入词典补充内容。",
        "start_test": "开始程度检测",
        "continue_learning": "继续学习",
        "your_progress": "你的进度",
        "at_a_glance": "快速概览",
        "total_words": "总词汇数",
        "learning_runs": "学习次数",
        "missed_words": "待复习错题",
        "synonym_ready": "已补同义词",
        "today_words": "今日词汇",
        "start_with_few": "先从几个词汇开始",
        "today_words_note": "先打开几张词汇卡，补齐更清晰的定义、例句和同义词。",
        "view_all": "查看全部",
        "recommended_for_you": "下一步建议",
        "choose_next": "选择你现在最适合的下一步",
        "choose_next_note": "用三个最快的入口保持学习节奏，不需要每次重新想该做什么。",
        "learning_session": "学习练习",
        "frequency_bands": "词汇分级",
        "browse_count": "按出现次数浏览",
        "open_dictionary": "打开词典",
        "bands_note": "数字越高，表示这个词汇在你近十年的《经济学人》资料中出现得越多。",
        "core_steps": "3 个核心步骤",
        "flow_sequence": "检测 → 练习 → 复习",
        "latest_result": "最近结果：{band}。",
        "first_test_prompt": "先完成第一次检测，系统才会建议适合的词汇起点。",
        "latest_score": "最近分数：{score}/{total}。",
        "start_short_session": "先从建议的词汇范围开始做一轮短练习。",
        "review_queue_count": "目前有 {count} 个错题等你复习。",
        "recommend_note_student": "先找出适合的起点，再稳定积累学术与高频词汇。",
        "recommend_note_teacher": "优先使用可教学、可解释、可复习的词汇内容。",
        "recommend_note_business": "优先强化商务沟通、AI 提示与精准专业表达。",
        "recommend_note_ai": "优先强化提示词、指令语言与高实用性的精准词汇。",
        "recommend_note_lifelong": "用平衡的方式持续积累，兼顾学习、检查与复习。",
        "card_student_test": "先找出目前适合的起始范围，再更有方向地往上积累。",
        "card_student_learning": "先做一轮短练习，稳定补强高价值学术词汇。",
        "card_student_dictionary": "按常见程度浏览，收藏适合阅读与写作的词汇。",
        "card_teacher_dictionary": "快速查词、比较词义与例句，整理成可教学的内容。",
        "card_teacher_review": "把错题整理成更适合教学与复习的材料。",
        "card_teacher_learning": "用短练习找出值得带进课堂的词汇。",
        "card_business_learning": "强化能改善会议、简报与决策表达的关键词汇。",
        "card_business_dictionary": "查找更精准的报告、email 与专业写作用语。",
        "card_business_test": "先快速确认目前范围，再集中在最适合的词汇分类。",
        "card_ai_learning": "建立可直接用在提示词、分析与工作流程中的精准词汇。",
        "card_ai_dictionary": "浏览适合提示、分析与写作的高实用性词汇。",
        "card_ai_test": "先估算程度，再集中练习回报最快的词汇范围。",
        "card_lifelong_learning": "用一轮短练习，稳定积累实用且能反复使用的词汇。",
        "card_lifelong_test": "先用快速测验找出舒服又有成就感的起点。",
        "card_lifelong_review": "回头复习曾经答错的词，慢慢变成长久记忆。",
        "back_to_dictionary": "回到词典",
        "dictionary_title": "词典",
        "dictionary_home_title": "搜索、浏览、整理你的词汇库。",
        "dictionary_home_lede": "知道词汇时可以直接搜索；想多看一些常见词汇时，也可以按分类浏览。",
        "review_queue": "复习清单",
        "missed_ready": "个错题待重新查看",
        "search_example_placeholder": "搜索词汇，例如 analyze",
        "search_button": "搜索",
        "search_tag": "搜索",
        "browse_tag": "浏览",
        "review_tag": "复习",
        "find_specific_word": "找特定词汇",
        "find_specific_word_note": "已经知道要查哪个词汇时，用这个最快。",
        "open_frequency_band": "打开一个词汇分类",
        "open_frequency_band_note": "想按常见程度学词汇时，用这个最方便。",
        "go_to_missed_words": "前往错题清单",
        "go_to_missed_words_note": "想根据自己真正答错的词汇来复习时，就看这里。",
        "choose_band_browse": "选择想看的词汇分类",
        "all_bands": "全部分类",
        "english_only": "只看有英文定义",
        "example_only": "只看有例句",
        "dictionary_search_title": "搜索词汇",
        "dictionary_search_hero": "快速找到你要的词汇。",
        "results": "搜索结果",
        "search_results_count": "“{query}”共有 {count} 条结果",
        "english_label": "英文",
        "chinese_label": "中文",
        "example_label": "例句",
        "no_search_match": "找不到符合这次搜索的词汇。",
        "no_search_match_note": "可以试试更短的关键词、移除一个筛选条件，或改用分类浏览。",
        "frequency_band": "词汇分类",
        "words_in_band": "这一组共有 {count} 个词汇。",
        "apply_filters": "应用筛选",
        "words_label": "词汇",
        "open_word_add_details": "打开这个词汇页补上更完整的内容。",
        "no_words_for_letter": "这个字母下目前没有词汇。",
        "no_words_for_letter_note": "试试其他字母，或移除其中一个筛选条件。",
        "word_status": "状态",
        "correct_label": "答对",
        "wrong_label": "答错",
        "overview_tab": "总览",
        "meaning_tab": "词义",
        "examples_tab": "例句",
        "notes_tab": "笔记",
        "definition_section": "定义",
        "core_meaning": "核心意思",
        "english_definition": "英文定义",
        "chinese_definition": "中文定义",
        "no_english_definition": "尚未加入英文定义。",
        "no_chinese_definition": "尚未加入中文定义。",
        "examples_section": "例句",
        "usage_related": "用法与相关词",
        "example_sentence": "例句",
        "no_example_sentence": "尚未加入例句。",
        "synonyms_label": "同义词",
        "no_synonyms": "尚未加入同义词。",
        "source_section": "来源",
        "workbook_references": "工作表来源",
        "pos_not_provided": "原始资料未提供词性",
        "notes_section": "笔记",
        "memory_hook": "你的记忆提示",
        "no_personal_notes": "目前还没有个人笔记，可以加上一句方便记忆的提示。",
        "edit_section": "编辑",
        "improve_word": "补强这个词汇",
        "improve_word_note": "补上更清楚的定义、例句和干扰选项，能让学习模式更完整。",
        "notes_label": "笔记",
        "wrong_sentence_options": "错误例句选项",
        "save_changes": "保存更改",
        "add_concise_english_definition": "加入简洁的英文定义",
        "add_ipa_placeholder": "加入 IPA，例如 /əˈbɪləti/",
        "one_synonym_per_line": "每行一个同义词",
        "add_natural_sentence": "加入一个自然的例句",
        "one_distractor_per_line": "每行一个错误例句选项",
        "learning_title": "学习",
        "learning_hero_title": "用短时间，稳稳地把词汇学起来。",
        "learning_hero_lede": "每次练习都会从你的《经济学人》词汇库出题。你补得越完整，之后的题目就会越实用、越不重复。",
        "latest_label": "最近",
        "ready_label": "准备好了",
        "most_recent_session": "最近一次练习",
        "start_new_session_note": "开始新的练习",
        "session_goal": "这一轮要做什么",
        "build_consistency": "先把基础答稳",
        "definition_short": "定义",
        "synonym_short": "同义词",
        "sentence_short": "例句",
        "definition_available_note": "一开始会先用定义题练习；之后词汇内容越完整，系统就会慢慢加入同义词和例句题。",
        "start_learning_session": "开始这一轮练习",
        "coverage": "当前内容",
        "learning_bank": "你的词汇库",
        "enriched_label": "已补内容",
        "sentence_ready": "已有例句",
        "how_it_works": "怎么用",
        "what_mode_gives_you": "这个模式会怎么帮助你",
        "study_rounds_note": "每次做短一点，更容易维持节奏，也不会一下子太累。",
        "definition_first": "先从定义开始",
        "definition_first_note": "即使内容还没完全补齐，也能先用意思题建立基础。",
        "review_after_answer": "每答完就复习",
        "review_after_answer_note": "每题之后都能看解释，需要时也能打开完整词汇页。",
        "smarter_over_time": "越用越完整",
        "smarter_over_time_note": "当你加入笔记、同义词和例句后，练习内容会自动变得更丰富。",
        "best_next_step": "下一步建议",
        "enrich_first": "先补几个词汇内容",
        "enrich_first_note": "你现在已经可以开始练习，但如果先补上一些英文定义、同义词和例句，整体效果会更好。",
        "latest_session": "最近一次练习",
        "recent_session_saved": "你最近一次的学习练习已经保存，可以直接再开始一轮。",
        "start_another_session": "再开始一轮",
        "question_counter": "第 {current} 题，共 {total} 题",
        "percent_complete": "已完成 {percent}%",
        "submit_answer": "提交答案",
        "before_answering": "作答前",
        "open_word": "查看词汇页",
        "pronunciation_label": "发音",
        "word_type": "词性",
        "frequency_band_label": "词汇分类",
        "what_stays_hidden": "这一步先不显示",
        "hidden_learning_note": "在你作答前，定义、同义词和例句都会先隐藏，这样更像真正练习。",
        "answered_counter": "已作答 {answered}/{total}",
        "correct_review": "答对",
        "review_label": "复习",
        "your_answer": "你的答案：",
        "correct_answer": "正确答案：",
        "nice_work_note": "做得不错，这个词汇正在往稳定记忆前进。",
        "read_details_note": "先看一下下面的说明，再继续下一题。",
        "see_session_result": "查看本次结果",
        "next_question": "下一题",
        "open_word_page": "打开词汇页",
        "after_answering": "作答后",
        "now_unlocked": "现在可以看到完整内容",
        "now_unlocked_note": "现在可以看完整意思，利用这一步再确认一次，帮助把词汇记住。",
        "correct_wrong": "答对 / 答错",
        "session_complete": "这一轮练习完成了",
        "learning_result_title": "这次你答对了 {score} 题。",
        "learning_result_lede": "这一轮练习已经保存。你可以根据下面结果决定要继续练、先复习，或回去补词汇内容。",
        "accuracy_label": "正确率",
        "session_score": "本次得分",
        "next_focus": "下一步建议：",
        "breakdown": "结果拆解",
        "question_types": "题型分布",
        "question_type_label": "题型",
        "total_label": "总数",
        "level_test_title": "程度检测",
        "find_starting_band": "找出适合你的词汇程度。",
        "test_intro_lede": "这个程度检测会从不同常见程度的词汇中抽出 {count} 道选择题，帮你估算目前的《经济学人》词汇程度。",
        "questions_label": "题目数",
        "definition_based_items": "以定义为主的题目",
        "what_it_measures": "这份检测在看什么",
        "foundation_across_bands": "看看你对不同层次词汇的掌握",
        "frequency_short": "常见度",
        "recognition_short": "识别",
        "placement_short": "定位",
        "test_goal_note": "结果会同时参考你的整体正确率，以及你在较难词汇上的表现。",
        "begin_test": "开始检测",
        "band_coverage": "出题范围",
        "sampled_ranges": "抽样分类",
        "what_this_means": "这代表什么",
        "sampled_from_band": "这一题是从 {band} 这一组词汇抽出的。",
        "goal_label": "目标",
        "test_goal_fast": "选出最合适的定义后继续往下。这份检测设计成快速、直接，而且有一致性。",
        "hidden_test_note": "在你提交答案前，完整定义和词汇细节都不会先显示，这样结果才更准确。",
        "recognized_correctly": "你正确辨认了这个词汇。",
        "revisit_later_note": "这是之后很适合放回学习模式再加强的词汇。",
        "see_test_result": "查看检测结果",
        "result_label": "结果",
        "getting_started": "起步中",
        "test_result_lede": "你在这次程度检测中答对了 {score} 题。根据结果，系统会建议你下一步适合从哪一组词汇开始。",
        "estimated_band_chip": "建议起点：{band}",
        "correct_chip": "答对：{score}",
        "weighted_chip": "加权：{percent}%",
        "test_result_note": "这个结果不只看总分，也会一起参考你在较难词汇上的表现。",
        "what_to_do_next": "接下来可以：",
        "band_breakdown": "各组表现",
        "band_performance": "你在不同词汇分类的表现",
        "band_accuracy_note": "这一组词汇的正确率是 {percent}%。",
        "try_again": "再测一次",
        "go_to_learning": "前往学习",
        "review_queue_title": "错题复习",
        "review_queue_lede": "这里会收集你在检测和练习中答错的词汇，让你之后复习时更有方向，不用乱猜。",
        "total_to_review": "待复习总数",
        "words_in_queue": "个词汇在清单里",
        "open_learning": "前往学习",
        "missed_times": "答错 {count} 次",
        "open_word_add_definition_example": "打开这个词汇页，补上英文定义和例句。",
        "all_clear": "目前清空了",
        "no_missed_words": "目前还没有错题。",
        "review_queue_auto": "做完一次检测或练习后，错题清单就会自动出现在这里。",
        "start_learning": "开始学习",
        "hero_chart_label": "词汇概况",
        "hero_chart_title": "你的 Economist 词汇分布",
        "hero_chart_note": "快速看看当前词汇资料在不同常见程度分类中的分布情况。",
        "hero_chart_total": "总词汇数",
        "hero_chart_bands": "词汇分类",
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
        "zh-Hans": {"definition": "定义", "synonym": "同义词", "sentence": "例句"},
    }
    return labels.get(lang, labels["en"]).get(value, value)


def translate_status(value: str, lang: str = "en") -> str:
    labels = {
        "en": {"new": "new", "learning": "learning", "review": "review", "mastered": "mastered"},
        "zh-Hant": {"new": "新字", "learning": "學習中", "review": "待複習", "mastered": "已熟悉"},
        "zh-Hans": {"new": "新词", "learning": "学习中", "review": "待复习", "mastered": "已熟悉"},
    }
    return labels.get(lang, labels["en"]).get(value, value)


def build_lang_url(request: Request, lang: str) -> str:
    params = list(request.query_params.multi_items())
    filtered = [(key, value) for key, value in params if key != "lang"]
    filtered.append(("lang", lang))
    query = urlencode(filtered)
    return f"{request.url.path}?{query}" if query else request.url.path


def build_home_url(lang: str) -> str:
    return f"/?lang={lang}" if lang != "en" else "/"


def get_profile_name(request: Request) -> str:
    raw = (request.cookies.get("profile_name") or "").strip()
    return raw[:40] if raw else "Lawrence"


def profile_initials(name: str) -> str:
    parts = [part for part in re.split(r"\s+", (name or "").strip()) if part]
    if not parts:
        return "EL"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def get_profile_persona(request: Request) -> str | None:
    raw = (request.cookies.get("profile_persona") or "").strip()
    return raw if raw in SUPPORTED_PERSONAS else None


def persona_message_key(persona: str | None) -> str:
    return {
        "student": "persona_message_student",
        "teacher": "persona_message_teacher",
        "business_professional": "persona_message_business",
        "ai_power_user": "persona_message_ai",
        "lifelong_learner": "persona_message_lifelong",
    }.get(persona or "", "persona_message_lifelong")


def recommendation_note_key(persona: str | None) -> str:
    return {
        "student": "recommend_note_student",
        "teacher": "recommend_note_teacher",
        "business_professional": "recommend_note_business",
        "ai_power_user": "recommend_note_ai",
        "lifelong_learner": "recommend_note_lifelong",
    }.get(persona or "", "recommend_note_lifelong")


def recommendation_cards(persona: str | None) -> list[dict[str, str]]:
    if persona == "student":
        return [
            {"tag_key": "placement", "title_key": "nav_test", "body_key": "card_student_test", "href": "/test", "class_name": "recommend-card-blue"},
            {"tag_key": "practice", "title_key": "learning_session", "body_key": "card_student_learning", "href": "/learning", "class_name": "recommend-card-pink"},
            {"tag_key": "review", "title_key": "nav_dictionary", "body_key": "card_student_dictionary", "href": "/dictionary", "class_name": "recommend-card-sand"},
        ]
    if persona == "teacher":
        return [
            {"tag_key": "review", "title_key": "nav_dictionary", "body_key": "card_teacher_dictionary", "href": "/dictionary", "class_name": "recommend-card-blue"},
            {"tag_key": "review", "title_key": "nav_missed", "body_key": "card_teacher_review", "href": "/review/missed", "class_name": "recommend-card-pink"},
            {"tag_key": "practice", "title_key": "nav_learning", "body_key": "card_teacher_learning", "href": "/learning", "class_name": "recommend-card-sand"},
        ]
    if persona == "business_professional":
        return [
            {"tag_key": "practice", "title_key": "nav_learning", "body_key": "card_business_learning", "href": "/learning", "class_name": "recommend-card-blue"},
            {"tag_key": "review", "title_key": "nav_dictionary", "body_key": "card_business_dictionary", "href": "/dictionary", "class_name": "recommend-card-pink"},
            {"tag_key": "placement", "title_key": "nav_test", "body_key": "card_business_test", "href": "/test", "class_name": "recommend-card-sand"},
        ]
    if persona == "ai_power_user":
        return [
            {"tag_key": "practice", "title_key": "nav_learning", "body_key": "card_ai_learning", "href": "/learning", "class_name": "recommend-card-blue"},
            {"tag_key": "review", "title_key": "nav_dictionary", "body_key": "card_ai_dictionary", "href": "/dictionary", "class_name": "recommend-card-pink"},
            {"tag_key": "placement", "title_key": "nav_test", "body_key": "card_ai_test", "href": "/test", "class_name": "recommend-card-sand"},
        ]
    return [
        {"tag_key": "practice", "title_key": "nav_learning", "body_key": "card_lifelong_learning", "href": "/learning", "class_name": "recommend-card-blue"},
        {"tag_key": "placement", "title_key": "nav_test", "body_key": "card_lifelong_test", "href": "/test", "class_name": "recommend-card-pink"},
        {"tag_key": "review", "title_key": "nav_missed", "body_key": "card_lifelong_review", "href": "/review/missed", "class_name": "recommend-card-sand"},
    ]


def hero_band_identity(range_label: str) -> dict[str, str]:
    identities = {
        "2000~": {"title": "基石", "subtitle": "The Foundation"},
        "500~1999": {"title": "深度洞察", "subtitle": "Insight"},
        "200~499": {"title": "精準修辭", "subtitle": "Precision"},
        "100~199": {"title": "智識擴張", "subtitle": "Intellectual"},
        "50~99": {"title": "菁英語庫", "subtitle": "The Elite Lexicon"},
    }
    return identities.get(range_label, {"title": range_label, "subtitle": ""})


def render(request: Request, template_name: str, **context) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    context.update(
        {
            "lang": lang,
            "profile_name": get_profile_name(request),
            "profile_initials": profile_initials(get_profile_name(request)),
            "profile_persona": get_profile_persona(request),
            "t": lambda key, **kwargs: translate(lang, key, **kwargs),
            "lang_url": lambda target_lang: build_lang_url(request, target_lang),
            "qtype_label": lambda value: translate_question_type(value, lang),
            "status_label": lambda value: translate_status(value, lang),
            "zh_text": lambda text: localize_chinese_text(text, lang),
            "zh_list": lambda items: localize_chinese_list(items, lang),
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
        "zh-Hans": ["进阶", "中高阶", "中阶", "初中阶", "基础建立中"],
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
            return "先從 50~99 這組詞彙開始，再優先替你最常答錯的詞彙補上筆記與例句。"
        if percent >= 0.7:
            return f"你目前可以穩定從 {estimated_band_label} 附近開始。接下來可以到詞典看更高一級的詞彙分類，並補強不熟的詞彙。"
        return f"接下來幾次學習，先集中在 {estimated_band_label} 和再低一級的詞彙分類，直到答案更自然為止。"
    if lang == "zh-Hans":
        if not estimated_band_label:
            return "先从 50~99 这一组词汇开始，再优先替你最常答错的词汇补上笔记与例句。"
        if percent >= 0.7:
            return f"你目前可以稳定从 {estimated_band_label} 附近开始。接下来可以到词典看更高一级的词汇分类，并补强不熟的词汇。"
        return f"接下来几次学习，先集中在 {estimated_band_label} 和再低一级的词汇分类，直到答案更自然为止。"
    if not estimated_band_label:
        return "Start with the 50~99 band, then add notes and examples to words you miss most often."
    if percent >= 0.7:
        return f"You can comfortably work around {estimated_band_label}. Move into the next harder band in Dictionary and enrich unfamiliar words."
    return f"Focus your next learning sessions around {estimated_band_label} and the band just below it until the answers feel automatic."


def learning_recommendation(correct: int, total: int, enriched_words: int, lang: str = "en") -> str:
    if lang == "zh-Hant":
        if total == 0:
            return "先替幾個詞彙補充更多內容，學習模式之後才能出更豐富的題目。"
        percent = correct / total
        if percent >= 0.8 and enriched_words > 0:
            return "節奏不錯。可以繼續學，或開始加入更高一級的詞彙分類與更多例句題。"
        if enriched_words == 0:
            return "定義題已經有幫助，但如果再補上同義詞和例句，下一輪學習會更完整。"
        return "先回頭看錯題、補清楚筆記，再持續在詞典裡增加更完整的詞彙內容。"
    if lang == "zh-Hans":
        if total == 0:
            return "先替几个词汇补充更多内容，学习模式之后才能出更丰富的题目。"
        percent = correct / total
        if percent >= 0.8 and enriched_words > 0:
            return "节奏不错。可以继续学，或开始加入更高一级的词汇分类与更多例句题。"
        if enriched_words == 0:
            return "定义题已经有帮助，但如果再补上同义词和例句，下一轮学习会更完整。"
        return "先回头看错题、补清楚笔记，再持续在词典里增加更完整的词汇内容。"
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


def parse_meaning_lines(value: str) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in str(value).replace(" | ", "\n").splitlines() if item and item.strip()]
    return items or ([str(value).strip()] if str(value).strip() else [])


def preferred_source_meanings(meanings_json: str, extra_json: str, lang: str) -> list[str]:
    if lang == "zh-Hans" and extra_json:
        try:
            extra = json.loads(extra_json)
        except json.JSONDecodeError:
            extra = {}
        if isinstance(extra, dict):
            simplified = parse_meaning_lines(extra.get("simplified_chinese_definition", ""))
            if simplified:
                return simplified
    return json_loads(meanings_json)


def definitions_map_for_words(conn: sqlite3.Connection, word_ids: list[int], lang: str = "en") -> dict[int, list[str]]:
    if not word_ids:
        return {}
    placeholders = ",".join("?" for _ in word_ids)
    rows = conn.execute(
        f"""
        SELECT word_id, meanings_json, extra_json
        FROM source_entries
        WHERE word_id IN ({placeholders})
        ORDER BY band_rank, workbook_name, row_number
        """,
        word_ids,
    ).fetchall()
    result = {word_id: [] for word_id in word_ids}
    for row in rows:
        seen = result[row["word_id"]]
        for meaning in preferred_source_meanings(row["meanings_json"], row["extra_json"], lang):
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


def word_payload(conn: sqlite3.Connection, word_id: int, lang: str = "en") -> dict:
    row = word_row(conn, word_id)
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
    definitions: list[str] = []
    for source_row in source_rows:
        for meaning in preferred_source_meanings(source_row["meanings_json"], source_row["extra_json"], lang):
            if meaning not in definitions:
                definitions.append(meaning)
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


def dashboard_spotlight_words(conn: sqlite3.Connection, limit: int = 4, lang: str = "en") -> list[dict]:
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
    definitions_map = definitions_map_for_words(conn, word_ids, lang)
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
    lang: str = "en",
) -> list[dict]:
    rows = search_words(
        conn,
        query,
        band_rank=band_rank,
        require_english=require_english,
        require_example=require_example,
    )
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids, lang)
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


def missed_words(conn: sqlite3.Connection, limit: int = 100, lang: str = "en") -> list[sqlite3.Row]:
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
    definitions_map = definitions_map_for_words(conn, word_ids, lang)
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
def landing_page(request: Request) -> HTMLResponse:
    return render(request, "landing.html")


@app.get("/dashboard", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    profile_name = get_profile_name(request)
    profile_persona = get_profile_persona(request)
    if profile_persona is None:
        return RedirectResponse(url=build_home_url(lang), status_code=303)
    stats = fetch_stats(conn)
    latest_test = latest_test_result(conn)
    latest_learning = latest_learning_result(conn)
    recommended_band = latest_test["estimated_band_label"] if latest_test else "50~99 (3924)"
    bands = decorate_band_rows(band_summary(conn))
    max_band_total = max((band["workbook_total"] for band in bands), default=1)
    hero_band_chart = [
        {
            "label": band["range_label"],
            "title": hero_band_identity(band["range_label"])["title"],
            "subtitle": hero_band_identity(band["range_label"])["subtitle"],
            "count": band["workbook_total"],
            "percent": max(18, round((band["workbook_total"] / max_band_total) * 100)),
        }
        for band in bands[:5]
    ]
    return render(
        request,
        "home.html",
        personalized_name=profile_name,
        persona_message=translate(lang, persona_message_key(profile_persona)),
        recommendation_note=translate(lang, recommendation_note_key(profile_persona)),
        recommendation_cards=recommendation_cards(profile_persona),
        stats=stats,
        bands=bands,
        latest_test=latest_test,
        latest_learning=latest_learning,
        recommended_band=recommended_band,
        missed_words_count=len(missed_words(conn, limit=10)),
        spotlight_words=dashboard_spotlight_words(conn),
        hero_band_chart=hero_band_chart,
    )


@app.post("/onboarding")
def onboarding_submit(
    request: Request,
    first_name: str = Form(""),
    persona: str = Form("lifelong_learner"),
) -> RedirectResponse:
    safe_persona = persona if persona in SUPPORTED_PERSONAS else "lifelong_learner"
    safe_name = (first_name or "").strip()[:40]
    lang = getattr(request.state, "lang", get_lang(request))
    response = RedirectResponse(url=(f"/dashboard?lang={lang}" if lang != "en" else "/dashboard"), status_code=303)
    response.set_cookie("profile_persona", safe_persona, max_age=60 * 60 * 24 * 365)
    if safe_name:
        response.set_cookie("profile_name", safe_name, max_age=60 * 60 * 24 * 365)
    else:
        response.delete_cookie("profile_name")
    return response


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
    payload = word_payload(conn, question["word_id"], getattr(request.state, "lang", get_lang(request)))
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
    payload = word_payload(conn, question["word_id"], getattr(request.state, "lang", get_lang(request)))
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
    payload = word_payload(conn, question["word_id"], getattr(request.state, "lang", get_lang(request)))
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
    return render(
        request,
        "dictionary_home.html",
        bands=bands,
        missed_count=len(missed_words(conn, limit=10, lang=getattr(request.state, "lang", get_lang(request)))),
    )


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
    definitions_map = definitions_map_for_words(conn, word_ids, getattr(request.state, "lang", get_lang(request)))
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
        lang=getattr(request.state, "lang", get_lang(request)),
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
    rows = missed_words(conn, lang=getattr(request.state, "lang", get_lang(request)))
    return render(request, "missed_words.html", rows=rows)


@app.get("/word/{word_id}", response_class=HTMLResponse)
def word_detail(request: Request, word_id: int) -> HTMLResponse:
    conn = db_conn()
    payload = word_payload(conn, word_id, getattr(request.state, "lang", get_lang(request)))
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
