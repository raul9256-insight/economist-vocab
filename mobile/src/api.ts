import { Platform } from "react-native";

function resolveApiBase() {
  const configured = process.env.EXPO_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) {
    return configured;
  }

  if (Platform.OS === "web" && typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "http://127.0.0.1:8000";
    }
  }

  return "https://economist-vocab.onrender.com";
}

const API_BASE = resolveApiBase();

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function responseErrorMessage(response: Response) {
  try {
    const payload = await response.json();
    if (payload?.detail) {
      return String(payload.detail);
    }
  } catch {
    // Fall back to the status code below.
  }
  return `Request failed: ${response.status}`;
}

export type MobileProfile = {
  name: string;
  initials: string;
  persona: string;
  persona_message: string;
  recommendation_note: string;
};

export type MobileUser = {
  id: number;
  display_name: string;
  email: string;
  persona: string;
  role: string;
  profile: MobileProfile;
};

export type AuthStatePayload = {
  authenticated: boolean;
  user: MobileUser | null;
};

export type WordCard = {
  id: number;
  lemma: string;
  band_label: string;
  english_definition: string;
  example_sentence: string;
  pronunciation: string;
  parts_of_speech: string[];
  chinese_preview: string[];
  chinese_headword: string;
};

export type BootstrapPayload = {
  profile: MobileProfile;
  stats: {
    total_words: number;
    words_with_synonyms: number;
    words_with_examples: number;
    tests_taken: number;
    learning_runs: number;
  };
  recommended_band: string;
  latest_test: null | { score: number; estimated_band_label: string };
  latest_learning: null | { score: number; session_id: number };
  hero_band_chart: Array<{
    rank: number;
    label: string;
    title: string;
    subtitle: string;
    tone: string;
    count: number;
    percent: number;
  }>;
  spotlight_words: WordCard[];
  recommendation_cards: Array<{
    title: string;
    body: string;
    href: string;
    tag: string;
  }>;
  missed_words_count: number;
  ai_power_summary: {
    target_count: number;
    completed_count: number;
    category_count: number;
    progress_label: string;
  };
};

export type DictionaryPayload = {
  query: string;
  result_count: number;
  results: WordCard[];
};

export type AiPowerCategory = {
  slug: string;
  title: string;
  english_title: string;
  description: string;
  starter_count: number;
  completed_count: number;
};

export type AiPowerCategoriesPayload = {
  summary: {
    target_count: number;
    completed_count: number;
    progress_label: string;
  };
  categories: AiPowerCategory[];
};

export type DictionaryWordDetail = {
  id: number;
  lemma: string;
  band_label: string;
  status: string;
  correct_count: number;
  wrong_count: number;
  notes: string;
  ipa: string;
  english_definition: string;
  chinese_definitions: string[];
  parts_of_speech: string[];
  example_sentence: string;
  synonyms: string[];
  sentence_distractors: string[];
};

export type LearningQuestion = {
  id: number;
  prompt_text: string;
  question_type: string;
  question_type_label: string;
  options: string[];
  word: {
    id: number;
    lemma: string;
    band_label: string;
    band_rank: number;
    ipa: string;
    parts_of_speech: string[];
  };
};

export type LearningReview = {
  id: number;
  prompt_text: string;
  question_type: string;
  question_type_label: string;
  options: string[];
  correct_option: string;
  user_answer: string;
  is_correct: boolean;
  explanation: string;
  word: {
    id: number;
    lemma: string;
    band_label: string;
    status: string;
    correct_count: number;
    wrong_count: number;
    ipa: string;
    parts_of_speech: string[];
    english_definition: string;
    chinese_definitions: string[];
    example_sentence: string;
    synonyms: string[];
    notes: string;
  };
};

export type LearningResult = {
  score: number;
  total: number;
  percent: number;
  recommendation: string;
  breakdown: Array<{
    question_type: string;
    question_type_label: string;
    correct: number;
    total: number;
  }>;
};

export type LearningQuestionState = {
  session_id: number;
  status: "question";
  progress: {
    current: number;
    answered: number;
    total: number;
    percent: number;
  };
  question: LearningQuestion;
};

export type LearningReviewState = {
  session_id: number;
  status: "review";
  progress: {
    current: number;
    answered: number;
    total: number;
    percent: number;
  };
  is_last: boolean;
  review: LearningReview;
};

export type LearningCompletedState = {
  session_id: number;
  status: "completed";
  progress: {
    current: number;
    answered: number;
    total: number;
    percent: number;
  };
  result: LearningResult;
};

export type LearningState = LearningQuestionState | LearningCompletedState;
export type NoteSavePayload = {
  word_id: number;
  notes: string;
  message: string;
};

export async function fetchMobileMe(lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return getJson<AuthStatePayload>(`/api/mobile/auth/me?${query}`);
}

export async function mobileLogin(params: { email: string; password: string; lang: string }) {
  const query = new URLSearchParams({ lang: params.lang }).toString();
  return postJson<AuthStatePayload>(`/api/mobile/auth/login?${query}`, {
    email: params.email,
    password: params.password,
  });
}

export async function mobileSignup(params: {
  display_name: string;
  email: string;
  password: string;
  confirm_password: string;
  persona: string;
  lang: string;
}) {
  const query = new URLSearchParams({ lang: params.lang }).toString();
  return postJson<AuthStatePayload>(`/api/mobile/auth/signup?${query}`, {
    display_name: params.display_name,
    email: params.email,
    password: params.password,
    confirm_password: params.confirm_password,
    persona: params.persona,
  });
}

export async function mobileLogout(lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return postJson<AuthStatePayload>(`/api/mobile/auth/logout?${query}`);
}

export async function fetchBootstrap(params: {
  lang: string;
  name: string;
  persona: string;
}) {
  const query = new URLSearchParams(params).toString();
  return getJson<BootstrapPayload>(`/api/mobile/bootstrap?${query}`);
}

export async function fetchDictionarySearch(params: { q: string; lang: string }) {
  const query = new URLSearchParams(params).toString();
  return getJson<DictionaryPayload>(`/api/mobile/dictionary/search?${query}`);
}

export async function fetchAiPowerCategories(lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return getJson<AiPowerCategoriesPayload>(`/api/mobile/ai-power/categories?${query}`);
}

export async function fetchDictionaryWordDetail(wordId: number, lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return getJson<DictionaryWordDetail>(`/api/mobile/word/${wordId}?${query}`);
}

export async function fetchLearningStart(lang: string, bandRank?: number) {
  const query = new URLSearchParams({
    lang,
    ...(bandRank ? { band_rank: String(bandRank) } : {}),
  }).toString();
  return postJson<LearningState>(`/api/mobile/learning/start?${query}`);
}

export async function fetchLearningState(sessionId: number, lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return getJson<LearningState>(`/api/mobile/learning/${sessionId}?${query}`);
}

export async function submitLearningAnswer(sessionId: number, answer: string, lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return postJson<LearningReviewState>(`/api/mobile/learning/${sessionId}/answer?${query}`, { answer });
}

export async function retryIncorrectLearning(sessionId: number, lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return postJson<LearningState>(`/api/mobile/learning/${sessionId}/retry-incorrect?${query}`);
}

export async function saveWordNote(wordId: number, notes: string, lang: string) {
  const query = new URLSearchParams({ lang }).toString();
  return postJson<NoteSavePayload>(`/api/mobile/word/${wordId}/note?${query}`, { notes });
}

export { API_BASE };
