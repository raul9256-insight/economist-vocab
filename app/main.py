from __future__ import annotations

import csv
import io
import json
import hashlib
import hmac
import logging
import os
import random
import re
import secrets
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    band_summary,
    definitions_for_word,
    fetch_stats,
    get_connection,
    letters_for_band,
    parts_of_speech_for_word,
    progression_profile_for_word,
)
from app.enrichment_io import (
    export_ai_power_template,
    export_taxonomy_template,
    export_template,
    import_ai_power_rows,
    import_enrichment_rows,
    import_taxonomy_rows,
    iter_enrichment_import_rows,
    iter_import_rows,
)
from app.openai_enrichment import evaluate_sentence_usage, generate_ai_insight_for_word, generate_enrichment_batch, load_env_file, sentence_ai_ready
from app.openai_speech import speech_api_ready, synthesize_pronunciation_audio, transcribe_pronunciation_audio, transcription_api_ready
from economist_vocab import DEFAULT_DB_PATH


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR.parent / "exports"
DATA_DIR = BASE_DIR.parent / "data"
AI_POWER_DATA_PATH = DATA_DIR / "ai_power_vocab.json"
STATIC_ASSET_VERSION = "20260505c"
app = FastAPI(title="VocabLab AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "https://economist-vocab.onrender.com",
        "https://vocablab-ai-mobile.onrender.com",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

USER_ID = 1
TEST_VOCAB_COUNT = 20
TEST_WORDS_PER_BAND = 4
TEST_LAYERS_PER_WORD = 5
TEST_QUESTION_COUNT = TEST_VOCAB_COUNT * TEST_LAYERS_PER_WORD
LEARNING_WORD_COUNT = 10
LEARNING_LAYERS_PER_WORD = 5
LEARNING_QUESTION_COUNT = LEARNING_WORD_COUNT * LEARNING_LAYERS_PER_WORD
SUPPORTED_LANGS = {"en", "zh-Hant", "zh-Hans"}
SUPPORTED_PERSONAS = {
    "student",
    "teacher",
    "business_professional",
    "ai_power_user",
    "lifelong_learner",
}

HOME_QUOTES = [
    {
        "text": "Without grammar very little can be conveyed, without vocabulary nothing can be conveyed.",
        "author": "Wilkins",
        "cite": "1972, p. 111",
    },
    {
        "text": "The most powerful programming language of the future isn’t C++ or Python. It’s English.",
        "author": "Jensen Huang",
        "cite": "",
    },
]

LEVEL_TEST_SYNONYMS = {
    "abandon": "leave",
    "abhor": "hate",
    "abide": "tolerate",
    "abnormal": "unusual",
    "abound": "flourish",
    "abrupt": "sudden",
    "absolute": "complete",
    "absolve": "exonerate",
    "absurd": "ridiculous",
    "abundant": "plentiful",
    "abysmal": "terrible",
    "accede": "agree",
    "acceptable": "satisfactory",
    "accessible": "reachable",
    "acclaim": "praise",
    "accomplish": "achieve",
    "accurate": "precise",
    "acquiesce": "comply",
    "active": "energetic",
    "acute": "severe",
    "adamant": "firm",
    "adapt": "adjust",
    "adept": "skilled",
    "admire": "respect",
    "admit": "confess",
    "advantage": "benefit",
    "advantageous": "beneficial",
    "adverse": "unfavorable",
    "affable": "friendly",
    "affluent": "wealthy",
    "aggravate": "worsen",
    "agile": "nimble",
    "agree": "consent",
    "alert": "watchful",
    "alienate": "estrange",
    "allay": "soothe",
    "alleviate": "ease",
    "allow": "permit",
    "aloof": "distant",
    "alter": "change",
    "altruism": "selflessness",
    "always": "forever",
    "ambiguous": "unclear",
    "ameliorate": "improve",
    "amicable": "friendly",
    "amplify": "enlarge",
    "ancient": "old",
    "anxious": "worried",
    "appear": "emerge",
    "appreciate": "value",
    "arbitrary": "random",
}

LEVEL_TEST_ANTONYMS = {
    "abandon": "keep",
    "abhor": "admire",
    "abide": "reject",
    "abnormal": "typical",
    "abound": "lack",
    "abrupt": "gradual",
    "absolute": "limited",
    "absolve": "condemn",
    "absurd": "reasonable",
    "abundant": "scarce",
    "abysmal": "excellent",
    "accede": "refuse",
    "acceptable": "flawed",
    "accessible": "remote",
    "acclaim": "criticize",
    "accomplish": "fail",
    "accurate": "imprecise",
    "acquiesce": "resist",
    "active": "idle",
    "acute": "mild",
    "adamant": "flexible",
    "adapt": "resist",
    "adept": "inept",
    "admire": "despise",
    "admit": "deny",
    "advantage": "drawback",
    "advantageous": "harmful",
    "adverse": "favorable",
    "affable": "brusque",
    "affluent": "poor",
    "aggravate": "alleviate",
    "agile": "awkward",
    "agree": "oppose",
    "alert": "inattentive",
    "alienate": "unite",
    "allay": "aggravate",
    "alleviate": "worsen",
    "allow": "block",
    "aloof": "friendly",
    "alter": "preserve",
    "altruism": "selfishness",
    "always": "rarely",
    "ambiguous": "clear",
    "ameliorate": "worsen",
    "amicable": "hostile",
    "amplify": "reduce",
    "ancient": "modern",
    "anxious": "calm",
    "appear": "vanish",
    "appreciate": "depreciate",
    "arbitrary": "systematic",
}

LEVEL_TEST_SYNONYMS.update(
    {
        "abdicate": "relinquish",
        "abduction": "kidnapping",
        "abhorrent": "detestable",
        "ablaze": "burning",
        "abreast": "informed",
        "abscond": "flee",
        "abstraction": "concept",
        "acidic": "sour",
        "acquire": "obtain",
        "acquisitive": "greedy",
        "adaptable": "flexible",
        "adhesive": "sticky",
        "admonish": "scold",
        "adolescence": "youth",
        "affectionate": "loving",
        "aficionado": "enthusiast",
        "agnostic": "skeptic",
        "alacrity": "eagerness",
        "alias": "pseudonym",
        "alibi": "excuse",
        "allotment": "allocation",
        "amalgam": "mixture",
        "amenity": "convenience",
        "amicably": "cordially",
        "amiss": "wrong",
        "amorphous": "shapeless",
        "analogous": "comparable",
        "ancillary": "auxiliary",
        "abject": "miserable",
        "abrasive": "harsh",
        "absurdity": "nonsense",
        "abusive": "cruel",
        "accentuate": "emphasize",
        "accessory": "add-on",
        "accomplice": "partner",
        "acumen": "insight",
        "adage": "proverb",
        "addictive": "habit-forming",
        "adherence": "loyalty",
        "adrift": "wandering",
        "adventurous": "daring",
        "adversity": "hardship",
        "affinity": "rapport",
        "affront": "insult",
        "aghast": "horrified",
        "agrarian": "rural",
        "alarmist": "scaremonger",
        "alienation": "estrangement",
        "allude": "imply",
        "alluring": "attractive",
        "amenable": "cooperative",
        "amiable": "pleasant",
        "abate": "subside",
        "abduct": "kidnap",
        "abstain": "refrain",
        "abstract": "theoretical",
        "accrue": "accumulate",
        "accuracy": "precision",
        "acquit": "clear",
        "adhere": "stick",
        "adjacent": "nearby",
        "admirable": "commendable",
        "adore": "cherish",
        "adversary": "opponent",
        "affirm": "assert",
        "agitate": "disturb",
        "agony": "anguish",
        "allegiance": "loyalty",
        "allure": "entice",
        "altitude": "elevation",
        "amass": "accumulate",
        "ambivalence": "uncertainty",
        "amuse": "entertain",
        "anarchy": "chaos",
        "anecdotal": "informal",
        "angst": "anxiety",
        "abolish": "eliminate",
        "absorb": "soak",
        "accelerate": "hasten",
        "accommodate": "house",
        "accompany": "escort",
        "accumulate": "collect",
        "accusation": "allegation",
        "aggregate": "total",
        "aggression": "hostility",
        "align": "arrange",
        "allocate": "assign",
        "amateur": "novice",
        "amend": "revise",
        "amnesty": "pardon",
        "ancestor": "forebear",
        "anchor": "secure",
        "annoy": "irritate",
        "anonymous": "unnamed",
        "anticipate": "expect",
        "appropriate": "suitable",
        "ability": "capacity",
        "abuse": "mistreatment",
        "academic": "scholarly",
        "accept": "receive",
        "access": "entry",
        "accident": "mishap",
        "achieve": "attain",
        "acknowledge": "recognize",
        "add": "include",
        "adjust": "modify",
        "adopt": "embrace",
        "advance": "progress",
        "advertise": "promote",
        "advice": "guidance",
        "advocate": "support",
        "affect": "influence",
        "afford": "manage",
        "agency": "organization",
        "agenda": "schedule",
        "agricultural": "farming",
        "aid": "help",
        "aim": "goal",
        "alarm": "warning",
        "alliance": "partnership",
        "alternative": "option",
        "ambition": "aspiration",
        "anger": "rage",
        "annual": "yearly",
        "answer": "reply",
        "apparent": "obvious",
        "appoint": "assign",
        "approve": "endorse",
        "argue": "contend",
    }
)

LEVEL_TEST_ANTONYMS.update(
    {
        "abdicate": "retain",
        "abduction": "release",
        "abhorrent": "admirable",
        "ablaze": "extinguished",
        "abreast": "unaware",
        "abscond": "remain",
        "abstraction": "reality",
        "acidic": "alkaline",
        "acquire": "lose",
        "acquisitive": "generous",
        "adaptable": "rigid",
        "adhesive": "slippery",
        "admonish": "praise",
        "adolescence": "adulthood",
        "affectionate": "cold",
        "aficionado": "novice",
        "agnostic": "believer",
        "alacrity": "reluctance",
        "alias": "realname",
        "alibi": "culpability",
        "allotment": "whole",
        "amalgam": "purity",
        "amenity": "nuisance",
        "amicably": "hostilely",
        "amiss": "correct",
        "amorphous": "defined",
        "analogous": "different",
        "ancillary": "primary",
        "abject": "proud",
        "abrasive": "gentle",
        "absurdity": "logic",
        "abusive": "kind",
        "accentuate": "minimize",
        "accessory": "essential",
        "accomplice": "opponent",
        "acumen": "stupidity",
        "adage": "novelty",
        "addictive": "repellent",
        "adherence": "defiance",
        "adrift": "anchored",
        "adventurous": "cautious",
        "adversity": "prosperity",
        "affinity": "aversion",
        "affront": "compliment",
        "aghast": "calm",
        "agrarian": "urban",
        "alarmist": "reassurer",
        "alienation": "belonging",
        "allude": "state",
        "alluring": "repellent",
        "amenable": "resistant",
        "amiable": "hostile",
        "abate": "intensify",
        "abduct": "release",
        "abstain": "indulge",
        "abstract": "concrete",
        "accrue": "dwindle",
        "accuracy": "error",
        "acquit": "convict",
        "adhere": "detach",
        "adjacent": "distant",
        "admirable": "shameful",
        "adore": "detest",
        "adversary": "ally",
        "affirm": "deny",
        "agitate": "calm",
        "agony": "comfort",
        "allegiance": "disloyalty",
        "allure": "repel",
        "altitude": "depth",
        "amass": "disperse",
        "ambivalence": "certainty",
        "amuse": "bore",
        "anarchy": "order",
        "anecdotal": "systematic",
        "angst": "calm",
        "abolish": "establish",
        "absorb": "emit",
        "accelerate": "slow",
        "accommodate": "evict",
        "accompany": "leave",
        "accumulate": "disperse",
        "accusation": "exoneration",
        "aggregate": "individual",
        "aggression": "peacefulness",
        "align": "disorganize",
        "allocate": "withhold",
        "amateur": "professional",
        "amend": "damage",
        "amnesty": "punishment",
        "ancestor": "descendant",
        "anchor": "release",
        "annoy": "please",
        "anonymous": "identified",
        "anticipate": "doubt",
        "appropriate": "unsuitable",
        "ability": "incapacity",
        "abuse": "care",
        "academic": "practical",
        "accept": "reject",
        "access": "barrier",
        "accident": "plan",
        "achieve": "fail",
        "acknowledge": "deny",
        "add": "remove",
        "adjust": "fix",
        "adopt": "reject",
        "advance": "retreat",
        "advertise": "conceal",
        "advice": "misinformation",
        "advocate": "oppose",
        "affect": "ignore",
        "afford": "lack",
        "agency": "inaction",
        "agenda": "chaos",
        "agricultural": "industrial",
        "aid": "hinder",
        "aim": "wander",
        "alarm": "reassurance",
        "alliance": "rivalry",
        "alternative": "necessity",
        "ambition": "apathy",
        "anger": "calm",
        "annual": "rare",
        "answer": "question",
        "apparent": "hidden",
        "appoint": "dismiss",
        "approve": "reject",
        "argue": "agree",
    }
)

DSE_LEVEL_TEST_SYNONYMS = {
    "interest": "concern",
    "domestic": "internal",
    "useful": "helpful",
    "terrorism": "extremism",
    "trial": "hearing",
    "rain": "rainfall",
    "conference": "meeting",
    "adjust": "modify",
    "document": "record",
    "province": "region",
    "increase": "rise",
    "protect": "shield",
    "complex": "complicated",
    "likely": "probable",
    "major": "significant",
    "foreign": "overseas",
    "success": "achievement",
    "failure": "defeat",
    "sustainable": "lasting",
    "quietly": "silently",
    "cynical": "distrustful",
    "doubt": "uncertainty",
    "invasion": "incursion",
    "overhaul": "reform",
    "genocide": "extermination",
    "clearing": "glade",
    "fragile": "delicate",
    "accurate": "precise",
    "reliable": "dependable",
    "visible": "apparent",
    "temporary": "short-lived",
    "ordinary": "typical",
    "empirical": "observed",
    "adjacent": "nearby",
    "anecdote": "story",
    "privilege": "advantage",
    "virtual": "digital",
    "foreseeable": "predictable",
    "radicalism": "extremism",
    "talent": "aptitude",
    "undocumented": "unrecorded",
    "spotlight": "attention",
    "abstract": "conceptual",
    "retain": "keep",
    "eliminate": "remove",
    "emerge": "appear",
    "impose": "enforce",
    "propagate": "spread",
    "outlier": "anomaly",
    "clandestine": "covert",
    "impenetrable": "dense",
    "watershed": "turning-point",
    "gargantuan": "enormous",
    "downturn": "slump",
    "principled": "ethical",
    "scrutiny": "inspection",
    "coherent": "logical",
    "acidic": "sour",
    "apathetic": "indifferent",
    "ascetic": "austere",
    "assiduous": "diligent",
    "atrophy": "decay",
    "attentive": "alert",
    "audible": "clear",
    "auspicious": "favorable",
    "autonomous": "independent",
    "moulder": "decay",
    "adaptable": "flexible",
    "obstreperous": "unruly",
    "banal": "ordinary",
    "barbaric": "savage",
    "bearable": "tolerable",
    "benevolence": "kindness",
    "toxicity": "poison",
    "definite": "certain",
    "amnesia": "forgetfulness",
    "precarious": "unstable",
}

DSE_LEVEL_TEST_ANTONYMS = {
    "interest": "indifference",
    "domestic": "foreign",
    "useful": "impractical",
    "terrorism": "peace",
    "trial": "settlement",
    "rain": "drought",
    "conference": "silence",
    "adjust": "preserve",
    "document": "erase",
    "province": "capital",
    "increase": "decline",
    "protect": "endanger",
    "complex": "simple",
    "likely": "improbable",
    "major": "minor",
    "foreign": "domestic",
    "success": "failure",
    "failure": "success",
    "sustainable": "wasteful",
    "quietly": "noisily",
    "cynical": "trusting",
    "doubt": "confidence",
    "invasion": "retreat",
    "overhaul": "neglect",
    "genocide": "protection",
    "clearing": "forest",
    "fragile": "sturdy",
    "accurate": "faulty",
    "reliable": "erratic",
    "visible": "hidden",
    "temporary": "permanent",
    "ordinary": "exceptional",
    "empirical": "theoretical",
    "adjacent": "distant",
    "anecdote": "analysis",
    "privilege": "burden",
    "virtual": "physical",
    "foreseeable": "unexpected",
    "radicalism": "moderation",
    "talent": "incompetence",
    "undocumented": "verified",
    "spotlight": "obscurity",
    "abstract": "concrete",
    "retain": "release",
    "eliminate": "preserve",
    "emerge": "vanish",
    "impose": "withdraw",
    "propagate": "suppress",
    "outlier": "norm",
    "clandestine": "open",
    "impenetrable": "accessible",
    "watershed": "stagnation",
    "gargantuan": "tiny",
    "downturn": "recovery",
    "principled": "corrupt",
    "scrutiny": "neglect",
    "coherent": "confused",
    "acidic": "alkaline",
    "apathetic": "enthusiastic",
    "ascetic": "indulgent",
    "assiduous": "lazy",
    "atrophy": "growth",
    "attentive": "negligent",
    "audible": "silent",
    "auspicious": "ominous",
    "autonomous": "dependent",
    "moulder": "flourish",
    "adaptable": "rigid",
    "obstreperous": "compliant",
    "banal": "original",
    "barbaric": "civilized",
    "bearable": "intolerable",
    "benevolence": "cruelty",
    "toxicity": "safety",
    "definite": "vague",
    "amnesia": "memory",
    "precarious": "secure",
}

LEVEL_TEST_SYNONYMS.update(DSE_LEVEL_TEST_SYNONYMS)
LEVEL_TEST_ANTONYMS.update(DSE_LEVEL_TEST_ANTONYMS)

LEVEL_TEST_EXAMPLE_SENTENCES = {
    "abhor": "Many voters abhor corruption in public office.",
    "abscond": "The treasurer tried to abscond with the charity funds.",
    "absurd": "The committee rejected the absurd proposal immediately.",
    "acceptable": "The revised contract was acceptable to both sides.",
    "accept": "The board decided to accept the proposal after a long debate.",
    "accede": "The minister refused to accede to the protesters' demands.",
    "accentuate": "The lighting can accentuate the museum's dramatic architecture.",
    "accessory": "The phone case is a useful accessory for frequent travellers.",
    "accompany": "A short note should accompany the financial report.",
    "accomplish": "The team hopes to accomplish the merger by June.",
    "accumulate": "Small errors can accumulate into a serious accounting problem.",
    "accurate": "The analyst needs accurate data before making a forecast.",
    "accusation": "The company denied the accusation of price-fixing.",
    "acknowledge": "The chief executive should acknowledge the mistake publicly.",
    "acquiesce": "The board may acquiesce if investors keep applying pressure.",
    "acquire": "The group plans to acquire a smaller rival next year.",
    "admirable": "Her patience during the negotiations was admirable.",
    "admire": "Many analysts admire the founder's discipline.",
    "admit": "The minister refused to admit that the policy had failed.",
    "admonish": "The judge had to admonish the witness for interrupting.",
    "adopt": "Several banks will adopt the new security standard.",
    "affirm": "The court will affirm the earlier ruling.",
    "aggression": "The treaty was designed to deter aggression.",
    "agitate": "The speech may agitate an already nervous market.",
    "aim": "The reformers aim to simplify the tax code.",
    "align": "Managers must align incentives with long-term goals.",
    "allocate": "The agency will allocate more funds to rural schools.",
    "allow": "The new rules allow firms to raise capital faster.",
    "allude": "The article seemed to allude to a pending investigation.",
    "amass": "The startup hopes to amass enough data to train its model.",
    "ambiguous": "The contract used ambiguous language about liability.",
    "amenity": "Fast internet has become an essential amenity for tenants.",
    "amuse": "The joke failed to amuse the audience.",
    "ancestor": "The steam engine was an ancestor of modern machinery.",
    "angst": "The election result added to investors' angst.",
    "anticipate": "Economists anticipate slower growth next quarter.",
    "appear": "New risks may appear as interest rates rise.",
    "appoint": "The board will appoint a new chair next month.",
    "appreciate": "Investors may appreciate the currency after reforms.",
    "approve": "Regulators are expected to approve the deal.",
    "arbitrary": "The court criticised the arbitrary use of power.",
    "argue": "Critics argue that the plan is too expensive.",
}

AI_POWER_TRACK = [
    {
        "slug": "core-instruction",
        "title": "Core Instruction Verbs",
        "title_zh_hant": "核心指令動詞",
        "title_zh_hans": "核心指令动词",
        "target_count": 80,
        "description": "High-utility verbs for prompting, briefing, revising, and directing AI output clearly.",
        "description_zh_hant": "最適合用在提示詞、任務說明、修改與指揮 AI 產出的高頻指令動詞。",
        "description_zh_hans": "最适合用在提示词、任务说明、修改与指挥 AI 产出的高频指令动词。",
        "normal_example": "Please clarify the main argument before you send the memo.",
        "prompt_example": "Analyze this meeting transcript, summarize the key risks, and rewrite the action items in a professional tone.",
        "terms": [
            "analyze", "summarize", "explain", "elaborate", "clarify", "outline", "brainstorm", "generate",
            "create", "rewrite", "refine", "optimize", "improve", "simplify", "expand", "prioritize",
            "evaluate", "assess", "compare", "contrast", "recommend", "suggest", "demonstrate", "illustrate",
            "visualize", "simulate", "role-play", "act as", "structure", "format", "organize", "categorize",
            "synthesize", "critique", "review", "proofread", "edit", "translate", "rephrase", "iterate",
            "debug", "troubleshoot", "ideate", "strategize", "conceptualize", "delegate", "negotiate",
            "facilitate", "moderate", "articulate", "quantify", "qualify", "validate", "verify", "justify",
            "substantiate", "extrapolate", "interpolate",
        ],
    },
    {
        "slug": "output-structure",
        "title": "Output Format & Structure",
        "title_zh_hant": "輸出格式與結構",
        "title_zh_hans": "输出格式与结构",
        "target_count": 70,
        "description": "Words and phrases that control shape, sequence, readability, and delivery format.",
        "description_zh_hant": "用來控制輸出形狀、順序、可讀性與交付格式的關鍵詞組。",
        "description_zh_hans": "用来控制输出形状、顺序、可读性与交付格式的关键词组。",
        "normal_example": "Use a checklist and a short executive summary in the final report.",
        "prompt_example": "Return the answer as a numbered list, then add a table with key takeaways and action items.",
        "terms": [
            "step-by-step", "bullet points", "numbered list", "table", "markdown", "JSON", "pros and cons",
            "advantages vs disadvantages", "summary first", "detailed version", "beginner-friendly",
            "advanced level", "example", "template", "framework", "checklist", "timeline", "flowchart",
            "comparison table", "key takeaways", "action items", "executive summary", "one-pager",
            "SWOT analysis", "mind map", "before and after",
        ],
    },
    {
        "slug": "quality-style",
        "title": "Quality & Style",
        "title_zh_hant": "品質與風格",
        "title_zh_hans": "品质与风格",
        "target_count": 90,
        "description": "Descriptors that tune tone, clarity, persuasion, and the professional quality of responses.",
        "description_zh_hant": "用來調整語氣、清晰度、說服力與整體專業質感的描述詞。",
        "description_zh_hans": "用来调整语气、清晰度、说服力与整体专业质感的描述词。",
        "normal_example": "Her presentation was concise, persuasive, and highly professional.",
        "prompt_example": "Rewrite this email in a concise, balanced, and data-driven style for senior stakeholders.",
        "terms": [
            "concise", "detailed", "professional", "formal", "casual", "engaging", "persuasive", "objective",
            "balanced", "insightful", "nuanced", "rigorous", "logical", "coherent", "elegant", "sophisticated",
            "clear", "precise", "natural", "fluent", "compelling", "authoritative", "empathetic",
            "motivational", "creative", "innovative", "strategic", "tactical", "data-driven", "evidence-based",
            "user-friendly", "high-quality", "premium", "robust", "sustainable", "ethical", "cutting-edge",
        ],
    },
    {
        "slug": "reasoning-thinking",
        "title": "Reasoning & Thinking",
        "title_zh_hant": "推理與思考",
        "title_zh_hans": "推理与思考",
        "target_count": 60,
        "description": "Mental-model vocabulary for decision-making, analysis, and deeper prompt reasoning.",
        "description_zh_hant": "適合決策、分析與更深層提示推理的思考模型詞彙。",
        "description_zh_hans": "适合决策、分析与更深层提示推理的思考模型词汇。",
        "normal_example": "We need a more systematic approach before making a final decision.",
        "prompt_example": "Think step by step, identify the root cause, weigh the alternatives, and recommend the strongest option.",
        "terms": [
            "think step by step", "chain of thought", "first principles", "break down", "analyze deeply",
            "evaluate options", "weigh pros and cons", "consider alternatives", "critical thinking",
            "systematic", "methodical", "logical reasoning", "root cause", "counterfactual", "assumption",
            "hypothesis", "inference", "deduction", "induction", "analogy", "mental model",
            "decision framework", "risk assessment", "scenario planning",
        ],
    },
    {
        "slug": "ai-tech",
        "title": "AI & Tech Terms",
        "title_zh_hant": "AI 與科技詞彙",
        "title_zh_hans": "AI 与科技词汇",
        "target_count": 80,
        "description": "Essential vocabulary for understanding modern AI systems, prompting, workflows, and tooling.",
        "description_zh_hant": "理解現代 AI 系統、提示工程、工作流程與工具時最常用的核心詞彙。",
        "description_zh_hans": "理解现代 AI 系统、提示工程、工作流程与工具时最常用的核心词汇。",
        "normal_example": "The product team is testing a new chatbot API with a larger context window.",
        "prompt_example": "Use the system prompt to define the role, then produce a retrieval-augmented answer with cited sources.",
        "terms": [
            "prompt", "prompting", "prompt engineering", "LLM", "large language model", "generative AI",
            "hallucination", "fine-tune", "context window", "token", "embedding", "few-shot", "zero-shot",
            "temperature", "top-p", "system prompt", "user prompt", "assistant response", "RAG",
            "retrieval augmented generation", "agent", "chain", "iteration", "output", "input",
            "training data", "inference", "parameters", "API", "integration", "workflow", "automation",
            "chatbot", "virtual assistant",
        ],
    },
    {
        "slug": "business-professional",
        "title": "Business & Professional Vocabulary",
        "title_zh_hant": "商務與專業詞彙",
        "title_zh_hans": "商务与专业词汇",
        "target_count": 120,
        "description": "Professional language for meetings, strategy, operations, positioning, and executive communication.",
        "description_zh_hant": "適合會議、策略、營運、定位與高階溝通場景的專業英語。",
        "description_zh_hans": "适合会议、策略、营运、定位与高阶沟通场景的专业英语。",
        "normal_example": "Stakeholder alignment is essential before we launch the strategic initiative.",
        "prompt_example": "Draft a quarterly review with KPI trends, ROI discussion, risk mitigation, and executive action items.",
        "terms": [
            "stakeholder", "KPI", "ROI", "synergy", "leverage", "optimize", "streamline", "scalability",
            "disrupt", "innovation", "agile", "ecosystem", "benchmark", "deliverables", "milestone",
            "pipeline", "revenue stream", "cost-benefit", "value proposition", "branding", "positioning",
            "negotiation", "consensus", "alignment", "accountability", "transparency", "governance",
            "compliance", "risk mitigation", "due diligence", "strategic initiative", "quarterly review",
            "performance metric",
        ],
    },
]

TRANSLATIONS = {
    "en": {
        "brand_title": "VocabLab AI",
        "brand_subtitle": "Personal vocabulary system",
        "nav_dashboard": "Dashboard",
        "nav_test": "Level Test",
        "nav_learning": "Learning",
        "nav_learning_sidebar": "Learning",
        "nav_dictionary": "Dictionary",
        "nav_business_vocab": "Business Vocab",
        "nav_missed": "Missed Words",
        "nav_bulk": "Bulk Import",
        "nav_statistics": "Statistics",
        "nav_teacher": "Teacher",
        "nav_admin": "Admin",
        "sidebar_flow_label": "Study Flow",
        "sidebar_flow_title": "Test, learn, review.",
        "sidebar_flow_text": "Use the level test to find your band, then build richer word cards over time.",
        "sidebar_flow_link": "Open learning",
        "topbar_search": "Search for words, bands, or definitions...",
        "topbar_project": "The VocabLab AI vocabulary project",
        "home_eyebrow": "Dashboard",
        "home_title": "Hello, Lawrence.",
        "home_lede": "Build your vocabulary with a clear daily flow: test, learn, and review.",
        "onboarding_step_1": "Step 1",
        "onboarding_step_2": "Step 2",
        "onboarding_title": "Welcome to VocabLab AI",
        "onboarding_lede": "Let's make your learning experience personal.",
        "landing_hero_kicker": "AI vocabulary system for long-term growth",
        "landing_hero_title": "Build vocabulary that stays with you across school, work, and AI use.",
        "landing_hero_body": "Turn testing, learning, notes, and review into one continuous knowledge graph you can keep growing over time.",
        "landing_feature_identity_title": "One identity",
        "landing_feature_identity_body": "Keep your name, role, and vocabulary path in one place.",
        "landing_feature_memory_title": "Long-term memory",
        "landing_feature_memory_body": "Save notes, mistakes, and review history as part of your learning record.",
        "landing_feature_transfer_title": "Portable growth",
        "landing_feature_transfer_body": "Carry your knowledge passport from school into professional life.",
        "landing_passport_label": "Knowledge Passport",
        "landing_passport_title": "Your words, notes, and progress become a portable learning asset.",
        "landing_passport_point_1": "Level tests, learning sessions, and saved notes stay connected.",
        "landing_passport_point_2": "Review weak words again in new future contexts.",
        "landing_passport_point_3": "Keep building one vocabulary graph instead of starting over.",
        "onboarding_name_label": "First name",
        "onboarding_name_hint": "Optional. Add your name if you'd like a more personal dashboard.",
        "onboarding_name_placeholder": "Your first name",
        "onboarding_role_title": "Who are you?",
        "onboarding_role_lede": "Pick the track that fits you best. We'll tailor the dashboard and recommendations right away.",
        "onboarding_submit": "Continue to my dashboard",
        "landing_mode_guest": "One-time user",
        "landing_mode_registered": "Registered user",
        "landing_guest_title": "Quick start without an account",
        "landing_guest_lede": "Use the current one-time setup, pick your role, and go straight into the dashboard.",
        "landing_registered_title": "Build Your Knowledge Passport",
        "landing_registered_lede": "When you leave school, continue your studies, or move into professional life, you can export your knowledge graph into your personal account. Your data, notes, and records become a knowledge passport you can carry into any future context.",
        "signup_title": "Create account",
        "signup_name_label": "Display name",
        "signup_name_placeholder": "Your name",
        "signup_email_label": "Email",
        "signup_email_placeholder": "you@example.com",
        "signup_password_label": "Password",
        "signup_password_placeholder": "Create a password",
        "signup_confirm_password_label": "Confirm password",
        "signup_confirm_password_placeholder": "Re-enter your password",
        "signup_submit": "Sign up",
        "login_title": "Log in",
        "login_email_label": "Email",
        "login_password_label": "Password",
        "login_submit": "Log in",
        "auth_or": "or",
        "auth_logout": "Log out",
        "auth_error_email_taken": "This email is already registered.",
        "auth_error_invalid_login": "Email or password is incorrect.",
        "auth_error_password_short": "Password must be at least 8 characters.",
        "auth_error_password_mismatch": "The two passwords do not match.",
        "auth_error_name_required": "Please add your display name.",
        "auth_error_email_required": "Please add a valid email.",
        "auth_error_teacher_invite_required": "Teacher accounts require a valid teacher invitation code.",
        "teacher_invite_code": "Teacher invitation code",
        "teacher_invite_code_note": "Only enter this if you are registering or switching to Teacher / Educator.",
        "nav_account": "Account",
        "account_title": "Account Settings",
        "account_lede": "Manage your profile, learning role, and password.",
        "account_profile": "Profile",
        "account_email": "Email",
        "account_persona": "Learning role",
        "account_save_profile": "Save profile",
        "account_password": "Password",
        "current_password": "Current password",
        "new_password": "New password",
        "change_password": "Change password",
        "account_profile_saved": "Profile updated.",
        "account_password_saved": "Password changed.",
        "account_error_password_current": "Current password is incorrect.",
        "account_login_required": "Please log in to manage your account.",
        "account_join_class": "Join Class",
        "account_join_class_note": "Enter an invite code from your teacher to link your learning records to a class.",
        "class_invite_code": "Invite code",
        "class_join_submit": "Join class",
        "class_joined": "Class joined.",
        "class_join_error": "Class code was not found.",
        "teacher_dashboard_title": "Teacher Dashboard",
        "teacher_dashboard_lede": "Create classes, share invite codes, and start tracking student learning records.",
        "teacher_create_class": "Create Class",
        "teacher_class_name": "Class name",
        "teacher_class_name_placeholder": "Grade 10 Economist Reading",
        "teacher_create_class_submit": "Create class",
        "teacher_my_classes": "My Classes",
        "teacher_no_classes": "No classes yet. Create your first class to generate an invite code.",
        "teacher_students": "Students",
        "teacher_student_name": "Student",
        "teacher_student_email": "Email",
        "teacher_joined_at": "Joined",
        "teacher_no_students": "No students have joined yet.",
        "teacher_only": "Please switch your account role to Teacher / Educator to use this page.",
        "teacher_class_snapshot": "Class Snapshot",
        "teacher_active_students": "Active Students",
        "teacher_avg_level_score": "Avg. Level Score",
        "teacher_avg_learning_accuracy": "Avg. Learning Accuracy",
        "teacher_learning_completed": "Learning Sessions",
        "teacher_at_risk_students": "At-Risk Students",
        "teacher_weakest_type": "Weakest Type",
        "teacher_student_progress": "Student Progress",
        "teacher_latest_test": "Latest Test",
        "teacher_recommended_band": "Recommended Band",
        "teacher_learning_accuracy": "Learning Accuracy",
        "teacher_learning_sessions": "Learning",
        "teacher_weak_area": "Weak Area",
        "teacher_last_active": "Last Active",
        "teacher_risk": "Risk",
        "teacher_recommendations": "Recommended Actions",
        "teacher_no_recommendations": "No urgent actions yet. Keep the class on the current learning plan.",
        "teacher_recommend_inactive": "{count} students have not been active recently. Send a reminder or assign a short review.",
        "teacher_recommend_accuracy": "{count} students are below 60% accuracy. Assign a lower-band revision set.",
        "teacher_recommend_weak_type": "The class is weakest in {question_type}. Create focused practice for this layer.",
        "teacher_create_assignment": "Create Assignment",
        "teacher_assignment_title": "Assignment title",
        "teacher_assignment_title_placeholder": "This week's Band 3 revision",
        "teacher_assignment_class": "Class",
        "teacher_assignment_band": "Vocabulary band",
        "teacher_assignment_due": "Due date",
        "teacher_create_assignment_submit": "Create assignment",
        "teacher_assignments": "Assignments",
        "teacher_no_assignments": "No assignments yet.",
        "teacher_assignment_completion": "Completion",
        "teacher_assignment_avg_score": "Avg. score",
        "teacher_assignment_created": "Assignment created.",
        "teacher_assignment_type": "Assignment type",
        "assignment_type_band_practice": "Band practice",
        "assignment_type_weak_review": "Weak-word review",
        "assignment_type_deep_learning": "Deep Learning",
        "teacher_total_classes": "Classes",
        "teacher_total_students": "Students",
        "teacher_open_assignments": "Open assignments",
        "teacher_class_report": "Export class report",
        "teacher_class_code_hint": "Students use this code to join the class from Account Settings.",
        "teacher_student_action": "Next action",
        "teacher_action_retest": "Ask this student to complete the DSE Level Test.",
        "teacher_action_review": "Assign focused review for {question_type}.",
        "teacher_action_remind": "Send a reminder and a short review task.",
        "teacher_action_extend": "Move this student to a higher-band practice set.",
        "admin_dashboard_title": "Admin Dashboard",
        "admin_dashboard_lede": "Overlook the whole VocabLab AI system: users, daily usage, tests, learning sessions, and Deep Learning activity.",
        "admin_only": "This dashboard is only available to system administrators.",
        "admin_system_snapshot": "System Snapshot",
        "admin_total_users": "Total Users",
        "admin_students": "Students",
        "admin_teachers": "Teachers",
        "admin_total_classes": "Classes",
        "admin_today_active_users": "Active Today",
        "admin_7day_active_users": "7-Day Active",
        "admin_today_tests": "Tests Today",
        "admin_today_learning": "Learning Today",
        "admin_today_deep_learning": "Deep Learning Today",
        "admin_daily_usage": "Daily Usage",
        "admin_user_overview": "User Overview",
        "admin_user": "User",
        "admin_role": "Role",
        "admin_joined": "Joined",
        "admin_last_active": "Last Active",
        "admin_tests": "Tests",
        "admin_learning": "Learning",
        "admin_deep_learning": "Deep Learning",
        "admin_no_users": "No registered users yet.",
        "admin_date": "Date",
        "admin_active_users": "Active users",
        "admin_level_tests": "Level tests",
        "admin_learning_sessions": "Learning sessions",
        "admin_mastery_attempts": "Deep Learning attempts",
        "assigned_practice": "Assigned Practice",
        "assigned_practice_note": "These tasks were assigned by your teacher.",
        "start_assignment": "Start assignment",
        "due_label": "Due",
        "risk_low": "Low",
        "risk_medium": "Medium",
        "risk_high": "High",
        "not_enough_data": "Not enough data",
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
        "classroom": "Classroom",
        "study_flow": "Study flow",
        "goal_note": "Start with your level test, then work the recommended band, then check missed words or the dictionary.",
        "start_test": "Start Level Test",
        "continue_learning": "Continue Learning",
        "student_today_plan": "Today's Study Plan",
        "student_today_plan_note": "Follow these steps in order. The app will keep your progress and point you to the next useful action.",
        "first_login_action": "Start DSE Level Test",
        "first_login_action_note": "Start here so VocabLab can recommend the right DSE band.",
        "resume_level_test_action": "Continue unfinished level test",
        "resume_learning_action": "Continue unfinished learning",
        "daily_task_action": "Today's 10-word learning session",
        "review_weak_words_action": "Review weak words",
        "deep_learning_three_action": "Deep Learning: 3 words",
        "recommended_path_title": "Recommended path",
        "recommended_path_body": "You should start from {band}.",
        "completed_words_this_session": "Words completed this session",
        "words_need_review": "Words to review",
        "review_mistakes": "Review Mistakes",
        "start_next_10_words": "Start Next 10 Words",
        "statistics_advice_title": "Study advice",
        "statistics_advice_no_test": "Start with the DSE Level Test so the system can recommend your first band.",
        "statistics_advice_no_learning": "Your next step is a 10-word learning session in your recommended DSE band.",
        "statistics_advice_weak_layer": "Your weakest area is {layer}. Practice this question type today.",
        "statistics_advice_good": "Your latest results are stable. Continue with the next 10 words and complete Deep Learning for your weak words.",
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
        "frequency_bands": "DSE Vocabulary Bands",
        "browse_count": "Browse by DSE learning level",
        "open_dictionary": "Open dictionary",
        "bands_note": "These bands are based on DSE learning level, exam usefulness, and academic vocabulary priority.",
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
        "brand_title": "VocabLab AI",
        "brand_subtitle": "個人詞彙學習系統",
        "nav_dashboard": "首頁總覽",
        "nav_test": "程度測驗",
        "nav_learning": "學習練習",
        "nav_learning_sidebar": "學習重溫",
        "nav_dictionary": "詞典查詢",
        "nav_business_vocab": "商務詞彙",
        "nav_missed": "錯題複習",
        "nav_bulk": "批次匯入",
        "nav_statistics": "統計數據",
        "nav_teacher": "教師",
        "nav_admin": "Admin",
        "sidebar_flow_label": "學習流程",
        "sidebar_flow_title": "先測驗，再學習，再複習。",
        "sidebar_flow_text": "先用程度檢測找出適合的詞彙範圍，再逐步補齊每張詞彙卡的內容。",
        "sidebar_flow_link": "前往學習",
        "topbar_search": "搜尋詞彙、分類或定義...",
        "topbar_project": "VocabLab AI 詞彙專案",
        "home_eyebrow": "首頁總覽",
        "home_title": "Lawrence，你好。",
        "home_lede": "把你的詞彙整理成清楚的每日學習流程：測驗、練習、複習。",
        "onboarding_step_1": "第 1 步",
        "onboarding_step_2": "第 2 步",
        "onboarding_title": "歡迎來到 VocabLab AI",
        "onboarding_lede": "先讓我們為你度身訂造最適合你的學習體驗",
        "landing_hero_kicker": "面向長期成長的 AI 詞彙系統",
        "landing_hero_title": "讓你的詞彙能力能一路帶進校園、職場與 AI 應用場景。",
        "landing_hero_body": "把測驗、學習、筆記與複習整理成同一張可持續成長的知識圖譜，不必每到新階段就重新開始。",
        "landing_feature_identity_title": "同一個學習身份",
        "landing_feature_identity_body": "把你的名字、角色與詞彙成長路徑整理在同一個地方。",
        "landing_feature_memory_title": "長期學習記憶",
        "landing_feature_memory_body": "把筆記、錯題與複習紀錄沉澱成你的學習資產。",
        "landing_feature_transfer_title": "可攜式成長紀錄",
        "landing_feature_transfer_body": "讓知識護照陪你從校園延伸到職場。",
        "landing_passport_label": "知識護照",
        "landing_passport_title": "你的詞彙、筆記與進步紀錄，都會成為可攜式的長期學習資產。",
        "landing_passport_point_1": "程度測驗、學習練習與個人筆記會彼此串接。",
        "landing_passport_point_2": "未來能把過去的弱點詞放進新的場景再次複習。",
        "landing_passport_point_3": "同一張詞彙知識圖譜會持續累積，而不是每次重新開始。",
        "onboarding_name_label": "名字",
        "onboarding_name_hint": "可選填",
        "onboarding_name_placeholder": "你的名字",
        "onboarding_role_title": "你是哪一類使用者？",
        "onboarding_role_lede": "請選最符合你的角色，我們的AI Agent會為你提供最貼合的學習內容",
        "onboarding_submit": "進入我的個人化首頁",
        "landing_mode_guest": "單次使用者",
        "landing_mode_registered": "註冊使用者",
        "landing_guest_title": "不需帳號，直接開始",
        "landing_guest_lede": "沿用目前的一次性設定直接進入首頁",
        "landing_registered_title": "建立你的知識護照（Build Your Knowledge Passport）",
        "landing_registered_lede": "當離開學校繼續進修或進入職場時，你可以將知識圖譜導出到個人賬號，這些數據、筆記、資料會成為你的知識護照，方便日後在任何場景應用。",
        "signup_title": "建立帳號",
        "signup_name_label": "顯示名稱",
        "signup_name_placeholder": "你的名字",
        "signup_email_label": "電子郵件",
        "signup_email_placeholder": "you@example.com",
        "signup_password_label": "密碼",
        "signup_password_placeholder": "建立密碼",
        "signup_confirm_password_label": "確認密碼",
        "signup_confirm_password_placeholder": "再次輸入密碼",
        "signup_submit": "註冊",
        "login_title": "登入帳號",
        "login_email_label": "電子郵件",
        "login_password_label": "密碼",
        "login_submit": "登入",
        "auth_or": "或",
        "auth_logout": "登出",
        "auth_error_email_taken": "這個電子郵件已經註冊過了。",
        "auth_error_invalid_login": "電子郵件或密碼不正確。",
        "auth_error_password_short": "密碼至少需要 8 個字元。",
        "auth_error_password_mismatch": "兩次輸入的密碼不一致。",
        "auth_error_name_required": "請填寫顯示名稱。",
        "auth_error_email_required": "請輸入有效的電子郵件。",
        "auth_error_teacher_invite_required": "Teacher 帳戶需要有效的老師邀請碼。",
        "teacher_invite_code": "老師邀請碼",
        "teacher_invite_code_note": "只有註冊或切換為 Teacher / Educator 時才需要填寫。",
        "nav_account": "帳戶",
        "account_title": "帳戶設定",
        "account_lede": "管理你的個人資料、學習角色與密碼。",
        "account_profile": "個人資料",
        "account_email": "電子郵件",
        "account_persona": "學習角色",
        "account_save_profile": "儲存個人資料",
        "account_password": "密碼",
        "current_password": "目前密碼",
        "new_password": "新密碼",
        "change_password": "修改密碼",
        "account_profile_saved": "個人資料已更新。",
        "account_password_saved": "密碼已更新。",
        "account_error_password_current": "目前密碼不正確。",
        "account_login_required": "請先登入才能管理帳戶。",
        "account_join_class": "加入班級",
        "account_join_class_note": "輸入老師提供的邀請碼，把你的學習紀錄連到班級。",
        "class_invite_code": "邀請碼",
        "class_join_submit": "加入班級",
        "class_joined": "已加入班級。",
        "class_join_error": "找不到這個班級邀請碼。",
        "teacher_dashboard_title": "教師 Dashboard",
        "teacher_dashboard_lede": "建立班級、分享邀請碼，開始追蹤學生的學習紀錄。",
        "teacher_create_class": "建立班級",
        "teacher_class_name": "班級名稱",
        "teacher_class_name_placeholder": "Grade 10 Economist Reading",
        "teacher_create_class_submit": "建立班級",
        "teacher_my_classes": "我的班級",
        "teacher_no_classes": "目前還沒有班級。先建立第一個班級，系統會產生邀請碼。",
        "teacher_students": "學生",
        "teacher_student_name": "學生",
        "teacher_student_email": "Email",
        "teacher_joined_at": "加入時間",
        "teacher_no_students": "暫時沒有學生加入。",
        "teacher_only": "請先把帳戶角色切換成 Teacher / Educator，才能使用這個頁面。",
        "teacher_class_snapshot": "班級總覽",
        "teacher_active_students": "活躍學生",
        "teacher_avg_level_score": "平均程度分",
        "teacher_avg_learning_accuracy": "平均練習準確率",
        "teacher_learning_completed": "完成練習",
        "teacher_at_risk_students": "需關注學生",
        "teacher_weakest_type": "最弱題型",
        "teacher_student_progress": "學生進度",
        "teacher_latest_test": "最近測驗",
        "teacher_recommended_band": "建議 Band",
        "teacher_learning_accuracy": "練習準確率",
        "teacher_learning_sessions": "練習次數",
        "teacher_weak_area": "弱項",
        "teacher_last_active": "最後活躍",
        "teacher_risk": "風險",
        "teacher_recommendations": "建議行動",
        "teacher_no_recommendations": "暫時沒有急需處理的事項，可以按目前學習節奏繼續。",
        "teacher_recommend_inactive": "{count} 位學生近期沒有活躍。建議發提醒或派一份短複習。",
        "teacher_recommend_accuracy": "{count} 位學生準確率低於 60%。建議派較低 band 的 revision set。",
        "teacher_recommend_weak_type": "全班最弱題型是 {question_type}。建議建立針對這一層的練習。",
        "teacher_create_assignment": "指派練習",
        "teacher_assignment_title": "練習標題",
        "teacher_assignment_title_placeholder": "本週 Band 3 revision",
        "teacher_assignment_class": "班級",
        "teacher_assignment_band": "詞彙 Band",
        "teacher_assignment_due": "截止日期",
        "teacher_create_assignment_submit": "建立指派",
        "teacher_assignments": "已派練習",
        "teacher_no_assignments": "目前還沒有指派練習。",
        "teacher_assignment_completion": "完成率",
        "teacher_assignment_avg_score": "平均分",
        "teacher_assignment_created": "已建立指派練習。",
        "teacher_assignment_type": "練習類型",
        "assignment_type_band_practice": "Band 練習",
        "assignment_type_weak_review": "弱詞重溫",
        "assignment_type_deep_learning": "深度學習",
        "teacher_total_classes": "班級",
        "teacher_total_students": "學生",
        "teacher_open_assignments": "進行中指派",
        "teacher_class_report": "匯出班級報告",
        "teacher_class_code_hint": "學生可在帳戶設定輸入此邀請碼加入班級。",
        "teacher_student_action": "下一步",
        "teacher_action_retest": "請這位學生先完成 DSE 程度測驗。",
        "teacher_action_review": "指派 {question_type} 針對練習。",
        "teacher_action_remind": "先發提醒，再派一份短複習。",
        "teacher_action_extend": "可安排更高 Band 的練習。",
        "admin_dashboard_title": "Admin Dashboard",
        "admin_dashboard_lede": "總覽整個 VocabLab AI 系統：用戶、每日使用量、程度測驗、學習練習和深度學習活動。",
        "admin_only": "這個 dashboard 只供系統管理員使用。",
        "admin_system_snapshot": "系統總覽",
        "admin_total_users": "總用戶",
        "admin_students": "學生",
        "admin_teachers": "老師",
        "admin_total_classes": "班級",
        "admin_today_active_users": "今日活躍",
        "admin_7day_active_users": "7 日活躍",
        "admin_today_tests": "今日測驗",
        "admin_today_learning": "今日學習",
        "admin_today_deep_learning": "今日深度學習",
        "admin_daily_usage": "每日使用量",
        "admin_user_overview": "用戶總覽",
        "admin_user": "用戶",
        "admin_role": "角色",
        "admin_joined": "加入",
        "admin_last_active": "最後活躍",
        "admin_tests": "測驗",
        "admin_learning": "學習",
        "admin_deep_learning": "深度學習",
        "admin_no_users": "暫時未有註冊用戶。",
        "admin_date": "日期",
        "admin_active_users": "活躍用戶",
        "admin_level_tests": "程度測驗",
        "admin_learning_sessions": "學習練習",
        "admin_mastery_attempts": "深度學習次數",
        "assigned_practice": "老師指派練習",
        "assigned_practice_note": "以下是老師指派給你的練習。",
        "start_assignment": "開始練習",
        "due_label": "截止",
        "risk_low": "低",
        "risk_medium": "中",
        "risk_high": "高",
        "not_enough_data": "資料不足",
        "persona_student": "學生",
        "persona_student_desc": "小學、中學、大學或研究所階段，想建立更強的學術英語能力",
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
        "classroom": "班級",
        "study_flow": "學習流程",
        "goal_note": "先做程度檢測，再練習建議的詞彙範圍，最後查看錯題或進入詞典補充內容。",
        "start_test": "開始程度檢測",
        "continue_learning": "繼續學習",
        "student_today_plan": "今日學習任務",
        "student_today_plan_note": "按順序完成以下任務。系統會保存進度，並指引你下一步最值得做甚麼。",
        "first_login_action": "開始 DSE 程度測驗",
        "first_login_action_note": "先從這裡開始，VocabLab 才能建議最適合你的 DSE 詞彙分級。",
        "resume_level_test_action": "繼續上次未完成測驗",
        "resume_learning_action": "繼續上次未完成練習",
        "daily_task_action": "今日 10 個詞學習練習",
        "review_weak_words_action": "複習薄弱詞彙",
        "deep_learning_three_action": "深度學習 3 個詞",
        "recommended_path_title": "建議學習路徑",
        "recommended_path_body": "建議你由 {band} 開始。",
        "completed_words_this_session": "本次完成詞彙",
        "words_need_review": "需要重溫的詞彙",
        "review_mistakes": "重練錯題",
        "start_next_10_words": "開始下一組 10 個詞",
        "statistics_advice_title": "學習建議",
        "statistics_advice_no_test": "先完成 DSE 程度測驗，系統才能建議你的起始分級。",
        "statistics_advice_no_learning": "下一步建議做一輪建議 DSE 分級的 10 個詞學習練習。",
        "statistics_advice_weak_layer": "你目前較弱的是 {layer}，今天建議集中練習這類題型。",
        "statistics_advice_good": "最近結果穩定。可以繼續下一組 10 個詞，並為薄弱詞彙完成深度學習。",
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
        "frequency_bands": "DSE 詞彙分級",
        "browse_count": "依 DSE 學習程度瀏覽",
        "open_dictionary": "打開詞典",
        "bands_note": "這些分級根據 DSE 學習程度、考試實用性和學術詞彙優先次序整理，並不是根據《經濟學人》出現頻率。",
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
        "business_vocab_title": "Business Vocabulary",
        "business_vocab_home_title": "Economist frequency, filtered by business context.",
        "business_vocab_home_lede": "Keep the 5-band Economist priority system, then browse by sector, topic, or business skill.",
        "business_vocab_tag": "Business",
        "business_vocab_action": "Business vocabulary view",
        "business_vocab_action_note": "Filter words by finance, technology, strategy, reports, meetings, and more.",
        "business_vocab_filters": "Business filters",
        "business_vocab_search_placeholder": "Search business words, e.g. inflation",
        "business_sector": "Sector",
        "business_topic": "Topic",
        "business_skill": "Business skill",
        "all_sectors": "All sectors",
        "all_topics": "All topics",
        "all_skills": "All skills",
        "business_featured_path": "Featured Path",
        "business_featured_path_title": "Finance & Markets — Band 1 to Band 3",
        "business_featured_path_note": "Start with core Economist words, then move into market analysis and sector-specific language.",
        "business_results_title": "Vocabulary Results",
        "business_results_count": "{count} business words shown",
        "business_band": "Business band",
        "economist_band": "Economist band",
        "business_context": "Business context",
        "business_use": "Use",
        "learn_word": "Learn",
        "business_no_match": "No business words matched these filters.",
        "business_no_match_note": "Try removing one filter or searching a broader business keyword.",
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
        "ai_insight_section": "AI Insight",
        "ai_insight_title": "Learn this word more intelligently",
        "ai_explain_simply": "Explain simply",
        "ai_nuance_comparison": "Nuance and comparison",
        "ai_use_it_better": "Use it better",
        "ai_simple_explanation_zh": "Chinese explanation",
        "ai_business_example_label": "Business example",
        "ai_prompt_example_label": "AI prompt example",
        "ai_usage_warning_label": "Usage warning",
        "ai_nuance_note_label": "Nuance note",
        "ai_compare_words_label": "Compare words",
        "ai_compare_words_hint": "One per line: word | note",
        "ai_simple_explanation_zh_placeholder": "Add a short Chinese explanation",
        "ai_nuance_note_placeholder": "Explain the nuance or difference from nearby words",
        "ai_business_example_placeholder": "Add one business example sentence",
        "ai_prompt_example_placeholder": "Add one AI prompt example",
        "ai_usage_warning_placeholder": "Add one short usage warning",
        "no_ai_insight": "No AI insight added yet.",
        "generate_ai_insight": "Generate AI Insight",
        "ai_insight_generate_note": "Use OpenAI to draft the explanation, nuance, comparison, business example, and AI prompt example for this word.",
        "ai_insight_generated": "AI Insight generated.",
        "ai_insight_error": "AI Insight generation failed",
        "word_mastery_tab": "Word Mastery Lab",
        "word_mastery_section": "Deep Learning",
        "word_mastery_title": "Pronounce, apply, and master this word",
        "word_mastery_lede": "Say the word, write one sentence, and let AI check whether your pronunciation, usage, and grammar are ready for real exam use.",
        "mastery_pronunciation_title": "1. Pronunciation practice",
        "mastery_sentence_title": "2. Sentence application",
        "mastery_record_note": "Your attempts are saved to your learning record.",
        "mastery_record_button": "Record my voice",
        "mastery_stop_button": "Stop and check",
        "mastery_retry_button": "Record again",
        "mastery_check_sentence": "Check with AI",
        "mastery_sentence_placeholder": "Write one sentence using this word.",
        "mastery_latest_result": "Latest mastery result",
        "mastery_no_attempt": "No deep-learning attempt saved yet.",
        "mastery_transcript": "AI heard",
        "mastery_feedback": "AI feedback",
        "mastery_corrected_sentence": "Corrected sentence",
        "mastery_suggested_upgrade": "Suggested upgrade",
        "mastery_score": "Score",
        "mastery_status": "Status",
        "mastery_api_not_ready": "AI checking is not configured yet.",
        "mastery_progress_section": "Learning Progress",
        "mastery_progress_title": "Vocabulary mastery ladder",
        "mastery_progress_lede": "Passing the five test layers shows test mastery. Full mastery requires pronunciation, sentence usage, and review.",
        "mastery_progress_percent": "{percent}% complete",
        "mastery_progress_not_started": "Not Started",
        "mastery_progress_seen": "Seen",
        "mastery_progress_learning": "Learning",
        "mastery_progress_practicing": "Practicing",
        "mastery_progress_tested": "Tested",
        "mastery_progress_deep_learning": "Deep Learning",
        "mastery_progress_mastered": "Mastered",
        "mastery_progress_exposure": "Opened",
        "mastery_progress_test_layers": "5-layer test",
        "mastery_progress_pronunciation": "Pronunciation",
        "mastery_progress_writing": "AI usage",
        "mastery_progress_review": "Review",
        "mastery_progress_average": "Average progress",
        "mastery_progress_mastered_count": "{count} mastered",
        "mastery_next_step": "Next step",
        "mastery_next_start": "Open this word and start the 5-layer test.",
        "mastery_next_continue_test": "Complete the remaining 5-layer test items.",
        "mastery_next_deep": "Finish pronunciation and AI sentence usage to move beyond Tested.",
        "mastery_next_review": "Review this word once more to reach 100% mastery.",
        "mastery_next_complete": "Fully mastered. Keep it in long-term review.",
        "mastery_list_hint": "Each card shows the current mastery stage and the missing steps.",
        "mastery_stage_exposure": "Exposure",
        "mastery_stage_test": "5-layer test",
        "mastery_stage_deep": "Deep Learning",
        "mastery_stage_review": "Review",
        "mastery_recording_unsupported": "Recording is not supported in this browser.",
        "mastery_recording": "Recording...",
        "mastery_checking": "Checking...",
        "mastery_sentence_required": "Please write a sentence first.",
        "dse_exam_use_section": "DSE Exam Use",
        "dse_exam_use_title": "How to use this word in DSE English",
        "dse_exam_use_lede": "Focus on where this word can help in Paper 1 reading, Paper 2 writing, and Paper 4 speaking.",
        "dse_paper_fit": "Best DSE fit",
        "dse_topic_fit": "Likely topics",
        "dse_writing_move": "Writing move",
        "dse_sample_sentence": "DSE-style sentence",
        "dse_common_mistake": "Common mistake",
        "dse_next_practice": "Next practice",
        "dse_next_practice_text": "Write one DSE Paper 2 sentence below, then use Deep Learning to check usage and grammar.",
        "progression_section": "Progression",
        "vocabulary_progression": "Vocabulary Progression",
        "meaning_family": "Meaning family",
        "current_stage_label": "Current stage",
        "next_step_label": "Next step",
        "cluster_domain_label": "Domain",
        "cluster_path_label": "Growth path",
        "progression_attributes": "Progression attributes",
        "formality_level_label": "Formality",
        "precision_level_label": "Precision",
        "exam_relevance_label": "Exam relevance",
        "business_relevance_label": "Business relevance",
        "ai_relevance_label": "AI relevance",
        "productivity_likelihood_label": "Active-use potential",
        "usage_notes_label": "Usage notes",
        "register_notes_label": "Register notes",
        "no_progression_data": "No progression mapping added yet.",
        "no_usage_note": "No usage note added yet.",
        "stage_fallback": "General stage",
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
        "learning_hero_lede": "Each session gives you multiple-choice practice from your vocabulary database. As you enrich more words, learning becomes deeper and less repetitive.",
        "recommended_learning_band": "Recommended learning band",
        "choose_learning_band": "Choose a band",
        "learning_band_note": "The suggestion comes from your latest Level Test, but you can choose any band for this session.",
        "learning_session_structure": "10 vocabulary items from one band, tested through 5 layers each.",
        "recommended_badge": "Recommended",
        "latest_label": "Latest",
        "ready_label": "Ready",
        "most_recent_session": "most recent session",
        "start_new_session_note": "start a new session",
        "session_goal": "Session Goal",
        "build_consistency": "Build consistency first",
        "definition_short": "Definition",
        "synonym_short": "Synonym",
        "sentence_short": "Sentence",
        "definition_available_note": "Each session now uses the same five layers as the Level Test: Chinese meaning, English definition, example application, similar word, and opposite word.",
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
        "review_after_answer": "Review after each word",
        "review_after_answer_note": "You answer all five layers first, then see the score and details for that vocabulary item.",
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
        "learning_word_performance": "Vocabulary Performance",
        "learning_word_performance_note": "Review each vocabulary item, its score, and which layer needs more practice.",
        "learning_question_review": "Question Review",
        "learning_question_review_note": "Use this section to check your answer against the correct answer for every learning question.",
        "score_out_of": "Score: {score}/{total}",
        "result_status": "Result",
        "prompt_label": "Prompt",
        "level_test_title": "Level Test",
        "find_starting_band": "Find your starting band.",
        "test_intro_lede": "This placement test uses {count} points: {vocab_count} vocabulary items, 4 from each band, tested through 5 layers of meaning, usage, similarity, and contrast.",
        "questions_label": "Questions",
        "definition_based_items": "definition-based items",
        "what_it_measures": "What It Measures",
        "foundation_across_bands": "Foundation across bands",
        "frequency_short": "DSE band",
        "recognition_short": "Recognition",
        "placement_short": "Placement",
        "test_goal_note": "Level Test is a fixed assessment, separate from Learning. It measures breadth across all five bands and gives a score out of 100.",
        "begin_test": "Begin Test",
        "continue_test": "Continue Test",
        "start_new_test": "Start New Test",
        "saved_incomplete_test": "Saved in-progress test",
        "resume_test_note": "You have answered {answered}/{total} questions ({percent}%). Continue from where you stopped.",
        "band_coverage": "Band Coverage",
        "sampled_ranges": "Sampled ranges",
        "what_this_means": "What this means",
        "sampled_from_band": "{range} is a DSE student learning band. It is based on DSE learning level, exam usefulness, and academic vocabulary priority, not Economist frequency.",
        "goal_label": "Goal",
        "test_goal_fast": "Each vocabulary item appears in five layers: Chinese definition, English definition, example use, similar word, and opposite word.",
        "hidden_test_note": "Definitions, usage clues, and full word details appear only after you submit, so the placement result stays fair.",
        "meaning_and_usage_items": "5 layers / 100 points",
        "recognized_correctly": "You recognized this word correctly.",
        "word_round_complete": "Vocabulary item complete",
        "word_round_score": "Score for this word",
        "word_round_score_note": "You have completed all five layers for this vocabulary item. Detailed answers will appear in the final report.",
        "revisit_later_note": "This is a useful word to revisit later in learning mode.",
        "see_test_result": "See Test Result",
        "view_statistics": "Statistics",
        "result_label": "Result",
        "getting_started": "Getting Started",
        "test_result_lede": "You answered {score} correctly in this placement test. This result estimates where you should start learning next.",
        "test_history_title": "Test History",
        "test_history_lede": "Review your past placement results, compare scores, and see how your starting band has changed over time.",
        "test_history_empty": "No completed level tests yet. Take your first test and your history will appear here.",
        "legacy_test_result": "Legacy partial result",
        "legacy_test_result_note": "This older result was saved before the current 100-question level test format, so it is not counted in headline statistics.",
        "report_question": "Report Question",
        "report_question_note": "Flag a question if the definition, sentence, synonym, antonym, or distractors feel wrong.",
        "feedback_reason_wrong_definition": "Wrong definition",
        "feedback_reason_bad_sentence": "Bad example sentence",
        "feedback_reason_too_easy": "Too easy",
        "feedback_reason_ambiguous": "Ambiguous",
        "feedback_reason_bad_distractor": "Bad distractor",
        "feedback_comment_placeholder": "Optional note",
        "send_feedback": "Send Feedback",
        "quality_feedback_title": "Question Feedback",
        "quality_feedback_empty": "No reported questions yet.",
        "quality_feedback_lede": "Review level-test questions reported as wrong, too easy, ambiguous, or unnatural.",
        "quality_feedback_open": "Open",
        "quality_feedback_reviewed": "Reviewed",
        "mark_reviewed": "Mark Reviewed",
        "repair_content": "Repair Content",
        "save_repair": "Save Repair",
        "antonyms_label": "Antonyms",
        "one_antonym_per_line": "One antonym per line",
        "start_review_session": "Start Review Session",
        "due_for_review": "Due for review",
        "next_review": "Next review",
        "completed_on": "Completed",
        "score_label": "Score",
        "accuracy_short": "Accuracy",
        "statistics_title": "Statistics",
        "statistics_lede": "Review your saved learning data in one place, then open the section you want to inspect in detail.",
        "statistics_latest_test": "Latest Test",
        "statistics_best_result": "Best Result",
        "statistics_tests_taken": "Tests Taken",
        "statistics_no_test_yet": "No test yet",
        "statistics_score_trend": "Score Trend",
        "statistics_recent_tests": "Recent tests",
        "statistics_out_of": "out of",
        "statistics_test_history_title": "Test History",
        "statistics_test_history_body": "Review past placement results, compare scores, and track how your starting band changes over time.",
        "statistics_level_test_section": "Level Test Results",
        "statistics_learning_section": "Learning Session Results",
        "statistics_latest_report": "Latest Full Report",
        "statistics_latest_report_body": "View the complete report, including placement result, question-type analysis, and performance across vocabulary bands.",
        "statistics_no_learning_yet": "No learning session yet",
        "statistics_latest_learning": "Latest Learning",
        "statistics_best_learning": "Best Learning",
        "statistics_learning_runs": "Learning Runs",
        "view_full_report": "View Full Report",
        "view_learning_result": "View Learning Result",
        "statistics_more_coming": "More statistics modules coming soon.",
        "bulk_import_tools": "Import Tools",
        "bulk_import_tools_note": "Manage workbook uploads, taxonomy imports, and AI enrichment in a lower-profile admin area.",
        "open_bulk_import": "Open Bulk Import",
        "estimated_band_chip": "Estimated band: {band}",
        "correct_chip": "Correct: {score}",
        "total_questions_chip": "Total questions: {total}",
        "accuracy_chip": "Accuracy: {percent}%",
        "weighted_chip": "Weighted: {percent}%",
        "test_result_note": "This result combines your total accuracy and how well you handled harder frequency bands.",
        "what_to_do_next": "What to do next:",
        "band_breakdown": "Band Breakdown",
        "band_performance": "How you performed by range",
        "band_accuracy_note": "{percent}% accuracy in this band.",
        "test_result_saved_summary_note": "This is a saved historical result. Detailed question breakdown was not stored for this older test session.",
        "complete_report_title": "Complete Level Test Report",
        "complete_report_lede": "Use this report to see whether your weakness is meaning, English definition, sentence application, similar words, or opposite words.",
        "layer_breakdown": "Five-Layer Breakdown",
        "layer_performance": "Performance by question layer",
        "strongest_layer": "Strongest layer",
        "weakest_layer": "Priority review layer",
        "word_report": "Word-by-word report",
        "word_report_note": "Each row shows how one vocabulary item performed across the five layers.",
        "tested_word": "Tested word",
        "layer_score": "Layer score",
        "meaning_snapshot": "Meaning snapshot",
        "correct_mark": "Correct",
        "wrong_mark": "Review",
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
        "hero_chart_label": "DSE Vocabulary Snapshot",
        "hero_chart_title": "Your DSE vocabulary bands",
        "hero_chart_note": "A quick look at how the DSE student vocabulary set is distributed across learning bands.",
        "hero_chart_total": "Total Words",
        "hero_chart_bands": "DSE vocabulary bands",
        "nav_ai_power": "AI Power Vocab",
        "ai_power_label": "New Track",
        "ai_power_title": "AI + Professional Power Vocabulary",
        "ai_power_lede": "A separate track for adults and professionals who want stronger prompting, clearer business English, and more precise communication with AI.",
        "ai_power_open": "Open AI Power Vocabulary",
        "ai_power_target": "500-word roadmap",
        "ai_power_categories": "Focus categories",
        "ai_power_starter": "Starter seed list",
        "ai_power_progress": "AI Power Level",
        "ai_power_structure_title": "What each word card should include",
        "ai_power_structure_lede": "This track stays separate from Economist frequency bands and is designed around direct real-world use.",
        "ai_power_item_english": "English",
        "ai_power_item_trad": "Traditional Chinese",
        "ai_power_item_simp": "Simplified Chinese",
        "ai_power_item_sentence": "Example sentence",
        "ai_power_item_prompt": "AI prompt example",
        "ai_power_category_terms": "{count} starter terms",
        "ai_power_home_title": "Build a second track for AI and professional use",
        "ai_power_home_note": "Keep frequency-based vocabulary study, and add a separate AI track for prompting, meetings, writing, and decision-making.",
        "ai_power_category_cta": "Category focus",
        "ai_power_examples_title": "Why this track is different",
        "ai_power_examples_lede": "Each category comes with normal usage and AI usage, so the vocabulary becomes immediately usable instead of purely academic.",
        "ai_power_template_title": "AI Power import template",
        "ai_power_template_lede": "Download an Excel sheet prefilled with categories and starter terms, then complete Traditional Chinese, Simplified Chinese, example sentences, and the five AI prompt scenarios in batches.",
        "ai_power_download_template": "Download Excel Template",
        "ai_power_template_note": "Suggested columns: English, Traditional Chinese, Simplified Chinese, example sentence, a general AI prompt example, five scenario-specific AI prompts, and notes.",
        "ai_power_upload_title": "Upload completed AI Power file",
        "ai_power_upload_button": "Import AI Power File",
        "ai_power_upload_success": "Import complete. Updated {count} AI Power entries.",
        "ai_power_search_title": "Find AI Power vocabulary fast",
        "ai_power_search_placeholder": "Search English, Chinese, type, IPA, or definition",
        "ai_power_category_all": "All categories",
        "ai_power_results": "{count} categories shown",
        "ai_power_open_category": "Open category",
        "ai_power_words_ready": "{count} words ready",
        "ai_power_back": "Back to AI Power Vocabulary",
        "ai_power_all_words": "All words in this category",
        "ai_power_prompt_usage": "Prompt usage",
        "ai_power_normal_usage": "Normal usage",
        "ai_power_back_category": "Back to category",
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
        "business_vocab_title": "商務詞彙",
        "business_vocab_home_title": "以 Economist 詞頻為主軸，再按商務情境篩選。",
        "business_vocab_home_lede": "保留 5 層 Economist 詞頻優先級，同時可按行業、主題或工作用途瀏覽。",
        "business_vocab_tag": "商務",
        "business_vocab_action": "商務詞彙視圖",
        "business_vocab_action_note": "按 finance、technology、strategy、reports、meetings 等情境篩選詞彙。",
        "business_vocab_filters": "商務篩選",
        "business_vocab_search_placeholder": "搜尋商務詞彙，例如 inflation",
        "business_sector": "行業",
        "business_topic": "主題",
        "business_skill": "工作用途",
        "all_sectors": "全部行業",
        "all_topics": "全部主題",
        "all_skills": "全部用途",
        "business_featured_path": "建議路徑",
        "business_featured_path_title": "Finance & Markets — Band 1 至 Band 3",
        "business_featured_path_note": "先學 Economist 核心詞，再進入市場分析與行業精準詞彙。",
        "business_results_title": "詞彙結果",
        "business_results_count": "目前顯示 {count} 個商務詞彙",
        "business_band": "商務 Band",
        "economist_band": "Economist Band",
        "business_context": "商務情境",
        "business_use": "用途",
        "learn_word": "學習",
        "business_no_match": "找不到符合這些篩選的商務詞彙。",
        "business_no_match_note": "可以移除一個篩選條件，或搜尋較寬的商務關鍵字。",
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
        "ai_insight_section": "AI 重點提示",
        "ai_insight_title": "用更聰明的方式理解這個詞",
        "ai_explain_simply": "簡單理解",
        "ai_nuance_comparison": "語感與比較",
        "ai_use_it_better": "更好地用出來",
        "ai_simple_explanation_zh": "中文解釋",
        "ai_business_example_label": "商務例句",
        "ai_prompt_example_label": "AI 提示範例",
        "ai_usage_warning_label": "使用提醒",
        "ai_nuance_note_label": "語感說明",
        "ai_compare_words_label": "比較詞",
        "ai_compare_words_hint": "每行一筆：詞彙 | 說明",
        "ai_simple_explanation_zh_placeholder": "加入一段簡短中文解釋",
        "ai_nuance_note_placeholder": "說明這個詞和相近詞的語感差異",
        "ai_business_example_placeholder": "加入一句商務場景例句",
        "ai_prompt_example_placeholder": "加入一句 AI 提示範例",
        "ai_usage_warning_placeholder": "加入一句簡短使用提醒",
        "no_ai_insight": "尚未加入 AI 重點提示。",
        "generate_ai_insight": "生成 AI 重點提示",
        "ai_insight_generate_note": "使用 OpenAI 為這個詞草擬簡單解釋、語感比較、商務例句與 AI 提示範例。",
        "ai_insight_generated": "AI 重點提示已生成。",
        "ai_insight_error": "AI 重點提示生成失敗",
        "word_mastery_tab": "深度學習",
        "word_mastery_section": "深度學習",
        "word_mastery_title": "讀出、用出、真正掌握這個詞",
        "word_mastery_lede": "讀出單字，再寫一句句子，讓 AI 檢查你的發音、用法和文法是否已適合真實考試情境。",
        "mastery_pronunciation_title": "1. 發音練習",
        "mastery_sentence_title": "2. 句子應用",
        "mastery_record_note": "你的練習結果會保存到學習紀錄。",
        "mastery_record_button": "錄下我的發音",
        "mastery_stop_button": "停止並檢查",
        "mastery_retry_button": "重新錄音",
        "mastery_check_sentence": "用 AI 檢查",
        "mastery_sentence_placeholder": "用這個詞寫一句句子。",
        "mastery_latest_result": "最近一次深度練習",
        "mastery_no_attempt": "尚未保存深度練習結果。",
        "mastery_transcript": "AI 聽到",
        "mastery_feedback": "AI 回饋",
        "mastery_corrected_sentence": "修正版句子",
        "mastery_suggested_upgrade": "升級版句子",
        "mastery_score": "分數",
        "mastery_status": "狀態",
        "mastery_api_not_ready": "AI 檢查尚未設定。",
        "mastery_progress_section": "學習進度",
        "mastery_progress_title": "詞彙掌握階梯",
        "mastery_progress_lede": "通過五層題型代表完成測驗掌握；真正 100% 掌握需要完成發音、句子應用與複習。",
        "mastery_progress_percent": "完成度 {percent}%",
        "mastery_progress_not_started": "未開始",
        "mastery_progress_seen": "已看過",
        "mastery_progress_learning": "學習中",
        "mastery_progress_practicing": "練習中",
        "mastery_progress_tested": "已通過測驗",
        "mastery_progress_deep_learning": "深度學習中",
        "mastery_progress_mastered": "已掌握",
        "mastery_progress_exposure": "已打開",
        "mastery_progress_test_layers": "五層題型",
        "mastery_progress_pronunciation": "發音",
        "mastery_progress_writing": "AI 用法",
        "mastery_progress_review": "複習",
        "mastery_progress_average": "平均進度",
        "mastery_progress_mastered_count": "{count} 個已掌握",
        "mastery_next_step": "下一步",
        "mastery_next_start": "打開這個詞，先開始五層題型測驗。",
        "mastery_next_continue_test": "完成尚未通過的五層題型。",
        "mastery_next_deep": "完成發音和 AI 句子應用，從「已通過測驗」進入深度學習。",
        "mastery_next_review": "再複習一次這個詞，就可以達到 100% 掌握。",
        "mastery_next_complete": "已完整掌握。之後保留在長期複習中即可。",
        "mastery_list_hint": "每張詞卡都會顯示目前掌握階段和仍未完成的步驟。",
        "mastery_stage_exposure": "接觸",
        "mastery_stage_test": "五層題型",
        "mastery_stage_deep": "深度學習",
        "mastery_stage_review": "複習",
        "mastery_recording_unsupported": "這個瀏覽器不支援錄音。",
        "mastery_recording": "錄音中...",
        "mastery_checking": "檢查中...",
        "mastery_sentence_required": "請先寫一句句子。",
        "dse_exam_use_section": "DSE 考試應用",
        "dse_exam_use_title": "這個詞在 DSE English 怎樣使用",
        "dse_exam_use_lede": "重點看它如何幫助 Paper 1 閱讀、Paper 2 寫作和 Paper 4 Speaking。",
        "dse_paper_fit": "最適合的 DSE 卷別",
        "dse_topic_fit": "常見題材",
        "dse_writing_move": "寫作用途",
        "dse_sample_sentence": "DSE 風格例句",
        "dse_common_mistake": "常見錯誤",
        "dse_next_practice": "下一步練習",
        "dse_next_practice_text": "在下面寫一句 DSE Paper 2 句子，再用深度學習檢查用法和文法。",
        "progression_section": "進階路徑",
        "vocabulary_progression": "詞彙進階路徑",
        "meaning_family": "核心語義群組",
        "current_stage_label": "目前階段",
        "next_step_label": "下一步建議",
        "cluster_domain_label": "主題領域",
        "cluster_path_label": "成長路徑",
        "progression_attributes": "進階屬性",
        "formality_level_label": "正式程度",
        "precision_level_label": "精準程度",
        "exam_relevance_label": "考試相關度",
        "business_relevance_label": "商務相關度",
        "ai_relevance_label": "AI 指令相關度",
        "productivity_likelihood_label": "主動產出機率",
        "usage_notes_label": "使用說明",
        "register_notes_label": "語域提醒",
        "no_progression_data": "尚未加入詞彙進階路徑。",
        "no_usage_note": "尚未加入使用說明。",
        "stage_fallback": "一般階段",
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
        "learning_hero_lede": "每次練習都會從你的詞彙庫出題。你補得越完整，之後的題目就會越實用、越不重複。",
        "recommended_learning_band": "建議學習分類",
        "choose_learning_band": "選擇詞彙分類",
        "learning_band_note": "系統會根據最近一次 Level Test 建議起點，但你也可以自由選擇任何一組。",
        "learning_session_structure": "每輪固定同一個 band 的 10 個詞彙，每個詞用 5 層題型練習。",
        "recommended_badge": "建議",
        "latest_label": "最近",
        "ready_label": "準備好了",
        "most_recent_session": "最近一次練習",
        "start_new_session_note": "開始新的練習",
        "session_goal": "這輪要做什麼",
        "build_consistency": "先把基礎答穩",
        "definition_short": "定義",
        "synonym_short": "同義詞",
        "sentence_short": "例句",
        "definition_available_note": "每輪會使用和 Level Test 一樣的五層題型：中文意思、英文定義、例句應用、相近詞與相反詞。",
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
        "review_after_answer": "每個詞後複習",
        "review_after_answer_note": "先完成同一個詞的五層題型，再看這個詞的得分與完整細節。",
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
        "learning_word_performance": "詞彙表現",
        "learning_word_performance_note": "查看每個詞的分數，以及哪一層題型需要再加強。",
        "learning_question_review": "題目回顧",
        "learning_question_review_note": "在這裡逐題核對你的答案和正確答案。",
        "score_out_of": "分數：{score}/{total}",
        "result_status": "結果",
        "prompt_label": "題目",
        "level_test_title": "程度檢測",
        "find_starting_band": "找出適合你的詞彙程度。",
        "test_intro_lede": "這個程度檢測共 {count} 分：20 個詞彙、每個 band 4 個，並透過中文意思、英文定義、例句應用、相近詞與相反詞 5 層題型評估。",
        "questions_label": "題目數",
        "definition_based_items": "以定義為主的題目",
        "what_it_measures": "這份檢測在看什麼",
        "foundation_across_bands": "看看你對不同層次詞彙的掌握",
        "frequency_short": "DSE 分級",
        "recognition_short": "辨識",
        "placement_short": "定位",
        "test_goal_note": "Level Test 是固定評量，和 Learning 分開。它會橫跨五個 band 測你的廣度，總分 100。",
        "begin_test": "開始測驗",
        "continue_test": "繼續測驗",
        "start_new_test": "重新開始測驗",
        "saved_incomplete_test": "已保存的未完成測驗",
        "resume_test_note": "你已完成 {answered}/{total} 題（{percent}%）。可以從上次中斷的位置繼續。",
        "band_coverage": "出題範圍",
        "sampled_ranges": "抽樣分類",
        "what_this_means": "這代表什麼",
        "sampled_from_band": "{range} 是 DSE 學生學習分級，根據 DSE 程度、考試實用性和學術詞彙優先次序整理，並不是根據《經濟學人》出現頻率。",
        "goal_label": "目標",
        "test_goal_fast": "每個詞會出現五層題型：中文意思、英文定義、例句應用、相近英文詞與相反英文詞。",
        "hidden_test_note": "在你送出答案前，完整定義、用法線索和詞彙細節都不會先顯示，這樣結果才比較準。",
        "meaning_and_usage_items": "5 層題型 / 100 分",
        "recognized_correctly": "你正確辨認了這個詞彙。",
        "word_round_complete": "這個詞已完成",
        "word_round_score": "這個詞的分數",
        "word_round_score_note": "你已完成這個詞的五層題型。詳細答案會在最後完整報告中顯示。",
        "revisit_later_note": "這是之後很適合放回學習模式再加強的詞彙。",
        "see_test_result": "查看檢測結果",
        "view_statistics": "統計數據",
        "result_label": "結果",
        "getting_started": "起步中",
        "test_result_lede": "你在這次程度檢測中答對了 {score} 題。根據結果，系統會建議你下一步適合從哪一組詞彙開始。",
        "test_history_title": "測驗紀錄",
        "test_history_lede": "回看你過往的程度檢測結果，比較分數，看看建議起始範圍如何隨時間變化。",
        "test_history_empty": "你還未完成任何程度檢測。先做第一次測驗，這裡就會開始累積紀錄。",
        "legacy_test_result": "舊版部分紀錄",
        "legacy_test_result_note": "這筆較舊結果是在目前 100 題程度測驗格式前保存，因此不會納入主要統計。",
        "report_question": "回報題目",
        "report_question_note": "如果定義、例句、相近詞、相反詞或錯誤選項不自然，可以先標記起來。",
        "feedback_reason_wrong_definition": "定義有誤",
        "feedback_reason_bad_sentence": "例句不自然",
        "feedback_reason_too_easy": "太容易",
        "feedback_reason_ambiguous": "有歧義",
        "feedback_reason_bad_distractor": "錯誤選項不好",
        "feedback_comment_placeholder": "補充說明，可留空",
        "send_feedback": "送出回報",
        "quality_feedback_title": "題目回報",
        "quality_feedback_empty": "目前沒有被回報的題目。",
        "quality_feedback_lede": "檢查被標記為錯誤、太簡單、有歧義或不自然的 Level Test 題目。",
        "quality_feedback_open": "待處理",
        "quality_feedback_reviewed": "已檢查",
        "mark_reviewed": "標記已檢查",
        "repair_content": "修正內容",
        "save_repair": "保存修正",
        "antonyms_label": "相反詞",
        "one_antonym_per_line": "每行一個相反詞",
        "start_review_session": "開始複習",
        "due_for_review": "到期複習",
        "next_review": "下次複習",
        "completed_on": "完成時間",
        "score_label": "分數",
        "accuracy_short": "正確率",
        "statistics_title": "統計數據",
        "statistics_lede": "把目前累積的學習資料集中在同一頁，再進入你想細看的統計功能。",
        "statistics_latest_test": "最近一次測驗",
        "statistics_best_result": "最佳結果",
        "statistics_tests_taken": "測驗次數",
        "statistics_no_test_yet": "尚未有測驗紀錄",
        "statistics_score_trend": "分數趨勢",
        "statistics_recent_tests": "最近幾次測驗",
        "statistics_out_of": "滿分",
        "statistics_test_history_title": "測驗紀錄",
        "statistics_test_history_body": "回看過往程度檢測結果，比較分數，追蹤建議起始範圍如何變化。",
        "statistics_level_test_section": "Level Test 結果",
        "statistics_learning_section": "Learning Session 結果",
        "statistics_latest_report": "最近完整報告",
        "statistics_latest_report_body": "查看完整報告，包括程度結果、題型分析和不同詞彙分類的表現。",
        "statistics_no_learning_yet": "尚未有學習紀錄",
        "statistics_latest_learning": "最近一次學習",
        "statistics_best_learning": "最佳學習結果",
        "statistics_learning_runs": "學習次數",
        "view_full_report": "查看完整報告",
        "view_learning_result": "查看學習結果",
        "statistics_more_coming": "之後會再加入更多統計模組。",
        "bulk_import_tools": "匯入工具",
        "bulk_import_tools_note": "把工作簿上傳、taxonomy 匯入與 AI 補全整理到較低調的管理入口。",
        "open_bulk_import": "開啟批次匯入",
        "estimated_band_chip": "建議起點：{band}",
        "correct_chip": "答對：{score}",
        "total_questions_chip": "總題數：{total}",
        "accuracy_chip": "正確率：{percent}%",
        "weighted_chip": "加權：{percent}%",
        "test_result_note": "這個結果不只看總分，也會一起參考你在較難詞彙上的表現。",
        "what_to_do_next": "接下來可以：",
        "band_breakdown": "各組表現",
        "band_performance": "你在不同詞彙分類的表現",
        "band_accuracy_note": "這一組詞彙的正確率是 {percent}%。",
        "test_result_saved_summary_note": "這是先前保存的歷史測驗結果。較舊的測驗紀錄未保留完整題目明細，所以這裡只顯示摘要結果。",
        "complete_report_title": "完整程度檢測報告",
        "complete_report_lede": "用這份報告判斷你的弱點是在中文意思、英文定義、例句應用、相近詞，還是相反詞。",
        "layer_breakdown": "五層題型分析",
        "layer_performance": "各題型層表現",
        "strongest_layer": "最強題型",
        "weakest_layer": "優先複習題型",
        "word_report": "逐詞報告",
        "word_report_note": "每一列顯示一個詞在五層題型中的表現。",
        "tested_word": "測驗詞彙",
        "layer_score": "題型分數",
        "meaning_snapshot": "意思摘要",
        "correct_mark": "答對",
        "wrong_mark": "待複習",
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
        "hero_chart_label": "DSE 詞彙概況",
        "hero_chart_title": "你的 DSE 詞彙分級",
        "hero_chart_note": "快速看看 DSE 學生詞彙在不同學習分級中的分布情況。",
        "hero_chart_total": "總詞彙數",
        "hero_chart_bands": "DSE 詞彙分級",
        "nav_ai_power": "AI 指令詞庫",
        "ai_power_label": "新詞彙軌道",
        "ai_power_title": "AI 與專業高價值詞彙",
        "ai_power_lede": "這是一條獨立於 Economist 頻率分類之外的新路線，專為想提升提示能力、商務英語與精準表達的成人與專業人士設計。",
        "ai_power_open": "打開 AI 指令詞庫",
        "ai_power_target": "500 詞路線圖",
        "ai_power_categories": "核心分類",
        "ai_power_starter": "起始種子詞",
        "ai_power_progress": "AI Power Level",
        "ai_power_structure_title": "每張詞卡應包含的內容",
        "ai_power_structure_lede": "這條詞彙軌道不混入 Economist 頻率分類，而是直接對應真實工作與 AI 使用場景。",
        "ai_power_item_english": "英文詞彙",
        "ai_power_item_trad": "繁體中文",
        "ai_power_item_simp": "簡體中文",
        "ai_power_item_sentence": "一般例句",
        "ai_power_item_prompt": "AI 提示範例",
        "ai_power_category_terms": "{count} 個起始詞",
        "ai_power_home_title": "建立第二條 AI 與專業應用詞彙軌道",
        "ai_power_home_note": "保留頻率式詞彙學習，再另外建立一條面向提示、會議、寫作與決策的 AI 詞彙路線。",
        "ai_power_category_cta": "分類重點",
        "ai_power_examples_title": "這條路線的差異",
        "ai_power_examples_lede": "每個分類都同時提供一般用法與 AI 用法，讓詞彙不是只會背，而是能立刻用。",
        "ai_power_template_title": "AI Power 匯入模板",
        "ai_power_template_lede": "下載已預填分類與起始詞的 Excel，之後可批量補上繁中、簡中、一般例句，以及 5 個 AI 提示使用情境。",
        "ai_power_download_template": "下載 Excel 模板",
        "ai_power_template_note": "建議欄位：英文、繁體中文、簡體中文、一般例句、通用 AI 提示範例、5 個情境化 AI 提示欄位，以及備註。",
        "ai_power_upload_title": "上傳已完成的 AI Power 檔案",
        "ai_power_upload_button": "匯入 AI Power 檔案",
        "ai_power_upload_success": "匯入完成，已更新 {count} 筆 AI Power 詞彙。",
        "ai_power_search_title": "快速找出 AI Power 詞彙",
        "ai_power_search_placeholder": "搜尋英文、中文、詞性、IPA 或英文定義",
        "ai_power_category_all": "全部分類",
        "ai_power_results": "目前顯示 {count} 個分類",
        "ai_power_open_category": "打開分類",
        "ai_power_words_ready": "已補齊 {count} 個詞",
        "ai_power_back": "返回 AI 指令詞庫",
        "ai_power_all_words": "此分類全部詞彙",
        "ai_power_prompt_usage": "提示用法",
        "ai_power_normal_usage": "一般用法",
        "ai_power_back_category": "返回分類",
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
        "brand_title": "VocabLab AI",
        "brand_subtitle": "个人词汇学习系统",
        "nav_dashboard": "首页总览",
        "nav_test": "程度检测",
        "nav_learning": "学习练习",
        "nav_learning_sidebar": "学习练习",
        "nav_dictionary": "词典查询",
        "nav_business_vocab": "商务词汇",
        "nav_missed": "错题复习",
        "nav_bulk": "批量导入",
        "nav_statistics": "统计数据",
        "nav_teacher": "教师",
        "nav_admin": "Admin",
        "sidebar_flow_label": "学习流程",
        "sidebar_flow_title": "先检测，再练习，再复习。",
        "sidebar_flow_text": "先用程度检测找出适合的词汇范围，再逐步补齐每张词汇卡的内容。",
        "sidebar_flow_link": "前往学习",
        "topbar_search": "搜索词汇、分类或定义...",
        "topbar_project": "VocabLab AI 词汇项目",
        "home_eyebrow": "首页总览",
        "home_title": "Lawrence，你好。",
        "home_lede": "把你的词汇整理成清晰的每日学习流程：检测、练习、复习。",
        "onboarding_step_1": "第 1 步",
        "onboarding_step_2": "第 2 步",
        "onboarding_title": "欢迎来到 VocabLab AI",
        "onboarding_lede": "先让我们把你的学习体验调整得更贴近你。",
        "landing_hero_kicker": "面向长期成长的 AI 词汇系统",
        "landing_hero_title": "让你的词汇能力能一路带进校园、职场与 AI 应用场景。",
        "landing_hero_body": "把测验、学习、笔记与复习整理成同一张可持续成长的知识图谱，不必每到新阶段就重新开始。",
        "landing_feature_identity_title": "同一个学习身份",
        "landing_feature_identity_body": "把你的名字、角色与词汇成长路径整理在同一个地方。",
        "landing_feature_memory_title": "长期学习记忆",
        "landing_feature_memory_body": "把笔记、错题与复习记录沉淀成你的学习资产。",
        "landing_feature_transfer_title": "可携式成长记录",
        "landing_feature_transfer_body": "让知识护照陪你从校园延伸到职场。",
        "landing_passport_label": "知识护照",
        "landing_passport_title": "你的词汇、笔记与进步记录，都会成为可携式的长期学习资产。",
        "landing_passport_point_1": "程度测验、学习练习与个人笔记会彼此串接。",
        "landing_passport_point_2": "未来能把过去的弱点词放进新的场景再次复习。",
        "landing_passport_point_3": "同一张词汇知识图谱会持续累积，而不是每次重新开始。",
        "onboarding_name_label": "名字",
        "onboarding_name_hint": "可选填。如果你愿意，我们会用名字让首页更有个人感。",
        "onboarding_name_placeholder": "你的名字",
        "onboarding_role_title": "你目前是哪一类使用者？",
        "onboarding_role_lede": "请选择最符合你的角色，我们会立刻调整首页和推荐内容。",
        "onboarding_submit": "进入我的个性化首页",
        "landing_mode_guest": "单次使用者",
        "landing_mode_registered": "注册用户",
        "landing_guest_title": "不需账号，直接开始",
        "landing_guest_lede": "沿用目前的一次性设置，选择角色后就能直接进入首页。",
        "landing_registered_title": "建立你的知识护照（Build Your Knowledge Passport）",
        "landing_registered_lede": "当离开学校继续进修或进入职场时，你可以将知识图谱导出到个人账号，这些数据、笔记、资料会成为你的知识护照，方便日后在任何场景应用。",
        "signup_title": "创建账号",
        "signup_name_label": "显示名称",
        "signup_name_placeholder": "你的名字",
        "signup_email_label": "电子邮件",
        "signup_email_placeholder": "you@example.com",
        "signup_password_label": "密码",
        "signup_password_placeholder": "创建密码",
        "signup_confirm_password_label": "确认密码",
        "signup_confirm_password_placeholder": "再次输入密码",
        "signup_submit": "注册",
        "login_title": "登录账号",
        "login_email_label": "电子邮件",
        "login_password_label": "密码",
        "login_submit": "登录",
        "auth_or": "或",
        "auth_logout": "登出",
        "auth_error_email_taken": "这个电子邮件已经注册过了。",
        "auth_error_invalid_login": "电子邮件或密码不正确。",
        "auth_error_password_short": "密码至少需要 8 个字符。",
        "auth_error_password_mismatch": "两次输入的密码不一致。",
        "auth_error_name_required": "请填写显示名称。",
        "auth_error_email_required": "请输入有效的电子邮件。",
        "auth_error_teacher_invite_required": "Teacher 账户需要有效的老师邀请码。",
        "teacher_invite_code": "老师邀请码",
        "teacher_invite_code_note": "只有注册或切换为 Teacher / Educator 时才需要填写。",
        "nav_account": "账户",
        "account_title": "账户设置",
        "account_lede": "管理你的个人资料、学习角色与密码。",
        "account_profile": "个人资料",
        "account_email": "电子邮件",
        "account_persona": "学习角色",
        "account_save_profile": "保存个人资料",
        "account_password": "密码",
        "current_password": "当前密码",
        "new_password": "新密码",
        "change_password": "修改密码",
        "account_profile_saved": "个人资料已更新。",
        "account_password_saved": "密码已更新。",
        "account_error_password_current": "当前密码不正确。",
        "account_login_required": "请先登录才能管理账户。",
        "account_join_class": "加入班级",
        "account_join_class_note": "输入老师提供的邀请码，把你的学习记录连到班级。",
        "class_invite_code": "邀请码",
        "class_join_submit": "加入班级",
        "class_joined": "已加入班级。",
        "class_join_error": "找不到这个班级邀请码。",
        "teacher_dashboard_title": "教师 Dashboard",
        "teacher_dashboard_lede": "建立班级、分享邀请码，开始追踪学生的学习记录。",
        "teacher_create_class": "建立班级",
        "teacher_class_name": "班级名称",
        "teacher_class_name_placeholder": "Grade 10 Economist Reading",
        "teacher_create_class_submit": "建立班级",
        "teacher_my_classes": "我的班级",
        "teacher_no_classes": "目前还没有班级。先建立第一个班级，系统会生成邀请码。",
        "teacher_students": "学生",
        "teacher_student_name": "学生",
        "teacher_student_email": "Email",
        "teacher_joined_at": "加入时间",
        "teacher_no_students": "暂时没有学生加入。",
        "teacher_only": "请先把账户角色切换成 Teacher / Educator，才能使用这个页面。",
        "teacher_class_snapshot": "班级总览",
        "teacher_active_students": "活跃学生",
        "teacher_avg_level_score": "平均程度分",
        "teacher_avg_learning_accuracy": "平均练习准确率",
        "teacher_learning_completed": "完成练习",
        "teacher_at_risk_students": "需关注学生",
        "teacher_weakest_type": "最弱题型",
        "teacher_student_progress": "学生进度",
        "teacher_latest_test": "最近检测",
        "teacher_recommended_band": "建议 Band",
        "teacher_learning_accuracy": "练习准确率",
        "teacher_learning_sessions": "练习次数",
        "teacher_weak_area": "弱项",
        "teacher_last_active": "最后活跃",
        "teacher_risk": "风险",
        "teacher_recommendations": "建议行动",
        "teacher_no_recommendations": "暂时没有急需处理的事项，可以按目前学习节奏继续。",
        "teacher_recommend_inactive": "{count} 位学生近期没有活跃。建议发提醒或派一份短复习。",
        "teacher_recommend_accuracy": "{count} 位学生准确率低于 60%。建议派较低 band 的 revision set。",
        "teacher_recommend_weak_type": "全班最弱题型是 {question_type}。建议建立针对这一层的练习。",
        "teacher_create_assignment": "指派练习",
        "teacher_assignment_title": "练习标题",
        "teacher_assignment_title_placeholder": "本周 Band 3 revision",
        "teacher_assignment_class": "班级",
        "teacher_assignment_band": "词汇 Band",
        "teacher_assignment_due": "截止日期",
        "teacher_create_assignment_submit": "建立指派",
        "teacher_assignments": "已派练习",
        "teacher_no_assignments": "目前还没有指派练习。",
        "teacher_assignment_completion": "完成率",
        "teacher_assignment_avg_score": "平均分",
        "teacher_assignment_created": "已建立指派练习。",
        "teacher_assignment_type": "练习类型",
        "assignment_type_band_practice": "Band 练习",
        "assignment_type_weak_review": "弱词复习",
        "assignment_type_deep_learning": "深度学习",
        "teacher_total_classes": "班级",
        "teacher_total_students": "学生",
        "teacher_open_assignments": "进行中指派",
        "teacher_class_report": "导出班级报告",
        "teacher_class_code_hint": "学生可在账户设置输入此邀请码加入班级。",
        "teacher_student_action": "下一步",
        "teacher_action_retest": "请这位学生先完成 DSE 程度测试。",
        "teacher_action_review": "指派 {question_type} 针对练习。",
        "teacher_action_remind": "先发提醒，再派一份短复习。",
        "teacher_action_extend": "可安排更高 Band 的练习。",
        "admin_dashboard_title": "Admin Dashboard",
        "admin_dashboard_lede": "总览整个 VocabLab AI 系统：用户、每日使用量、程度测试、学习练习和深度学习活动。",
        "admin_only": "这个 dashboard 只供系统管理员使用。",
        "admin_system_snapshot": "系统总览",
        "admin_total_users": "总用户",
        "admin_students": "学生",
        "admin_teachers": "老师",
        "admin_total_classes": "班级",
        "admin_today_active_users": "今日活跃",
        "admin_7day_active_users": "7 日活跃",
        "admin_today_tests": "今日检测",
        "admin_today_learning": "今日学习",
        "admin_today_deep_learning": "今日深度学习",
        "admin_daily_usage": "每日使用量",
        "admin_user_overview": "用户总览",
        "admin_user": "用户",
        "admin_role": "角色",
        "admin_joined": "加入",
        "admin_last_active": "最后活跃",
        "admin_tests": "检测",
        "admin_learning": "学习",
        "admin_deep_learning": "深度学习",
        "admin_no_users": "暂时没有注册用户。",
        "admin_date": "日期",
        "admin_active_users": "活跃用户",
        "admin_level_tests": "程度检测",
        "admin_learning_sessions": "学习练习",
        "admin_mastery_attempts": "深度学习次数",
        "assigned_practice": "老师指派练习",
        "assigned_practice_note": "以下是老师指派给你的练习。",
        "start_assignment": "开始练习",
        "due_label": "截止",
        "risk_low": "低",
        "risk_medium": "中",
        "risk_high": "高",
        "not_enough_data": "资料不足",
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
        "classroom": "班级",
        "study_flow": "学习流程",
        "goal_note": "先做程度检测，再练习建议的词汇范围，最后查看错题或进入词典补充内容。",
        "start_test": "开始程度检测",
        "continue_learning": "继续学习",
        "student_today_plan": "今日学习任务",
        "student_today_plan_note": "按顺序完成以下任务。系统会保存进度，并指引你下一步最值得做什么。",
        "first_login_action": "开始 DSE 程度检测",
        "first_login_action_note": "先从这里开始，VocabLab 才能建议最适合你的 DSE 词汇分级。",
        "resume_level_test_action": "继续上次未完成检测",
        "resume_learning_action": "继续上次未完成练习",
        "daily_task_action": "今日 10 个词学习练习",
        "review_weak_words_action": "复习薄弱词汇",
        "deep_learning_three_action": "深度学习 3 个词",
        "recommended_path_title": "建议学习路径",
        "recommended_path_body": "建议你由 {band} 开始。",
        "completed_words_this_session": "本次完成词汇",
        "words_need_review": "需要重温的词汇",
        "review_mistakes": "重练错题",
        "start_next_10_words": "开始下一组 10 个词",
        "statistics_advice_title": "学习建议",
        "statistics_advice_no_test": "先完成 DSE 程度检测，系统才能建议你的起始分级。",
        "statistics_advice_no_learning": "下一步建议做一轮建议 DSE 分级的 10 个词学习练习。",
        "statistics_advice_weak_layer": "你目前较弱的是 {layer}，今天建议集中练习这类题型。",
        "statistics_advice_good": "最近结果稳定。可以继续下一组 10 个词，并为薄弱词汇完成深度学习。",
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
        "frequency_bands": "DSE 词汇分级",
        "browse_count": "按 DSE 学习程度浏览",
        "open_dictionary": "打开词典",
        "bands_note": "这些分级根据 DSE 学习程度、考试实用性和学术词汇优先次序整理，并不是根据《经济学人》出现频率。",
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
        "ai_insight_section": "AI 重点提示",
        "ai_insight_title": "用更聪明的方式理解这个词",
        "ai_explain_simply": "简单理解",
        "ai_nuance_comparison": "语感与比较",
        "ai_use_it_better": "更好地用出来",
        "ai_simple_explanation_zh": "中文解释",
        "ai_business_example_label": "商务例句",
        "ai_prompt_example_label": "AI 提示范例",
        "ai_usage_warning_label": "使用提醒",
        "ai_nuance_note_label": "语感说明",
        "ai_compare_words_label": "比较词",
        "ai_compare_words_hint": "每行一笔：词汇 | 说明",
        "ai_simple_explanation_zh_placeholder": "加入一段简短中文解释",
        "ai_nuance_note_placeholder": "说明这个词和相近词的语感差异",
        "ai_business_example_placeholder": "加入一句商务场景例句",
        "ai_prompt_example_placeholder": "加入一句 AI 提示范例",
        "ai_usage_warning_placeholder": "加入一句简短使用提醒",
        "no_ai_insight": "尚未加入 AI 重点提示。",
        "generate_ai_insight": "生成 AI 重点提示",
        "ai_insight_generate_note": "使用 OpenAI 为这个词草拟简单解释、语感比较、商务例句与 AI 提示范例。",
        "ai_insight_generated": "AI 重点提示已生成。",
        "ai_insight_error": "AI 重点提示生成失败",
        "word_mastery_tab": "深度学习",
        "word_mastery_section": "深度学习",
        "word_mastery_title": "读出、用出、真正掌握这个词",
        "word_mastery_lede": "读出单词，再写一句句子，让 AI 检查你的发音、用法和语法是否已适合真实考试情境。",
        "mastery_pronunciation_title": "1. 发音练习",
        "mastery_sentence_title": "2. 句子应用",
        "mastery_record_note": "你的练习结果会保存到学习记录。",
        "mastery_record_button": "录下我的发音",
        "mastery_stop_button": "停止并检查",
        "mastery_retry_button": "重新录音",
        "mastery_check_sentence": "用 AI 检查",
        "mastery_sentence_placeholder": "用这个词写一句句子。",
        "mastery_latest_result": "最近一次深度练习",
        "mastery_no_attempt": "尚未保存深度练习结果。",
        "mastery_transcript": "AI 听到",
        "mastery_feedback": "AI 反馈",
        "mastery_corrected_sentence": "修正版句子",
        "mastery_suggested_upgrade": "升级版句子",
        "mastery_score": "分数",
        "mastery_status": "状态",
        "mastery_api_not_ready": "AI 检查尚未设置。",
        "mastery_progress_section": "学习进度",
        "mastery_progress_title": "词汇掌握阶梯",
        "mastery_progress_lede": "通过五层题型代表完成测验掌握；真正 100% 掌握需要完成发音、句子应用与复习。",
        "mastery_progress_percent": "完成度 {percent}%",
        "mastery_progress_not_started": "未开始",
        "mastery_progress_seen": "已看过",
        "mastery_progress_learning": "学习中",
        "mastery_progress_practicing": "练习中",
        "mastery_progress_tested": "已通过测验",
        "mastery_progress_deep_learning": "深度学习中",
        "mastery_progress_mastered": "已掌握",
        "mastery_progress_exposure": "已打开",
        "mastery_progress_test_layers": "五层题型",
        "mastery_progress_pronunciation": "发音",
        "mastery_progress_writing": "AI 用法",
        "mastery_progress_review": "复习",
        "mastery_progress_average": "平均进度",
        "mastery_progress_mastered_count": "{count} 个已掌握",
        "mastery_next_step": "下一步",
        "mastery_next_start": "打开这个词，先开始五层题型检测。",
        "mastery_next_continue_test": "完成尚未通过的五层题型。",
        "mastery_next_deep": "完成发音和 AI 句子应用，从「已通过检测」进入深度学习。",
        "mastery_next_review": "再复习一次这个词，就可以达到 100% 掌握。",
        "mastery_next_complete": "已完整掌握。之后保留在长期复习中即可。",
        "mastery_list_hint": "每张词卡都会显示目前掌握阶段和仍未完成的步骤。",
        "mastery_stage_exposure": "接触",
        "mastery_stage_test": "五层题型",
        "mastery_stage_deep": "深度学习",
        "mastery_stage_review": "复习",
        "mastery_recording_unsupported": "这个浏览器不支持录音。",
        "mastery_recording": "录音中...",
        "mastery_checking": "检查中...",
        "mastery_sentence_required": "请先写一句句子。",
        "dse_exam_use_section": "DSE 考试应用",
        "dse_exam_use_title": "这个词在 DSE English 怎样使用",
        "dse_exam_use_lede": "重点看它如何帮助 Paper 1 阅读、Paper 2 写作和 Paper 4 Speaking。",
        "dse_paper_fit": "最适合的 DSE 卷别",
        "dse_topic_fit": "常见题材",
        "dse_writing_move": "写作用途",
        "dse_sample_sentence": "DSE 风格例句",
        "dse_common_mistake": "常见错误",
        "dse_next_practice": "下一步练习",
        "dse_next_practice_text": "在下面写一句 DSE Paper 2 句子，再用深度学习检查用法和语法。",
        "progression_section": "进阶路径",
        "vocabulary_progression": "词汇进阶路径",
        "meaning_family": "核心语义群组",
        "current_stage_label": "目前阶段",
        "next_step_label": "下一步建议",
        "cluster_domain_label": "主题领域",
        "cluster_path_label": "成长路径",
        "progression_attributes": "进阶属性",
        "formality_level_label": "正式程度",
        "precision_level_label": "精准程度",
        "exam_relevance_label": "考试相关度",
        "business_relevance_label": "商务相关度",
        "ai_relevance_label": "AI 指令相关度",
        "productivity_likelihood_label": "主动产出机率",
        "usage_notes_label": "使用说明",
        "register_notes_label": "语域提醒",
        "no_progression_data": "尚未加入词汇进阶路径。",
        "no_usage_note": "尚未加入使用说明。",
        "stage_fallback": "一般阶段",
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
        "learning_hero_lede": "每次练习都会从你的词汇库出题。你补得越完整，之后的题目就会越实用、越不重复。",
        "recommended_learning_band": "建议学习分类",
        "choose_learning_band": "选择词汇分类",
        "learning_band_note": "系统会根据最近一次 Level Test 建议起点，但你也可以自由选择任何一组。",
        "learning_session_structure": "每轮固定同一个 band 的 10 个词汇，每个词用 5 层题型练习。",
        "recommended_badge": "建议",
        "latest_label": "最近",
        "ready_label": "准备好了",
        "most_recent_session": "最近一次练习",
        "start_new_session_note": "开始新的练习",
        "session_goal": "这一轮要做什么",
        "build_consistency": "先把基础答稳",
        "definition_short": "定义",
        "synonym_short": "同义词",
        "sentence_short": "例句",
        "definition_available_note": "每轮会使用和 Level Test 一样的五层题型：中文意思、英文定义、例句应用、相近词与相反词。",
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
        "review_after_answer": "每个词后复习",
        "review_after_answer_note": "先完成同一个词的五层题型，再看这个词的得分与完整细节。",
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
        "learning_word_performance": "词汇表现",
        "learning_word_performance_note": "查看每个词的分数，以及哪一层题型需要再加强。",
        "learning_question_review": "题目回顾",
        "learning_question_review_note": "在这里逐题核对你的答案和正确答案。",
        "score_out_of": "分数：{score}/{total}",
        "result_status": "结果",
        "prompt_label": "题目",
        "level_test_title": "程度检测",
        "find_starting_band": "找出适合你的词汇程度。",
        "test_intro_lede": "这个程度检测共 {count} 分：20 个词汇、每个 band 4 个，并通过中文意思、英文定义、例句应用、相近词与相反词 5 层题型评估。",
        "questions_label": "题目数",
        "definition_based_items": "以定义为主的题目",
        "what_it_measures": "这份检测在看什么",
        "foundation_across_bands": "看看你对不同层次词汇的掌握",
        "frequency_short": "DSE 分级",
        "recognition_short": "识别",
        "placement_short": "定位",
        "test_goal_note": "Level Test 是固定评量，和 Learning 分开。它会横跨五个 band 测你的广度，满分 100。",
        "begin_test": "开始检测",
        "continue_test": "继续检测",
        "start_new_test": "重新开始检测",
        "saved_incomplete_test": "已保存的未完成检测",
        "resume_test_note": "你已完成 {answered}/{total} 题（{percent}%）。可以从上次中断的位置继续。",
        "band_coverage": "出题范围",
        "sampled_ranges": "抽样分类",
        "what_this_means": "这代表什么",
        "sampled_from_band": "{range} 是 DSE 学生学习分级，根据 DSE 程度、考试实用性和学术词汇优先次序整理，并不是根据《经济学人》出现频率。",
        "goal_label": "目标",
        "test_goal_fast": "每个词会出现五层题型：中文意思、英文定义、例句应用、相近英文词与相反英文词。",
        "hidden_test_note": "在你提交答案前，完整定义、用法线索和词汇细节都不会先显示，这样结果才更准确。",
        "meaning_and_usage_items": "5 层题型 / 100 分",
        "recognized_correctly": "你正确辨认了这个词汇。",
        "word_round_complete": "这个词已完成",
        "word_round_score": "这个词的分数",
        "word_round_score_note": "你已完成这个词的五层题型。详细答案会在最后完整报告中显示。",
        "revisit_later_note": "这是之后很适合放回学习模式再加强的词汇。",
        "see_test_result": "查看检测结果",
        "view_statistics": "统计数据",
        "result_label": "结果",
        "getting_started": "起步中",
        "test_result_lede": "你在这次程度检测中答对了 {score} 题。根据结果，系统会建议你下一步适合从哪一组词汇开始。",
        "test_history_title": "检测记录",
        "test_history_lede": "回看你过往的程度检测结果，比较分数，看看建议起始范围如何随时间变化。",
        "test_history_empty": "你还未完成任何程度检测。先做第一次检测，这里就会开始积累记录。",
        "legacy_test_result": "旧版部分记录",
        "legacy_test_result_note": "这笔较旧结果是在目前 100 题程度检测格式前保存，因此不会纳入主要统计。",
        "report_question": "回报题目",
        "report_question_note": "如果定义、例句、相近词、相反词或错误选项不自然，可以先标记起来。",
        "feedback_reason_wrong_definition": "定义有误",
        "feedback_reason_bad_sentence": "例句不自然",
        "feedback_reason_too_easy": "太容易",
        "feedback_reason_ambiguous": "有歧义",
        "feedback_reason_bad_distractor": "错误选项不好",
        "feedback_comment_placeholder": "补充说明，可留空",
        "send_feedback": "送出回报",
        "quality_feedback_title": "题目回报",
        "quality_feedback_empty": "目前没有被回报的题目。",
        "quality_feedback_lede": "检查被标记为错误、太简单、有歧义或不自然的 Level Test 题目。",
        "quality_feedback_open": "待处理",
        "quality_feedback_reviewed": "已检查",
        "mark_reviewed": "标记已检查",
        "repair_content": "修正内容",
        "save_repair": "保存修正",
        "antonyms_label": "相反词",
        "one_antonym_per_line": "每行一个相反词",
        "start_review_session": "开始复习",
        "due_for_review": "到期复习",
        "next_review": "下次复习",
        "completed_on": "完成时间",
        "score_label": "分数",
        "accuracy_short": "正确率",
        "statistics_title": "统计数据",
        "statistics_lede": "把目前积累的学习资料集中在同一页，再进入你想细看的统计功能。",
        "statistics_latest_test": "最近一次检测",
        "statistics_best_result": "最佳结果",
        "statistics_tests_taken": "检测次数",
        "statistics_no_test_yet": "尚未有检测记录",
        "statistics_score_trend": "分数趋势",
        "statistics_recent_tests": "最近几次检测",
        "statistics_out_of": "满分",
        "statistics_test_history_title": "检测记录",
        "statistics_test_history_body": "回看过往程度检测结果，比较分数，追踪建议起始范围如何变化。",
        "statistics_level_test_section": "Level Test 结果",
        "statistics_learning_section": "Learning Session 结果",
        "statistics_latest_report": "最近完整报告",
        "statistics_latest_report_body": "查看完整报告，包括程度结果、题型分析和不同词汇分类的表现。",
        "statistics_no_learning_yet": "尚未有学习记录",
        "statistics_latest_learning": "最近一次学习",
        "statistics_best_learning": "最佳学习结果",
        "statistics_learning_runs": "学习次数",
        "view_full_report": "查看完整报告",
        "view_learning_result": "查看学习结果",
        "statistics_more_coming": "之后会再加入更多统计模块。",
        "bulk_import_tools": "导入工具",
        "bulk_import_tools_note": "把工作簿上传、taxonomy 导入与 AI 补全整理到较低调的管理入口。",
        "open_bulk_import": "打开批量导入",
        "estimated_band_chip": "建议起点：{band}",
        "correct_chip": "答对：{score}",
        "total_questions_chip": "总题数：{total}",
        "accuracy_chip": "正确率：{percent}%",
        "weighted_chip": "加权：{percent}%",
        "test_result_note": "这个结果不只看总分，也会一起参考你在较难词汇上的表现。",
        "what_to_do_next": "接下来可以：",
        "band_breakdown": "各组表现",
        "band_performance": "你在不同词汇分类的表现",
        "band_accuracy_note": "这一组词汇的正确率是 {percent}%。",
        "test_result_saved_summary_note": "这是先前保存的历史检测结果。较旧的检测记录未保留完整题目明细，所以这里只显示摘要结果。",
        "complete_report_title": "完整程度检测报告",
        "complete_report_lede": "用这份报告判断你的弱点是在中文意思、英文定义、例句应用、相近词，还是相反词。",
        "layer_breakdown": "五层题型分析",
        "layer_performance": "各题型层表现",
        "strongest_layer": "最强题型",
        "weakest_layer": "优先复习题型",
        "word_report": "逐词报告",
        "word_report_note": "每一行显示一个词在五层题型中的表现。",
        "tested_word": "检测词汇",
        "layer_score": "题型分数",
        "meaning_snapshot": "意思摘要",
        "correct_mark": "答对",
        "wrong_mark": "待复习",
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
        "hero_chart_label": "DSE 词汇概况",
        "hero_chart_title": "你的 DSE 词汇分级",
        "hero_chart_note": "快速看看 DSE 学生词汇在不同学习分级中的分布情况。",
        "hero_chart_total": "总词汇数",
        "hero_chart_bands": "DSE 词汇分级",
        "nav_ai_power": "AI 指令词库",
        "ai_power_label": "新词汇路线",
        "ai_power_title": "AI 与专业高价值词汇",
        "ai_power_lede": "这是一条独立于 Economist 频率分类之外的新路线，专为想提升提示能力、商务英语与精准表达的成人与专业人士设计。",
        "ai_power_open": "打开 AI 指令词库",
        "ai_power_target": "500 词路线图",
        "ai_power_categories": "核心分类",
        "ai_power_starter": "起始种子词",
        "ai_power_progress": "AI Power Level",
        "ai_power_structure_title": "每张词卡应包含的内容",
        "ai_power_structure_lede": "这条词汇路线不混入 Economist 频率分类，而是直接对应真实工作与 AI 使用场景。",
        "ai_power_item_english": "英文词汇",
        "ai_power_item_trad": "繁体中文",
        "ai_power_item_simp": "简体中文",
        "ai_power_item_sentence": "一般例句",
        "ai_power_item_prompt": "AI 提示范例",
        "ai_power_category_terms": "{count} 个起始词",
        "ai_power_home_title": "建立第二条 AI 与专业应用词汇路线",
        "ai_power_home_note": "保留频率式词汇学习，再另外建立一条面向提示、会议、写作与决策的 AI 词汇路线。",
        "ai_power_category_cta": "分类重点",
        "ai_power_examples_title": "这条路线的差异",
        "ai_power_examples_lede": "每个分类都同时提供一般用法与 AI 用法，让词汇不是只会背，而是能立刻用。",
        "ai_power_template_title": "AI Power 导入模板",
        "ai_power_template_lede": "下载已预填分类与起始词的 Excel，之后可批量补上繁中、简中、一般例句与 AI 提示范例。",
        "ai_power_download_template": "下载 Excel 模板",
        "ai_power_template_note": "建议栏位：英文、繁体中文、简体中文、一般例句、AI 提示范例与备注。",
        "ai_power_upload_title": "上传已完成的 AI Power 文件",
        "ai_power_upload_button": "导入 AI Power 文件",
        "ai_power_upload_success": "导入完成，已更新 {count} 笔 AI Power 词汇。",
        "ai_power_search_title": "快速找出 AI Power 词汇",
        "ai_power_search_placeholder": "搜索英文、中文、词性、IPA 或英文定义",
        "ai_power_category_all": "全部分类",
        "ai_power_results": "当前显示 {count} 个分类",
        "ai_power_open_category": "打开分类",
        "ai_power_words_ready": "已补齐 {count} 个词",
        "ai_power_back": "返回 AI 指令词库",
        "ai_power_all_words": "此分类全部词汇",
        "ai_power_prompt_usage": "提示用法",
        "ai_power_normal_usage": "一般用法",
        "ai_power_back_category": "返回分类",
    }
)


def db_conn() -> sqlite3.Connection:
    return get_connection()


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
        "en": {
            "definition": "Definition",
            "synonym": "Synonym",
            "sentence": "Sentence",
            "chinese_definition": "Chinese Definition",
            "english_definition": "English Definition",
            "example_application": "Example Application",
            "similar_word": "Similar Word",
            "opposite_word": "Opposite Word",
        },
        "zh-Hant": {
            "definition": "定義",
            "synonym": "同義詞",
            "sentence": "例句",
            "chinese_definition": "中文意思",
            "english_definition": "英文定義",
            "example_application": "例句應用",
            "similar_word": "相近英文詞",
            "opposite_word": "相反英文詞",
        },
        "zh-Hans": {
            "definition": "定义",
            "synonym": "同义词",
            "sentence": "例句",
            "chinese_definition": "中文意思",
            "english_definition": "英文定义",
            "example_application": "例句应用",
            "similar_word": "相近英文词",
            "opposite_word": "相反英文词",
        },
    }
    return labels.get(lang, labels["en"]).get(value, value)


def question_instruction(value: str, lang: str = "en") -> str:
    labels = {
        "en": {
            "chinese_definition": "Layer 1: select the correct Chinese definition.",
            "english_definition": "Layer 2: select the correct English definition.",
            "example_application": "Layer 3: select the sentence that uses the word correctly.",
            "similar_word": "Layer 4: select the most similar English word.",
            "opposite_word": "Layer 5: select the opposite English word.",
            "definition": "Select the correct definition.",
            "synonym": "Select the closest synonym.",
            "sentence": "Select the sentence where this word fits naturally in the blank.",
        },
        "zh-Hant": {
            "chinese_definition": "第 1 層：選出正確的中文意思。",
            "english_definition": "第 2 層：選出正確的英文定義。",
            "example_application": "第 3 層：選出最能正確運用這個詞的例句。",
            "similar_word": "第 4 層：選出意思最接近的英文詞。",
            "opposite_word": "第 5 層：選出意思相反的英文詞。",
            "definition": "選出正確的定義。",
            "synonym": "選出最接近的同義詞。",
            "sentence": "選出這個詞最自然放入空格的句子。",
        },
        "zh-Hans": {
            "chinese_definition": "第 1 层：选出正确的中文意思。",
            "english_definition": "第 2 层：选出正确的英文定义。",
            "example_application": "第 3 层：选出最能正确运用这个词的例句。",
            "similar_word": "第 4 层：选出意思最接近的英文词。",
            "opposite_word": "第 5 层：选出意思相反的英文词。",
            "definition": "选出正确的定义。",
            "synonym": "选出最接近的同义词。",
            "sentence": "选出这个词最自然放入空格的句子。",
        },
    }
    return labels.get(lang, labels["en"]).get(value, labels.get(lang, labels["en"]).get("definition", value))


def translate_status(value: str, lang: str = "en") -> str:
    labels = {
        "en": {"new": "new", "seen": "seen", "learning": "learning", "review": "review", "mastered": "mastered"},
        "zh-Hant": {"new": "新字", "seen": "已看過", "learning": "學習中", "review": "待複習", "mastered": "已熟悉"},
        "zh-Hans": {"new": "新词", "seen": "已看过", "learning": "学习中", "review": "待复习", "mastered": "已熟悉"},
    }
    return labels.get(lang, labels["en"]).get(value, value)


def translate_relation_type(value: str, lang: str = "en") -> str:
    labels = {
        "en": {
            "level_up": "Level-up suggestions",
            "more_formal": "More formal alternatives",
            "more_precise": "More precise alternatives",
            "more_business": "Business alternatives",
            "more_academic": "Academic alternatives",
            "more_ai": "AI prompt alternatives",
            "related_not_interchangeable": "Related but not interchangeable",
        },
        "zh-Hant": {
            "level_up": "升級建議",
            "more_formal": "更正式的替代詞",
            "more_precise": "更精準的替代詞",
            "more_business": "更適合商務情境",
            "more_academic": "更適合學術情境",
            "more_ai": "更適合 AI 指令",
            "related_not_interchangeable": "相關但不能直接互換",
        },
        "zh-Hans": {
            "level_up": "升级建议",
            "more_formal": "更正式的替代词",
            "more_precise": "更精准的替代词",
            "more_business": "更适合商务情境",
            "more_academic": "更适合学术情境",
            "more_ai": "更适合 AI 指令",
            "related_not_interchangeable": "相关但不能直接互换",
        },
    }
    return labels.get(lang, labels["en"]).get(value, value.replace("_", " ").title())


def build_lang_url(request: Request, lang: str) -> str:
    params = list(request.query_params.multi_items())
    filtered = [(key, value) for key, value in params if key != "lang"]
    filtered.append(("lang", lang))
    query = urlencode(filtered)
    return f"{request.url.path}?{query}" if query else request.url.path


def build_home_url(lang: str) -> str:
    return f"/?lang={lang}" if lang != "en" else "/"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or "$" not in password_hash:
        return False
    salt, expected = password_hash.split("$", 1)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return hmac.compare_digest(actual, expected)


def normalized_email(value: str) -> str:
    return (value or "").strip().lower()[:160]


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value or ""))


def role_for_persona(persona: str) -> str:
    return "teacher" if persona == "teacher" else "student"


def configured_teacher_invite_codes() -> set[str]:
    raw_values = [
        os.environ.get("TEACHER_INVITE_CODE", ""),
        os.environ.get("TEACHER_INVITE_CODES", ""),
    ]
    codes: set[str] = set()
    for raw in raw_values:
        for item in raw.split(","):
            code = re.sub(r"[^A-Z0-9]", "", item.strip().upper())
            if code:
                codes.add(code)
    return codes


def teacher_invite_code_valid(value: str) -> bool:
    code = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return bool(code and code in configured_teacher_invite_codes())


def registered_user_row(request: Request) -> sqlite3.Row | None:
    raw = (request.cookies.get("registered_user_id") or "").strip()
    if not raw.isdigit():
        return None
    conn = db_conn()
    return conn.execute("SELECT * FROM users WHERE id = ?", (int(raw),)).fetchone()


def current_user_id(request: Request) -> int:
    user = registered_user_row(request)
    return int(user["id"]) if user is not None else USER_ID


def is_teacher_user(user: sqlite3.Row | None) -> bool:
    return bool(user and ((user["role"] if "role" in user.keys() else "") == "teacher" or (user["persona"] or "") == "teacher"))


def is_admin_user(user: sqlite3.Row | None) -> bool:
    if user is None:
        return False
    role = (user["role"] if "role" in user.keys() else "") or ""
    if role == "admin":
        return True
    email = ((user["email"] if "email" in user.keys() else "") or "").strip().lower()
    admin_emails = {
        item.strip().lower()
        for item in os.environ.get("ADMIN_EMAILS", "").split(",")
        if item.strip()
    }
    if email and email in admin_emails:
        return True
    return int(user["id"]) == USER_ID


def generate_invite_code(conn: sqlite3.Connection) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if conn.execute("SELECT 1 FROM teacher_classes WHERE invite_code = ?", (code,)).fetchone() is None:
            return code


def get_profile_name(request: Request) -> str:
    user = registered_user_row(request)
    if user is not None:
        display_name = (user["display_name"] or "").strip()
        if display_name:
            return display_name[:40]
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
    user = registered_user_row(request)
    if user is not None:
        persona = (user["persona"] or "").strip()
        if persona in SUPPORTED_PERSONAS:
            return persona
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
            {"tag_key": "classroom", "title_key": "nav_teacher", "body_key": "teacher_dashboard_lede", "href": "/teacher", "class_name": "recommend-card-blue"},
            {"tag_key": "review", "title_key": "nav_dictionary", "body_key": "card_teacher_dictionary", "href": "/dictionary", "class_name": "recommend-card-blue"},
            {"tag_key": "review", "title_key": "nav_missed", "body_key": "card_teacher_review", "href": "/review/missed", "class_name": "recommend-card-pink"},
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
        "2000~": {"title": "基石", "subtitle": "The Foundation", "tone": "foundation"},
        "500~1999": {"title": "深度洞察", "subtitle": "Insight", "tone": "insight"},
        "200~499": {"title": "精準修辭", "subtitle": "Precision", "tone": "precision"},
        "100~199": {"title": "智識擴張", "subtitle": "Intellectual", "tone": "intellectual"},
        "50~99": {"title": "菁英語庫", "subtitle": "The Elite Lexicon", "tone": "elite"},
        "Core DSE Survival": {"title": "核心求生詞庫", "subtitle": "Core DSE Survival", "tone": "foundation"},
        "DSE Standard": {"title": "DSE 標準詞庫", "subtitle": "DSE Standard", "tone": "insight"},
        "DSE High Score": {"title": "DSE 高分詞庫", "subtitle": "DSE High Score", "tone": "precision"},
        "5*/5** Advanced": {"title": "5*/5** 進階詞庫", "subtitle": "5*/5** Advanced", "tone": "intellectual"},
        "Academic Extension": {"title": "學術延伸詞庫", "subtitle": "Academic Extension", "tone": "elite"},
    }
    return identities.get(range_label, {"title": range_label, "subtitle": "", "tone": "default"})


def band_range_from_label(label: str | None) -> str:
    return (label or "").split(" (", 1)[0]


def band_display_identity(label: str | None, lang: str = "en") -> dict[str, str]:
    range_label = band_range_from_label(label)
    identity = hero_band_identity(range_label)
    simplified_titles = {
        "基石": "基石",
        "深度洞察": "深度洞察",
        "精準修辭": "精准修辞",
        "智識擴張": "智识扩张",
        "菁英語庫": "菁英语库",
        "核心求生詞庫": "核心求生词库",
        "DSE 標準詞庫": "DSE 标准词库",
        "DSE 高分詞庫": "DSE 高分词库",
        "5*/5** 進階詞庫": "5*/5** 进阶词库",
        "學術延伸詞庫": "学术延伸词库",
    }
    title = simplified_titles.get(identity["title"], identity["title"]) if lang == "zh-Hans" else identity["title"]
    display_label = f"{identity['subtitle']} / {title}" if identity["subtitle"] else title or (label or "")
    return {
        "raw_label": label or "",
        "range_label": range_label,
        "title": title,
        "subtitle": identity["subtitle"],
        "tone": identity["tone"],
        "display_label": display_label,
    }


def slugify_ai_power_value(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def load_ai_power_entries() -> list[dict[str, str]]:
    if not AI_POWER_DATA_PATH.exists():
        return []
    try:
        return json.loads(AI_POWER_DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_ai_power_entries(rows: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing_rows = load_ai_power_entries()
    merged_map = {
        row["english"].strip().lower(): dict(row)
        for row in existing_rows
        if row.get("english", "").strip()
    }
    order = [
        row["english"].strip().lower()
        for row in existing_rows
        if row.get("english", "").strip()
    ]
    for row in rows:
        key = row.get("english", "").strip().lower()
        if not key:
            continue
        current = merged_map.get(key, {})
        merged = dict(current)
        for field, value in row.items():
            if field == "english" or str(value).strip():
                merged[field] = value
        merged_map[key] = merged
        if key not in order:
            order.append(key)
    merged_rows = [merged_map[key] for key in order if key in merged_map]
    AI_POWER_DATA_PATH.write_text(json.dumps(merged_rows, ensure_ascii=False, indent=2), encoding="utf-8")


def ai_power_track(lang: str = "en") -> dict:
    imported_rows = load_ai_power_entries()
    imported_map = {row["english"].strip().lower(): row for row in imported_rows if row.get("english", "").strip()}
    categories = []
    starter_count = 0
    completed_count = 0
    for item in AI_POWER_TRACK:
        title = item["title"]
        description = item["description"]
        sorted_terms = sorted(item["terms"], key=lambda term: term.lower())
        if lang == "zh-Hant":
            title = item["title_zh_hant"]
            description = item["description_zh_hant"]
        elif lang == "zh-Hans":
            title = item["title_zh_hans"]
            description = item["description_zh_hans"]
        starter_count += len(sorted_terms)
        enriched_terms = []
        for term in sorted_terms:
            entry = imported_map.get(term.strip().lower(), {})
            is_completed = any(
                [
                    entry.get("type_of_word", "").strip(),
                    entry.get("english_definition", "").strip(),
                    entry.get("traditional_chinese", "").strip(),
                    entry.get("simplified_chinese", "").strip(),
                    entry.get("example_sentence", "").strip(),
                    entry.get("ai_prompt_example", "").strip(),
                    entry.get("ipa", "").strip(),
                ]
            )
            if any(
                [is_completed]
            ):
                completed_count += 1
            enriched_terms.append(
                {
                    "english": term,
                    "slug": slugify_ai_power_value(term),
                    "type_of_word": entry.get("type_of_word", ""),
                    "english_definition": entry.get("english_definition", ""),
                    "traditional_chinese": entry.get("traditional_chinese", ""),
                    "simplified_chinese": entry.get("simplified_chinese", ""),
                    "example_sentence": entry.get("example_sentence", ""),
                    "ai_prompt_example": entry.get("ai_prompt_example", ""),
                    "prompt_strategic": entry.get("prompt_strategic", ""),
                    "prompt_creative": entry.get("prompt_creative", ""),
                    "prompt_technical": entry.get("prompt_technical", ""),
                    "prompt_finance": entry.get("prompt_finance", ""),
                    "prompt_education": entry.get("prompt_education", ""),
                    "ipa": entry.get("ipa", ""),
                    "completed": is_completed,
                }
            )

        category_completed_count = sum(1 for entry in enriched_terms if entry["completed"])
        categories.append(
            {
                "slug": item["slug"],
                "title": title,
                "english_title": item["title"],
                "description": description,
                "target_count": item["target_count"],
                "starter_count": len(sorted_terms),
                "terms": sorted_terms,
                "entries": enriched_terms,
                "completed_count": category_completed_count,
                "normal_example": item["normal_example"],
                "prompt_example": item["prompt_example"],
            }
        )
    return {
        "target_count": 500,
        "starter_count": starter_count,
        "category_count": len(categories),
        "progress_label": f"{completed_count} / 500",
        "completed_count": completed_count,
        "categories": categories,
    }


def filter_ai_power_track(track: dict, query: str = "", category_slug: str = "") -> dict:
    normalized_query = query.strip().lower()
    filtered_categories = []
    shown_count = 0

    for category in track["categories"]:
        if category_slug and category["slug"] != category_slug:
            continue

        category_haystack = " ".join(
            [
                category.get("title", ""),
                category.get("english_title", ""),
                category.get("description", ""),
            ]
        ).lower()

        filtered_entries = []
        for entry in category["entries"]:
            haystack = " ".join(
                [
                    entry.get("english", ""),
                    entry.get("type_of_word", ""),
                    entry.get("english_definition", ""),
                    entry.get("traditional_chinese", ""),
                    entry.get("simplified_chinese", ""),
                    entry.get("example_sentence", ""),
                    entry.get("ai_prompt_example", ""),
                    entry.get("ipa", ""),
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            filtered_entries.append(entry)

        if normalized_query and normalized_query in category_haystack:
            category_copy = dict(category)
            category_copy["matched_count"] = len(category["entries"])
            filtered_categories.append(category_copy)
            shown_count += 1
        elif filtered_entries:
            category_copy = dict(category)
            category_copy["matched_count"] = len(filtered_entries)
            filtered_categories.append(category_copy)
            shown_count += 1
        elif not normalized_query and not category_slug:
            filtered_categories.append(category)
            shown_count += 1

    filtered_track = dict(track)
    filtered_track["categories"] = filtered_categories
    filtered_track["shown_count"] = shown_count
    return filtered_track


def ai_power_category_by_slug(track: dict, slug: str) -> dict | None:
    for category in track["categories"]:
        if category["slug"] == slug:
            return category
    return None


def ai_power_entry_by_slug(category: dict, entry_slug: str) -> dict | None:
    for entry in category["entries"]:
        if entry["slug"] == entry_slug:
            return entry
    return None


def ai_prompt_sections(entry: dict, lang: str = "en") -> list[dict[str, str]]:
    word = entry.get("english", "")
    base_prompt = entry.get("ai_prompt_example", "").strip() or f'Use "{word}" naturally in the response.'
    if lang == "zh-Hant":
        return [
            {
                "title": "專業諮詢與管理",
                "subtitle": "Strategic & Professional Services",
                "prompt": entry.get("prompt_strategic", "").strip() or f"{base_prompt} 請同時補上利害關係人、風險、優先順序與下一步建議。",
            },
            {
                "title": "創意與內容行銷",
                "subtitle": "Creative & Marketing Content",
                "prompt": entry.get("prompt_creative", "").strip() or f"{base_prompt} 請把語氣調整得更具吸引力，並加入受眾洞察、主訊息與內容角度。",
            },
            {
                "title": "技術、工程與學術",
                "subtitle": "Technology, Engineering & Research",
                "prompt": entry.get("prompt_technical", "").strip() or f"{base_prompt} 請讓回答更有結構，包含方法、假設、技術細節與驗證方向。",
            },
            {
                "title": "金融、法律與合規",
                "subtitle": "Finance, Legal & Compliance",
                "prompt": entry.get("prompt_finance", "").strip() or f"{base_prompt} 請使用更精準與審慎的語言，並加入風險揭露、合規考量與決策重點。",
            },
            {
                "title": "教育與終身學習",
                "subtitle": "Education & Lifelong Learning",
                "prompt": entry.get("prompt_education", "").strip() or f"{base_prompt} 請用更清楚、可教學的方式說明，並補上步驟、例子與常見誤解。",
            },
        ]
    if lang == "zh-Hans":
        return [
            {
                "title": "专业咨询与管理",
                "subtitle": "Strategic & Professional Services",
                "prompt": entry.get("prompt_strategic", "").strip() or f"{base_prompt} 请同时补上利益相关者、风险、优先顺序与下一步建议。",
            },
            {
                "title": "创意与内容营销",
                "subtitle": "Creative & Marketing Content",
                "prompt": entry.get("prompt_creative", "").strip() or f"{base_prompt} 请把语气调整得更具吸引力，并加入受众洞察、主信息与内容角度。",
            },
            {
                "title": "技术、工程与学术",
                "subtitle": "Technology, Engineering & Research",
                "prompt": entry.get("prompt_technical", "").strip() or f"{base_prompt} 请让回答更有结构，包含方法、假设、技术细节与验证方向。",
            },
            {
                "title": "金融、法律与合规",
                "subtitle": "Finance, Legal & Compliance",
                "prompt": entry.get("prompt_finance", "").strip() or f"{base_prompt} 请使用更精准与审慎的语言，并加入风险披露、合规考量与决策重点。",
            },
            {
                "title": "教育与终身学习",
                "subtitle": "Education & Lifelong Learning",
                "prompt": entry.get("prompt_education", "").strip() or f"{base_prompt} 请用更清楚、可教学的方式说明，并补上步骤、例子与常见误解。",
            },
        ]
    return [
        {
            "title": "Strategic & Professional Services",
            "subtitle": "Professional consulting and management",
            "prompt": entry.get("prompt_strategic", "").strip() or f"{base_prompt} Add stakeholders, risks, priorities, and recommended next steps.",
        },
        {
            "title": "Creative & Marketing Content",
            "subtitle": "Creative and audience-facing communication",
            "prompt": entry.get("prompt_creative", "").strip() or f"{base_prompt} Make the tone more audience-aware and add messaging angles, hooks, and content direction.",
        },
        {
            "title": "Technology, Engineering & Research",
            "subtitle": "Technical and analytical work",
            "prompt": entry.get("prompt_technical", "").strip() or f"{base_prompt} Make the answer more structured with method, assumptions, technical detail, and validation steps.",
        },
        {
            "title": "Finance, Legal & Compliance",
            "subtitle": "High-precision professional contexts",
            "prompt": entry.get("prompt_finance", "").strip() or f"{base_prompt} Use more precise and risk-aware language, including compliance checks and decision considerations.",
        },
        {
            "title": "Education & Lifelong Learning",
            "subtitle": "Teaching and self-learning",
            "prompt": entry.get("prompt_education", "").strip() or f"{base_prompt} Explain it in a teachable way with steps, examples, and common misunderstandings to avoid.",
        },
    ]


def mobile_profile(name: str = "", persona: str = "", lang: str = "en") -> dict[str, str]:
    safe_name = (name or "").strip()[:40] or "Lawrence"
    safe_persona = persona if persona in SUPPORTED_PERSONAS else "lifelong_learner"
    return {
        "name": safe_name,
        "initials": profile_initials(safe_name),
        "persona": safe_persona,
        "persona_message": translate(lang, persona_message_key(safe_persona)),
        "recommendation_note": translate(lang, recommendation_note_key(safe_persona)),
    }


def mobile_word_card(word: dict, lang: str = "en") -> dict:
    chinese_preview = word.get("chinese_preview", []) or []
    return {
        "id": word.get("id"),
        "lemma": word.get("lemma", ""),
        "band_label": word.get("best_band_label", ""),
        "english_definition": word.get("english_definition", ""),
        "example_sentence": word.get("example_sentence", ""),
        "pronunciation": word.get("pronunciation", ""),
        "parts_of_speech": word.get("parts_of_speech", []),
        "chinese_preview": [localize_chinese_text(item, lang) for item in chinese_preview],
        "chinese_headword": localize_chinese_text(word.get("chinese_headword", ""), lang),
    }


def mobile_recommendation_cards(persona: str, lang: str = "en") -> list[dict[str, str]]:
    cards = recommendation_cards(persona)
    return [
        {
            "title": translate(lang, card["title_key"]),
            "body": translate(lang, card["body_key"]),
            "href": card["href"],
            "tag": translate(lang, card["tag_key"]),
        }
        for card in cards
    ]


def render(request: Request, template_name: str, **context) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    user = registered_user_row(request)
    context.update(
        {
            "lang": lang,
            "profile_name": get_profile_name(request),
            "profile_initials": profile_initials(get_profile_name(request)),
            "profile_persona": get_profile_persona(request),
            "registered_user": user,
            "is_teacher": is_teacher_user(user),
            "is_admin": is_admin_user(user),
            "static_version": STATIC_ASSET_VERSION,
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


def accuracy_color(percent: int | float | None) -> dict[str, str]:
    value = max(0, min(100, round(float(percent or 0))))
    hue = round((value / 100) * 120)
    return {
        "solid": f"hsl({hue} 58% 42%)",
        "tint": f"hsl({hue} 58% 42% / 0.14)",
        "track": "rgba(214, 224, 232, 0.9)",
    }


TEST_BAND_LABELS = {
    50: "50~99 (3924)",
    100: "100~199 (3180)",
    200: "200~499 (3176)",
    500: "500~1999 (3000)",
    2000: "2000~ (2330)",
}

TEST_BAND_EASIEST_TO_HARDEST = [2000, 500, 200, 100, 50]

STUDENT_DSE_BANDS = {
    1: {"label": "Core DSE Survival", "count": 1226, "target": "Level 2-3"},
    2: {"label": "DSE Standard", "count": 1008, "target": "Level 3-4"},
    3: {"label": "DSE High Score", "count": 1285, "target": "Level 4-5"},
    4: {"label": "5*/5** Advanced", "count": 1805, "target": "Level 5-5*"},
    5: {"label": "Academic Extension", "count": 2000, "target": "Level 5* / 5** extension"},
}

ECONOMIST_TO_STUDENT_DSE_RANK = {
    2000: 1,
    500: 2,
    200: 3,
    100: 4,
    50: 5,
}


def band_level_label(band_rank: int | None, lang: str = "en") -> str:
    labels = {
        "en": {
            2000: "Foundation",
            500: "Lower Intermediate",
            200: "Intermediate",
            100: "Upper Intermediate",
            50: "Advanced",
        },
        "zh-Hant": {
            2000: "基礎常用",
            500: "初中階",
            200: "中階",
            100: "中高階",
            50: "進階",
        },
        "zh-Hans": {
            2000: "基础常用",
            500: "初中阶",
            200: "中阶",
            100: "中高阶",
            50: "进阶",
        },
    }
    if band_rank in labels.get(lang, labels["en"]):
        return labels.get(lang, labels["en"])[band_rank]
    return progress_label(0, lang)


def easier_band_label_from_rank(band_rank: int | None) -> str | None:
    if band_rank is None:
        return None
    ordered = TEST_BAND_EASIEST_TO_HARDEST
    if band_rank not in ordered:
        return None
    idx = ordered.index(band_rank)
    if idx <= 0:
        return None
    next_rank = ordered[idx - 1]
    return TEST_BAND_LABELS.get(next_rank)


def level_recommendation(estimated_band_label: str | None, estimated_band_rank: int | None, percent: float, lang: str = "en") -> str:
    easier_band = easier_band_label_from_rank(estimated_band_rank)
    estimated_display = band_display_identity(estimated_band_label, lang)["display_label"] if estimated_band_label else ""
    easier_display = band_display_identity(easier_band, lang)["display_label"] if easier_band else ""
    if lang == "zh-Hant":
        if not estimated_band_label:
            return "先從 2000~ 這組最常用詞彙開始，再優先替你最常答錯的詞彙補上筆記與例句。"
        if percent >= 0.95:
            if easier_band:
                return f"你這次已經穩定掌握到 {estimated_display}。建議從下一級較難詞彙開始，同時把 {easier_display} 當作快速複習範圍。"
            return f"你這次已經穩定掌握整份檢測，建議直接挑戰 {estimated_display} 這組低頻高階詞彙。"
        if percent >= 0.7:
            return f"你目前可以穩定從 {estimated_display} 附近開始。接下來可以往較低頻、更高階的詞彙分類前進。"
        if easier_band:
            return f"接下來幾次學習，先集中在 {estimated_display} 和較容易一級的 {easier_display}，直到答案更自然為止。"
        return f"接下來幾次學習，先集中在 {estimated_display}，直到答案更自然為止。"
    if lang == "zh-Hans":
        if not estimated_band_label:
            return "先从 2000~ 这一组最常用词汇开始，再优先替你最常答错的词汇补上笔记与例句。"
        if percent >= 0.95:
            if easier_band:
                return f"你这次已经稳定掌握到 {estimated_display}。建议从下一级较难词汇开始，同时把 {easier_display} 当作快速复习范围。"
            return f"你这次已经稳定掌握整份检测，建议直接挑战 {estimated_display} 这组低频高阶词汇。"
        if percent >= 0.7:
            return f"你目前可以稳定从 {estimated_display} 附近开始。接下来可以往较低频、更高阶的词汇分类前进。"
        if easier_band:
            return f"接下来几次学习，先集中在 {estimated_display} 和较容易一级的 {easier_display}，直到答案更自然为止。"
        return f"接下来几次学习，先集中在 {estimated_display}，直到答案更自然为止。"
    if not estimated_band_label:
        return "Start with the 2000~ band, the most common foundation range, then add notes and examples to words you miss most often."
    if percent >= 0.95:
        if easier_band:
            return f"You've stably mastered {estimated_display}. Move toward the next rarer band, and use {easier_display} as a quick review range."
        return f"You've stably mastered the whole placement set. Challenge yourself with {estimated_display}, the rarer advanced range."
    if percent >= 0.7:
        return f"You can comfortably work around {estimated_display}. Move toward rarer, harder bands in Dictionary and enrich unfamiliar words."
    if easier_band:
        return f"Focus your next learning sessions around {estimated_display} and the easier {easier_display} band until the answers feel automatic."
    return f"Focus your next learning sessions around {estimated_display} until the answers feel automatic."


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


def ensure_user_study_card(conn: sqlite3.Connection, user_id: int, word_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO user_study_cards (
            user_id, word_id, status, correct_count, wrong_count, streak, ease,
            interval_days, notes, last_reviewed_at, next_review_at
        )
        SELECT
            ?, study_cards.word_id, study_cards.status, study_cards.correct_count,
            study_cards.wrong_count, study_cards.streak, study_cards.ease,
            study_cards.interval_days, study_cards.notes, study_cards.last_reviewed_at,
            study_cards.next_review_at
        FROM study_cards
        WHERE study_cards.word_id = ?
        """,
        (user_id, word_id),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO user_study_cards (user_id, word_id)
        VALUES (?, ?)
        """,
        (user_id, word_id),
    )
    conn.commit()


def word_row(conn: sqlite3.Connection, word_id: int, user_id: int = USER_ID) -> sqlite3.Row:
    ensure_user_study_card(conn, user_id, word_id)
    row = conn.execute(
        """
        SELECT words.*, user_study_cards.notes, user_study_cards.correct_count, user_study_cards.wrong_count,
               user_study_cards.status, user_study_cards.last_reviewed_at, user_study_cards.next_review_at
        FROM words
        JOIN user_study_cards ON user_study_cards.word_id = words.id
        WHERE words.id = ? AND user_study_cards.user_id = ?
        """,
        (word_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Word not found")
    return row


def mark_word_seen(conn: sqlite3.Connection, *, user_id: int, word_id: int) -> None:
    ensure_user_study_card(conn, user_id, word_id)
    conn.execute(
        """
        UPDATE user_study_cards
        SET status = 'seen',
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
          AND word_id = ?
          AND status = 'new'
          AND correct_count = 0
          AND wrong_count = 0
        """,
        (user_id, word_id),
    )
    conn.commit()


def normalize_spoken_word(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def pronunciation_score(target_word: str, transcript: str) -> dict[str, object]:
    target = normalize_spoken_word(target_word)
    heard_words = [normalize_spoken_word(part) for part in re.split(r"\s+", transcript or "") if normalize_spoken_word(part)]
    if not target:
        return {"score": 0, "recognized": False, "status": "Needs review"}
    best_ratio = 0.0
    for heard in heard_words or [normalize_spoken_word(transcript)]:
        ratio = SequenceMatcher(None, target, heard).ratio()
        best_ratio = max(best_ratio, ratio)
    recognized = any(heard == target for heard in heard_words)
    if recognized:
        score = 92
    elif target in normalize_spoken_word(transcript):
        score = 86
    else:
        score = round(best_ratio * 100)
    if score >= 90:
        status = "Mastered"
    elif score >= 75:
        status = "Almost mastered"
    elif score >= 60:
        status = "Needs review"
    else:
        status = "Relearn"
    return {"score": max(0, min(100, score)), "recognized": recognized, "status": status}


def mastery_feedback_for_pronunciation(target_word: str, transcript: str, score: int, lang: str = "en") -> str:
    if lang == "zh-Hant":
        if score >= 85:
            return f"AI 能清楚辨認出 {target_word}。發音已經可以理解，之後可再留意重音和自然節奏。"
        return f"AI 聽到的是「{transcript or '未能辨認'}」。請慢一點讀，先聽一次標準發音，再重新錄音。"
    if lang == "zh-Hans":
        if score >= 85:
            return f"AI 能清楚辨认出 {target_word}。发音已经可以理解，之后可再留意重音和自然节奏。"
        return f"AI 听到的是「{transcript or '未能辨认'}」。请慢一点读，先听一次标准发音，再重新录音。"
    if score >= 85:
        return f"AI recognized {target_word}. Your pronunciation is understandable; next, refine stress and rhythm."
    return f'AI heard "{transcript or "unclear audio"}". Try speaking a little slower after listening to the model pronunciation.'


def friendly_ai_failure_message(feature: str, lang: str = "en") -> str:
    if lang == "zh-Hant":
        return f"{feature} 暫時未能完成。請稍後再試，或請管理員檢查 OpenAI / AssemblyAI / Gemini API 額度與環境變數。"
    if lang == "zh-Hans":
        return f"{feature} 暂时未能完成。请稍后再试，或请管理员检查 OpenAI / AssemblyAI / Gemini API 额度与环境变量。"
    return f"{feature} is temporarily unavailable. Please try again later, or ask the admin to check OpenAI / AssemblyAI / Gemini API quota and environment variables."


def save_word_mastery_attempt(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    word_id: int,
    attempt_type: str,
    input_text: str = "",
    transcript: str = "",
    score: int = 0,
    status: str = "",
    feedback: str = "",
    corrected_sentence: str = "",
    suggested_upgrade: str = "",
    payload: dict | None = None,
) -> None:
    ensure_user_study_card(conn, user_id, word_id)
    conn.execute(
        """
        INSERT INTO word_mastery_attempts (
            user_id, word_id, attempt_type, input_text, transcript, score, status,
            feedback, corrected_sentence, suggested_upgrade, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            word_id,
            attempt_type,
            input_text.strip(),
            transcript.strip(),
            max(0, min(100, int(score or 0))),
            status.strip(),
            feedback.strip(),
            corrected_sentence.strip(),
            suggested_upgrade.strip(),
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )
    if int(score or 0) >= 75:
        conn.execute(
            """
            UPDATE user_study_cards
            SET status = CASE WHEN ? >= 90 THEN 'mastered' ELSE status END,
                correct_count = correct_count + 1,
                streak = streak + 1,
                last_reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND word_id = ?
            """,
            (int(score or 0), user_id, word_id),
        )
    else:
        conn.execute(
            """
            UPDATE user_study_cards
            SET status = 'review',
                wrong_count = wrong_count + 1,
                streak = 0,
                last_reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND word_id = ?
            """,
            (user_id, word_id),
        )
    conn.commit()


def latest_word_mastery_attempts(conn: sqlite3.Connection, *, word_id: int, user_id: int) -> dict[str, sqlite3.Row | None]:
    result: dict[str, sqlite3.Row | None] = {"pronunciation": None, "sentence": None}
    for attempt_type in result:
        result[attempt_type] = conn.execute(
            """
            SELECT *
            FROM word_mastery_attempts
            WHERE user_id = ? AND word_id = ? AND attempt_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, word_id, attempt_type),
        ).fetchone()
    return result


MASTERY_TEST_LAYERS = [
    ("chinese_definition", ["chinese_definition"]),
    ("english_definition", ["english_definition", "definition"]),
    ("example_application", ["example_application", "sentence"]),
    ("similar_word", ["similar_word", "synonym"]),
    ("opposite_word", ["opposite_word", "antonym"]),
]


def word_mastery_status(percent: int, test_complete: bool, deep_complete: bool, review_complete: bool) -> tuple[str, str]:
    if percent >= 100 and test_complete and deep_complete and review_complete:
        return "mastered", "mastery_progress_mastered"
    if percent >= 71:
        return "deep-learning", "mastery_progress_deep_learning"
    if test_complete:
        return "tested", "mastery_progress_tested"
    if percent >= 41:
        return "practicing", "mastery_progress_practicing"
    if percent >= 21:
        return "learning", "mastery_progress_learning"
    if percent > 0:
        return "seen", "mastery_progress_seen"
    return "not-started", "mastery_progress_not_started"


def word_mastery_next_step_key(percent: int, test_complete: bool, deep_complete: bool, review_complete: bool) -> str:
    if percent >= 100 and test_complete and deep_complete and review_complete:
        return "mastery_next_complete"
    if test_complete and deep_complete and not review_complete:
        return "mastery_next_review"
    if test_complete and not deep_complete:
        return "mastery_next_deep"
    if percent > 0:
        return "mastery_next_continue_test"
    return "mastery_next_start"


def word_mastery_progress(conn: sqlite3.Connection, *, word_id: int, user_id: int, lang: str) -> dict[str, object]:
    latest_mastery = latest_word_mastery_attempts(conn, word_id=word_id, user_id=user_id)
    card = conn.execute(
        """
        SELECT status, correct_count, wrong_count, last_reviewed_at, notes
        FROM user_study_cards
        WHERE user_id = ?
          AND word_id = ?
        """,
        (user_id, word_id),
    ).fetchone()
    answered_rows = conn.execute(
        """
        SELECT question_type, MAX(is_correct) AS passed
        FROM (
            SELECT assessment_questions.question_type, assessment_questions.is_correct
            FROM assessment_questions
            JOIN assessment_sessions ON assessment_sessions.id = assessment_questions.session_id
            WHERE assessment_sessions.user_id = ?
              AND assessment_questions.word_id = ?
              AND assessment_questions.is_correct IS NOT NULL
            UNION ALL
            SELECT learning_questions.question_type, learning_questions.is_correct
            FROM learning_questions
            JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
            WHERE learning_sessions.user_id = ?
              AND learning_questions.word_id = ?
              AND learning_questions.is_correct IS NOT NULL
        )
        GROUP BY question_type
        """,
        (user_id, word_id, user_id, word_id),
    ).fetchall()
    passed_by_type = {row["question_type"]: bool(row["passed"]) for row in answered_rows}
    layers = []
    passed_layers = 0
    for canonical, aliases in MASTERY_TEST_LAYERS:
        passed = any(passed_by_type.get(alias, False) for alias in aliases)
        passed_layers += 1 if passed else 0
        layers.append(
            {
                "key": canonical,
                "short": {
                    "chinese_definition": "中",
                    "english_definition": "EN",
                    "example_application": "EX",
                    "similar_word": "SYN",
                    "opposite_word": "ANT",
                }[canonical],
                "label": translate_question_type(canonical, lang),
                "complete": passed,
            }
        )

    pronunciation_complete = bool(latest_mastery["pronunciation"] and int(latest_mastery["pronunciation"]["score"] or 0) >= 75)
    sentence_complete = bool(latest_mastery["sentence"] and int(latest_mastery["sentence"]["score"] or 0) >= 75)
    review_row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM user_review_log
        WHERE user_id = ?
          AND word_id = ?
          AND grade = 'good'
        """,
        (user_id, word_id),
    ).fetchone()
    review_complete = int(review_row["total"] if review_row else 0) > 0
    test_complete = passed_layers == len(MASTERY_TEST_LAYERS)
    exposure_complete = bool(
        card
        and (
            card["status"] != "new"
            or int(card["correct_count"] or 0) > 0
            or int(card["wrong_count"] or 0) > 0
            or bool(card["last_reviewed_at"])
            or bool((card["notes"] or "").strip())
        )
    )
    raw_percent = 15 if exposure_complete else 0
    raw_percent += passed_layers * 10
    if pronunciation_complete:
        raw_percent += 10
    if sentence_complete:
        raw_percent += 15
    if review_complete:
        raw_percent += 10

    if test_complete and not (pronunciation_complete or sentence_complete or review_complete):
        percent = min(raw_percent, 70)
    elif pronunciation_complete and not sentence_complete:
        percent = min(raw_percent, 80)
    elif sentence_complete and not review_complete:
        percent = min(raw_percent, 90)
    else:
        percent = raw_percent
    if not (test_complete and pronunciation_complete and sentence_complete and review_complete):
        percent = min(percent, 99)
    percent = max(0, min(100, percent))
    tone, label_key = word_mastery_status(percent, test_complete, pronunciation_complete and sentence_complete, review_complete)
    segments = [
        {"key": "exposure", "label": translate(lang, "mastery_progress_exposure"), "complete": exposure_complete, "weight": 15},
        {"key": "test", "label": translate(lang, "mastery_progress_test_layers"), "complete": test_complete, "weight": 50},
        {"key": "pronunciation", "label": translate(lang, "mastery_progress_pronunciation"), "complete": pronunciation_complete, "weight": 10},
        {"key": "writing", "label": translate(lang, "mastery_progress_writing"), "complete": sentence_complete, "weight": 15},
        {"key": "review", "label": translate(lang, "mastery_progress_review"), "complete": review_complete, "weight": 10},
    ]
    return {
        "percent": percent,
        "tone": tone,
        "status_label": translate(lang, label_key),
        "next_step": translate(lang, word_mastery_next_step_key(percent, test_complete, pronunciation_complete and sentence_complete, review_complete)),
        "test_complete": test_complete,
        "deep_complete": pronunciation_complete and sentence_complete,
        "review_complete": review_complete,
        "exposure_complete": exposure_complete,
        "layers": layers,
        "segments": segments,
    }


def dse_exam_profile_for_word(
    lemma: str,
    *,
    band_rank: int | None,
    parts_of_speech: list[str],
    english_definition: str = "",
    example_sentence: str = "",
    lang: str = "en",
) -> dict[str, object]:
    text = f"{lemma} {english_definition} {example_sentence}".lower()
    topic_keywords = [
        ("Environment", "環境", "环境", ["climate", "environment", "green", "sustainable", "pollution", "energy", "waste"]),
        ("Technology", "科技", "科技", ["technology", "digital", "ai", "data", "online", "internet", "automation"]),
        ("Economy & Work", "經濟與工作", "经济与工作", ["market", "econom", "business", "work", "job", "labour", "income", "firm"]),
        ("Society & Policy", "社會與政策", "社会与政策", ["society", "policy", "government", "public", "community", "inequality", "rights"]),
        ("Education & Youth", "教育與青年", "教育与青年", ["education", "school", "student", "youth", "learn", "exam", "teacher"]),
        ("Health & Lifestyle", "健康與生活", "健康与生活", ["health", "mental", "stress", "lifestyle", "wellbeing", "medical"]),
    ]
    topics: list[str] = []
    for en_label, zh_hant_label, zh_hans_label, keywords in topic_keywords:
        if any(keyword in text for keyword in keywords):
            topics.append(zh_hant_label if lang == "zh-Hant" else zh_hans_label if lang == "zh-Hans" else en_label)
    if not topics:
        topics = [
            "Social issues",
            "Argument writing",
        ] if lang == "en" else [
            "社會議題",
            "議論寫作",
        ] if lang == "zh-Hant" else [
            "社会议题",
            "议论写作",
        ]

    pos_text = " ".join(parts_of_speech).lower()
    paper_fit = ["Paper 1 Reading", "Paper 2 Writing"]
    if band_rank in {50, 100, 200}:
        paper_fit.append("Paper 4 Speaking")
    if "verb" in pos_text:
        writing_move = {
            "en": "Use it to describe an action, trend, policy effect, or cause-and-effect relationship.",
            "zh-Hant": "可用來描述行動、趨勢、政策影響或因果關係。",
            "zh-Hans": "可用来描述行动、趋势、政策影响或因果关系。",
        }
    elif "adjective" in pos_text or "adj" in pos_text:
        writing_move = {
            "en": "Use it to make your description or argument more precise.",
            "zh-Hant": "可用來令描述或論點更精準。",
            "zh-Hans": "可用来令描述或论点更精准。",
        }
    elif "noun" in pos_text:
        writing_move = {
            "en": "Use it as a key concept in topic sentences, examples, and conclusions.",
            "zh-Hant": "可作為 topic sentence、例子或結論中的核心概念。",
            "zh-Hans": "可作为 topic sentence、例子或结论中的核心概念。",
        }
    else:
        writing_move = {
            "en": "Use it when you need a more exact DSE writing word instead of a simple everyday word.",
            "zh-Hant": "當你想把日常用字升級成更精準的 DSE 寫作用字時使用。",
            "zh-Hans": "当你想把日常用词升级成更精准的 DSE 写作用词时使用。",
        }
    common_mistake = {
        "en": "Do not only memorise the Chinese meaning. Check the part of speech and use the word in a complete sentence.",
        "zh-Hant": "不要只背中文意思；要先確認詞性，再把它放入完整句子。",
        "zh-Hans": "不要只背中文意思；要先确认词性，再把它放入完整句子。",
    }
    sample_sentence = example_sentence.strip() or f"This issue shows why {lemma} matters in modern society."
    return {
        "paper_fit": paper_fit,
        "topics": topics[:3],
        "writing_move": writing_move.get(lang, writing_move["en"]),
        "sample_sentence": sample_sentence,
        "common_mistake": common_mistake.get(lang, common_mistake["en"]),
    }


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


def word_payload(conn: sqlite3.Connection, word_id: int, lang: str = "en", user_id: int = USER_ID) -> dict:
    row = word_row(conn, word_id, user_id)
    parts_of_speech = parts_of_speech_for_word(conn, word_id)
    progression = progression_profile_for_word(conn, word_id)
    relationship_groups = [
        {
            **group,
            "label": translate_relation_type(group["relation_type"], lang),
        }
        for group in progression["relationship_groups"]
    ]
    preferred_relation_order = {
        "level_up": 0,
        "more_business": 1,
        "more_precise": 2,
        "more_formal": 3,
        "more_ai": 4,
        "more_academic": 5,
        "related_not_interchangeable": 6,
    }
    sorted_groups = sorted(
        relationship_groups,
        key=lambda group: preferred_relation_order.get(group["relation_type"], 99),
    )
    next_suggestions: list[dict] = []
    for group in sorted_groups:
        for item in group["words"]:
            next_suggestions.append(
                {
                    "lemma": item["lemma"],
                    "band_label": item["band_label"],
                    "relation_label": group["label"],
                    "explanation": item["explanation"],
                }
            )
            if len(next_suggestions) >= 3:
                break
        if len(next_suggestions) >= 3:
            break
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
        SELECT
            english_definition,
            pronunciation,
            synonyms_json,
            example_sentence,
            sentence_distractors_json,
            ai_simple_explanation_en,
            ai_simple_explanation_zh,
            ai_nuance_note,
            ai_compare_words_json,
            ai_business_example,
            ai_prompt_example,
            ai_usage_warning
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word_id,),
    ).fetchone()
    source_fallback = source_fallback_for_word(conn, word_id)
    english_definition = (enrichment["english_definition"] if enrichment and enrichment["english_definition"] else source_fallback["english_definition"])
    synonyms = json_loads(enrichment["synonyms_json"]) if enrichment else []
    example_sentence = (enrichment["example_sentence"] if enrichment and enrichment["example_sentence"] else source_fallback["example_sentence"])
    dse_exam_profile = dse_exam_profile_for_word(
        row["lemma"],
        band_rank=row["best_band_rank"],
        parts_of_speech=parts_of_speech,
        english_definition=english_definition,
        example_sentence=example_sentence,
        lang=lang,
    )
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
        "dse_exam_profile": dse_exam_profile,
        "sentence_distractors": json_loads(enrichment["sentence_distractors_json"]) if enrichment else [],
        "ai_insight": {
            "simple_explanation_en": enrichment["ai_simple_explanation_en"] if enrichment else "",
            "simple_explanation_zh": enrichment["ai_simple_explanation_zh"] if enrichment else "",
            "nuance_note": enrichment["ai_nuance_note"] if enrichment else "",
            "compare_words": json_loads(enrichment["ai_compare_words_json"]) if enrichment else [],
            "business_example": enrichment["ai_business_example"] if enrichment else "",
            "prompt_example": enrichment["ai_prompt_example"] if enrichment else "",
            "usage_warning": enrichment["ai_usage_warning"] if enrichment else "",
        },
        "progression": {
            **progression,
            "relationship_groups": relationship_groups,
            "next_suggestions": next_suggestions,
        },
    }


def band_accuracy_rows(conn: sqlite3.Connection, session_id: int, lang: str = "en") -> list[dict]:
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
        identity = band_display_identity(row["band_label"], lang)
        result.append(
            {
                "band_label": row["band_label"],
                "band_display_label": identity["display_label"],
                "band_tone": identity["tone"],
                "correct": correct,
                "total": total,
                "accuracy": round(accuracy * 100),
                "color": accuracy_color(round(accuracy * 100))["solid"],
                "tint": accuracy_color(round(accuracy * 100))["tint"],
            }
        )
    return result


def layer_accuracy_rows(conn: sqlite3.Connection, session_id: int, lang: str = "en") -> list[dict]:
    rows = conn.execute(
        """
        SELECT question_type,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
               COUNT(*) AS total
        FROM assessment_questions
        WHERE session_id = ?
        GROUP BY question_type
        """,
        (session_id,),
    ).fetchall()
    row_map = {row["question_type"]: row for row in rows}
    ordered_types = [
        "chinese_definition",
        "english_definition",
        "example_application",
        "similar_word",
        "opposite_word",
    ]
    result = []
    for question_type in ordered_types:
        row = row_map.get(question_type)
        total = row["total"] if row else 0
        correct = row["correct"] if row else 0
        accuracy = round((correct / total) * 100) if total else 0
        result.append(
            {
                "question_type": question_type,
                "label": translate_question_type(question_type, lang),
                "correct": correct,
                "total": total,
                "accuracy": accuracy,
                "color": accuracy_color(accuracy)["solid"],
                "tint": accuracy_color(accuracy)["tint"],
            }
        )
    return result


def word_report_rows(conn: sqlite3.Connection, session_id: int, lang: str = "en", user_id: int = USER_ID) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            assessment_questions.word_id,
            assessment_questions.band_label,
            assessment_questions.question_type,
            assessment_questions.id AS question_id,
            assessment_questions.is_correct,
            words.lemma
        FROM assessment_questions
        JOIN words ON words.id = assessment_questions.word_id
        WHERE assessment_questions.session_id = ?
        ORDER BY MIN(assessment_questions.position) OVER (PARTITION BY assessment_questions.word_id),
                 assessment_questions.position
        """,
        (session_id,),
    ).fetchall()
    ordered_types = [
        "chinese_definition",
        "english_definition",
        "example_application",
        "similar_word",
        "opposite_word",
    ]
    buckets: dict[int, dict] = {}
    order: list[int] = []
    for row in rows:
        word_id = row["word_id"]
        if word_id not in buckets:
            payload = word_payload(conn, word_id, lang, user_id)
            identity = band_display_identity(row["band_label"], lang)
            buckets[word_id] = {
                "word_id": word_id,
                "lemma": row["lemma"],
                "band_label": row["band_label"],
                "band_display_label": identity["display_label"],
                "band_tone": identity["tone"],
                "chinese_definition": payload["chinese_headword"],
                "english_definition": payload["english_definition"],
                "layers": {question_type: None for question_type in ordered_types},
                "question_ids": {},
            }
            order.append(word_id)
        buckets[word_id]["layers"][row["question_type"]] = bool(row["is_correct"])
        buckets[word_id]["question_ids"][row["question_type"]] = row["question_id"]
    result = []
    for word_id in order:
        item = buckets[word_id]
        correct_count = sum(1 for value in item["layers"].values() if value)
        item["correct_count"] = correct_count
        item["total_count"] = len(ordered_types)
        item["accuracy"] = round((correct_count / len(ordered_types)) * 100)
        result.append(item)
    return result


def learning_word_report_rows(conn: sqlite3.Connection, session_id: int, lang: str = "en", user_id: int = USER_ID) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            learning_questions.word_id,
            learning_questions.question_type,
            learning_questions.id AS question_id,
            learning_questions.prompt_text,
            learning_questions.user_answer,
            learning_questions.correct_option,
            learning_questions.is_correct,
            words.lemma
        FROM learning_questions
        JOIN words ON words.id = learning_questions.word_id
        WHERE learning_questions.session_id = ?
        ORDER BY MIN(learning_questions.position) OVER (PARTITION BY learning_questions.word_id),
                 learning_questions.position
        """,
        (session_id,),
    ).fetchall()
    buckets: dict[int, dict] = {}
    order: list[int] = []
    for row in rows:
        word_id = row["word_id"]
        if word_id not in buckets:
            payload = word_payload(conn, word_id, lang, user_id)
            buckets[word_id] = {
                "word_id": word_id,
                "lemma": row["lemma"],
                "chinese_definition": payload["chinese_headword"],
                "english_definition": payload["english_definition"],
                "questions": [],
            }
            order.append(word_id)
        buckets[word_id]["questions"].append(
            {
                "question_id": row["question_id"],
                "question_type": row["question_type"],
                "question_type_label": translate_question_type(row["question_type"], lang),
                "prompt_text": row["prompt_text"],
                "user_answer": row["user_answer"],
                "correct_option": row["correct_option"],
                "is_correct": bool(row["is_correct"]),
            }
        )
    result = []
    for word_id in order:
        item = buckets[word_id]
        total_count = len(item["questions"])
        correct_count = sum(1 for question in item["questions"] if question["is_correct"])
        item["correct_count"] = correct_count
        item["total_count"] = total_count
        item["accuracy"] = round((correct_count / total_count) * 100) if total_count else 0
        result.append(item)
    return result


def report_focus_rows(layer_rows: list[dict]) -> dict[str, dict | None]:
    available = [row for row in layer_rows if row["total"]]
    if not available:
        return {"strongest": None, "weakest": None}
    strongest = max(available, key=lambda row: (row["accuracy"], row["correct"]))
    weakest = min(available, key=lambda row: (row["accuracy"], row["correct"]))
    return {"strongest": strongest, "weakest": weakest}


def decorate_band_rows(rows: list[sqlite3.Row]) -> list[dict]:
    decorated = []
    for row in rows:
        label = row["best_band_label"]
        identity = hero_band_identity(label.split(" (")[0])
        match = re.search(r"\((\d+)\)", label)
        workbook_total = int(match.group(1)) if match else row["total"]
        decorated.append(
            {
                "best_band_rank": row["best_band_rank"],
                "best_band_label": label,
                "total": row["total"],
                "workbook_total": workbook_total,
                "range_label": label.split(" (")[0],
                "title": identity["title"],
                "subtitle": identity["subtitle"],
                "tone": identity["tone"],
            }
        )
    return sorted(decorated, key=lambda band: band["best_band_rank"], reverse=True)


def student_dse_band_rows(conn: sqlite3.Connection, lang: str = "en", user_id: int = USER_ID) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            dse_band_rank,
            dse_band_label,
            COUNT(*) AS total,
            COUNT(word_id) AS matched_total
        FROM student_dse_vocab
        GROUP BY dse_band_rank, dse_band_label
        ORDER BY dse_band_rank
        """
    ).fetchall()
    row_map = {int(row["dse_band_rank"]): row for row in rows}
    recommended_rank = recommended_student_dse_band_rank(conn, user_id)
    cards = []
    for rank, config in STUDENT_DSE_BANDS.items():
        row = row_map.get(rank)
        total = int(row["total"] if row else config["count"])
        matched_total = int(row["matched_total"] if row else 0)
        identity = band_display_identity(config["label"], lang)
        cards.append(
            {
                "best_band_rank": rank,
                "best_band_label": config["label"],
                "range_label": config["label"],
                "title": identity["title"],
                "subtitle": identity["subtitle"],
                "display_label": identity["display_label"],
                "tone": identity["tone"],
                "total": total,
                "workbook_total": total,
                "matched_total": matched_total,
                "target": config["target"],
                "recommended": rank == recommended_rank,
            }
        )
    return cards


def recommended_student_dse_band_rank(conn: sqlite3.Connection, user_id: int = USER_ID) -> int:
    latest_test = latest_test_result(conn, user_id=user_id)
    if latest_test is not None and latest_test["estimated_band_rank"] in STUDENT_DSE_BANDS:
        return int(latest_test["estimated_band_rank"])
    economist_rank = recommended_learning_band_rank(conn, user_id)
    return ECONOMIST_TO_STUDENT_DSE_RANK.get(economist_rank, 1)


def student_dse_letters_for_band(conn: sqlite3.Connection, band_rank: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT UPPER(SUBSTR(words.lemma, 1, 1)) AS letter
        FROM student_dse_vocab
        JOIN words ON words.id = student_dse_vocab.word_id
        WHERE student_dse_vocab.dse_band_rank = ?
        ORDER BY letter
        """,
        (band_rank,),
    ).fetchall()
    return [row["letter"] for row in rows if row["letter"]]


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


def latest_test_result(conn: sqlite3.Connection, full_only: bool = True, user_id: int = USER_ID) -> sqlite3.Row | None:
    min_questions_clause = "AND COALESCE(question_count, 0) >= ?" if full_only else ""
    params: tuple[object, ...] = (TEST_QUESTION_COUNT,) if full_only else ()
    return conn.execute(
        f"""
        SELECT *
        FROM assessment_sessions
        WHERE status = 'completed'
          AND user_id = ?
          {min_questions_clause}
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, *params),
    ).fetchone()


def active_test_session(conn: sqlite3.Connection, user_id: int = USER_ID) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT assessment_sessions.*, COUNT(assessment_questions.id) AS question_total
        FROM assessment_sessions
        LEFT JOIN assessment_questions ON assessment_questions.session_id = assessment_sessions.id
        WHERE assessment_sessions.status = 'active'
          AND assessment_sessions.user_id = ?
        GROUP BY assessment_sessions.id
        HAVING question_total > 0
           AND assessment_sessions.current_index < question_total
        ORDER BY assessment_sessions.id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def test_history_rows(conn: sqlite3.Connection, limit: int = 50, full_only: bool = False, user_id: int = USER_ID) -> list[dict]:
    full_only_clause = "HAVING total_questions >= ?" if full_only else ""
    params: tuple[object, ...] = (user_id, TEST_QUESTION_COUNT, limit) if full_only else (user_id, limit)
    rows = conn.execute(
        f"""
        SELECT
            assessment_sessions.id,
            assessment_sessions.started_at,
            assessment_sessions.completed_at,
            assessment_sessions.score,
            assessment_sessions.estimated_band_label,
            COUNT(assessment_questions.id) AS total_questions,
            SUM(CASE WHEN assessment_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct_answers
        FROM assessment_sessions
        LEFT JOIN assessment_questions ON assessment_questions.session_id = assessment_sessions.id
        WHERE assessment_sessions.status = 'completed'
          AND assessment_sessions.user_id = ?
        GROUP BY assessment_sessions.id
        {full_only_clause}
        ORDER BY assessment_sessions.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    history: list[dict] = []
    for row in rows:
        total_questions = int(row["total_questions"] or 0)
        correct_answers = int(row["correct_answers"] or 0)
        is_full_test = total_questions >= TEST_QUESTION_COUNT
        history.append(
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "score": row["score"],
                "estimated_band_label": row["estimated_band_label"],
                "total_questions": total_questions,
                "correct_answers": correct_answers,
                "accuracy_percent": round((correct_answers / total_questions) * 100) if total_questions else None,
                "is_full_test": is_full_test,
                "is_legacy": not is_full_test,
            }
        )
    return history


def latest_learning_result(conn: sqlite3.Connection, user_id: int = USER_ID) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE status = 'completed' AND user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def active_learning_session(conn: sqlite3.Connection, user_id: int = USER_ID) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT learning_sessions.*, COUNT(learning_questions.id) AS question_total
        FROM learning_sessions
        LEFT JOIN learning_questions ON learning_questions.session_id = learning_sessions.id
        WHERE learning_sessions.status = 'active'
          AND learning_sessions.user_id = ?
        GROUP BY learning_sessions.id
        HAVING question_total > 0
           AND learning_sessions.current_index < question_total
        ORDER BY learning_sessions.id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def student_today_plan_items(
    *,
    latest_test: sqlite3.Row | None,
    active_test: sqlite3.Row | None,
    active_learning: sqlite3.Row | None,
    latest_learning: sqlite3.Row | None,
    missed_count: int,
) -> list[dict[str, str | bool]]:
    if latest_test is None:
        return [
            {
                "title_key": "first_login_action",
                "body_key": "first_login_action_note",
                "href": f"/test/{active_test['id']}" if active_test else "/test",
                "primary": True,
            }
        ]
    items: list[dict[str, str | bool]] = []
    if active_test is not None:
        items.append(
            {
                "title_key": "resume_level_test_action",
                "body_key": "saved_incomplete_test",
                "href": f"/test/{active_test['id']}",
                "primary": True,
            }
        )
    if active_learning is not None:
        items.append(
            {
                "title_key": "resume_learning_action",
                "body_key": "start_short_session",
                "href": f"/learning/{active_learning['id']}",
                "primary": not items,
            }
        )
    items.append(
        {
            "title_key": "daily_task_action",
            "body_key": "start_short_session",
            "href": "/learning",
            "primary": not items,
        }
    )
    items.append(
        {
            "title_key": "review_weak_words_action",
            "body_key": "review_queue_count" if missed_count else "go_to_missed_words_note",
            "href": "/review/missed",
            "primary": False,
        }
    )
    if latest_learning is not None:
        items.append(
            {
                "title_key": "deep_learning_three_action",
                "body_key": "card_student_dictionary",
                "href": "/dictionary",
                "primary": False,
            }
        )
    return items[:4]


def learning_history_rows(conn: sqlite3.Connection, limit: int = 5, user_id: int = USER_ID) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            learning_sessions.id,
            learning_sessions.started_at,
            learning_sessions.completed_at,
            learning_sessions.score,
            COUNT(learning_questions.id) AS total_questions,
            SUM(CASE WHEN learning_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct_answers
        FROM learning_sessions
        LEFT JOIN learning_questions ON learning_questions.session_id = learning_sessions.id
        WHERE learning_sessions.status = 'completed'
          AND learning_sessions.user_id = ?
        GROUP BY learning_sessions.id
        ORDER BY learning_sessions.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    history: list[dict] = []
    for row in rows:
        total_questions = int(row["total_questions"] or 0)
        correct_answers = int(row["correct_answers"] or row["score"] or 0)
        history.append(
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "score": int(row["score"] or 0),
                "total_questions": total_questions,
                "correct_answers": correct_answers,
                "accuracy_percent": round((correct_answers / total_questions) * 100) if total_questions else None,
            }
        )
    return history


def statistics_advice(conn: sqlite3.Connection, latest_test: dict | None, latest_learning: dict | None, lang: str) -> str:
    if latest_test is None:
        return translate(lang, "statistics_advice_no_test")
    if latest_learning is None:
        return translate(lang, "statistics_advice_no_learning")
    try:
        layer_rows = layer_accuracy_rows(conn, int(latest_test["id"]), lang)
        focus = report_focus_rows(layer_rows)
        weakest = focus["weakest"]
        if weakest and int(weakest["accuracy"] or 0) < 75:
            return translate(lang, "statistics_advice_weak_layer", layer=weakest["label"])
    except Exception:
        pass
    return translate(lang, "statistics_advice_good")


def question_feedback_rows(conn: sqlite3.Connection, limit: int = 100, status: str = "open") -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            question_feedback.*,
            words.lemma,
            COALESCE(word_enrichment.english_definition, '') AS english_definition,
            COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
            COALESCE(word_enrichment.synonyms_json, '[]') AS synonyms_json,
            COALESCE(word_enrichment.antonyms_json, '[]') AS antonyms_json,
            COALESCE(word_enrichment.example_sentence, '') AS example_sentence,
            COALESCE(word_enrichment.sentence_distractors_json, '[]') AS sentence_distractors_json,
            assessment_questions.correct_option,
            assessment_questions.options_json,
            assessment_questions.prompt_text,
            assessment_questions.band_label
        FROM question_feedback
        LEFT JOIN words ON words.id = question_feedback.word_id
        LEFT JOIN word_enrichment ON word_enrichment.word_id = question_feedback.word_id
        LEFT JOIN assessment_questions ON assessment_questions.id = question_feedback.question_id
        WHERE question_feedback.status = ?
        ORDER BY question_feedback.id DESC
        LIMIT ?
        """,
        (status, limit),
    ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                **dict(row),
                "options": json_loads(row["options_json"]) if row["options_json"] else [],
                "synonyms": json_loads(row["synonyms_json"]),
                "antonyms": json_loads(row["antonyms_json"]),
                "sentence_distractors": json_loads(row["sentence_distractors_json"]),
            }
        )
    return result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_study_card_schedule(conn: sqlite3.Connection, word_id: int, is_correct: bool, source: str, user_id: int = USER_ID) -> None:
    ensure_user_study_card(conn, user_id, word_id)
    card = conn.execute(
        "SELECT * FROM user_study_cards WHERE user_id = ? AND word_id = ?",
        (user_id, word_id),
    ).fetchone()
    now = datetime.now(timezone.utc)
    ease = float(card["ease"] or 2.5)
    interval = float(card["interval_days"] or 0)
    streak = int(card["streak"] or 0)
    correct_count = int(card["correct_count"] or 0)
    wrong_count = int(card["wrong_count"] or 0)

    if is_correct:
        streak += 1
        correct_count += 1
        interval = 2 if interval < 2 else min(60, interval * ease)
        ease = min(3.2, ease + 0.03)
        status = "review"
        grade = "good"
    else:
        streak = 0
        wrong_count += 1
        interval = 1
        ease = max(1.3, ease - 0.2)
        status = "learning"
        grade = "again"

    next_review_at = (now + timedelta(days=interval)).isoformat()
    conn.execute(
        """
        UPDATE user_study_cards
        SET status = ?, correct_count = ?, wrong_count = ?, streak = ?, ease = ?,
            interval_days = ?, last_reviewed_at = ?, next_review_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND word_id = ?
        """,
        (
            status,
            correct_count,
            wrong_count,
            streak,
            ease,
            interval,
            now.isoformat(),
            next_review_at,
            user_id,
            word_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO user_review_log (user_id, word_id, reviewed_at, prompt_mode, grade)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, word_id, now.isoformat(), source, grade),
    )


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
                "best_band_rank": row["best_band_rank"],
                "english_definition": english_definition,
                "example_sentence": example_sentence,
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
                "parts_of_speech": parts,
                "chinese_preview": definitions[:2],
            }
        )
    return cards


BUSINESS_SECTORS = [
    {
        "slug": "macroeconomics",
        "label_en": "Macroeconomics",
        "label_zh_hant": "宏觀經濟",
        "keywords": ["inflation", "recession", "monetary", "fiscal", "productivity", "growth", "economy", "economic", "central bank", "interest rate", "gdp"],
    },
    {
        "slug": "finance-markets",
        "label_en": "Finance & Markets",
        "label_zh_hant": "金融與市場",
        "keywords": ["equity", "bond", "yield", "liquidity", "valuation", "market", "investor", "stock", "asset", "capital", "volatility", "portfolio"],
    },
    {
        "slug": "banking-fintech",
        "label_en": "Banking & FinTech",
        "label_zh_hant": "銀行與金融科技",
        "keywords": ["bank", "deposit", "lending", "loan", "default", "payment", "credit", "fintech", "mortgage", "balance sheet"],
    },
    {
        "slug": "technology-ai",
        "label_en": "Technology & AI",
        "label_zh_hant": "科技與 AI",
        "keywords": ["algorithm", "automation", "semiconductor", "software", "data", "digital", "platform", "model", "artificial intelligence", "technology", "chip"],
    },
    {
        "slug": "energy-climate",
        "label_en": "Energy & Climate",
        "label_zh_hant": "能源與氣候",
        "keywords": ["carbon", "climate", "emission", "renewable", "energy", "oil", "gas", "green", "transition", "sustainable", "decarbonisation"],
    },
    {
        "slug": "healthcare-biotech",
        "label_en": "Healthcare & Biotech",
        "label_zh_hant": "醫療與生物科技",
        "keywords": ["health", "medical", "trial", "pharmaceutical", "diagnosis", "vaccine", "therapy", "drug", "biotech", "hospital", "patient"],
    },
    {
        "slug": "real-estate-infrastructure",
        "label_en": "Real Estate & Infrastructure",
        "label_zh_hant": "房地產與基建",
        "keywords": ["housing", "property", "construction", "land", "infrastructure", "mortgage", "urban", "building", "transport"],
    },
    {
        "slug": "trade-supply-chain",
        "label_en": "Trade & Supply Chain",
        "label_zh_hant": "貿易與供應鏈",
        "keywords": ["trade", "tariff", "export", "import", "logistics", "supply chain", "shipping", "manufacturer", "factory", "globalisation"],
    },
    {
        "slug": "geopolitics",
        "label_en": "Geopolitics",
        "label_zh_hant": "地緣政治",
        "keywords": ["sanction", "diplomacy", "sovereignty", "alliance", "conflict", "war", "security", "china", "asia", "russia", "government"],
    },
    {
        "slug": "consumer-retail",
        "label_en": "Consumer & Retail",
        "label_zh_hant": "消費與零售",
        "keywords": ["consumer", "retail", "demand", "brand", "subscription", "spending", "e-commerce", "customer", "price", "sales"],
    },
    {
        "slug": "management-strategy",
        "label_en": "Management & Strategy",
        "label_zh_hant": "管理與策略",
        "keywords": ["strategy", "acquisition", "merger", "efficiency", "expansion", "restructuring", "management", "competitive", "operation", "executive"],
    },
    {
        "slug": "law-regulation",
        "label_en": "Law & Regulation",
        "label_zh_hant": "法律與監管",
        "keywords": ["antitrust", "compliance", "litigation", "legislation", "regulation", "regulator", "law", "legal", "oversight", "policy"],
    },
]

BUSINESS_TOPICS = [
    {"slug": "growth-recession", "label_en": "Growth & Recession", "label_zh_hant": "增長與衰退", "keywords": ["growth", "recession", "cycle", "slowdown", "expansion", "productivity", "gdp"]},
    {"slug": "inflation-interest-rates", "label_en": "Inflation & Interest Rates", "label_zh_hant": "通脹與利率", "keywords": ["inflation", "interest rate", "monetary", "central bank", "tightening", "yield", "price"]},
    {"slug": "ai-automation", "label_en": "AI & Automation", "label_zh_hant": "AI 與自動化", "keywords": ["ai", "artificial intelligence", "automation", "algorithm", "model", "data", "software"]},
    {"slug": "climate-esg", "label_en": "Climate & ESG", "label_zh_hant": "氣候與 ESG", "keywords": ["climate", "carbon", "emission", "renewable", "sustainable", "green", "esg"]},
    {"slug": "global-trade", "label_en": "Global Trade", "label_zh_hant": "全球貿易", "keywords": ["trade", "tariff", "export", "import", "supply chain", "global", "logistics"]},
    {"slug": "regulation-antitrust", "label_en": "Regulation & Antitrust", "label_zh_hant": "監管與反壟斷", "keywords": ["regulation", "regulator", "antitrust", "compliance", "oversight", "legal", "law"]},
    {"slug": "inequality-society", "label_en": "Inequality & Society", "label_zh_hant": "不平等與社會", "keywords": ["inequality", "society", "social", "poverty", "income", "education", "welfare"]},
    {"slug": "innovation-productivity", "label_en": "Innovation & Productivity", "label_zh_hant": "創新與生產力", "keywords": ["innovation", "productivity", "efficiency", "technology", "research", "development"]},
    {"slug": "risk-crisis", "label_en": "Risk & Crisis", "label_zh_hant": "風險與危機", "keywords": ["risk", "crisis", "shock", "uncertainty", "vulnerability", "exposure", "default"]},
    {"slug": "china-asia", "label_en": "China & Asia", "label_zh_hant": "中國與亞洲", "keywords": ["china", "asia", "asian", "beijing", "hong kong", "taiwan", "japan", "india"]},
]

BUSINESS_SKILLS = [
    {"slug": "business-reports", "label_en": "Business Reports", "label_zh_hant": "商務報告", "keywords": ["indicate", "suggest", "reflect", "imply", "trend", "outlook", "forecast", "estimate"]},
    {"slug": "market-analysis", "label_en": "Market Analysis", "label_zh_hant": "市場分析", "keywords": ["volatility", "valuation", "sentiment", "momentum", "market", "yield", "liquidity", "equity"]},
    {"slug": "strategy-discussion", "label_en": "Strategy Discussion", "label_zh_hant": "策略討論", "keywords": ["strategy", "expansion", "acquisition", "partnership", "differentiation", "competitive", "positioning"]},
    {"slug": "risk-assessment", "label_en": "Risk Assessment", "label_zh_hant": "風險評估", "keywords": ["risk", "exposure", "vulnerability", "downside", "uncertainty", "threat", "crisis"]},
    {"slug": "presentation-english", "label_en": "Presentation English", "label_zh_hant": "簡報英語", "keywords": ["highlight", "emphasise", "demonstrate", "illustrate", "show", "explain", "present"]},
    {"slug": "formal-email-writing", "label_en": "Formal Email Writing", "label_zh_hant": "正式電郵寫作", "keywords": ["regarding", "attached", "appreciate", "clarify", "request", "confirm", "proposal"]},
    {"slug": "negotiation", "label_en": "Negotiation", "label_zh_hant": "談判", "keywords": ["compromise", "concession", "terms", "proposal", "agreement", "deal", "bargain"]},
    {"slug": "executive-summary", "label_en": "Executive Summary", "label_zh_hant": "高層摘要", "keywords": ["driver", "implication", "forecast", "recommendation", "priority", "decision", "outcome"]},
]


def localized_business_taxonomy(items: list[dict], lang: str) -> list[dict[str, str]]:
    label_key = "label_zh_hant" if lang in {"zh-Hant", "zh-Hans"} else "label_en"
    localized = []
    for item in items:
        label = item[label_key]
        localized.append({"slug": item["slug"], "label": localize_chinese_text(label, lang)})
    return localized


def match_business_items(text: str, items: list[dict], lang: str, limit: int = 2) -> list[dict[str, str]]:
    haystack = text.lower()
    matches = []
    for item in items:
        score = sum(1 for keyword in item["keywords"] if keyword.lower() in haystack)
        if score:
            label = item["label_en"] if lang == "en" else localize_chinese_text(item["label_zh_hant"], lang)
            matches.append({"slug": item["slug"], "label": label, "score": score})
    matches.sort(key=lambda item: (-item["score"], item["label"]))
    return [{"slug": item["slug"], "label": item["label"]} for item in matches[:limit]]


def business_band_identity(band_rank: int | None, band_label: str | None, lang: str = "en") -> dict[str, str]:
    names = {
        1: ("Core Economist Vocabulary", "Economist 核心詞彙"),
        2: ("Business Insight Vocabulary", "商務洞察詞彙"),
        3: ("Sector Precision Vocabulary", "行業精準詞彙"),
        4: ("Executive / Analytical Vocabulary", "高階分析詞彙"),
        5: ("Elite Editorial Lexicon", "菁英社論詞庫"),
    }
    english, chinese = names.get(band_rank or 0, ("Business Economist Vocabulary", "商務 Economist 詞彙"))
    label = english if lang == "en" else localize_chinese_text(chinese, lang)
    return {**band_display_identity(band_label, lang), "business_label": label}


def business_word_search_text(word: dict) -> str:
    chinese = " ".join(str(item) for item in word.get("chinese_preview", []))
    parts = " ".join(str(item) for item in word.get("parts_of_speech", []))
    return " ".join(
        [
            str(word.get("lemma", "")),
            str(word.get("english_definition", "")),
            str(word.get("example_sentence", "")),
            chinese,
            parts,
        ]
    )


def attach_business_tags(word: dict, lang: str) -> dict:
    text = business_word_search_text(word)
    sectors = match_business_items(text, BUSINESS_SECTORS, lang)
    topics = match_business_items(text, BUSINESS_TOPICS, lang)
    skills = match_business_items(text, BUSINESS_SKILLS, lang)
    if not sectors:
        sectors = [localized_business_taxonomy(BUSINESS_SECTORS, lang)[0]]
    if not topics:
        topics = [localized_business_taxonomy(BUSINESS_TOPICS, lang)[0]]
    if not skills:
        skills = [localized_business_taxonomy(BUSINESS_SKILLS, lang)[0]]
    band_identity = business_band_identity(word.get("best_band_rank"), word.get("best_band_label"), lang)
    return {
        **word,
        "business_band_label": band_identity["business_label"],
        "band_tone": band_identity["tone"],
        "sectors": sectors,
        "topics": topics,
        "skills": skills,
    }


def business_filter_matches(word: dict, sector: str, topic: str, skill: str) -> bool:
    return (
        (not sector or any(item["slug"] == sector for item in word["sectors"]))
        and (not topic or any(item["slug"] == topic for item in word["topics"]))
        and (not skill or any(item["slug"] == skill for item in word["skills"]))
    )


def business_vocab_seed_cards(conn: sqlite3.Connection, band_rank: int | None, lang: str) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if band_rank is not None:
        clauses.append("words.best_band_rank = ?")
        params.append(band_rank)
    rows = conn.execute(
        f"""
        SELECT words.id, words.lemma, words.best_band_label, words.best_band_rank,
               COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
               COALESCE(word_enrichment.english_definition, '') AS english_definition,
               COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        WHERE {' AND '.join(clauses)}
        ORDER BY words.best_band_rank, words.lemma
        LIMIT 450
        """,
        params,
    ).fetchall()
    word_ids = [row["id"] for row in rows]
    definitions_map = definitions_map_for_words(conn, word_ids, lang)
    parts_map = parts_of_speech_map_for_words(conn, word_ids)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    cards = []
    for row in rows:
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        cards.append(
            {
                "id": row["id"],
                "lemma": row["lemma"],
                "best_band_label": row["best_band_label"],
                "best_band_rank": row["best_band_rank"],
                "english_definition": row["english_definition"] or source_fallback["english_definition"],
                "example_sentence": row["example_sentence"] or source_fallback["example_sentence"],
                "pronunciation": row["pronunciation"] or source_fallback["pronunciation"],
                "parts_of_speech": parts_map.get(row["id"], []),
                "chinese_preview": definitions_map.get(row["id"], [])[:2],
            }
        )
    return cards


def business_vocabulary_cards(
    conn: sqlite3.Connection,
    *,
    q: str,
    band_rank: int | None,
    sector: str,
    topic: str,
    skill: str,
    lang: str,
) -> list[dict]:
    if q.strip():
        candidates = search_result_cards(conn, q, band_rank=band_rank, require_english=False, require_example=False, lang=lang)
    else:
        candidates = business_vocab_seed_cards(conn, band_rank, lang)
    tagged = [attach_business_tags(word, lang) for word in candidates]
    return [word for word in tagged if business_filter_matches(word, sector, topic, skill)][:120]


def missed_words(conn: sqlite3.Connection, limit: int = 100, lang: str = "en", user_id: int = USER_ID) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        WITH wrong_answers AS (
            SELECT assessment_questions.word_id, assessment_questions.answered_at AS seen_at, 'test' AS source
            FROM assessment_questions
            JOIN assessment_sessions ON assessment_sessions.id = assessment_questions.session_id
            WHERE assessment_questions.is_correct = 0
              AND assessment_sessions.user_id = ?
            UNION ALL
            SELECT learning_questions.word_id, learning_questions.answered_at AS seen_at, 'learning' AS source
            FROM learning_questions
            JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
            WHERE learning_questions.is_correct = 0
              AND learning_sessions.user_id = ?
        )
        SELECT
            words.id,
            words.lemma,
            words.best_band_label,
            COUNT(*) AS miss_count,
            MAX(wrong_answers.seen_at) AS last_seen,
            user_study_cards.status,
            user_study_cards.next_review_at,
            user_study_cards.streak,
            COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
            COALESCE(word_enrichment.english_definition, '') AS english_definition,
            COALESCE(word_enrichment.example_sentence, '') AS example_sentence
        FROM wrong_answers
        JOIN words ON words.id = wrong_answers.word_id
        JOIN user_study_cards ON user_study_cards.word_id = words.id AND user_study_cards.user_id = ?
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        GROUP BY words.id, words.lemma, words.best_band_label, user_study_cards.status, user_study_cards.next_review_at, user_study_cards.streak,
                 word_enrichment.pronunciation, word_enrichment.english_definition, word_enrichment.example_sentence
        ORDER BY
            CASE WHEN user_study_cards.next_review_at IS NOT NULL AND user_study_cards.next_review_at <= ? THEN 0 ELSE 1 END,
            miss_count DESC,
            last_seen DESC
        LIMIT ?
        """,
        (user_id, user_id, user_id, utc_now_iso(), limit),
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
                "status": row["status"],
                "next_review_at": row["next_review_at"],
                "streak": row["streak"],
                "is_due": bool(row["next_review_at"] and row["next_review_at"] <= utc_now_iso()),
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


def test_word_score(conn: sqlite3.Connection, session_id: int, word_id: int) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
            COUNT(*) AS total
        FROM assessment_questions
        WHERE session_id = ? AND word_id = ? AND answered_at IS NOT NULL
        """,
        (session_id, word_id),
    ).fetchone()
    correct = int(row["correct"] or 0) if row else 0
    total = int(row["total"] or 0) if row else 0
    return {"correct": correct, "total": total}


def learning_word_score(conn: sqlite3.Connection, session_id: int, word_id: int) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
            COUNT(*) AS total
        FROM learning_questions
        WHERE session_id = ? AND word_id = ? AND answered_at IS NOT NULL
        """,
        (session_id, word_id),
    ).fetchone()
    correct = int(row["correct"] or 0) if row else 0
    total = int(row["total"] or 0) if row else 0
    return {"correct": correct, "total": total}


def test_question_by_id(conn: sqlite3.Connection, session_id: int, question_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM assessment_questions
        WHERE session_id = ? AND id = ?
        """,
        (session_id, question_id),
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
    target_pos = parts_of_speech_for_word(conn, word_id)
    options: list[str] = []

    if target_pos:
        placeholders = ",".join("?" for _ in target_pos)
        rows = conn.execute(
            f"""
            SELECT DISTINCT source_entries.word_id, source_entries.meanings_json
            FROM source_entries
            WHERE source_entries.band_rank = ?
              AND source_entries.word_id != ?
              AND source_entries.meanings_json <> '[]'
              AND source_entries.pos IN ({placeholders})
            ORDER BY RANDOM()
            LIMIT 40
            """,
            (band_rank, word_id, *target_pos),
        ).fetchall()
        for row in rows:
            for meaning in json_loads(row["meanings_json"]):
                if meaning not in options:
                    options.append(meaning)
                if len(options) >= limit:
                    return options

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


def english_definition_for_word(conn: sqlite3.Connection, word_id: int) -> str:
    enrichment = conn.execute(
        "SELECT english_definition FROM word_enrichment WHERE word_id = ?",
        (word_id,),
    ).fetchone()
    if enrichment is not None and enrichment["english_definition"]:
        return enrichment["english_definition"].strip()
    return source_fallback_for_word(conn, word_id)["english_definition"].strip()


def example_sentence_for_word(conn: sqlite3.Connection, word_id: int) -> str:
    word = conn.execute("SELECT lemma FROM words WHERE id = ?", (word_id,)).fetchone()
    if word is not None:
        seeded_sentence = LEVEL_TEST_EXAMPLE_SENTENCES.get(word["lemma"].strip().lower(), "")
        if seeded_sentence:
            return seeded_sentence
    enrichment = conn.execute(
        "SELECT example_sentence FROM word_enrichment WHERE word_id = ?",
        (word_id,),
    ).fetchone()
    if enrichment is not None and enrichment["example_sentence"]:
        return enrichment["example_sentence"].strip()
    return source_fallback_for_word(conn, word_id)["example_sentence"].strip()


def first_quality_relation(values: list[str], lemma: str) -> str:
    for value in values:
        clean = str(value).strip()
        if clean and not shares_obvious_root(lemma, clean):
            return clean
    return ""


def level_test_synonym_for_word(conn: sqlite3.Connection, word: sqlite3.Row) -> str:
    enrichment = conn.execute(
        "SELECT synonyms_json FROM word_enrichment WHERE word_id = ?",
        (word["id"],),
    ).fetchone()
    if enrichment is not None:
        candidate = first_quality_relation(json_loads(enrichment["synonyms_json"]), word["lemma"])
        if candidate:
            return candidate
    return LEVEL_TEST_SYNONYMS.get(word["lemma"].strip().lower(), "")


def level_test_antonym_for_word(conn: sqlite3.Connection, word: sqlite3.Row) -> str:
    enrichment = conn.execute(
        "SELECT antonyms_json FROM word_enrichment WHERE word_id = ?",
        (word["id"],),
    ).fetchone()
    if enrichment is not None:
        candidate = first_quality_relation(json_loads(enrichment["antonyms_json"]), word["lemma"])
        if candidate:
            return candidate
    return LEVEL_TEST_ANTONYMS.get(word["lemma"].strip().lower(), "")


NEGATIVE_PREFIXES = ("dis", "un", "in", "im", "il", "ir", "non", "anti", "de", "mis")
COMMON_SUFFIXES = ("ing", "ed", "ly", "ness", "ment", "tion", "sion", "able", "ible", "al", "ous", "ive", "er", "est", "y", "s")


def normalized_choice(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def light_stem(value: str) -> str:
    word = normalized_choice(value)
    for prefix in NEGATIVE_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 4:
            word = word[len(prefix):]
            break
    for suffix in COMMON_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    return word


def shares_obvious_root(left: str, right: str) -> bool:
    first = normalized_choice(left)
    second = normalized_choice(right)
    if not first or not second:
        return False
    if first == second:
        return True
    if len(first) >= 4 and len(second) >= 4 and (first in second or second in first):
        return True
    return light_stem(first) == light_stem(second)


def valid_blanked_sentence(value: str) -> bool:
    clean = (value or "").strip()
    return clean.count("____") == 1 and len(clean.split()) >= 5


def word_choice_is_quality(target: str, correct: str, candidate: str) -> bool:
    clean = (candidate or "").strip()
    if not clean:
        return False
    candidate_key = clean.lower()
    if candidate_key in {target.lower(), correct.lower()}:
        return False
    if shares_obvious_root(target, clean) or shares_obvious_root(correct, clean):
        return False
    return True


def option_words(conn: sqlite3.Connection, word: sqlite3.Row, correct: str, limit: int = 3) -> list[str]:
    options: list[str] = []
    target_pos = parts_of_speech_for_word(conn, word["id"])
    pos_clause = ""
    params: list[object] = [word["id"], correct, word["best_band_rank"]]
    if target_pos:
        placeholders = ",".join("?" for _ in target_pos)
        pos_clause = f"AND source_entries.pos IN ({placeholders})"
        params.extend(target_pos)
    rows = conn.execute(
        f"""
        SELECT DISTINCT words.lemma
        FROM words
        LEFT JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
          AND lower(lemma) != lower(?)
          AND words.best_band_rank = ?
          {pos_clause}
        ORDER BY RANDOM()
        LIMIT 120
        """,
        tuple(params),
    ).fetchall()
    for row in rows:
        value = row["lemma"].strip()
        if word_choice_is_quality(word["lemma"], correct, value) and value not in options:
            options.append(value)
        if len(options) >= limit:
            return options
    fallback = conn.execute(
        """
        SELECT lemma
        FROM words
        WHERE id != ?
          AND lower(lemma) != lower(?)
        ORDER BY RANDOM()
        LIMIT 160
        """,
        (word["id"], correct),
    ).fetchall()
    for row in fallback:
        value = row["lemma"].strip()
        if word_choice_is_quality(word["lemma"], correct, value) and value not in options:
            options.append(value)
        if len(options) >= limit:
            return options
    return options


def english_definition_distractors(conn: sqlite3.Connection, word_id: int, limit: int = 3) -> list[str]:
    options: list[str] = []
    target = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    target_pos = parts_of_speech_for_word(conn, word_id)
    pos_clause = ""
    params: list[object] = [word_id]
    if target is not None and target["best_band_rank"]:
        pos_clause += " AND words.best_band_rank = ?"
        params.append(target["best_band_rank"])
    if target_pos:
        placeholders = ",".join("?" for _ in target_pos)
        pos_clause += f" AND source_entries.pos IN ({placeholders})"
        params.extend(target_pos)
    rows = conn.execute(
        f"""
        SELECT DISTINCT words.id
        FROM words
        JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
          {pos_clause}
        ORDER BY RANDOM()
        LIMIT 120
        """,
        tuple(params),
    ).fetchall()
    for row in rows:
        definition = english_definition_for_word(conn, row["id"])
        if definition and definition not in options:
            options.append(definition)
        if len(options) >= limit:
            return options
    fallback = conn.execute(
        """
        SELECT DISTINCT words.id
        FROM words
        JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
        ORDER BY RANDOM()
        LIMIT 160
        """,
        (word_id,),
    ).fetchall()
    for row in fallback:
        definition = english_definition_for_word(conn, row["id"])
        if definition and definition not in options:
            options.append(definition)
        if len(options) >= limit:
            return options
    return options


def example_sentence_distractors(conn: sqlite3.Connection, word_id: int, limit: int = 3) -> list[str]:
    options: list[str] = []
    target = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    target_pos = parts_of_speech_for_word(conn, word_id)
    pos_clause = ""
    params: list[object] = [word_id]
    if target is not None and target["best_band_rank"]:
        pos_clause += " AND words.best_band_rank = ?"
        params.append(target["best_band_rank"])
    if target_pos:
        placeholders = ",".join("?" for _ in target_pos)
        pos_clause += f" AND source_entries.pos IN ({placeholders})"
        params.extend(target_pos)
    rows = conn.execute(
        f"""
        SELECT DISTINCT words.id, words.lemma
        FROM words
        JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
          {pos_clause}
        ORDER BY RANDOM()
        LIMIT 160
        """,
        tuple(params),
    ).fetchall()
    for row in rows:
        sentence = example_sentence_for_word(conn, row["id"])
        blanked = blank_word_in_sentence(sentence, row["lemma"])
        if blanked and valid_blanked_sentence(blanked) and blanked not in options:
            options.append(blanked)
        if len(options) >= limit:
            return options
    fallback = conn.execute(
        """
        SELECT DISTINCT words.id, words.lemma
        FROM words
        JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
        ORDER BY RANDOM()
        LIMIT 200
        """,
        (word_id,),
    ).fetchall()
    for row in fallback:
        sentence = example_sentence_for_word(conn, row["id"])
        blanked = blank_word_in_sentence(sentence, row["lemma"])
        if blanked and valid_blanked_sentence(blanked) and blanked not in options:
            options.append(blanked)
        if len(options) >= limit:
            return options
    return options


def build_level_test_options(correct: str, distractors: list[str], validator=None) -> list[str] | None:
    options = [correct]
    seen = {str(correct).strip().lower()}
    for value in distractors:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen and (validator is None or validator(clean)):
            options.append(clean)
            seen.add(key)
        if len(options) >= 4:
            break
    if len(options) < 4:
        return None
    random.shuffle(options)
    return options[:4]


def build_chinese_definition_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    meanings = definitions_for_word(conn, word["id"])
    if not meanings:
        return None
    correct = meanings[0]
    options = build_level_test_options(
        correct,
        distractor_definitions(conn, band_rank=word["best_band_rank"], word_id=word["id"]),
    )
    if options is None:
        return None
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "chinese_definition",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options, ensure_ascii=False),
        "explanation": "Layer 1: select the correct Chinese definition.",
    }


def build_english_definition_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    correct = english_definition_for_word(conn, word["id"])
    if not correct:
        return None
    options = build_level_test_options(correct, english_definition_distractors(conn, word["id"]))
    if options is None:
        return None
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "english_definition",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options, ensure_ascii=False),
        "explanation": "Layer 2: select the correct English definition.",
    }


def build_example_application_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    sentence = example_sentence_for_word(conn, word["id"])
    correct = blank_word_in_sentence(sentence, word["lemma"])
    if not correct or not valid_blanked_sentence(correct):
        return None
    options = build_level_test_options(
        correct,
        example_sentence_distractors(conn, word["id"]),
        validator=valid_blanked_sentence,
    )
    if options is None:
        return None
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "example_application",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options, ensure_ascii=False),
        "explanation": "Layer 3: select the sentence where this word fits naturally in the blank.",
    }


def build_similar_word_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    correct = level_test_synonym_for_word(conn, word)
    if not correct or shares_obvious_root(word["lemma"], correct):
        return None
    options = build_level_test_options(
        correct,
        option_words(conn, word, correct),
        validator=lambda value: word_choice_is_quality(word["lemma"], correct, value),
    )
    if options is None:
        return None
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "similar_word",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options, ensure_ascii=False),
        "explanation": "Layer 4: select the most similar English word.",
    }


def build_opposite_word_question(conn: sqlite3.Connection, word: sqlite3.Row, position: int) -> dict | None:
    correct = level_test_antonym_for_word(conn, word)
    if not correct or shares_obvious_root(word["lemma"], correct):
        return None
    options = build_level_test_options(
        correct,
        option_words(conn, word, correct),
        validator=lambda value: word_choice_is_quality(word["lemma"], correct, value),
    )
    if options is None:
        return None
    return {
        "position": position,
        "word_id": word["id"],
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "question_type": "opposite_word",
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options, ensure_ascii=False),
        "explanation": "Layer 5: select the opposite English word.",
    }


LEVEL_TEST_BUILDERS = (
    build_chinese_definition_question,
    build_english_definition_question,
    build_example_application_question,
    build_similar_word_question,
    build_opposite_word_question,
)


def blank_word_in_sentence(sentence: str, lemma: str) -> str | None:
    clean_sentence = (sentence or "").strip()
    clean_lemma = (lemma or "").strip()
    if not clean_sentence or not clean_lemma:
        return None
    parts = [re.escape(part) for part in clean_lemma.split()]
    if not parts:
        return None
    pattern = r"\b" + r"\s+".join(parts) + r"\b"
    blanked = re.sub(pattern, "____", clean_sentence, count=1, flags=re.IGNORECASE)
    if blanked == clean_sentence:
        return None
    return blanked


def sentence_distractor_options(conn: sqlite3.Connection, word: sqlite3.Row, limit: int = 3) -> list[str]:
    options: list[str] = []
    enrichment = conn.execute(
        """
        SELECT sentence_distractors_json
        FROM word_enrichment
        WHERE word_id = ?
        """,
        (word["id"],),
    ).fetchone()
    if enrichment is not None:
        for sentence in json_loads(enrichment["sentence_distractors_json"]):
            clean = blank_word_in_sentence(sentence, word["lemma"])
            if clean and clean not in options:
                options.append(clean)
            if len(options) >= limit:
                return options

    target_pos = parts_of_speech_for_word(conn, word["id"])
    pos_clause = ""
    params: list[object] = [word["id"]]
    if target_pos:
        placeholders = ",".join("?" for _ in target_pos)
        pos_clause = f"AND source_entries.pos IN ({placeholders})"
        params.extend(target_pos)

    rows = conn.execute(
        f"""
        SELECT DISTINCT
            words.id AS other_word_id,
            words.lemma AS other_lemma,
            COALESCE(NULLIF(word_enrichment.example_sentence, ''), '') AS stored_example
        FROM words
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        LEFT JOIN source_entries ON source_entries.word_id = words.id
        WHERE words.id != ?
          {pos_clause}
        ORDER BY RANDOM()
        LIMIT 80
        """,
        tuple(params),
    ).fetchall()
    for row in rows:
        example_sentence = row["stored_example"] or source_fallback_for_word(conn, row["other_word_id"])["example_sentence"]
        clean = blank_word_in_sentence(example_sentence, row["other_lemma"])
        if clean and clean not in options:
            options.append(clean)
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
    source_fallback = source_fallback_for_word(conn, word["id"])
    example_sentence = ""
    if enrichment is not None and enrichment["example_sentence"]:
        example_sentence = enrichment["example_sentence"].strip()
    elif source_fallback["example_sentence"]:
        example_sentence = source_fallback["example_sentence"].strip()
    if not example_sentence:
        return None
    correct = blank_word_in_sentence(example_sentence, word["lemma"])
    if not correct:
        return None
    options = [correct] + sentence_distractor_options(conn, word, limit=3)
    if len(options) < 4:
        return None
    random.shuffle(options)
    return {
        "position": position,
        "word_id": word["id"],
        "question_type": "sentence",
        "band_rank": word["best_band_rank"],
        "band_label": word["best_band_label"],
        "prompt_text": word["lemma"],
        "correct_option": correct,
        "options_json": json.dumps(options[:4], ensure_ascii=False),
        "explanation": "Choose the sentence where this word fits naturally in the blank.",
    }


def level_test_candidate_words(conn: sqlite3.Connection, band_rank: int, limit: int = 180) -> list[sqlite3.Row]:
    seeded_lemmas = sorted(set(LEVEL_TEST_SYNONYMS).intersection(LEVEL_TEST_ANTONYMS))
    seeded_clause = ""
    params: list[object] = [band_rank]
    if band_rank in STUDENT_DSE_BANDS:
        dse_to_economist = {value: key for key, value in ECONOMIST_TO_STUDENT_DSE_RANK.items()}
        params.append(dse_to_economist.get(band_rank, 2000))
    if seeded_lemmas:
        placeholders = ",".join("?" for _ in seeded_lemmas)
        seeded_clause = f"OR lower(words.lemma) IN ({placeholders})"
        params.extend(seeded_lemmas)
    params.append(limit)
    if band_rank in STUDENT_DSE_BANDS:
        source_clause = "(student_dse_vocab.dse_band_rank = ? OR words.best_band_rank = ?)"
        source_join = "LEFT JOIN student_dse_vocab ON student_dse_vocab.word_id = words.id"
    else:
        source_clause = "words.best_band_rank = ?"
        source_join = ""
    return conn.execute(
        f"""
        SELECT words.*, COUNT(assessment_questions.id) AS test_use_count
        FROM words
        {source_join}
        JOIN source_entries ON source_entries.word_id = words.id
        LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
        LEFT JOIN assessment_questions ON assessment_questions.word_id = words.id
        WHERE {source_clause}
          AND source_entries.meanings_json <> '[]'
          AND (
            (
              COALESCE(word_enrichment.synonyms_json, '[]') <> '[]'
              AND COALESCE(word_enrichment.antonyms_json, '[]') <> '[]'
            )
            {seeded_clause}
        )
        GROUP BY words.id
        ORDER BY test_use_count ASC, RANDOM()
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()


def create_test_session(conn: sqlite3.Connection, user_id: int = USER_ID) -> int:
    band_rows = student_dse_band_rows(conn, user_id=user_id)
    questions: list[dict] = []
    position = 1
    used_word_ids: set[int] = set()
    band_word_counts: dict[int, int] = defaultdict(int)
    for band in band_rows:
        rows = level_test_candidate_words(conn, band["best_band_rank"])
        for word in rows:
            if word["id"] in used_word_ids:
                continue
            if not level_test_synonym_for_word(conn, word) or not level_test_antonym_for_word(conn, word):
                continue
            word_questions: list[dict] = []
            for offset, builder in enumerate(LEVEL_TEST_BUILDERS):
                question = builder(conn, word, position + offset)
                if question is None:
                    word_questions = []
                    break
                question["band_rank"] = band["best_band_rank"]
                question["band_label"] = band["best_band_label"]
                word_questions.append(question)
            if len(word_questions) != TEST_LAYERS_PER_WORD:
                continue
            questions.extend(word_questions)
            position += TEST_LAYERS_PER_WORD
            used_word_ids.add(word["id"])
            band_word_counts[band["best_band_rank"]] += 1
            if band_word_counts[band["best_band_rank"]] >= TEST_WORDS_PER_BAND:
                break
        if band_word_counts[band["best_band_rank"]] < TEST_WORDS_PER_BAND:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough level-test-ready words in band {band['best_band_label']}",
            )
    if len(questions) != TEST_QUESTION_COUNT:
        raise HTTPException(status_code=400, detail="Not enough level-test-ready words to build a 100-point test")

    cursor = conn.execute(
        """
        INSERT INTO assessment_sessions (user_id)
        VALUES (?)
        """,
        (user_id,),
    )
    session_id = cursor.lastrowid
    for question in questions:
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


def recommended_learning_band_rank(conn: sqlite3.Connection, user_id: int = USER_ID) -> int:
    latest_test = latest_test_result(conn, user_id=user_id)
    if latest_test is not None and latest_test["estimated_band_rank"] in STUDENT_DSE_BANDS:
        reverse_map = {value: key for key, value in ECONOMIST_TO_STUDENT_DSE_RANK.items()}
        return reverse_map.get(int(latest_test["estimated_band_rank"]), 2000)
    if latest_test is not None and latest_test["estimated_band_rank"] in TEST_BAND_EASIEST_TO_HARDEST:
        return int(latest_test["estimated_band_rank"])
    return 2000


def learning_band_cards(conn: sqlite3.Connection, lang: str = "en", user_id: int = USER_ID) -> list[dict]:
    return student_dse_band_rows(conn, lang, user_id)


def create_learning_session(conn: sqlite3.Connection, band_rank: int | None = None, user_id: int = USER_ID, assignment_id: int | None = None) -> int:
    if band_rank in STUDENT_DSE_BANDS:
        selected_rank = int(band_rank)
    elif band_rank in ECONOMIST_TO_STUDENT_DSE_RANK:
        selected_rank = ECONOMIST_TO_STUDENT_DSE_RANK[int(band_rank)]
    else:
        selected_rank = recommended_student_dse_band_rank(conn, user_id)
    band_config = STUDENT_DSE_BANDS.get(selected_rank)
    if band_config is None:
        raise HTTPException(status_code=400, detail="Selected DSE learning band was not found")
    dse_to_economist = {value: key for key, value in ECONOMIST_TO_STUDENT_DSE_RANK.items()}
    fallback_economist_rank = dse_to_economist.get(selected_rank, 2000)
    conn.execute(
        """
        INSERT OR IGNORE INTO user_study_cards (
            user_id, word_id, status, correct_count, wrong_count, streak, ease,
            interval_days, notes, last_reviewed_at, next_review_at
        )
        SELECT
            ?, words.id,
            COALESCE(study_cards.status, 'new'),
            COALESCE(study_cards.correct_count, 0),
            COALESCE(study_cards.wrong_count, 0),
            COALESCE(study_cards.streak, 0),
            COALESCE(study_cards.ease, 2.5),
            COALESCE(study_cards.interval_days, 0),
            COALESCE(study_cards.notes, ''),
            study_cards.last_reviewed_at,
            study_cards.next_review_at
        FROM words
        LEFT JOIN study_cards ON study_cards.word_id = words.id
        LEFT JOIN student_dse_vocab ON student_dse_vocab.word_id = words.id
        WHERE student_dse_vocab.dse_band_rank = ? OR words.best_band_rank = ?
        """,
        (user_id, selected_rank, fallback_economist_rank),
    )
    cursor = conn.execute(
        """
        INSERT INTO learning_sessions (user_id, band_rank, band_label, assignment_id)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, selected_rank, band_config["label"], assignment_id),
    )
    session_id = cursor.lastrowid
    words = conn.execute(
        """
        SELECT DISTINCT words.*, COUNT(learning_questions.id) AS learning_use_count
        FROM words
        JOIN user_study_cards ON user_study_cards.word_id = words.id AND user_study_cards.user_id = ?
        LEFT JOIN student_dse_vocab ON student_dse_vocab.word_id = words.id
        JOIN source_entries ON source_entries.word_id = words.id
        LEFT JOIN learning_questions ON learning_questions.word_id = words.id
        WHERE source_entries.meanings_json <> '[]'
          AND (student_dse_vocab.dse_band_rank = ? OR words.best_band_rank = ?)
        GROUP BY words.id
        ORDER BY
            CASE WHEN student_dse_vocab.dse_band_rank = ? THEN 0 ELSE 1 END,
            CASE
                WHEN user_study_cards.next_review_at IS NOT NULL AND user_study_cards.next_review_at <= ? THEN 0
                WHEN user_study_cards.wrong_count > 0 THEN 1
                WHEN user_study_cards.status = 'learning' THEN 2
                WHEN user_study_cards.status = 'new' THEN 3
                ELSE 4
            END,
            user_study_cards.wrong_count DESC,
            user_study_cards.next_review_at,
            learning_use_count ASC,
            RANDOM()
        """,
        (user_id, selected_rank, fallback_economist_rank, selected_rank, utc_now_iso()),
    ).fetchall()
    populate_learning_session(conn, session_id, words)
    total_questions = conn.execute(
        "SELECT COUNT(*) FROM learning_questions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if total_questions != LEARNING_QUESTION_COUNT:
        conn.execute("DELETE FROM learning_questions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM learning_sessions WHERE id = ?", (session_id,))
        conn.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Not enough learning-ready words in band {band_config['label']}",
        )
    return session_id


def populate_learning_session(conn: sqlite3.Connection, session_id: int, words: list[sqlite3.Row]) -> None:
    position = 1
    used_word_ids: set[int] = set()
    for word in words:
        if len(used_word_ids) >= LEARNING_WORD_COUNT:
            break
        if not level_test_synonym_for_word(conn, word) or not level_test_antonym_for_word(conn, word):
            continue
        added_for_word = 0
        word_questions: list[dict] = []
        for offset, builder in enumerate(LEVEL_TEST_BUILDERS):
            question = builder(conn, word, position + offset)
            if question is None:
                word_questions = []
                break
            word_questions.append(question)
        if len(word_questions) != LEARNING_LAYERS_PER_WORD:
            continue
        for question in word_questions:
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


def create_weak_words_learning_session(conn: sqlite3.Connection, user_id: int, lang: str = "en") -> int:
    missed = missed_words(conn, limit=LEARNING_WORD_COUNT * 3, lang=lang, user_id=user_id)
    word_ids = [item["id"] for item in missed]
    if not word_ids:
        raise HTTPException(status_code=400, detail="No missed words are ready for review yet")
    placeholders = ",".join("?" for _ in word_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT words.*
        FROM words
        WHERE words.id IN ({placeholders})
        ORDER BY CASE words.id
            {" ".join(f"WHEN ? THEN {index}" for index, _ in enumerate(word_ids))}
            ELSE {len(word_ids)}
        END
        """,
        (*word_ids, *word_ids),
    ).fetchall()
    primary = rows[0]
    cursor = conn.execute(
        """
        INSERT INTO learning_sessions (user_id, band_rank, band_label)
        VALUES (?, ?, ?)
        """,
        (user_id, primary["best_band_rank"], primary["best_band_label"]),
    )
    session_id = cursor.lastrowid
    populate_learning_session(conn, session_id, rows)
    total_questions = conn.execute(
        "SELECT COUNT(*) FROM learning_questions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if total_questions == 0:
        conn.execute("DELETE FROM learning_sessions WHERE id = ?", (session_id,))
        conn.commit()
        raise HTTPException(status_code=400, detail="No missed words are ready for review yet")
    return session_id


def create_learning_retry_session(conn: sqlite3.Connection, source_session_id: int) -> int:
    source_session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (source_session_id,)).fetchone()
    cursor = conn.execute(
        """
        INSERT INTO learning_sessions (user_id, band_rank, band_label)
        VALUES (?, ?, ?)
        """,
        (
            source_session["user_id"] if source_session else USER_ID,
            source_session["band_rank"] if source_session else None,
            source_session["band_label"] if source_session else None,
        ),
    )
    session_id = cursor.lastrowid
    rows = conn.execute(
        """
        SELECT DISTINCT words.*
        FROM learning_questions
        JOIN words ON words.id = learning_questions.word_id
        WHERE learning_questions.session_id = ?
          AND COALESCE(learning_questions.is_correct, 0) = 0
        ORDER BY learning_questions.position
        """,
        (source_session_id,),
    ).fetchall()
    populate_learning_session(conn, session_id, rows)
    return session_id


def test_progress(session: sqlite3.Row) -> dict:
    total = int(session["question_total"]) if "question_total" in session.keys() else TEST_QUESTION_COUNT
    current = session["current_index"] + 1
    answered = session["current_index"]
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


def finish_test_session(conn: sqlite3.Connection, session_id: int) -> dict:
    summary = summarize_test_session(conn, session_id)
    conn.execute(
        """
        UPDATE assessment_sessions
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            score = ?,
            question_count = ?,
            accuracy_percent = ?,
            weighted_percent = ?,
            estimated_band_rank = ?,
            estimated_band_label = ?
        WHERE id = ?
        """,
        (
            summary["total_correct"],
            summary["question_count"],
            summary["accuracy_percent"],
            summary["weighted_percent"],
            summary["estimated_rank"],
            summary["estimated_label"],
            session_id,
        ),
    )
    conn.commit()
    return summary


def summarize_test_session(conn: sqlite3.Connection, session_id: int) -> dict:
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
    ordered_source = list(STUDENT_DSE_BANDS) if any(rank in STUDENT_DSE_BANDS for rank in band_scores) else TEST_BAND_EASIEST_TO_HARDEST
    ordered_ranks = [rank for rank in ordered_source if rank in band_scores]
    for band_rank in ordered_ranks:
        answers = band_scores[band_rank]
        weight = 1 + ordered_ranks.index(band_rank)
        weighted_score += sum(answers) * weight
        weighted_total += len(answers) * weight
        if answers and sum(answers) / len(answers) >= 0.6:
            estimated_rank = band_rank
            estimated_label = labels[band_rank]
    accuracy_percent = round((total_correct / len(rows)) * 100) if rows else 0
    weighted_percent = round((weighted_score / weighted_total) * 100) if weighted_total else 0
    return {
        "accuracy_percent": accuracy_percent,
        "weighted_percent": weighted_percent,
        "estimated_rank": estimated_rank,
        "estimated_label": estimated_label,
        "total_correct": total_correct,
        "question_count": len(rows),
    }


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
    mode = request.query_params.get("mode", "guest")
    auth_error = request.query_params.get("auth_error", "")
    return render(
        request,
        "landing.html",
        landing_mode=mode if mode in {"guest", "registered"} else "guest",
        auth_error=auth_error,
    )


@app.get("/dashboard", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    try:
        conn = db_conn()
        profile_name = get_profile_name(request)
        profile_persona = get_profile_persona(request)
        if profile_persona is None:
            return RedirectResponse(url=build_home_url(lang), status_code=303)
        user_id = current_user_id(request)
        stats = fetch_stats(conn, user_id)
        latest_test = latest_test_result(conn, user_id=user_id)
        latest_learning = latest_learning_result(conn, user_id)
        active_test = active_test_session(conn, user_id)
        active_learning = active_learning_session(conn, user_id)
        recommended_band = latest_test["estimated_band_label"] if latest_test else "Core DSE Survival"
        bands = student_dse_band_rows(conn, lang, user_id) if profile_persona == "student" else decorate_band_rows(band_summary(conn))
        dashboard_vocab_total = sum(int(band["workbook_total"] or 0) for band in bands[:5])
        max_band_total = max((band["workbook_total"] for band in bands), default=1)
        hero_band_chart = [
            {
                "label": band["range_label"],
                "title": band["title"],
                "subtitle": band["subtitle"],
                "tone": band["tone"],
                "count": band["workbook_total"],
                "percent": max(18, round((band["workbook_total"] / max_band_total) * 100)),
            }
            for band in bands[:5]
        ]
        missed_words_count = len(missed_words(conn, limit=10, user_id=user_id))
        spotlight_words = dashboard_spotlight_words(conn)
        today_plan_items = student_today_plan_items(
            latest_test=latest_test,
            active_test=active_test,
            active_learning=active_learning,
            latest_learning=latest_learning,
            missed_count=missed_words_count,
        )
    except Exception:
        profile_name = (request.cookies.get("profile_name") or "Lawrence").strip()[:40] or "Lawrence"
        profile_persona = request.cookies.get("profile_persona") if request.cookies.get("profile_persona") in SUPPORTED_PERSONAS else "lifelong_learner"
        stats = {
            "total_words": 0,
            "words_with_synonyms": 0,
            "words_with_examples": 0,
            "tests_taken": 0,
            "learning_runs": 0,
        }
        latest_test = None
        latest_learning = None
        active_test = None
        active_learning = None
        recommended_band = "50~99 (3924)"
        bands = []
        dashboard_vocab_total = 0
        hero_band_chart = []
        missed_words_count = 0
        spotlight_words = []
        today_plan_items = []
    dashboard_quote = random.choice(HOME_QUOTES)
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
        active_test=active_test,
        active_learning=active_learning,
        recommended_band=recommended_band,
        dashboard_vocab_total=dashboard_vocab_total,
        missed_words_count=missed_words_count,
        today_plan_items=today_plan_items,
        spotlight_words=spotlight_words,
        hero_band_chart=hero_band_chart,
        dashboard_quote=dashboard_quote,
        ai_power=ai_power_track(lang),
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


def auth_redirect_url(lang: str, *, error_key: str = "", mode: str = "registered") -> str:
    params = []
    if mode:
        params.append(("mode", mode))
    if error_key:
        params.append(("auth_error", error_key))
    if lang != "en":
        params.append(("lang", lang))
    query = urlencode(params)
    return f"/?{query}" if query else "/"


@app.post("/auth/signup")
def auth_signup(
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    persona: str = Form("lifelong_learner"),
    teacher_invite_code: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    safe_name = (display_name or "").strip()[:40]
    safe_email = normalized_email(email)
    safe_persona = persona if persona in SUPPORTED_PERSONAS else "lifelong_learner"
    if not safe_name:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_name_required"), status_code=303)
    if not valid_email(safe_email):
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_email_required"), status_code=303)
    if len(password or "") < 8:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_password_short"), status_code=303)
    if password != confirm_password:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_password_mismatch"), status_code=303)
    if safe_persona == "teacher" and not teacher_invite_code_valid(teacher_invite_code):
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_teacher_invite_required"), status_code=303)
    existing = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (safe_email,)).fetchone()
    if existing is not None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_email_taken"), status_code=303)
    username_seed = re.sub(r"[^a-z0-9]+", "_", safe_email.split("@", 1)[0]).strip("_") or "user"
    username = username_seed
    suffix = 1
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        suffix += 1
        username = f"{username_seed}_{suffix}"
    cursor = conn.execute(
        """
        INSERT INTO users (username, email, password_hash, display_name, persona, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (username, safe_email, hash_password(password), safe_name, safe_persona, role_for_persona(safe_persona)),
    )
    conn.commit()
    user_id = cursor.lastrowid
    response = RedirectResponse(url=(f"/dashboard?lang={lang}" if lang != "en" else "/dashboard"), status_code=303)
    response.set_cookie("registered_user_id", str(user_id), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    response.set_cookie("profile_name", safe_name, max_age=60 * 60 * 24 * 365)
    response.set_cookie("profile_persona", safe_persona, max_age=60 * 60 * 24 * 365)
    return response


@app.post("/auth/login")
def auth_login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    safe_email = normalized_email(email)
    user = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (safe_email,)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        return RedirectResponse(url=auth_redirect_url(lang, error_key="auth_error_invalid_login"), status_code=303)
    response = RedirectResponse(url=(f"/dashboard?lang={lang}" if lang != "en" else "/dashboard"), status_code=303)
    response.set_cookie("registered_user_id", str(user["id"]), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    response.set_cookie("profile_name", (user["display_name"] or "Lawrence")[:40], max_age=60 * 60 * 24 * 365)
    response.set_cookie("profile_persona", (user["persona"] or "lifelong_learner"), max_age=60 * 60 * 24 * 365)
    return response


@app.post("/auth/logout")
def auth_logout(request: Request) -> RedirectResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    response = RedirectResponse(url=build_home_url(lang), status_code=303)
    response.delete_cookie("registered_user_id")
    response.delete_cookie("profile_name")
    response.delete_cookie("profile_persona")
    return response


PERSONA_OPTIONS = [
    {"value": "student", "label_key": "persona_student"},
    {"value": "teacher", "label_key": "persona_teacher"},
    {"value": "business_professional", "label_key": "persona_business"},
    {"value": "ai_power_user", "label_key": "persona_ai"},
    {"value": "lifelong_learner", "label_key": "persona_lifelong"},
]


def account_redirect_url(lang: str, message_key: str = "") -> str:
    params = []
    if message_key:
        params.append(("message", message_key))
    if lang != "en":
        params.append(("lang", lang))
    query = urlencode(params)
    return f"/account?{query}" if query else "/account"


def teacher_redirect_url(lang: str, message_key: str = "") -> str:
    params = []
    if message_key:
        params.append(("message", message_key))
    if lang != "en":
        params.append(("lang", lang))
    query = urlencode(params)
    return f"/teacher?{query}" if query else "/teacher"


def parse_db_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days_since_db_datetime(value: str | None) -> int | None:
    parsed = parse_db_datetime(value)
    if parsed is None:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def percent_value(correct: int, total: int) -> int | None:
    return round((correct / total) * 100) if total else None


def latest_activity_at(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute(
        """
        SELECT MAX(activity_at) AS last_active
        FROM (
            SELECT started_at AS activity_at FROM assessment_sessions WHERE user_id = ?
            UNION ALL SELECT completed_at FROM assessment_sessions WHERE user_id = ? AND completed_at IS NOT NULL
            UNION ALL SELECT assessment_questions.answered_at
            FROM assessment_questions
            JOIN assessment_sessions ON assessment_sessions.id = assessment_questions.session_id
            WHERE assessment_sessions.user_id = ? AND assessment_questions.answered_at IS NOT NULL
            UNION ALL SELECT started_at FROM learning_sessions WHERE user_id = ?
            UNION ALL SELECT completed_at FROM learning_sessions WHERE user_id = ? AND completed_at IS NOT NULL
            UNION ALL SELECT learning_questions.answered_at
            FROM learning_questions
            JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
            WHERE learning_sessions.user_id = ? AND learning_questions.answered_at IS NOT NULL
            UNION ALL SELECT created_at FROM word_mastery_attempts WHERE user_id = ?
        )
        """,
        (user_id, user_id, user_id, user_id, user_id, user_id, user_id),
    ).fetchone()
    return row["last_active"] if row and row["last_active"] else ""


def weak_question_type_for_user(conn: sqlite3.Connection, user_id: int, lang: str) -> dict:
    rows = conn.execute(
        """
        SELECT question_type,
               SUM(correct) AS correct,
               SUM(total) AS total
        FROM (
            SELECT assessment_questions.question_type,
                   SUM(CASE WHEN assessment_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct,
                   COUNT(*) AS total
            FROM assessment_questions
            JOIN assessment_sessions ON assessment_sessions.id = assessment_questions.session_id
            WHERE assessment_sessions.user_id = ?
              AND assessment_questions.is_correct IS NOT NULL
            GROUP BY assessment_questions.question_type
            UNION ALL
            SELECT learning_questions.question_type,
                   SUM(CASE WHEN learning_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct,
                   COUNT(*) AS total
            FROM learning_questions
            JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
            WHERE learning_sessions.user_id = ?
              AND learning_questions.is_correct IS NOT NULL
            GROUP BY learning_questions.question_type
        )
        GROUP BY question_type
        HAVING total > 0
        """,
        (user_id, user_id),
    ).fetchall()
    if not rows:
        return {"label": translate(lang, "not_enough_data"), "accuracy": None, "question_type": ""}
    weakest = min(rows, key=lambda row: ((row["correct"] or 0) / max(row["total"] or 1, 1), -(row["total"] or 0)))
    accuracy = percent_value(int(weakest["correct"] or 0), int(weakest["total"] or 0))
    return {
        "label": translate_question_type(weakest["question_type"], lang),
        "accuracy": accuracy,
        "question_type": weakest["question_type"],
    }


def learning_summary_for_user(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT learning_sessions.id) AS completed_sessions,
               SUM(CASE WHEN learning_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct,
               COUNT(learning_questions.id) AS total
        FROM learning_sessions
        LEFT JOIN learning_questions ON learning_questions.session_id = learning_sessions.id
            AND learning_questions.is_correct IS NOT NULL
        WHERE learning_sessions.user_id = ?
          AND learning_sessions.status = 'completed'
        """,
        (user_id,),
    ).fetchone()
    correct = int(row["correct"] or 0) if row else 0
    total = int(row["total"] or 0) if row else 0
    return {
        "completed_sessions": int(row["completed_sessions"] or 0) if row else 0,
        "correct": correct,
        "total": total,
        "accuracy": percent_value(correct, total),
    }


def admin_activity_union_sql() -> str:
    return """
        SELECT user_id, started_at AS activity_at, 'level_test' AS activity_type
        FROM assessment_sessions
        WHERE started_at IS NOT NULL
        UNION ALL
        SELECT user_id, completed_at AS activity_at, 'level_test_completed' AS activity_type
        FROM assessment_sessions
        WHERE completed_at IS NOT NULL
        UNION ALL
        SELECT assessment_sessions.user_id, assessment_questions.answered_at AS activity_at, 'level_test_answer' AS activity_type
        FROM assessment_questions
        JOIN assessment_sessions ON assessment_sessions.id = assessment_questions.session_id
        WHERE assessment_questions.answered_at IS NOT NULL
        UNION ALL
        SELECT user_id, started_at AS activity_at, 'learning' AS activity_type
        FROM learning_sessions
        WHERE started_at IS NOT NULL
        UNION ALL
        SELECT user_id, completed_at AS activity_at, 'learning_completed' AS activity_type
        FROM learning_sessions
        WHERE completed_at IS NOT NULL
        UNION ALL
        SELECT learning_sessions.user_id, learning_questions.answered_at AS activity_at, 'learning_answer' AS activity_type
        FROM learning_questions
        JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
        WHERE learning_questions.answered_at IS NOT NULL
        UNION ALL
        SELECT user_id, created_at AS activity_at, 'deep_learning' AS activity_type
        FROM word_mastery_attempts
        WHERE created_at IS NOT NULL
    """


def admin_snapshot(conn: sqlite3.Connection) -> dict:
    users = conn.execute(
        """
        SELECT
            COUNT(*) AS total_users,
            SUM(CASE WHEN role = 'teacher' OR persona = 'teacher' THEN 1 ELSE 0 END) AS teachers,
            SUM(CASE WHEN role = 'student' OR role = '' OR role IS NULL THEN 1 ELSE 0 END) AS students
        FROM users
        """
    ).fetchone()
    classes = conn.execute("SELECT COUNT(*) AS total FROM teacher_classes").fetchone()
    today = datetime.now(timezone.utc).date().isoformat()
    active_today = conn.execute(
        f"""
        SELECT COUNT(DISTINCT user_id) AS total
        FROM ({admin_activity_union_sql()})
        WHERE DATE(activity_at) = DATE(?)
        """,
        (today,),
    ).fetchone()
    active_7day = conn.execute(
        f"""
        SELECT COUNT(DISTINCT user_id) AS total
        FROM ({admin_activity_union_sql()})
        WHERE DATE(activity_at) >= DATE(?, '-6 day')
        """,
        (today,),
    ).fetchone()
    tests_today = conn.execute("SELECT COUNT(*) AS total FROM assessment_sessions WHERE DATE(started_at) = DATE(?)", (today,)).fetchone()
    learning_today = conn.execute("SELECT COUNT(*) AS total FROM learning_sessions WHERE DATE(started_at) = DATE(?)", (today,)).fetchone()
    mastery_today = conn.execute("SELECT COUNT(*) AS total FROM word_mastery_attempts WHERE DATE(created_at) = DATE(?)", (today,)).fetchone()
    return {
        "total_users": int(users["total_users"] or 0),
        "teachers": int(users["teachers"] or 0),
        "students": int(users["students"] or 0),
        "classes": int(classes["total"] or 0),
        "active_today": int(active_today["total"] or 0),
        "active_7day": int(active_7day["total"] or 0),
        "tests_today": int(tests_today["total"] or 0),
        "learning_today": int(learning_today["total"] or 0),
        "deep_learning_today": int(mastery_today["total"] or 0),
    }


def admin_daily_usage_rows(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT DATE(activity_at) AS activity_date,
               COUNT(DISTINCT user_id) AS active_users,
               SUM(CASE WHEN activity_type = 'level_test' THEN 1 ELSE 0 END) AS level_tests,
               SUM(CASE WHEN activity_type = 'learning' THEN 1 ELSE 0 END) AS learning_sessions,
               SUM(CASE WHEN activity_type = 'deep_learning' THEN 1 ELSE 0 END) AS mastery_attempts
        FROM ({admin_activity_union_sql()})
        WHERE DATE(activity_at) >= DATE('now', ?)
        GROUP BY DATE(activity_at)
        ORDER BY activity_date DESC
        """,
        (f"-{max(1, days) - 1} day",),
    ).fetchall()
    by_date = {row["activity_date"]: row for row in rows}
    today = datetime.now(timezone.utc).date()
    result = []
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        row = by_date.get(day)
        result.append(
            {
                "date": day,
                "active_users": int(row["active_users"] or 0) if row else 0,
                "level_tests": int(row["level_tests"] or 0) if row else 0,
                "learning_sessions": int(row["learning_sessions"] or 0) if row else 0,
                "mastery_attempts": int(row["mastery_attempts"] or 0) if row else 0,
            }
        )
    return result


def admin_user_overview_rows(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT users.id, users.username, users.email, users.display_name, users.persona, users.role, users.created_at,
               COUNT(DISTINCT assessment_sessions.id) AS tests,
               COUNT(DISTINCT learning_sessions.id) AS learning_sessions,
               COUNT(DISTINCT word_mastery_attempts.id) AS deep_learning_attempts
        FROM users
        LEFT JOIN assessment_sessions ON assessment_sessions.user_id = users.id
        LEFT JOIN learning_sessions ON learning_sessions.user_id = users.id
        LEFT JOIN word_mastery_attempts ON word_mastery_attempts.user_id = users.id
        GROUP BY users.id
        ORDER BY users.created_at DESC, users.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for row in rows:
        last_active = latest_activity_at(conn, int(row["id"]))
        result.append(
            {
                "id": int(row["id"]),
                "display_name": row["display_name"] or row["username"] or f"User {row['id']}",
                "email": row["email"] or "",
                "role": row["role"] or role_for_persona(row["persona"] or "student"),
                "persona": row["persona"] or "",
                "created_at": row["created_at"],
                "last_active": last_active,
                "last_active_days": days_since_db_datetime(last_active),
                "tests": int(row["tests"] or 0),
                "learning_sessions": int(row["learning_sessions"] or 0),
                "deep_learning_attempts": int(row["deep_learning_attempts"] or 0),
            }
        )
    return result


def risk_status_for_student(latest_score: int | None, learning_accuracy: int | None, last_active: str) -> str:
    inactive_days = days_since_db_datetime(last_active)
    if inactive_days is None:
        return "high"
    if inactive_days >= 7 or (learning_accuracy is not None and learning_accuracy < 60) or (latest_score is not None and latest_score < 60):
        return "high"
    if inactive_days >= 3 or (learning_accuracy is not None and learning_accuracy < 70) or latest_score is None:
        return "medium"
    return "low"


def class_weak_question_type(student_rows: list[dict], lang: str) -> dict:
    weakest_rows = [row["weak_question_type"] for row in student_rows if row["weak_question_type"]["accuracy"] is not None]
    if not weakest_rows:
        return {"label": translate(lang, "not_enough_data"), "accuracy": None, "question_type": ""}
    return min(weakest_rows, key=lambda row: row["accuracy"])


def teacher_student_progress_rows(conn: sqlite3.Connection, students: list[sqlite3.Row], lang: str) -> list[dict]:
    progress_rows: list[dict] = []
    for student in students:
        user_id = int(student["id"])
        latest_test = latest_test_result(conn, user_id=user_id)
        learning = learning_summary_for_user(conn, user_id)
        weak_type = weak_question_type_for_user(conn, user_id, lang)
        last_active = latest_activity_at(conn, user_id) or student["joined_at"]
        latest_score = int(latest_test["score"]) if latest_test and latest_test["score"] is not None else None
        risk = risk_status_for_student(latest_score, learning["accuracy"], last_active)
        next_action_key = "teacher_action_extend"
        next_action_kwargs: dict[str, str] = {}
        if latest_score is None:
            next_action_key = "teacher_action_retest"
        elif risk == "high":
            next_action_key = "teacher_action_remind"
        elif weak_type["accuracy"] is not None and weak_type["accuracy"] < 75:
            next_action_key = "teacher_action_review"
            next_action_kwargs = {"question_type": weak_type["label"]}
        progress_rows.append(
            {
                "id": user_id,
                "display_name": student["display_name"] or student["username"],
                "email": student["email"] or "",
                "joined_at": student["joined_at"],
                "latest_test_score": latest_score,
                "recommended_band": latest_test["estimated_band_label"] if latest_test else "",
                "learning_sessions": learning["completed_sessions"],
                "learning_accuracy": learning["accuracy"],
                "weak_question_type": weak_type,
                "last_active": last_active,
                "last_active_days": days_since_db_datetime(last_active),
                "risk": risk,
                "risk_label": translate(lang, f"risk_{risk}"),
                "next_action": translate(lang, next_action_key, **next_action_kwargs),
            }
        )
    return progress_rows


def teacher_class_snapshot(student_rows: list[dict], lang: str) -> dict:
    student_count = len(student_rows)
    active_count = sum(1 for row in student_rows if row["last_active_days"] is not None and row["last_active_days"] <= 7)
    scores = [row["latest_test_score"] for row in student_rows if row["latest_test_score"] is not None]
    learning_accuracies = [row["learning_accuracy"] for row in student_rows if row["learning_accuracy"] is not None]
    avg_score = round(sum(scores) / len(scores)) if scores else None
    avg_learning_accuracy = round(sum(learning_accuracies) / len(learning_accuracies)) if learning_accuracies else None
    at_risk_count = sum(1 for row in student_rows if row["risk"] == "high")
    weakest = class_weak_question_type(student_rows, lang)
    return {
        "student_count": student_count,
        "active_students": active_count,
        "avg_level_score": avg_score,
        "avg_learning_accuracy": avg_learning_accuracy,
        "learning_sessions": sum(row["learning_sessions"] for row in student_rows),
        "at_risk_students": at_risk_count,
        "weakest_type": weakest,
    }


def teacher_recommendation_rows(snapshot: dict, student_rows: list[dict], lang: str) -> list[str]:
    recommendations: list[str] = []
    inactive_count = sum(1 for row in student_rows if row["last_active_days"] is None or row["last_active_days"] >= 7)
    low_accuracy_count = sum(
        1 for row in student_rows
        if (row["learning_accuracy"] is not None and row["learning_accuracy"] < 60)
        or (row["latest_test_score"] is not None and row["latest_test_score"] < 60)
    )
    weakest = snapshot["weakest_type"]
    if inactive_count:
        recommendations.append(translate(lang, "teacher_recommend_inactive", count=inactive_count))
    if low_accuracy_count:
        recommendations.append(translate(lang, "teacher_recommend_accuracy", count=low_accuracy_count))
    if weakest["accuracy"] is not None and weakest["accuracy"] < 70:
        recommendations.append(translate(lang, "teacher_recommend_weak_type", question_type=weakest["label"]))
    return recommendations


def teacher_dashboard_snapshot(classes: list[dict], assignments: list[dict]) -> dict:
    return {
        "total_classes": len(classes),
        "total_students": sum(int(item["snapshot"]["student_count"]) for item in classes),
        "active_students": sum(int(item["snapshot"]["active_students"]) for item in classes),
        "at_risk_students": sum(int(item["snapshot"]["at_risk_students"]) for item in classes),
        "open_assignments": len(assignments),
    }


def assignment_type_label(value: str, lang: str) -> str:
    safe_value = value if value in {"band_practice", "weak_review", "deep_learning"} else "band_practice"
    return translate(lang, f"assignment_type_{safe_value}")


def teacher_assignment_rows(conn: sqlite3.Connection, teacher_user_id: int, lang: str = "en") -> list[dict]:
    rows = conn.execute(
        """
        SELECT class_assignments.*,
               teacher_classes.name AS class_name,
               COUNT(DISTINCT class_memberships.student_user_id) AS student_count,
               COUNT(DISTINCT CASE WHEN learning_sessions.status = 'completed' THEN learning_sessions.user_id END) AS completed_count,
               AVG(CASE WHEN learning_sessions.status = 'completed' THEN learning_sessions.score END) AS avg_score
        FROM class_assignments
        JOIN teacher_classes ON teacher_classes.id = class_assignments.class_id
        LEFT JOIN class_memberships ON class_memberships.class_id = class_assignments.class_id
        LEFT JOIN learning_sessions ON learning_sessions.assignment_id = class_assignments.id
        WHERE class_assignments.teacher_user_id = ?
        GROUP BY class_assignments.id
        ORDER BY class_assignments.created_at DESC, class_assignments.id DESC
        """,
        (teacher_user_id,),
    ).fetchall()
    assignments: list[dict] = []
    for row in rows:
        student_count = int(row["student_count"] or 0)
        completed_count = int(row["completed_count"] or 0)
        assignments.append(
            {
                "row": row,
                "student_count": student_count,
                "completed_count": completed_count,
                "completion_percent": round((completed_count / student_count) * 100) if student_count else 0,
                "avg_score": round(float(row["avg_score"])) if row["avg_score"] is not None else None,
                "type_label": assignment_type_label(row["assignment_type"] or "band_practice", lang),
            }
        )
    return assignments


def student_assignment_rows(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT class_assignments.*,
               teacher_classes.name AS class_name,
               teacher.display_name AS teacher_name,
               latest.session_id,
               latest.status AS session_status,
               latest.score AS session_score
        FROM class_memberships
        JOIN teacher_classes ON teacher_classes.id = class_memberships.class_id
        JOIN users AS teacher ON teacher.id = teacher_classes.teacher_user_id
        JOIN class_assignments ON class_assignments.class_id = teacher_classes.id
        LEFT JOIN (
            SELECT assignment_id, user_id, MAX(id) AS session_id, status, score
            FROM learning_sessions
            WHERE user_id = ? AND assignment_id IS NOT NULL
            GROUP BY assignment_id, user_id
        ) AS latest ON latest.assignment_id = class_assignments.id
        WHERE class_memberships.student_user_id = ?
        ORDER BY class_assignments.created_at DESC, class_assignments.id DESC
        """,
        (user_id, user_id),
    ).fetchall()
    return [dict(row) for row in rows]


def teacher_class_rows(conn: sqlite3.Connection, teacher_user_id: int, lang: str = "en") -> list[dict]:
    rows = conn.execute(
        """
        SELECT teacher_classes.*,
               COUNT(class_memberships.id) AS student_count
        FROM teacher_classes
        LEFT JOIN class_memberships ON class_memberships.class_id = teacher_classes.id
        WHERE teacher_classes.teacher_user_id = ?
        GROUP BY teacher_classes.id
        ORDER BY teacher_classes.created_at DESC, teacher_classes.id DESC
        """,
        (teacher_user_id,),
    ).fetchall()
    classes: list[dict] = []
    for row in rows:
        students = conn.execute(
            """
            SELECT users.id, users.username, users.display_name, users.email, class_memberships.joined_at
            FROM class_memberships
            JOIN users ON users.id = class_memberships.student_user_id
            WHERE class_memberships.class_id = ?
            ORDER BY class_memberships.joined_at DESC
            """,
            (row["id"],),
        ).fetchall()
        student_progress = teacher_student_progress_rows(conn, students, lang)
        snapshot = teacher_class_snapshot(student_progress, lang)
        classes.append(
            {
                "row": row,
                "students": students,
                "student_progress": student_progress,
                "snapshot": snapshot,
                "recommendations": teacher_recommendation_rows(snapshot, student_progress, lang),
            }
        )
    return classes


def teacher_class_csv_response(conn: sqlite3.Connection, teacher_user_id: int, class_id: int, lang: str) -> Response | None:
    row = conn.execute(
        "SELECT * FROM teacher_classes WHERE id = ? AND teacher_user_id = ?",
        (class_id, teacher_user_id),
    ).fetchone()
    if row is None:
        return None
    students = conn.execute(
        """
        SELECT users.id, users.username, users.display_name, users.email, class_memberships.joined_at
        FROM class_memberships
        JOIN users ON users.id = class_memberships.student_user_id
        WHERE class_memberships.class_id = ?
        ORDER BY class_memberships.joined_at DESC
        """,
        (class_id,),
    ).fetchall()
    progress = teacher_student_progress_rows(conn, students, lang)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "student",
            "email",
            "latest_test_score",
            "recommended_band",
            "learning_accuracy",
            "learning_sessions",
            "weak_area",
            "last_active_days",
            "risk",
            "next_action",
        ]
    )
    for student in progress:
        writer.writerow(
            [
                student["display_name"],
                student["email"],
                student["latest_test_score"] if student["latest_test_score"] is not None else "",
                student["recommended_band"],
                student["learning_accuracy"] if student["learning_accuracy"] is not None else "",
                student["learning_sessions"],
                student["weak_question_type"]["label"],
                student["last_active_days"] if student["last_active_days"] is not None else "",
                student["risk_label"],
                student["next_action"],
            ]
        )
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", row["name"]).strip("-") or f"class-{class_id}"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}-report.csv"'},
    )


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, message: str = Query("")) -> HTMLResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    allowed_messages = {
        "account_profile_saved",
        "account_password_saved",
        "account_error_password_current",
        "auth_error_password_short",
        "auth_error_name_required",
        "auth_error_teacher_invite_required",
        "class_joined",
        "class_join_error",
    }
    return render(
        request,
        "account.html",
        user=user,
        persona_options=PERSONA_OPTIONS,
        message_key=message if message in allowed_messages else "",
    )


@app.post("/account/profile")
def account_profile_update(
    request: Request,
    display_name: str = Form(""),
    persona: str = Form("lifelong_learner"),
    teacher_invite_code: str = Form(""),
) -> RedirectResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    safe_name = display_name.strip()[:40]
    if not safe_name:
        return RedirectResponse(url=account_redirect_url(lang, "auth_error_name_required"), status_code=303)
    safe_persona = persona if persona in SUPPORTED_PERSONAS else "lifelong_learner"
    if safe_persona == "teacher" and not is_teacher_user(user) and not teacher_invite_code_valid(teacher_invite_code):
        return RedirectResponse(url=account_redirect_url(lang, "auth_error_teacher_invite_required"), status_code=303)
    conn = db_conn()
    conn.execute(
        """
        UPDATE users
        SET display_name = ?, persona = ?, role = ?
        WHERE id = ?
        """,
        (safe_name, safe_persona, role_for_persona(safe_persona), user["id"]),
    )
    conn.commit()
    response = RedirectResponse(url=account_redirect_url(lang, "account_profile_saved"), status_code=303)
    response.set_cookie("profile_name", safe_name, max_age=60 * 60 * 24 * 365)
    response.set_cookie("profile_persona", safe_persona, max_age=60 * 60 * 24 * 365)
    return response


@app.post("/account/password")
def account_password_update(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
) -> RedirectResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not verify_password(current_password, user["password_hash"]):
        return RedirectResponse(url=account_redirect_url(lang, "account_error_password_current"), status_code=303)
    if len(new_password or "") < 8:
        return RedirectResponse(url=account_redirect_url(lang, "auth_error_password_short"), status_code=303)
    conn = db_conn()
    conn.execute(
        """
        UPDATE users
        SET password_hash = ?
        WHERE id = ?
        """,
        (hash_password(new_password), user["id"]),
    )
    conn.commit()
    return RedirectResponse(url=account_redirect_url(lang, "account_password_saved"), status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> HTMLResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not is_admin_user(user):
        return render(request, "admin_dashboard.html", user=user, allowed=False)
    conn = db_conn()
    return render(
        request,
        "admin_dashboard.html",
        user=user,
        allowed=True,
        snapshot=admin_snapshot(conn),
        daily_usage=admin_daily_usage_rows(conn),
        users=admin_user_overview_rows(conn),
    )


@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request, message: str = Query("")) -> HTMLResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not is_teacher_user(user):
        return render(request, "teacher_dashboard.html", user=user, classes=[], message_key="teacher_only")
    allowed_messages = {"account_profile_saved", "teacher_assignment_created"}
    conn = db_conn()
    classes = teacher_class_rows(conn, int(user["id"]), lang)
    assignments = teacher_assignment_rows(conn, int(user["id"]), lang)
    return render(
        request,
        "teacher_dashboard.html",
        user=user,
        classes=classes,
        assignments=assignments,
        teacher_snapshot=teacher_dashboard_snapshot(classes, assignments),
        bands=student_dse_band_rows(conn, lang, int(user["id"])),
        message_key=message if message in allowed_messages else "",
    )


@app.post("/teacher/classes")
def teacher_class_create(request: Request, name: str = Form("")) -> RedirectResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not is_teacher_user(user):
        return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)
    safe_name = (name or "").strip()[:80]
    if not safe_name:
        safe_name = "New Class"
    conn = db_conn()
    conn.execute(
        """
        INSERT INTO teacher_classes (teacher_user_id, name, invite_code)
        VALUES (?, ?, ?)
        """,
        (user["id"], safe_name, generate_invite_code(conn)),
    )
    conn.commit()
    return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)


@app.post("/teacher/assignments")
def teacher_assignment_create(
    request: Request,
    class_id: int = Form(...),
    title: str = Form(""),
    band_rank: int = Form(2000),
    assignment_type: str = Form("band_practice"),
    due_date: str = Form(""),
) -> RedirectResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not is_teacher_user(user):
        return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)
    conn = db_conn()
    class_row = conn.execute(
        "SELECT id FROM teacher_classes WHERE id = ? AND teacher_user_id = ?",
        (class_id, user["id"]),
    ).fetchone()
    if class_row is None:
        return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)
    selected_rank = band_rank if band_rank in STUDENT_DSE_BANDS else 1
    safe_assignment_type = assignment_type if assignment_type in {"band_practice", "weak_review", "deep_learning"} else "band_practice"
    band_label = STUDENT_DSE_BANDS.get(selected_rank, STUDENT_DSE_BANDS[1])["label"]
    safe_title = (title or "").strip()[:100] or f"{band_label} Practice"
    safe_due = (due_date or "").strip()[:20]
    conn.execute(
        """
        INSERT INTO class_assignments (class_id, teacher_user_id, title, band_rank, band_label, assignment_type, due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (class_id, user["id"], safe_title, selected_rank, band_label, safe_assignment_type, safe_due),
    )
    conn.commit()
    return RedirectResponse(url=teacher_redirect_url(lang, "teacher_assignment_created"), status_code=303)


@app.get("/teacher/classes/{class_id}/report.csv")
def teacher_class_report_export(request: Request, class_id: int) -> Response:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    if not is_teacher_user(user):
        return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)
    response = teacher_class_csv_response(db_conn(), int(user["id"]), class_id, lang)
    if response is None:
        return RedirectResponse(url=teacher_redirect_url(lang), status_code=303)
    return response


@app.post("/classes/join")
def class_join(request: Request, invite_code: str = Form("")) -> RedirectResponse:
    user = registered_user_row(request)
    lang = getattr(request.state, "lang", get_lang(request))
    if user is None:
        return RedirectResponse(url=auth_redirect_url(lang, error_key="account_login_required"), status_code=303)
    code = re.sub(r"[^A-Z0-9]", "", (invite_code or "").upper())
    conn = db_conn()
    class_row = conn.execute("SELECT id FROM teacher_classes WHERE invite_code = ?", (code,)).fetchone()
    if class_row is None:
        return RedirectResponse(url=account_redirect_url(lang, "class_join_error"), status_code=303)
    conn.execute(
        """
        INSERT OR IGNORE INTO class_memberships (class_id, student_user_id)
        VALUES (?, ?)
        """,
        (class_row["id"], user["id"]),
    )
    conn.commit()
    return RedirectResponse(url=account_redirect_url(lang, "class_joined"), status_code=303)


@app.get("/test", response_class=HTMLResponse)
def test_intro(request: Request) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    lang = getattr(request.state, "lang", get_lang(request))
    active_test = active_test_session(conn, user_id=user_id)
    return render(
        request,
        "test_intro.html",
        bands=student_dse_band_rows(conn, lang, user_id),
        question_count=TEST_QUESTION_COUNT,
        vocab_count=TEST_VOCAB_COUNT,
        words_per_band=TEST_WORDS_PER_BAND,
        layers_per_word=TEST_LAYERS_PER_WORD,
        has_test_history=latest_test_result(conn, user_id=user_id) is not None,
        active_test=active_test,
        active_test_progress=test_progress(active_test) if active_test is not None else None,
    )


@app.get("/test/history", response_class=HTMLResponse)
def test_history(request: Request) -> HTMLResponse:
    conn = db_conn()
    return render(request, "test_history.html", history=test_history_rows(conn, user_id=current_user_id(request)))


@app.get("/quality/feedback", response_class=HTMLResponse)
def quality_feedback(request: Request, status: str = Query("open")) -> HTMLResponse:
    conn = db_conn()
    safe_status = status if status in {"open", "reviewed"} else "open"
    return render(
        request,
        "quality_feedback.html",
        rows=question_feedback_rows(conn, status=safe_status),
        status=safe_status,
    )


@app.post("/quality/feedback/{feedback_id}/reviewed")
def quality_feedback_reviewed(request: Request, feedback_id: int) -> RedirectResponse:
    conn = db_conn()
    conn.execute(
        """
        UPDATE question_feedback
        SET status = 'reviewed',
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (feedback_id,),
    )
    conn.commit()
    lang = getattr(request.state, "lang", get_lang(request))
    return RedirectResponse(url=f"/quality/feedback?lang={lang}", status_code=303)


@app.post("/quality/feedback/{feedback_id}/repair")
def quality_feedback_repair(
    request: Request,
    feedback_id: int,
    english_definition: str = Form(""),
    pronunciation: str = Form(""),
    synonyms: str = Form(""),
    antonyms: str = Form(""),
    example_sentence: str = Form(""),
    sentence_distractors: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    feedback = conn.execute("SELECT * FROM question_feedback WHERE id = ?", (feedback_id,)).fetchone()
    if feedback is None or feedback["word_id"] is None:
        return RedirectResponse(url="/quality/feedback", status_code=303)
    synonym_items = [item.strip() for item in synonyms.splitlines() if item.strip()]
    antonym_items = [item.strip() for item in antonyms.splitlines() if item.strip()]
    distractor_items = [item.strip() for item in sentence_distractors.splitlines() if item.strip()]
    conn.execute(
        """
        INSERT INTO word_enrichment (
            word_id,
            english_definition,
            pronunciation,
            synonyms_json,
            antonyms_json,
            example_sentence,
            sentence_distractors_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(word_id) DO UPDATE SET
            english_definition = excluded.english_definition,
            pronunciation = excluded.pronunciation,
            synonyms_json = excluded.synonyms_json,
            antonyms_json = excluded.antonyms_json,
            example_sentence = excluded.example_sentence,
            sentence_distractors_json = excluded.sentence_distractors_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            feedback["word_id"],
            english_definition.strip(),
            pronunciation.strip(),
            json.dumps(synonym_items, ensure_ascii=False),
            json.dumps(antonym_items, ensure_ascii=False),
            example_sentence.strip(),
            json.dumps(distractor_items, ensure_ascii=False),
        ),
    )
    conn.execute(
        """
        UPDATE question_feedback
        SET status = 'reviewed',
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (feedback_id,),
    )
    conn.commit()
    lang = getattr(request.state, "lang", get_lang(request))
    return RedirectResponse(url=f"/quality/feedback?lang={lang}", status_code=303)


@app.get("/statistics", response_class=HTMLResponse)
def statistics_page(request: Request) -> HTMLResponse:
    try:
        return statistics_page_impl(request)
    except Exception:
        lang = getattr(request.state, "lang", get_lang(request))
        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html lang="en">
            <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Statistics | VocabLab AI</title></head>
            <body style="font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; max-width: 760px; margin: 48px auto; padding: 0 20px; line-height: 1.5;">
              <h1>Statistics</h1>
              <p>The statistics dashboard is available, but some saved history data could not be loaded on this deployment.</p>
              <p>統計頁可以使用，但這次部署有部分歷史紀錄暫時無法讀取。</p>
              <p><a href="/test/history">Open Level Test History</a> · <a href="/test">Start Level Test</a> · <a href="/learning">Open Learning</a></p>
            </body>
            </html>
            """,
            status_code=200,
            headers={"content-language": lang},
        )


def statistics_page_impl(request: Request) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    lang = getattr(request.state, "lang", get_lang(request))
    try:
        history = test_history_rows(conn, limit=5, full_only=True, user_id=user_id)
    except sqlite3.Error:
        history = []
    try:
        learning_history = learning_history_rows(conn, limit=5, user_id=user_id)
    except sqlite3.Error:
        learning_history = []
    latest = history[0] if history else None
    latest_learning = learning_history[0] if learning_history else None
    best = None
    best_learning = None
    max_question_total = max((item["total_questions"] or 0) for item in history) if history else 0
    score_scale_max = max_question_total or (max((item["score"] or 0) for item in history) if history else 0) or 1
    learning_scale_max = max((item["total_questions"] or 0) for item in learning_history) if learning_history else 0
    learning_scale_max = learning_scale_max or (max((item["score"] or 0) for item in learning_history) if learning_history else 0) or 1
    if history:
        best = max(
            history,
            key=lambda item: (
                item["score"] or 0,
                item["accuracy_percent"] if item["accuracy_percent"] is not None else -1,
                item["id"],
            ),
        )
    if learning_history:
        best_learning = max(
            learning_history,
            key=lambda item: (
                item["accuracy_percent"] if item["accuracy_percent"] is not None else -1,
                item["score"] or 0,
                item["id"],
            ),
        )

    def score_percent(item: dict | None) -> int:
        if not item:
            return 0
        score = int(item["score"] or 0)
        total = int(item["total_questions"] or 0) or score_scale_max
        return round((score / max(total, 1)) * 100)

    recent_chart: list[dict[str, int | str]] = []
    for index, item in enumerate(reversed(history), start=1):
        percent = score_percent(item)
        recent_chart.append(
            {
                "label": f"T{index}",
                "score": int(item["score"] or 0),
                "percent": percent,
                "height": max(18, percent),
            }
        )

    recent_line_points = ""
    recent_line_dots: list[dict[str, int | str]] = []
    if recent_chart:
        if len(recent_chart) == 1:
            item = recent_chart[0]
            x = 50
            y = max(6, 46 - round((int(item["percent"]) / 100) * 36))
            recent_line_points = f"{x},{y}"
            recent_line_dots.append({"x": x, "y": y, "label": item["label"], "score": item["score"]})
        else:
            for idx, item in enumerate(recent_chart):
                x = round((idx / (len(recent_chart) - 1)) * 100)
                y = max(6, 46 - round((int(item["percent"]) / 100) * 36))
                recent_line_dots.append({"x": x, "y": y, "label": item["label"], "score": item["score"]})
        recent_line_points = " ".join(f"{item['x']},{item['y']}" for item in recent_line_dots)

    def learning_percent(item: dict | None) -> int:
        if not item:
            return 0
        score = int(item["score"] or 0)
        total = int(item["total_questions"] or 0) or learning_scale_max
        return round((score / max(total, 1)) * 100)

    return render(
        request,
        "statistics.html",
        history=history,
        learning_history=learning_history,
        latest_test_history=latest,
        latest_learning_history=latest_learning,
        best_test_history=best,
        best_learning_history=best_learning,
        tests_taken_count=len(history),
        learning_runs_count=len(learning_history),
        statistics_advice=statistics_advice(conn, latest, latest_learning, lang),
        latest_test_percent=score_percent(latest),
        latest_learning_percent=learning_percent(latest_learning),
        best_test_percent=score_percent(best),
        best_learning_percent=learning_percent(best_learning),
        score_scale_max=score_scale_max,
        learning_scale_max=learning_scale_max,
        recent_chart=recent_chart,
        recent_line_points=recent_line_points,
        recent_line_dots=recent_line_dots,
    )


@app.post("/test/start")
def test_start(request: Request, force_new: int = Form(0)) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    if not force_new:
        active_test = active_test_session(conn, user_id=user_id)
        if active_test is not None:
            return RedirectResponse(url=f"/test/{active_test['id']}", status_code=303)
    session_id = create_test_session(conn, user_id)
    return RedirectResponse(url=f"/test/{session_id}", status_code=303)


@app.get("/test/{session_id}", response_class=HTMLResponse)
def test_question(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute(
        """
        SELECT assessment_sessions.*, COUNT(assessment_questions.id) AS question_total
        FROM assessment_sessions
        LEFT JOIN assessment_questions ON assessment_questions.session_id = assessment_sessions.id
        WHERE assessment_sessions.id = ? AND assessment_sessions.user_id = ?
        GROUP BY assessment_sessions.id
        """,
        (session_id, user_id),
    ).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question = current_test_question(conn, session_id)
    if question is None:
        finish_test_session(conn, session_id)
        return RedirectResponse(url=f"/test/{session_id}/result", status_code=303)
    lang = getattr(request.state, "lang", get_lang(request))
    band_identity = band_display_identity(question["band_label"], lang)
    return render(
        request,
        "test_question.html",
        session=session,
        question=question,
        word=word_payload(conn, question["word_id"], lang, user_id)["word"],
        band_identity=band_identity,
        question_instruction=question_instruction(question["question_type"], lang),
        options=json_loads(question["options_json"]),
        progress=test_progress(session),
    )


@app.post("/test/{session_id}/answer")
def test_answer(request: Request, session_id: int, answer: str = Form(...)) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
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
    update_study_card_schedule(conn, question["word_id"], bool(is_correct), "level_test", user_id)
    conn.commit()
    total_questions = conn.execute(
        "SELECT COUNT(*) FROM assessment_questions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if int(question["position"] or 0) >= int(total_questions or 0):
        finish_test_session(conn, session_id)
        return RedirectResponse(url=f"/test/{session_id}/review?question_id={question['id']}", status_code=303)
    if int(question["position"] or 0) % TEST_LAYERS_PER_WORD != 0:
        return RedirectResponse(url=f"/test/{session_id}", status_code=303)
    return RedirectResponse(url=f"/test/{session_id}/review?question_id={question['id']}", status_code=303)


@app.post("/test/{session_id}/feedback")
def test_feedback(
    request: Request,
    session_id: int,
    question_id: int = Form(...),
    reason: str = Form(...),
    comment: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT id FROM assessment_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question = test_question_by_id(conn, session_id, question_id)
    lang = getattr(request.state, "lang", get_lang(request))
    if question is None:
        return RedirectResponse(url=f"/test/{session_id}?lang={lang}", status_code=303)
    safe_reason = reason.strip()[:80]
    safe_comment = comment.strip()[:500]
    conn.execute(
        """
        INSERT INTO question_feedback (
            session_id, question_id, word_id, question_type, reason, comment
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            question_id,
            question["word_id"],
            question["question_type"],
            safe_reason,
            safe_comment,
        ),
    )
    conn.commit()
    referer = request.headers.get("referer") or f"/test/{session_id}/review?question_id={question_id}"
    return RedirectResponse(url=referer, status_code=303)


@app.get("/test/{session_id}/review", response_class=HTMLResponse)
def test_review(request: Request, session_id: int, question_id: int | None = Query(None)) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute(
        """
        SELECT assessment_sessions.*, COUNT(assessment_questions.id) AS question_total
        FROM assessment_sessions
        LEFT JOIN assessment_questions ON assessment_questions.session_id = assessment_sessions.id
        WHERE assessment_sessions.id = ? AND assessment_sessions.user_id = ?
        GROUP BY assessment_sessions.id
        """,
        (session_id, user_id),
    ).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question = test_question_by_id(conn, session_id, question_id) if question_id is not None else previous_test_question(conn, session_id)
    if question is None:
        return RedirectResponse(url=f"/test/{session_id}", status_code=303)
    lang = getattr(request.state, "lang", get_lang(request))
    payload = word_payload(conn, question["word_id"], lang, user_id)
    band_identity = band_display_identity(question["band_label"], lang)
    is_last = session["current_index"] >= session["question_total"]
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
        word_score=test_word_score(conn, session_id, question["word_id"]),
        band_identity=band_identity,
        is_last=is_last,
        progress=test_progress(session),
    )


@app.get("/test/{session_id}/result", response_class=HTMLResponse)
def test_result(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    question_count = conn.execute(
        "SELECT COUNT(*) FROM assessment_questions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if session["status"] != "completed":
        summary = finish_test_session(conn, session_id)
        session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
        has_detailed_results = question_count > 0
    elif question_count > 0:
        summary = summarize_test_session(conn, session_id)
        has_detailed_results = True
    else:
        summary = {
            "accuracy_percent": session["accuracy_percent"],
            "weighted_percent": session["weighted_percent"],
            "estimated_rank": session["estimated_band_rank"],
            "estimated_label": session["estimated_band_label"] or "Getting Started",
            "question_count": session["question_count"],
        }
        has_detailed_results = False
    if has_detailed_results and (
        session["question_count"] != summary["question_count"]
        or session["accuracy_percent"] != summary["accuracy_percent"]
        or session["weighted_percent"] != summary["weighted_percent"]
        or session["estimated_band_rank"] != summary["estimated_rank"]
        or session["estimated_band_label"] != summary["estimated_label"]
    ):
        conn.execute(
            """
            UPDATE assessment_sessions
            SET question_count = ?, accuracy_percent = ?, weighted_percent = ?, estimated_band_rank = ?, estimated_band_label = ?
            WHERE id = ?
            """,
            (
                summary["question_count"],
                summary["accuracy_percent"],
                summary["weighted_percent"],
                summary["estimated_rank"],
                summary["estimated_label"],
                session_id,
            ),
        )
        conn.commit()
        session = conn.execute("SELECT * FROM assessment_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    lang = getattr(request.state, "lang", get_lang(request))
    band_rows = band_accuracy_rows(conn, session_id, lang)
    layer_rows = layer_accuracy_rows(conn, session_id, lang)
    word_rows = word_report_rows(conn, session_id, lang, user_id) if has_detailed_results else []
    focus_rows = report_focus_rows(layer_rows)
    display_total_questions = summary["question_count"] if summary.get("question_count") else session["question_count"]
    display_accuracy_percent = summary["accuracy_percent"] if summary["accuracy_percent"] is not None else session["accuracy_percent"]
    accuracy_ratio = (display_accuracy_percent / 100) if display_accuracy_percent is not None else 0
    display_band_label = summary["estimated_label"] if has_detailed_results else (session["estimated_band_label"] or "Getting Started")
    display_band_rank = summary["estimated_rank"] if has_detailed_results else session["estimated_band_rank"]
    display_band_identity = band_display_identity(display_band_label, lang) if display_band_label != "Getting Started" else None
    level_name = band_level_label(display_band_rank, lang)
    recommendation = level_recommendation(display_band_label, display_band_rank, accuracy_ratio, lang)
    has_accuracy_visual = display_accuracy_percent is not None
    return render(
        request,
        "test_result.html",
        session=session,
        band_results=band_rows,
        layer_results=layer_rows,
        word_report_rows=word_rows,
        focus_rows=focus_rows,
        summary=summary,
        has_detailed_results=has_detailed_results,
        display_total_questions=display_total_questions,
        display_accuracy_percent=display_accuracy_percent,
        has_accuracy_visual=has_accuracy_visual,
        level_name=level_name,
        display_band_label=display_band_label,
        display_band_identity=display_band_identity,
        recommendation=recommendation,
        result_color=accuracy_color(display_accuracy_percent if display_accuracy_percent is not None else None),
    )


@app.get("/learning", response_class=HTMLResponse)
def learning_intro(request: Request) -> HTMLResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    user_id = current_user_id(request)
    enrichment = conn.execute(
        """
        SELECT
            COUNT(*) AS enriched_words,
            SUM(CASE WHEN json_array_length(synonyms_json) > 0 THEN 1 ELSE 0 END) AS synonym_ready,
            SUM(CASE WHEN example_sentence <> '' THEN 1 ELSE 0 END) AS sentence_ready
        FROM word_enrichment
        """
    ).fetchone()
    latest_learning = latest_learning_result(conn, user_id)
    recommended_rank = recommended_student_dse_band_rank(conn, user_id)
    recommended_band = STUDENT_DSE_BANDS.get(recommended_rank, STUDENT_DSE_BANDS[1])["label"]
    recommended_identity = band_display_identity(recommended_band, lang)
    return render(
        request,
        "learning_intro.html",
        stats=fetch_stats(conn, user_id),
        enrichment=enrichment,
        latest_learning=latest_learning,
        assignments=student_assignment_rows(conn, user_id),
        bands=learning_band_cards(conn, lang, user_id),
        recommended_band_rank=recommended_rank,
        recommended_band_identity=recommended_identity,
        learning_word_count=LEARNING_WORD_COUNT,
        learning_layers_per_word=LEARNING_LAYERS_PER_WORD,
        learning_question_count=LEARNING_QUESTION_COUNT,
    )


@app.post("/learning/start")
def learning_start(request: Request, band_rank: int | None = Form(None), assignment_id: int | None = Form(None)) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    selected_band_rank = band_rank
    selected_assignment_id = None
    if assignment_id:
        assignment = conn.execute(
            """
            SELECT class_assignments.*
            FROM class_assignments
            JOIN class_memberships ON class_memberships.class_id = class_assignments.class_id
            WHERE class_assignments.id = ?
              AND class_memberships.student_user_id = ?
            """,
            (assignment_id, user_id),
        ).fetchone()
        if assignment is not None:
            selected_assignment_id = int(assignment["id"])
            selected_band_rank = int(assignment["band_rank"])
    session_id = create_learning_session(conn, selected_band_rank, user_id, selected_assignment_id)
    return RedirectResponse(url=f"/learning/{session_id}", status_code=303)


@app.post("/learning/review-weak")
def learning_review_weak(request: Request) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    lang = getattr(request.state, "lang", get_lang(request))
    session_id = create_weak_words_learning_session(conn, user_id, lang)
    return RedirectResponse(url=f"/learning/{session_id}", status_code=303)


@app.post("/learning/{session_id}/retry-incorrect")
def learning_retry_incorrect(request: Request, session_id: int) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    source_session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if source_session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    retry_session_id = create_learning_retry_session(conn, session_id)
    return RedirectResponse(url=f"/learning/{retry_session_id}", status_code=303)


@app.get("/learning/{session_id}", response_class=HTMLResponse)
def learning_question(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = current_learning_question(conn, session_id)
    if question is None:
        finish_learning_session(conn, session_id)
        return RedirectResponse(url=f"/learning/{session_id}/result", status_code=303)
    lang = getattr(request.state, "lang", get_lang(request))
    payload = word_payload(conn, question["word_id"], lang, user_id)
    return render(
        request,
        "learning_question.html",
        session=session,
        question=question,
        word=payload["word"],
        band_identity=band_display_identity(session["band_label"] or payload["word"]["best_band_label"], lang),
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
def learning_answer(request: Request, session_id: int, answer: str = Form(...)) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
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
    update_study_card_schedule(conn, question["word_id"], bool(is_correct), "learning", user_id)
    conn.commit()
    total_questions = conn.execute(
        "SELECT COUNT(*) FROM learning_questions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if int(question["position"] or 0) >= int(total_questions or 0):
        finish_learning_session(conn, session_id)
        return RedirectResponse(url=f"/learning/{session_id}/review", status_code=303)
    if int(question["position"] or 0) % LEARNING_LAYERS_PER_WORD != 0:
        return RedirectResponse(url=f"/learning/{session_id}", status_code=303)
    return RedirectResponse(url=f"/learning/{session_id}/review", status_code=303)


@app.get("/learning/{session_id}/review", response_class=HTMLResponse)
def learning_review(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = previous_learning_question(conn, session_id)
    if question is None:
        return RedirectResponse(url=f"/learning/{session_id}", status_code=303)
    lang = getattr(request.state, "lang", get_lang(request))
    payload = word_payload(conn, question["word_id"], lang, user_id)
    progress = learning_progress(conn, session)
    is_last = progress["answered"] >= progress["total"]
    return render(
        request,
        "learning_review.html",
        session=session,
        question=question,
        word=payload["word"],
        band_identity=band_display_identity(session["band_label"] or payload["word"]["best_band_label"], lang),
        definitions=payload["definitions"],
        parts_of_speech=payload["parts_of_speech"],
        english_definition=payload["english_definition"],
        pronunciation=payload["pronunciation"],
        synonyms=payload["synonyms"],
        example_sentence=payload["example_sentence"],
        word_score=learning_word_score(conn, session_id, question["word_id"]),
        progress=progress,
        is_last=is_last,
    )


@app.get("/learning/{session_id}/result", response_class=HTMLResponse)
def learning_result(request: Request, session_id: int) -> HTMLResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    finish_learning_session(conn, session_id)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
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
    word_results = learning_word_report_rows(conn, session_id, lang, user_id)
    question_review_rows = [question for word in word_results for question in word["questions"]]
    recommendation = learning_recommendation(session["score"], total, enriched_words, lang)
    band_identity = band_display_identity(session["band_label"], lang) if session["band_label"] else None
    completed_word_count = sum(1 for word in word_results if word["correct_count"] == word["total_count"])
    review_words = [word for word in word_results if word["correct_count"] < word["total_count"]]
    return render(
        request,
        "learning_result.html",
        session=session,
        question_results=rows,
        word_results=word_results,
        question_review_rows=question_review_rows,
        recommendation=recommendation,
        band_identity=band_identity,
        completed_word_count=completed_word_count,
        review_words=review_words,
        percent=round((session["score"] / total) * 100) if total else 0,
    )


@app.get("/dictionary", response_class=HTMLResponse)
def dictionary_home(request: Request) -> HTMLResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    user_id = current_user_id(request)
    bands = student_dse_band_rows(conn, lang, user_id)
    return render(
        request,
        "dictionary_home.html",
        bands=bands,
        missed_count=len(missed_words(conn, limit=10, lang=lang, user_id=user_id)),
    )


@app.get("/business-vocabulary", response_class=HTMLResponse)
def business_vocabulary(
    request: Request,
    q: str = Query(""),
    band_rank: str | None = Query(None),
    sector: str = Query(""),
    topic: str = Query(""),
    skill: str = Query(""),
) -> HTMLResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    selected_band = int(band_rank) if band_rank and band_rank.strip() else None
    valid_sectors = {item["slug"] for item in BUSINESS_SECTORS}
    valid_topics = {item["slug"] for item in BUSINESS_TOPICS}
    valid_skills = {item["slug"] for item in BUSINESS_SKILLS}
    selected_sector = sector if sector in valid_sectors else ""
    selected_topic = topic if topic in valid_topics else ""
    selected_skill = skill if skill in valid_skills else ""
    results = business_vocabulary_cards(
        conn,
        q=q,
        band_rank=selected_band,
        sector=selected_sector,
        topic=selected_topic,
        skill=selected_skill,
        lang=lang,
    )
    return render(
        request,
        "business_vocabulary.html",
        query=q,
        bands=decorate_band_rows(band_summary(conn)),
        selected_band=selected_band,
        sectors=localized_business_taxonomy(BUSINESS_SECTORS, lang),
        topics=localized_business_taxonomy(BUSINESS_TOPICS, lang),
        skills=localized_business_taxonomy(BUSINESS_SKILLS, lang),
        selected_sector=selected_sector,
        selected_topic=selected_topic,
        selected_skill=selected_skill,
        results=results,
        result_count=len(results),
    )


@app.get("/ai-power-vocabulary", response_class=HTMLResponse)
def ai_power_vocabulary(
    request: Request,
    q: str = Query(""),
    category: str = Query(""),
) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    track = ai_power_track(lang)
    filtered_track = filter_ai_power_track(track, q, category)
    return render(
        request,
        "ai_power_vocab.html",
        ai_power=filtered_track,
        ai_power_categories=track["categories"],
        ai_query=q,
        ai_category=category,
    )


@app.get("/ai-power-vocabulary/template")
def ai_power_vocabulary_template(missing_only: int = Query(0)) -> FileResponse:
    filename = "ai-power-vocabulary-missing-template.xlsx" if missing_only else "ai-power-vocabulary-template.xlsx"
    output_path = EXPORT_DIR / filename
    export_ai_power_template(ai_power_track("en")["categories"], output_path, missing_only=bool(missing_only))
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@app.post("/ai-power-vocabulary/upload")
async def ai_power_vocabulary_upload(file: UploadFile = File(...)) -> RedirectResponse:
    content = await file.read()
    rows = iter_import_rows(file.filename or "", content)
    imported_rows, stats = import_ai_power_rows(rows)
    save_ai_power_entries(imported_rows)
    return RedirectResponse(
        url=f"/ai-power-vocabulary?imported=1&updated={stats['updated']}",
        status_code=303,
    )


@app.get("/ai-power-vocabulary/category/{category_slug}", response_class=HTMLResponse)
def ai_power_category_page(request: Request, category_slug: str) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    track = ai_power_track(lang)
    category = ai_power_category_by_slug(track, category_slug)
    if category is None:
        raise HTTPException(status_code=404, detail="AI Power category not found")
    return render(
        request,
        "ai_power_category.html",
        category=category,
    )


@app.get("/ai-power-vocabulary/category/{category_slug}/{entry_slug}", response_class=HTMLResponse)
def ai_power_entry_page(request: Request, category_slug: str, entry_slug: str) -> HTMLResponse:
    lang = getattr(request.state, "lang", get_lang(request))
    track = ai_power_track(lang)
    category = ai_power_category_by_slug(track, category_slug)
    if category is None:
        raise HTTPException(status_code=404, detail="AI Power category not found")
    entry = ai_power_entry_by_slug(category, entry_slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="AI Power word not found")
    return render(
        request,
        "ai_power_word.html",
        category=category,
        entry=entry,
        prompt_sections=ai_prompt_sections(entry, lang),
    )


MOBILE_AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def mobile_cookie_kwargs(request: Request, httponly: bool = True) -> dict:
    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    return {
        "max_age": MOBILE_AUTH_COOKIE_MAX_AGE,
        "httponly": httponly,
        "samesite": "none" if secure_cookie else "lax",
        "secure": secure_cookie,
    }


def mobile_user_response_payload(user: sqlite3.Row | None, lang: str) -> dict:
    if user is None:
        return {"authenticated": False, "user": None}
    display_name = (user["display_name"] or user["username"] or "Student").strip()[:40]
    persona = user["persona"] if user["persona"] in SUPPORTED_PERSONAS else "student"
    role = user["role"] if "role" in user.keys() and user["role"] else role_for_persona(persona)
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "display_name": display_name,
            "email": user["email"] or "",
            "persona": persona,
            "role": role,
            "profile": mobile_profile(display_name, persona, lang),
        },
    }


def mobile_auth_json_response(request: Request, payload: dict, user: sqlite3.Row | None = None) -> JSONResponse:
    response = JSONResponse(payload)
    if user is None:
        return response
    persona = user["persona"] if user["persona"] in SUPPORTED_PERSONAS else "student"
    display_name = (user["display_name"] or user["username"] or "Student").strip()[:40]
    response.set_cookie("registered_user_id", str(user["id"]), **mobile_cookie_kwargs(request, httponly=True))
    response.set_cookie("profile_name", display_name, **mobile_cookie_kwargs(request, httponly=False))
    response.set_cookie("profile_persona", persona, **mobile_cookie_kwargs(request, httponly=False))
    return response


@app.get("/api/mobile/auth/me")
def mobile_auth_me(request: Request, lang: str = Query("en")) -> JSONResponse:
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user = registered_user_row(request)
    return mobile_auth_json_response(request, mobile_user_response_payload(user, safe_lang), user)


@app.post("/api/mobile/auth/signup")
def mobile_auth_signup(
    request: Request,
    lang: str = Query("en"),
    payload: dict = Body(...),
) -> JSONResponse:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    safe_name = (str(payload.get("display_name") or payload.get("name") or "")).strip()[:40]
    safe_email = normalized_email(str(payload.get("email") or ""))
    password = str(payload.get("password") or "")
    confirm_password = str(payload.get("confirm_password") or "")
    persona = str(payload.get("persona") or "student")
    safe_persona = persona if persona in SUPPORTED_PERSONAS else "student"
    teacher_invite_code = str(payload.get("teacher_invite_code") or payload.get("teacherInviteCode") or "")
    if not safe_name:
        raise HTTPException(status_code=400, detail="Please enter your name.")
    if not valid_email(safe_email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if safe_persona == "teacher" and not teacher_invite_code_valid(teacher_invite_code):
        raise HTTPException(status_code=400, detail="Teacher accounts require a valid teacher invitation code.")
    existing = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (safe_email,)).fetchone()
    if existing is not None:
        raise HTTPException(status_code=400, detail="This email is already registered.")
    username_seed = re.sub(r"[^a-z0-9]+", "_", safe_email.split("@", 1)[0]).strip("_") or "user"
    username = username_seed
    suffix = 1
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        suffix += 1
        username = f"{username_seed}_{suffix}"
    cursor = conn.execute(
        """
        INSERT INTO users (username, email, password_hash, display_name, persona, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (username, safe_email, hash_password(password), safe_name, safe_persona, role_for_persona(safe_persona)),
    )
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return mobile_auth_json_response(request, mobile_user_response_payload(user, safe_lang), user)


@app.post("/api/mobile/auth/login")
def mobile_auth_login(
    request: Request,
    lang: str = Query("en"),
    payload: dict = Body(...),
) -> JSONResponse:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    safe_email = normalized_email(str(payload.get("email") or ""))
    password = str(payload.get("password") or "")
    user = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (safe_email,)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return mobile_auth_json_response(request, mobile_user_response_payload(user, safe_lang), user)


@app.post("/api/mobile/auth/logout")
def mobile_auth_logout(request: Request, lang: str = Query("en")) -> JSONResponse:
    response = JSONResponse({"authenticated": False, "user": None})
    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    response.delete_cookie("registered_user_id", samesite="none" if secure_cookie else "lax", secure=secure_cookie)
    response.delete_cookie("profile_name", samesite="none" if secure_cookie else "lax", secure=secure_cookie)
    response.delete_cookie("profile_persona", samesite="none" if secure_cookie else "lax", secure=secure_cookie)
    return response


@app.get("/api/mobile/bootstrap")
def mobile_bootstrap(
    request: Request,
    lang: str = Query("en"),
    name: str = Query(""),
    persona: str = Query("lifelong_learner"),
) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user = registered_user_row(request)
    user_id = int(user["id"]) if user is not None else USER_ID
    if user is not None:
        name = (user["display_name"] or user["username"] or name)
        persona = user["persona"] or persona
    profile = mobile_profile(name, persona, safe_lang)
    stats = fetch_stats(conn, user_id)
    latest_test = latest_test_result(conn, user_id=user_id)
    latest_learning = latest_learning_result(conn, user_id=user_id)
    bands = student_dse_band_rows(conn, safe_lang, user_id)
    max_band_total = max((band["workbook_total"] for band in bands), default=1)
    hero_band_chart = [
        {
            "rank": band["best_band_rank"],
            "label": band["range_label"],
            "title": band["title"],
            "subtitle": band["subtitle"],
            "tone": band["tone"],
            "count": band["workbook_total"],
            "percent": max(18, round((band["workbook_total"] / max_band_total) * 100)),
        }
        for band in bands[:5]
    ]
    spotlight = [mobile_word_card(item, safe_lang) for item in dashboard_spotlight_words(conn, limit=6, lang=safe_lang)]
    ai_power = ai_power_track(safe_lang)
    return {
        "profile": profile,
        "stats": stats,
        "recommended_band": latest_test["estimated_band_label"] if latest_test else STUDENT_DSE_BANDS[1]["label"],
        "latest_test": (
            {
                "session_id": latest_test["id"],
                "score": latest_test["score"],
                "estimated_band_label": latest_test["estimated_band_label"],
            }
            if latest_test
            else None
        ),
        "latest_learning": (
            {
                "score": latest_learning["score"],
                "session_id": latest_learning["id"],
            }
            if latest_learning
            else None
        ),
        "hero_band_chart": hero_band_chart,
        "spotlight_words": spotlight,
        "recommendation_cards": mobile_recommendation_cards(profile["persona"], safe_lang),
        "missed_words_count": len(missed_words(conn, limit=20, lang=safe_lang)),
        "ai_power_summary": {
            "target_count": ai_power["target_count"],
            "completed_count": ai_power["completed_count"],
            "category_count": ai_power["category_count"],
            "progress_label": ai_power["progress_label"],
        },
    }


@app.get("/api/mobile/dictionary/search")
def mobile_dictionary_search(
    q: str = Query(""),
    lang: str = Query("en"),
    band_rank: int | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    rows = search_result_cards(conn, q, band_rank=band_rank, lang=safe_lang) if q.strip() else []
    return {
        "query": q,
        "result_count": len(rows[:limit]),
        "results": [mobile_word_card(item, safe_lang) for item in rows[:limit]],
    }


@app.get("/api/mobile/word/{word_id}")
def mobile_word_detail(request: Request, word_id: int, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    payload = word_payload(conn, word_id, safe_lang, current_user_id(request))
    word = payload["word"]
    return {
        "id": word["id"],
        "lemma": word["lemma"],
        "band_label": word["best_band_label"],
        "status": translate_status(word["status"], safe_lang),
        "correct_count": word["correct_count"],
        "wrong_count": word["wrong_count"],
        "notes": word["notes"] or "",
        "ipa": payload["pronunciation"],
        "english_definition": payload["english_definition"],
        "chinese_definitions": [localize_chinese_text(item, safe_lang) for item in payload["definitions"]],
        "parts_of_speech": payload["parts_of_speech"],
        "example_sentence": payload["example_sentence"],
        "synonyms": payload["synonyms"],
        "sentence_distractors": payload["sentence_distractors"],
    }


@app.post("/api/mobile/word/{word_id}/note")
def mobile_word_note_update(
    request: Request,
    word_id: int,
    lang: str = Query("en"),
    notes: str = Body("", embed=True),
) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    word_row(conn, word_id, user_id)
    cleaned = notes.strip()
    conn.execute(
        """
        UPDATE user_study_cards
        SET notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND word_id = ?
        """,
        (cleaned, user_id, word_id),
    )
    conn.commit()
    payload = word_payload(conn, word_id, safe_lang, user_id)
    return {
        "word_id": word_id,
        "notes": payload["word"]["notes"] or "",
        "message": "saved",
    }


def mobile_learning_question_payload(conn: sqlite3.Connection, question: sqlite3.Row, lang: str, user_id: int = USER_ID) -> dict:
    payload = word_payload(conn, question["word_id"], lang, user_id)
    word = conn.execute(
        """
        SELECT id, lemma, best_band_label, best_band_rank
        FROM words
        WHERE id = ?
        """,
        (question["word_id"],),
    ).fetchone()
    parts_of_speech = parts_of_speech_for_word(conn, question["word_id"])
    return {
        "id": question["id"],
        "prompt_text": question["prompt_text"],
        "question_type": question["question_type"],
        "question_type_label": translate_question_type(question["question_type"], lang),
        "options": json_loads(question["options_json"]),
        "word": {
            "id": word["id"],
            "lemma": word["lemma"],
            "band_label": word["best_band_label"],
            "band_rank": word["best_band_rank"],
            "ipa": payload["pronunciation"],
            "parts_of_speech": parts_of_speech,
        },
    }


def mobile_learning_review_payload(conn: sqlite3.Connection, question: sqlite3.Row, lang: str, user_id: int = USER_ID) -> dict:
    payload = word_payload(conn, question["word_id"], lang, user_id)
    word = payload["word"]
    return {
        "id": question["id"],
        "prompt_text": question["prompt_text"],
        "question_type": question["question_type"],
        "question_type_label": translate_question_type(question["question_type"], lang),
        "options": json_loads(question["options_json"]),
        "correct_option": question["correct_option"],
        "user_answer": question["user_answer"] or "",
        "is_correct": bool(question["is_correct"]),
        "explanation": question["explanation"] or "",
        "word": {
            "id": word["id"],
            "lemma": word["lemma"],
            "band_label": word["best_band_label"],
            "status": translate_status(word["status"], lang),
            "correct_count": word["correct_count"],
            "wrong_count": word["wrong_count"],
            "ipa": payload["pronunciation"],
            "parts_of_speech": payload["parts_of_speech"],
            "english_definition": payload["english_definition"],
            "chinese_definitions": [localize_chinese_text(item, lang) for item in payload["definitions"]],
            "example_sentence": payload["example_sentence"],
            "synonyms": payload["synonyms"],
            "notes": word["notes"] or "",
        },
    }


def mobile_learning_result_payload(conn: sqlite3.Connection, session_id: int, lang: str) -> dict:
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
    percent = round((session["score"] / total) * 100) if total else 0
    return {
        "session_id": session_id,
        "status": "completed",
        "progress": {
            "current": total,
            "answered": total,
            "total": total,
            "percent": 100 if total else 0,
        },
        "result": {
            "score": session["score"],
            "total": total,
            "percent": percent,
            "recommendation": learning_recommendation(session["score"], total, enriched_words, lang),
            "breakdown": [
                {
                    "question_type": row["question_type"],
                    "question_type_label": translate_question_type(row["question_type"], lang),
                    "correct": row["correct"],
                    "total": row["total"],
                }
                for row in rows
            ],
        },
    }


def mobile_active_learning_payload(conn: sqlite3.Connection, session: sqlite3.Row, lang: str) -> dict:
    progress = learning_progress(conn, session)
    return {
        "session_id": session["id"],
        "band_rank": session["band_rank"],
        "band_label": session["band_label"] or "",
        "status": session["status"],
        "started_at": session["started_at"],
        "progress": progress,
        "resume_label": f"{progress['answered']} / {progress['total']}",
    }


@app.get("/api/mobile/learning/active")
def mobile_learning_active(request: Request, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    session = conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE user_id = ?
          AND status <> 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if session is None:
        return {"active": False, "session": None}
    question = current_learning_question(conn, session["id"])
    if question is None:
        return {"active": False, "session": None}
    return {
        "active": True,
        "session": mobile_active_learning_payload(conn, session, safe_lang),
    }


@app.get("/api/mobile/learning/progress")
def mobile_learning_progress(request: Request, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    summary = learning_summary_for_user(conn, user_id)
    rows = conn.execute(
        """
        SELECT learning_questions.question_type,
               SUM(CASE WHEN learning_questions.is_correct = 1 THEN 1 ELSE 0 END) AS correct,
               COUNT(*) AS total
        FROM learning_questions
        JOIN learning_sessions ON learning_sessions.id = learning_questions.session_id
        WHERE learning_sessions.user_id = ?
          AND learning_questions.is_correct IS NOT NULL
        GROUP BY learning_questions.question_type
        HAVING total > 0
        """,
        (user_id,),
    ).fetchall()
    type_breakdown = [
        {
            "question_type": row["question_type"],
            "question_type_label": translate_question_type(row["question_type"], safe_lang),
            "correct": int(row["correct"] or 0),
            "total": int(row["total"] or 0),
            "accuracy": percent_value(int(row["correct"] or 0), int(row["total"] or 0)),
        }
        for row in rows
    ]
    weakest = min(
        type_breakdown,
        key=lambda item: ((item["correct"] / max(item["total"], 1)), -item["total"]),
        default=None,
    )
    history = learning_history_rows(conn, limit=5, user_id=user_id)
    missed = missed_words(conn, limit=5, lang=safe_lang)
    return {
        "summary": {
            "completed_sessions": summary["completed_sessions"],
            "correct": summary["correct"],
            "total": summary["total"],
            "accuracy": summary["accuracy"],
            "missed_words_count": len(missed_words(conn, limit=50, lang=safe_lang)),
        },
        "weakest_question_type": weakest,
        "type_breakdown": type_breakdown,
        "recent_sessions": history,
        "missed_words": [
            {
                "id": item["id"],
                "lemma": item["lemma"],
                "band_label": item["best_band_label"],
                "chinese_headword": (item.get("chinese_preview") or [""])[0],
            }
            for item in missed
        ],
    }


@app.post("/api/mobile/learning/start")
def mobile_learning_start(request: Request, lang: str = Query("en"), band_rank: int | None = Query(None)) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    session_id = create_learning_session(conn, band_rank, user_id=user_id)
    question = current_learning_question(conn, session_id)
    if question is None:
        return mobile_learning_result_payload(conn, session_id, safe_lang)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    return {
        "session_id": session_id,
        "status": "question",
        "progress": learning_progress(conn, session),
        "question": mobile_learning_question_payload(conn, question, safe_lang, user_id),
    }


@app.post("/api/mobile/learning/review-weak")
def mobile_learning_review_weak(request: Request, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    session_id = create_weak_words_learning_session(conn, user_id, safe_lang)
    question = current_learning_question(conn, session_id)
    if question is None:
        return mobile_learning_result_payload(conn, session_id, safe_lang)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    return {
        "session_id": session_id,
        "status": "question",
        "progress": learning_progress(conn, session),
        "question": mobile_learning_question_payload(conn, question, safe_lang, user_id),
    }


@app.post("/api/mobile/learning/{session_id}/retry-incorrect")
def mobile_learning_retry_incorrect(request: Request, session_id: int, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    source_session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if source_session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    if source_session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Learning session not found")
    retry_session_id = create_learning_retry_session(conn, session_id)
    question = current_learning_question(conn, retry_session_id)
    if question is None:
        return mobile_learning_result_payload(conn, retry_session_id, safe_lang)
    retry_session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (retry_session_id,)).fetchone()
    return {
        "session_id": retry_session_id,
        "status": "question",
        "progress": learning_progress(conn, retry_session),
        "question": mobile_learning_question_payload(conn, question, safe_lang, user_id),
    }


@app.get("/api/mobile/learning/{session_id}")
def mobile_learning_state(request: Request, session_id: int, lang: str = Query("en")) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    if session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = current_learning_question(conn, session_id)
    if question is None:
        return mobile_learning_result_payload(conn, session_id, safe_lang)
    return {
        "session_id": session_id,
        "status": "question",
        "progress": learning_progress(conn, session),
        "question": mobile_learning_question_payload(conn, question, safe_lang, user_id),
    }


@app.post("/api/mobile/learning/{session_id}/answer")
def mobile_learning_answer(
    request: Request,
    session_id: int,
    lang: str = Query("en"),
    answer: str = Body(..., embed=True),
) -> dict:
    conn = db_conn()
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    user_id = current_user_id(request)
    session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Learning session not found")
    if session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Learning session not found")
    question = current_learning_question(conn, session_id)
    if question is None:
        return mobile_learning_result_payload(conn, session_id, safe_lang)
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
    update_study_card_schedule(conn, question["word_id"], bool(is_correct), "mobile_learning", user_id)
    conn.commit()
    updated_session = conn.execute("SELECT * FROM learning_sessions WHERE id = ?", (session_id,)).fetchone()
    reviewed_question = previous_learning_question(conn, session_id)
    progress = learning_progress(conn, updated_session)
    return {
        "session_id": session_id,
        "status": "review",
        "progress": progress,
        "is_last": progress["answered"] >= progress["total"],
        "review": mobile_learning_review_payload(conn, reviewed_question, safe_lang, user_id),
    }


@app.get("/api/mobile/ai-power/categories")
def mobile_ai_power_categories(lang: str = Query("en")) -> dict:
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    track = ai_power_track(safe_lang)
    categories = [
        {
            "slug": category["slug"],
            "title": category["title"],
            "english_title": category["english_title"],
            "description": category["description"],
            "starter_count": category["starter_count"],
            "completed_count": category["completed_count"],
        }
        for category in track["categories"]
    ]
    return {
        "summary": {
            "target_count": track["target_count"],
            "completed_count": track["completed_count"],
            "progress_label": track["progress_label"],
        },
        "categories": categories,
    }


@app.get("/api/mobile/ai-power/category/{category_slug}")
def mobile_ai_power_category(category_slug: str, lang: str = Query("en")) -> dict:
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    track = ai_power_track(safe_lang)
    category = ai_power_category_by_slug(track, category_slug)
    if category is None:
        raise HTTPException(status_code=404, detail="AI Power category not found")
    return {
        "category": {
            "slug": category["slug"],
            "title": category["title"],
            "english_title": category["english_title"],
            "description": category["description"],
            "starter_count": category["starter_count"],
            "completed_count": category["completed_count"],
        },
        "entries": [
            {
                "english": entry["english"],
                "slug": entry["slug"],
                "type_of_word": entry["type_of_word"],
                "traditional_chinese": localize_chinese_text(entry["traditional_chinese"], safe_lang),
                "simplified_chinese": entry["simplified_chinese"],
                "english_definition": entry["english_definition"],
                "ipa": entry["ipa"],
            }
            for entry in category["entries"]
        ],
    }


@app.get("/api/mobile/ai-power/category/{category_slug}/{entry_slug}")
def mobile_ai_power_word(category_slug: str, entry_slug: str, lang: str = Query("en")) -> dict:
    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    track = ai_power_track(safe_lang)
    category = ai_power_category_by_slug(track, category_slug)
    if category is None:
        raise HTTPException(status_code=404, detail="AI Power category not found")
    entry = ai_power_entry_by_slug(category, entry_slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="AI Power word not found")
    return {
        "category": {
            "slug": category["slug"],
            "title": category["title"],
            "english_title": category["english_title"],
        },
        "entry": {
            "english": entry["english"],
            "slug": entry["slug"],
            "type_of_word": entry["type_of_word"],
            "english_definition": entry["english_definition"],
            "traditional_chinese": localize_chinese_text(entry["traditional_chinese"], safe_lang),
            "simplified_chinese": entry["simplified_chinese"],
            "example_sentence": entry["example_sentence"],
            "ipa": entry["ipa"],
            "prompt_sections": ai_prompt_sections(entry, safe_lang),
        },
    }


@app.get("/dictionary/band/{band_rank}", response_class=HTMLResponse)
def dictionary_band(
    request: Request,
    band_rank: int,
    letter: str | None = None,
    has_english: int = Query(0),
    has_example: int = Query(0),
) -> HTMLResponse:
    conn = db_conn()
    lang = getattr(request.state, "lang", get_lang(request))
    is_student_dse_band = band_rank in STUDENT_DSE_BANDS
    if is_student_dse_band:
        config = STUDENT_DSE_BANDS[band_rank]
        band = {
            "best_band_rank": band_rank,
            "best_band_label": config["label"],
            "total": conn.execute(
                "SELECT COUNT(*) FROM student_dse_vocab WHERE dse_band_rank = ?",
                (band_rank,),
            ).fetchone()[0],
        }
        letters = student_dse_letters_for_band(conn, band_rank)
    else:
        band = conn.execute(
            """
            SELECT best_band_rank, best_band_label, COUNT(*) AS total
            FROM words
            WHERE best_band_rank = ?
            GROUP BY best_band_rank, best_band_label
            """,
            (band_rank,),
        ).fetchone()
        letters = letters_for_band(conn, band_rank)
    if band is None:
        raise HTTPException(status_code=404, detail="Band not found")
    active_letter = (letter or "A").upper()
    if is_student_dse_band:
        rows = conn.execute(
            """
            SELECT words.id, words.lemma, words.best_band_label,
                   student_dse_vocab.dse_band_label,
                   COALESCE(word_enrichment.pronunciation, '') AS pronunciation,
                   COALESCE(word_enrichment.english_definition, '') AS english_definition,
                   COALESCE(word_enrichment.example_sentence, '') AS example_sentence
            FROM student_dse_vocab
            JOIN words ON words.id = student_dse_vocab.word_id
            LEFT JOIN word_enrichment ON word_enrichment.word_id = words.id
            WHERE student_dse_vocab.dse_band_rank = ?
              AND UPPER(SUBSTR(words.lemma, 1, 1)) = ?
              AND (? = 0 OR COALESCE(word_enrichment.english_definition, '') <> '')
              AND (? = 0 OR COALESCE(word_enrichment.example_sentence, '') <> '')
            ORDER BY words.lemma
            LIMIT 500
            """,
            (band_rank, active_letter, has_english, has_example),
        ).fetchall()
    else:
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
    user_id = current_user_id(request)
    definitions_map = definitions_map_for_words(conn, word_ids, lang)
    fallback_map = source_fallbacks_for_words(conn, word_ids)
    words = []
    for row in rows:
        definitions = definitions_map.get(row["id"], [])
        source_fallback = fallback_map.get(row["id"], {"pronunciation": "", "english_definition": "", "example_sentence": ""})
        mastery_progress = word_mastery_progress(conn, word_id=row["id"], user_id=user_id, lang=lang)
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
                "mastery_progress": mastery_progress,
            }
        )
    progress_average = round(sum(word["mastery_progress"]["percent"] for word in words) / len(words)) if words else 0
    mastered_count = sum(1 for word in words if word["mastery_progress"]["percent"] >= 100)
    return render(
        request,
        "dictionary_band.html",
        band=band,
        letters=letters,
        active_letter=active_letter,
        words=words,
        progress_average=progress_average,
        mastered_count=mastered_count,
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
    lang = getattr(request.state, "lang", get_lang(request))
    return render(
        request,
        "bulk_import.html",
        bands=student_dse_band_rows(conn, lang, current_user_id(request)),
        stats=fetch_stats(conn),
        export_dir=str(EXPORT_DIR),
        api_key_ready=bool(os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()),
        openai_key_ready=bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        gemini_key_ready=bool(os.environ.get("GEMINI_API_KEY", "").strip()),
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
    rows = iter_enrichment_import_rows(file.filename or "", content)
    stats = import_enrichment_rows(conn, rows)
    return RedirectResponse(
        url=f"/bulk-import?imported=1&updated={stats['updated']}&source_updated={stats['source_updated']}&missing={stats['missing_words']}",
        status_code=303,
    )


@app.post("/bulk-import/export-taxonomy")
def bulk_export_taxonomy_template(
    band_rank: str = Form(""),
    limit: str = Form("300"),
) -> RedirectResponse:
    conn = db_conn()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    selected_band = int(band_rank) if band_rank.strip() else None
    selected_limit = int(limit) if limit.strip() else None
    band_suffix = f"band-{selected_band}" if selected_band is not None else "all-bands"
    output_path = EXPORT_DIR / f"taxonomy-template-{band_suffix}.xlsx"
    export_taxonomy_template(
        conn,
        output_path,
        band_rank=selected_band,
        limit=selected_limit,
    )
    return RedirectResponse(url="/bulk-import?taxonomy_exported=1", status_code=303)


@app.post("/bulk-import/upload-taxonomy")
async def bulk_import_taxonomy_upload(file: UploadFile = File(...)) -> RedirectResponse:
    conn = db_conn()
    content = await file.read()
    rows = iter_import_rows(file.filename or "", content)
    stats = import_taxonomy_rows(conn, rows)
    return RedirectResponse(
        url=(
            "/bulk-import?"
            f"taxonomy_imported=1&updated={stats['updated']}"
            f"&missing={stats['missing_words']}"
            f"&related_missing={stats['missing_related_words']}"
        ),
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
    rows = missed_words(conn, lang=getattr(request.state, "lang", get_lang(request)), user_id=current_user_id(request))
    return render(request, "missed_words.html", rows=rows)


@app.get("/word/{word_id}", response_class=HTMLResponse)
def word_detail(request: Request, word_id: int) -> HTMLResponse:
    conn = db_conn()
    load_env_file()
    lang = getattr(request.state, "lang", get_lang(request))
    user_id = current_user_id(request)
    mark_word_seen(conn, user_id=user_id, word_id=word_id)
    payload = word_payload(conn, word_id, lang, user_id)
    payload["pronunciation_ai_ready"] = transcription_api_ready()
    payload["sentence_check_ready"] = sentence_ai_ready()
    payload["ai_key_ready"] = payload["pronunciation_ai_ready"] or payload["sentence_check_ready"]
    payload["latest_mastery"] = latest_word_mastery_attempts(conn, word_id=word_id, user_id=user_id)
    payload["mastery_progress"] = word_mastery_progress(conn, word_id=word_id, user_id=user_id, lang=lang)
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


@app.post("/api/word/{word_id}/deep-learning/pronunciation")
async def word_deep_learning_pronunciation(
    request: Request,
    word_id: int,
    audio: UploadFile = File(...),
    lang: str = Form("en"),
) -> dict:
    conn = db_conn()
    user_id = current_user_id(request)
    word = word_row(conn, word_id, user_id)
    safe_lang = lang if lang in SUPPORTED_LANGS else get_lang(request)
    if not transcription_api_ready():
        raise HTTPException(status_code=503, detail=translate(get_lang(request), "mastery_api_not_ready"))
    audio_bytes = await audio.read()
    if len(audio_bytes) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio file is too large.")
    try:
        transcript = transcribe_pronunciation_audio(
            audio_bytes,
            filename=audio.filename or "pronunciation.webm",
            target_word=word["lemma"],
        )
    except Exception as exc:
        logger.exception("Pronunciation check failed for word_id=%s", word_id)
        raise HTTPException(status_code=502, detail=friendly_ai_failure_message("Pronunciation check", safe_lang)) from exc

    scored = pronunciation_score(word["lemma"], transcript)
    feedback = mastery_feedback_for_pronunciation(word["lemma"], transcript, int(scored["score"]), safe_lang)
    payload = {
        "attempt_type": "pronunciation",
        "target_word": word["lemma"],
        "transcript": transcript,
        "score": scored["score"],
        "status": scored["status"],
        "recognized": scored["recognized"],
        "feedback": feedback,
    }
    save_word_mastery_attempt(
        conn,
        user_id=user_id,
        word_id=word_id,
        attempt_type="pronunciation",
        transcript=transcript,
        score=int(scored["score"]),
        status=str(scored["status"]),
        feedback=feedback,
        payload=payload,
    )
    return payload


@app.post("/api/word/{word_id}/deep-learning/sentence")
def word_deep_learning_sentence(
    request: Request,
    word_id: int,
    sentence: str = Form(...),
    lang: str = Form("en"),
) -> dict:
    conn = db_conn()
    user_id = current_user_id(request)
    word_row(conn, word_id, user_id)
    cleaned_sentence = sentence.strip()
    if not cleaned_sentence:
        raise HTTPException(status_code=400, detail=translate(get_lang(request), "mastery_sentence_required"))
    if len(cleaned_sentence) > 800:
        raise HTTPException(status_code=400, detail="Sentence is too long.")
    if not sentence_ai_ready():
        raise HTTPException(status_code=503, detail=translate(get_lang(request), "mastery_api_not_ready"))
    safe_lang = lang if lang in SUPPORTED_LANGS else get_lang(request)
    try:
        result = evaluate_sentence_usage(conn, word_id=word_id, sentence=cleaned_sentence, lang=safe_lang)
    except Exception as exc:
        logger.exception("Sentence check failed for word_id=%s", word_id)
        raise HTTPException(status_code=502, detail=friendly_ai_failure_message("Sentence check", safe_lang)) from exc
    save_word_mastery_attempt(
        conn,
        user_id=user_id,
        word_id=word_id,
        attempt_type="sentence",
        input_text=cleaned_sentence,
        score=int(result.get("overall_score", 0) or 0),
        status=str(result.get("status", "")),
        feedback=str(result.get("feedback", "")),
        corrected_sentence=str(result.get("corrected_sentence", "")),
        suggested_upgrade=str(result.get("suggested_upgrade", "")),
        payload=result,
    )
    return {
        "attempt_type": "sentence",
        "input_text": cleaned_sentence,
        **result,
    }


@app.post("/word/{word_id}/update")
def update_word(
    request: Request,
    word_id: int,
    notes: str = Form(""),
    english_definition: str = Form(""),
    pronunciation: str = Form(""),
    synonyms: str = Form(""),
    example_sentence: str = Form(""),
    sentence_distractors: str = Form(""),
    ai_simple_explanation_en: str = Form(""),
    ai_simple_explanation_zh: str = Form(""),
    ai_nuance_note: str = Form(""),
    ai_compare_words: str = Form(""),
    ai_business_example: str = Form(""),
    ai_prompt_example: str = Form(""),
    ai_usage_warning: str = Form(""),
) -> RedirectResponse:
    conn = db_conn()
    user_id = current_user_id(request)
    word = word_row(conn, word_id, user_id)
    synonym_items = [item.strip() for item in synonyms.splitlines() if item.strip()]
    distractor_items = [item.strip() for item in sentence_distractors.splitlines() if item.strip()]
    compare_word_items = []
    for line in ai_compare_words.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if "|" in cleaned:
            word_text, note_text = cleaned.split("|", 1)
            compare_word_items.append({"word": word_text.strip(), "note": note_text.strip()})
        else:
            compare_word_items.append({"word": cleaned, "note": ""})
    conn.execute(
        """
        UPDATE user_study_cards
        SET notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND word_id = ?
        """,
        (notes.strip(), user_id, word_id),
    )
    conn.execute(
        """
        INSERT INTO word_enrichment (
            word_id,
            english_definition,
            pronunciation,
            synonyms_json,
            example_sentence,
            sentence_distractors_json,
            ai_simple_explanation_en,
            ai_simple_explanation_zh,
            ai_nuance_note,
            ai_compare_words_json,
            ai_business_example,
            ai_prompt_example,
            ai_usage_warning
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(word_id) DO UPDATE SET
            english_definition = excluded.english_definition,
            pronunciation = excluded.pronunciation,
            synonyms_json = excluded.synonyms_json,
            example_sentence = excluded.example_sentence,
            sentence_distractors_json = excluded.sentence_distractors_json,
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
            english_definition.strip(),
            pronunciation.strip(),
            json.dumps(synonym_items, ensure_ascii=False),
            example_sentence.strip(),
            json.dumps(distractor_items, ensure_ascii=False),
            ai_simple_explanation_en.strip(),
            ai_simple_explanation_zh.strip(),
            ai_nuance_note.strip(),
            json.dumps(compare_word_items, ensure_ascii=False),
            ai_business_example.strip(),
            ai_prompt_example.strip(),
            ai_usage_warning.strip(),
        ),
    )
    conn.commit()
    return RedirectResponse(url=f"/word/{word['id']}", status_code=303)


@app.post("/word/{word_id}/generate-ai-insight")
def generate_word_ai_insight(word_id: int) -> RedirectResponse:
    conn = db_conn()
    try:
        generate_ai_insight_for_word(conn, word_id=word_id)
    except RuntimeError as exc:
        return RedirectResponse(url=f"/word/{word_id}?ai_error={str(exc)}", status_code=303)
    except Exception as exc:
        return RedirectResponse(url=f"/word/{word_id}?ai_error={str(exc)}", status_code=303)
    return RedirectResponse(url=f"/word/{word_id}?ai_generated=1", status_code=303)
