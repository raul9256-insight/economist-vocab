import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { StatusBar as ExpoStatusBar } from "expo-status-bar";

import {
  API_BASE,
  AiPowerCategoriesPayload,
  BootstrapPayload,
  DictionaryPayload,
  DictionaryWordDetail,
  LearningCompletedState,
  LearningQuestionState,
  LearningReviewState,
  MobileUser,
  fetchAiPowerCategories,
  fetchBootstrap,
  fetchDictionarySearch,
  fetchDictionaryWordDetail,
  fetchMobileMe,
  fetchLearningStart,
  fetchLearningState,
  mobileLogin,
  mobileLogout,
  mobileSignup,
  retryIncorrectLearning,
  saveWordNote,
  submitLearningAnswer,
} from "./src/api";
import { colors, shadows } from "./src/theme";

type PersonaOption = {
  key: string;
  label: string;
  description: string;
  featured?: boolean;
};

const personaOptions: PersonaOption[] = [
  {
    key: "student",
    label: "Student",
    description: "Academic growth, reading, and stronger vocabulary foundations.",
  },
  {
    key: "teacher",
    label: "Teacher / Educator",
    description: "Teaching, explaining, and building useful learning materials.",
  },
  {
    key: "business_professional",
    label: "Business Professional",
    description: "Sharper communication for meetings, writing, and decisions.",
    featured: true,
  },
  {
    key: "ai_power_user",
    label: "AI Power User",
    description: "Prompting, analysis, and high-precision work with AI tools.",
  },
  {
    key: "lifelong_learner",
    label: "Lifelong Learner",
    description: "Practical vocabulary growth for long-term confidence.",
  },
];

type TabKey = "home" | "learning" | "dictionary" | "ai" | "profile";
type AuthMode = "login" | "signup";
type MobileLang = "en" | "zh-Hant" | "zh-Hans";

const mobileCopy = {
  en: {
    setupEyebrow: "Mobile App Setup",
    setupTitle: "Welcome to VocabLab AI",
    setupSubtitle:
      "Choose how you want to use the app first. You can try it once as a guest, or log in to keep your records across mobile and web.",
    checkingLogin: "Checking your saved login...",
    firstName: "First name",
    whoAreYou: "Who are you?",
    bestFit: "Best fit",
    language: "Language",
    continueGuest: "Continue as guest",
    loginSignupSave: "Login / Sign up to save progress",
    authEyebrow: "VocabLab Mobile",
    loginTitle: "Log in to continue",
    signupTitle: "Create your account",
    authSubtitle:
      "Use the same VocabLab AI account as the web app so your learning records, notes, and results stay together. You can also go back and continue once as a guest.",
    login: "Login",
    signup: "Sign up",
    name: "Name",
    email: "Email",
    password: "Password",
    confirmPassword: "Confirm password",
    passwordPlaceholder: "At least 8 characters",
    confirmPasswordPlaceholder: "Type the password again",
    accountType: "Account type",
    pleaseWait: "Please wait...",
    createAccount: "Create account",
    newHere: "New here? Create an account",
    alreadyHaveAccount: "Already have an account? Login",
    backToGuest: "Back to guest setup",
    personas: {
      student: ["Student", "Academic growth, reading, and stronger vocabulary foundations."],
      teacher: ["Teacher / Educator", "Teaching, explaining, and building useful learning materials."],
      business_professional: ["Business Professional", "Sharper communication for meetings, writing, and decisions."],
      ai_power_user: ["AI Power User", "Prompting, analysis, and high-precision work with AI tools."],
      lifelong_learner: ["Lifelong Learner", "Practical vocabulary growth for long-term confidence."],
    },
  },
  "zh-Hant": {
    setupEyebrow: "手機版設定",
    setupTitle: "歡迎使用 VocabLab AI",
    setupSubtitle:
      "先選擇你想怎樣使用這個 app。你可以先以訪客身份試用一次，也可以登入，讓學習紀錄在手機版和網頁版同步保存。",
    checkingLogin: "正在檢查已儲存的登入狀態...",
    firstName: "名字",
    whoAreYou: "你是哪一類用戶？",
    bestFit: "最適合",
    language: "語言",
    continueGuest: "以訪客身份繼續",
    loginSignupSave: "登入 / 註冊以保存進度",
    authEyebrow: "VocabLab 手機版",
    loginTitle: "登入後繼續",
    signupTitle: "建立你的帳戶",
    authSubtitle:
      "使用和網頁版相同的 VocabLab AI 帳戶，讓你的學習紀錄、筆記和結果集中保存。你亦可以返回，以訪客身份先試用一次。",
    login: "登入",
    signup: "註冊",
    name: "姓名",
    email: "電郵",
    password: "密碼",
    confirmPassword: "再次確認密碼",
    passwordPlaceholder: "最少 8 個字元",
    confirmPasswordPlaceholder: "再次輸入密碼",
    accountType: "帳戶類型",
    pleaseWait: "請稍候...",
    createAccount: "建立帳戶",
    newHere: "第一次使用？建立帳戶",
    alreadyHaveAccount: "已有帳戶？登入",
    backToGuest: "返回訪客設定",
    personas: {
      student: ["學生", "提升學術閱讀能力，建立更穩固的詞彙基礎。"],
      teacher: ["老師 / 教育工作者", "用於教學、解釋詞彙，以及建立實用學習材料。"],
      business_professional: ["商務專業人士", "提升會議、寫作和決策溝通的精準度。"],
      ai_power_user: ["AI 進階用戶", "強化提示詞、分析和高精準度 AI 工作流程。"],
      lifelong_learner: ["終身學習者", "為長期自學和實用表達建立更有信心的詞彙能力。"],
    },
  },
  "zh-Hans": {
    setupEyebrow: "手机版设置",
    setupTitle: "欢迎使用 VocabLab AI",
    setupSubtitle:
      "先选择你想怎样使用这个 app。你可以先以访客身份试用一次，也可以登录，让学习记录在手机版和网页版同步保存。",
    checkingLogin: "正在检查已保存的登录状态...",
    firstName: "名字",
    whoAreYou: "你是哪一类用户？",
    bestFit: "最适合",
    language: "语言",
    continueGuest: "以访客身份继续",
    loginSignupSave: "登录 / 注册以保存进度",
    authEyebrow: "VocabLab 手机版",
    loginTitle: "登录后继续",
    signupTitle: "建立你的账户",
    authSubtitle:
      "使用和网页版相同的 VocabLab AI 账户，让你的学习记录、笔记和结果集中保存。你也可以返回，以访客身份先试用一次。",
    login: "登录",
    signup: "注册",
    name: "姓名",
    email: "邮箱",
    password: "密码",
    confirmPassword: "再次确认密码",
    passwordPlaceholder: "至少 8 个字符",
    confirmPasswordPlaceholder: "再次输入密码",
    accountType: "账户类型",
    pleaseWait: "请稍候...",
    createAccount: "建立账户",
    newHere: "第一次使用？建立账户",
    alreadyHaveAccount: "已有账户？登录",
    backToGuest: "返回访客设置",
    personas: {
      student: ["学生", "提升学术阅读能力，建立更稳固的词汇基础。"],
      teacher: ["老师 / 教育工作者", "用于教学、解释词汇，以及建立实用学习材料。"],
      business_professional: ["商务专业人士", "提升会议、写作和决策沟通的精准度。"],
      ai_power_user: ["AI 进阶用户", "强化提示词、分析和高精准度 AI 工作流程。"],
      lifelong_learner: ["终身学习者", "为长期自学和实用表达建立更有信心的词汇能力。"],
    },
  },
} as const;

type PersonaKey = keyof typeof mobileCopy.en.personas;

function getMobileCopy(lang: string) {
  return mobileCopy[(lang as MobileLang) in mobileCopy ? (lang as MobileLang) : "en"];
}

function getPersonaCopy(lang: string, key: string) {
  const copy = getMobileCopy(lang);
  return copy.personas[key as PersonaKey] || mobileCopy.en.personas.lifelong_learner;
}

const bandColors: Record<string, string> = {
  foundation: colors.foundation,
  insight: colors.insight,
  precision: colors.precision,
  intellectual: colors.intellectual,
  elite: colors.elite,
  default: colors.navSoft,
};

function loadBrowserVoices() {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return [] as SpeechSynthesisVoice[];
  }
  return window.speechSynthesis.getVoices();
}

function pickBetterEnglishVoice() {
  const voices = loadBrowserVoices();
  if (!voices.length) {
    return null;
  }

  const scoreVoice = (voice: SpeechSynthesisVoice) => {
    const lang = (voice.lang || "").toLowerCase();
    const name = (voice.name || "").toLowerCase();
    let score = 0;

    if (lang.startsWith("en-us")) score += 5;
    else if (lang.startsWith("en-gb")) score += 4;
    else if (lang.startsWith("en")) score += 3;

    if (name.includes("samantha")) score += 4;
    if (name.includes("ava")) score += 4;
    if (name.includes("allison")) score += 3;
    if (name.includes("daniel")) score += 3;
    if (name.includes("karen")) score += 3;
    if (name.includes("serena")) score += 3;
    if (name.includes("google us english")) score += 2;
    if (name.includes("zira")) score += 2;
    if (name.includes("david")) score += 2;
    if (voice.default) score += 1;
    if (name.includes("compact")) score -= 1;
    if (name.includes("enhanced")) score += 1;
    if (name.includes("premium")) score += 1;

    return score;
  };

  const englishVoices = voices.filter((voice) => (voice.lang || "").toLowerCase().startsWith("en"));
  if (!englishVoices.length) {
    return null;
  }

  return englishVoices.sort((a, b) => scoreVoice(b) - scoreVoice(a))[0];
}

export default function App() {
  const [started, setStarted] = useState(false);
  const [name, setName] = useState("");
  const [lang, setLang] = useState("en");
  const [persona, setPersona] = useState("business_professional");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [showAuthForm, setShowAuthForm] = useState(false);
  const [authUser, setAuthUser] = useState<MobileUser | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authConfirmPassword, setAuthConfirmPassword] = useState("");
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [loadingAuth, setLoadingAuth] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>("home");
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | null>(null);
  const [dictionary, setDictionary] = useState<DictionaryPayload | null>(null);
  const [selectedWord, setSelectedWord] = useState<DictionaryWordDetail | null>(null);
  const [dictionaryQuery, setDictionaryQuery] = useState("analyze");
  const [dictionaryNoteDraft, setDictionaryNoteDraft] = useState("");
  const [aiCategories, setAiCategories] = useState<AiPowerCategoriesPayload | null>(null);
  const [learningQuestion, setLearningQuestion] = useState<LearningQuestionState | null>(null);
  const [learningReview, setLearningReview] = useState<LearningReviewState | null>(null);
  const [learningResult, setLearningResult] = useState<LearningCompletedState | null>(null);
  const [selectedLearningAnswer, setSelectedLearningAnswer] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [loadingHome, setLoadingHome] = useState(false);
  const [loadingDictionary, setLoadingDictionary] = useState(false);
  const [loadingWordDetail, setLoadingWordDetail] = useState(false);
  const [loadingAi, setLoadingAi] = useState(false);
  const [loadingLearning, setLoadingLearning] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [savingDictionaryNote, setSavingDictionaryNote] = useState(false);
  const [error, setError] = useState("");
  const [pronunciationNotice, setPronunciationNotice] = useState("");
  const [noteNotice, setNoteNotice] = useState("");

  useEffect(() => {
    setCheckingAuth(true);
    fetchMobileMe(lang)
      .then((payload) => {
        if (payload.authenticated && payload.user) {
          applyAuthenticatedUser(payload.user);
        }
      })
      .catch(() => {
        setAuthUser(null);
        setStarted(false);
      })
      .finally(() => setCheckingAuth(false));
  }, []);

  useEffect(() => {
    if (!started) {
      return;
    }
    setLoadingHome(true);
    setError("");
    fetchBootstrap({ lang, name, persona })
      .then(setBootstrap)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingHome(false));
  }, [started, lang, name, persona]);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }
    window.speechSynthesis.getVoices();
    const handleVoicesChanged = () => {
      window.speechSynthesis.getVoices();
    };
    window.speechSynthesis.onvoiceschanged = handleVoicesChanged;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  useEffect(() => {
    if (!started || activeTab !== "dictionary") {
      return;
    }
    setSelectedWord(null);
    setLoadingDictionary(true);
    fetchDictionarySearch({ q: dictionaryQuery, lang })
      .then(setDictionary)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingDictionary(false));
  }, [started, activeTab, dictionaryQuery, lang]);

  useEffect(() => {
    if (!started || activeTab !== "ai") {
      return;
    }
    setLoadingAi(true);
    fetchAiPowerCategories(lang)
      .then(setAiCategories)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingAi(false));
  }, [started, activeTab, lang]);

  useEffect(() => {
    if (!started || activeTab !== "learning") {
      return;
    }
    if (learningQuestion || learningReview || learningResult) {
      return;
    }
    startLearningFlow();
  }, [started, activeTab, lang]);

  const greetingName = useMemo(() => {
    if (bootstrap?.profile?.name) {
      return bootstrap.profile.name;
    }
    return name.trim() || "Lawrence";
  }, [bootstrap?.profile?.name, name]);

  const selectedPersonaLabel = useMemo(
    () => getPersonaCopy(lang, persona)[0],
    [lang, persona],
  );
  const copy = getMobileCopy(lang);

  function applyAuthenticatedUser(user: MobileUser) {
    setAuthUser(user);
    setName(user.display_name || "");
    setPersona(user.persona || "student");
    setShowAuthForm(false);
    setStarted(true);
    setActiveTab("home");
  }

  function continueAsGuest() {
    setAuthUser(null);
    setShowAuthForm(false);
    setStarted(true);
    setActiveTab("home");
  }

  function openAuthForm(mode: AuthMode = "login") {
    setAuthMode(mode);
    setShowAuthForm(true);
    setError("");
  }

  function clearAuthForm() {
    setAuthEmail("");
    setAuthPassword("");
    setAuthConfirmPassword("");
  }

  function submitAuthForm() {
    setLoadingAuth(true);
    setError("");
    const email = authEmail.trim();
    const password = authPassword;
    const request =
      authMode === "login"
        ? mobileLogin({ email, password, lang })
        : mobileSignup({
            display_name: name.trim(),
            email,
            password,
            confirm_password: authConfirmPassword,
            persona,
            lang,
          });
    request
      .then((payload) => {
        if (payload.user) {
          applyAuthenticatedUser(payload.user);
          clearAuthForm();
        }
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingAuth(false));
  }

  function logout() {
    setLoadingAuth(true);
    setError("");
    mobileLogout(lang)
      .then(() => {
        setAuthUser(null);
        setStarted(false);
        setShowAuthForm(false);
        setActiveTab("home");
        setBootstrap(null);
        resetLearningFlow();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingAuth(false));
  }

  function openDictionaryWithWord(word: string) {
    setDictionaryQuery(word);
    setSelectedWord(null);
    setActiveTab("dictionary");
  }

  function openWordDetail(wordId: number) {
    setLoadingWordDetail(true);
    setError("");
    fetchDictionaryWordDetail(wordId, lang)
      .then((payload) => {
        setSelectedWord(payload);
        setDictionaryNoteDraft(payload.notes || "");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingWordDetail(false));
  }

  function closeWordDetail() {
    setSelectedWord(null);
    setDictionaryNoteDraft("");
  }

  function resetLearningFlow() {
    setLearningQuestion(null);
    setLearningReview(null);
    setLearningResult(null);
    setSelectedLearningAnswer("");
    setNoteDraft("");
    setNoteNotice("");
  }

  function applyLearningState(payload: LearningQuestionState | LearningCompletedState) {
    setLearningReview(null);
    setSelectedLearningAnswer("");
    setNoteDraft("");
    setNoteNotice("");
    if (payload.status === "completed") {
      setLearningQuestion(null);
      setLearningResult(payload);
      return;
    }
    setLearningResult(null);
    setLearningQuestion(payload);
  }

  function startLearningFlow() {
    setLoadingLearning(true);
    setError("");
    resetLearningFlow();
    fetchLearningStart(lang)
      .then((payload) => {
        applyLearningState(payload);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingLearning(false));
  }

  function continueLearningFlow() {
    const sessionId = learningReview?.session_id ?? learningQuestion?.session_id ?? learningResult?.session_id;
    if (!sessionId) {
      startLearningFlow();
      return;
    }
    setLoadingLearning(true);
    setError("");
    fetchLearningState(sessionId, lang)
      .then((payload) => {
        applyLearningState(payload);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingLearning(false));
  }

  function submitCurrentLearningAnswer() {
    if (!learningQuestion || !selectedLearningAnswer) {
      return;
    }
    setLoadingLearning(true);
    setError("");
    submitLearningAnswer(learningQuestion.session_id, selectedLearningAnswer, lang)
      .then((payload) => {
        setLearningQuestion(null);
        setLearningResult(null);
        setLearningReview(payload);
        setNoteDraft(payload.review.word.notes || "");
        setNoteNotice("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingLearning(false));
  }

  function restartIncorrectLearning() {
    const sessionId = learningResult?.session_id;
    if (!sessionId) {
      return;
    }
    setLoadingLearning(true);
    setError("");
    resetLearningFlow();
    retryIncorrectLearning(sessionId, lang)
      .then((payload) => {
        applyLearningState(payload);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingLearning(false));
  }

  function saveCurrentReviewNote() {
    const wordId = learningReview?.review.word.id;
    if (!wordId) {
      return;
    }
    setSavingNote(true);
    setError("");
    setNoteNotice("");
    saveWordNote(wordId, noteDraft, lang)
      .then((payload) => {
        setNoteDraft(payload.notes);
        setLearningReview((current) =>
          current
            ? {
                ...current,
                review: {
                  ...current.review,
                  word: {
                    ...current.review.word,
                    notes: payload.notes,
                  },
                },
              }
            : current,
        );
        setNoteNotice("Note saved");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSavingNote(false));
  }

  function saveDictionaryNote() {
    const wordId = selectedWord?.id;
    if (!wordId) {
      return;
    }
    setSavingDictionaryNote(true);
    setError("");
    setNoteNotice("");
    saveWordNote(wordId, dictionaryNoteDraft, lang)
      .then((payload) => {
        setDictionaryNoteDraft(payload.notes);
        setSelectedWord((current) => (current ? { ...current, notes: payload.notes } : current));
        setNoteNotice("Note saved");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSavingDictionaryNote(false));
  }

  function pronounceWord(text: string) {
    if (!text) {
      return;
    }
    if (Platform.OS === "web" && typeof window !== "undefined" && "speechSynthesis" in window) {
      const synth = window.speechSynthesis;
      synth.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-US";
      utterance.rate = 0.76;
      utterance.pitch = 0.92;
      utterance.volume = 1;
      const preferredVoice = pickBetterEnglishVoice();
      if (preferredVoice) {
        utterance.voice = preferredVoice;
        utterance.lang = preferredVoice.lang || "en-US";
      }
      synth.speak(utterance);
      setPronunciationNotice(preferredVoice ? `Playing "${text}" with a natural English voice.` : `Playing "${text}" with the browser voice.`);
      return;
    }
    setPronunciationNotice("Pronunciation is currently available in web preview first.");
  }

  if (!started && !showAuthForm) {
    return (
      <SafeAreaView style={styles.safe}>
        <ExpoStatusBar style="dark" />
        <ScrollView contentContainerStyle={styles.onboardingWrap}>
          <Text style={styles.eyebrow}>{copy.setupEyebrow}</Text>
          <Text style={styles.title}>{copy.setupTitle}</Text>
          <Text style={styles.subtitle}>{copy.setupSubtitle}</Text>

          <View style={styles.panel}>
            {checkingAuth ? (
              <View style={styles.authLoadingBox}>
                <ActivityIndicator color={colors.navSoft} />
                <Text style={styles.cardNote}>{copy.checkingLogin}</Text>
              </View>
            ) : null}

            <Text style={styles.label}>{copy.firstName}</Text>
            <TextInput
              value={name}
              onChangeText={setName}
              placeholder="Wah"
              placeholderTextColor="#9d9488"
              style={styles.input}
              autoCapitalize="words"
            />

            <Text style={[styles.label, styles.sectionLabel]}>{copy.whoAreYou}</Text>
            {personaOptions.map((option) => {
              const [personaLabel, personaDescription] = getPersonaCopy(lang, option.key);
              return (
                <Pressable
                  key={option.key}
                  onPress={() => setPersona(option.key)}
                  style={[
                    styles.personaCard,
                    persona === option.key && styles.personaCardActive,
                    option.featured && styles.personaFeatured,
                  ]}
                >
                  <View style={styles.personaHead}>
                    <Text style={styles.personaTitle}>{personaLabel}</Text>
                    {option.featured ? <Text style={styles.featuredTag}>{copy.bestFit}</Text> : null}
                  </View>
                  <Text style={styles.personaDesc}>{personaDescription}</Text>
                </Pressable>
              );
            })}

            <Text style={[styles.label, styles.sectionLabel]}>{copy.language}</Text>
            <View style={styles.langRow}>
              {[
                ["en", "English"],
                ["zh-Hant", "繁中"],
                ["zh-Hans", "简中"],
              ].map(([key, label]) => (
                <Pressable
                  key={key}
                  onPress={() => setLang(key)}
                  style={[styles.langChip, lang === key && styles.langChipActive]}
                >
                  <Text style={[styles.langChipText, lang === key && styles.langChipTextActive]}>{label}</Text>
                </Pressable>
              ))}
            </View>

            <Pressable style={styles.primaryButton} onPress={continueAsGuest}>
              <Text style={styles.primaryButtonText}>{copy.continueGuest}</Text>
            </Pressable>

            <Pressable style={styles.secondaryButton} onPress={() => openAuthForm("login")}>
              <Text style={styles.secondaryButtonText}>{copy.loginSignupSave}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (!started && showAuthForm) {
    return (
      <SafeAreaView style={styles.safe}>
        <ExpoStatusBar style="dark" />
        <ScrollView contentContainerStyle={styles.onboardingWrap}>
          <Text style={styles.eyebrow}>{copy.authEyebrow}</Text>
          <Text style={styles.title}>{authMode === "login" ? copy.loginTitle : copy.signupTitle}</Text>
          <Text style={styles.subtitle}>{copy.authSubtitle}</Text>

          <View style={styles.panel}>
            {checkingAuth ? (
              <View style={styles.authLoadingBox}>
                <ActivityIndicator color={colors.navSoft} />
                <Text style={styles.cardNote}>{copy.checkingLogin}</Text>
              </View>
            ) : null}

            <View style={styles.authModeRow}>
              {[
                ["login", copy.login],
                ["signup", copy.signup],
              ].map(([key, label]) => (
                <Pressable
                  key={key}
                  onPress={() => {
                    setAuthMode(key as AuthMode);
                    setError("");
                  }}
                  style={[styles.authModeButton, authMode === key && styles.authModeButtonActive]}
                >
                  <Text style={[styles.authModeText, authMode === key && styles.authModeTextActive]}>{label}</Text>
                </Pressable>
              ))}
            </View>

            {authMode === "signup" ? (
              <>
                <Text style={styles.label}>{copy.name}</Text>
                <TextInput
                  value={name}
                  onChangeText={setName}
                  placeholder="Wah"
                  placeholderTextColor="#9d9488"
                  style={styles.input}
                  autoCapitalize="words"
                />
              </>
            ) : null}

            <Text style={styles.label}>{copy.email}</Text>
            <TextInput
              value={authEmail}
              onChangeText={setAuthEmail}
              placeholder="student@example.com"
              placeholderTextColor="#9d9488"
              style={styles.input}
              autoCapitalize="none"
              keyboardType="email-address"
            />

            <Text style={styles.label}>{copy.password}</Text>
            <TextInput
              value={authPassword}
              onChangeText={setAuthPassword}
              placeholder={copy.passwordPlaceholder}
              placeholderTextColor="#9d9488"
              style={styles.input}
              secureTextEntry
            />

            {authMode === "signup" ? (
              <>
                <Text style={styles.label}>{copy.confirmPassword}</Text>
                <TextInput
                  value={authConfirmPassword}
                  onChangeText={setAuthConfirmPassword}
                  placeholder={copy.confirmPasswordPlaceholder}
                  placeholderTextColor="#9d9488"
                  style={styles.input}
                  secureTextEntry
                />

                <Text style={[styles.label, styles.sectionLabel]}>{copy.accountType}</Text>
                {personaOptions.map((option) => {
                  const [personaLabel, personaDescription] = getPersonaCopy(lang, option.key);
                  return (
                    <Pressable
                      key={option.key}
                      onPress={() => setPersona(option.key)}
                      style={[
                        styles.personaCard,
                        persona === option.key && styles.personaCardActive,
                        option.featured && styles.personaFeatured,
                      ]}
                    >
                      <View style={styles.personaHead}>
                        <Text style={styles.personaTitle}>{personaLabel}</Text>
                        {option.featured ? <Text style={styles.featuredTag}>{copy.bestFit}</Text> : null}
                      </View>
                      <Text style={styles.personaDesc}>{personaDescription}</Text>
                    </Pressable>
                  );
                })}
              </>
            ) : null}

            <Text style={[styles.label, styles.sectionLabel]}>{copy.language}</Text>
            <View style={styles.langRow}>
              {[
                ["en", "English"],
                ["zh-Hant", "繁中"],
                ["zh-Hans", "简中"],
              ].map(([key, label]) => (
                <Pressable
                  key={key}
                  onPress={() => setLang(key)}
                  style={[styles.langChip, lang === key && styles.langChipActive]}
                >
                  <Text style={[styles.langChipText, lang === key && styles.langChipTextActive]}>{label}</Text>
                </Pressable>
              ))}
            </View>

            {error ? <Text style={styles.authErrorText}>{error}</Text> : null}

            <Pressable style={[styles.primaryButton, loadingAuth && styles.primaryButtonDisabled]} onPress={submitAuthForm} disabled={loadingAuth}>
              <Text style={styles.primaryButtonText}>
                {loadingAuth ? copy.pleaseWait : authMode === "login" ? copy.login : copy.createAccount}
              </Text>
            </Pressable>

            <Pressable
              style={styles.authSwitchLink}
              onPress={() => {
                setAuthMode(authMode === "login" ? "signup" : "login");
                setError("");
              }}
            >
              <Text style={styles.authSwitchText}>
                {authMode === "login" ? copy.newHere : copy.alreadyHaveAccount}
              </Text>
            </Pressable>

            <Pressable style={styles.authSwitchLink} onPress={() => setShowAuthForm(false)}>
              <Text style={styles.authSwitchText}>{copy.backToGuest}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ExpoStatusBar style="dark" />
      <StatusBar barStyle="dark-content" />

      <View style={styles.header}>
        <View>
          <Text style={styles.headerBrand}>VocabLab AI</Text>
          <Text style={styles.headerMeta}>Personal vocabulary system</Text>
        </View>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{bootstrap?.profile.initials || "EL"}</Text>
        </View>
      </View>

      <View style={styles.navTabs}>
        {[
          ["home", "Home"],
          ["learning", "Learning"],
          ["dictionary", "Dictionary"],
          ["ai", "AI"],
          ["profile", "Profile"],
        ].map(([key, label]) => (
          <Pressable
            key={key}
            onPress={() => setActiveTab(key as TabKey)}
            style={[styles.navTab, activeTab === key && styles.navTabActive]}
          >
            <Text style={[styles.navTabText, activeTab === key && styles.navTabTextActive]}>{label}</Text>
          </Pressable>
        ))}
      </View>

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
      {pronunciationNotice ? <Text style={styles.noticeText}>{pronunciationNotice}</Text> : null}
      {noteNotice ? <Text style={styles.noticeText}>{noteNotice}</Text> : null}

      <ScrollView contentContainerStyle={styles.screen}>
        {activeTab === "home" && (
          <>
            {loadingHome || !bootstrap ? (
              <View style={[styles.card, shadows.card]}>
                <ActivityIndicator size="large" color={colors.navSoft} />
                <Text style={styles.loadingTitle}>Preparing your mobile dashboard...</Text>
                <Text style={styles.cardNote}>
                  We&apos;re loading your vocabulary snapshot, recommendations, and today&apos;s words.
                </Text>
              </View>
            ) : (
              <>
                <View style={[styles.heroCard, shadows.card]}>
                  <View style={styles.heroTopRow}>
                    <View style={styles.heroBadge}>
                      <Text style={styles.heroBadgeText}>{selectedPersonaLabel}</Text>
                    </View>
                    <View style={styles.heroBadgeSoft}>
                      <Text style={styles.heroBadgeSoftText}>
                        {lang === "en" ? "English" : lang === "zh-Hant" ? "繁中" : "简中"}
                      </Text>
                    </View>
                  </View>
                  <Text style={styles.quote}>
                    “Without grammar very little can be conveyed, without vocabulary nothing can be conveyed.”
                  </Text>
                </View>

                <View style={[styles.card, shadows.card]}>
                  <Text style={styles.sectionEyebrow}>Dashboard</Text>
                  <Text style={styles.cardTitle}>Hello, {greetingName}</Text>
                  <Text style={styles.cardBody}>{bootstrap.profile.persona_message}</Text>
                  <Text style={styles.cardNote}>{bootstrap.profile.recommendation_note}</Text>
                  <View style={styles.quickActionRow}>
                    <QuickAction label="Open Dictionary" tone="soft" onPress={() => setActiveTab("dictionary")} />
                    <QuickAction label="Open AI Track" tone="primary" onPress={() => setActiveTab("ai")} />
                  </View>
                </View>

                <View style={styles.metricGrid}>
                  <MetricCard label="Total Words" value={String(bootstrap.stats.total_words)} />
                  <MetricCard label="Tests Taken" value={String(bootstrap.stats.tests_taken)} />
                  <MetricCard label="Learning Runs" value={String(bootstrap.stats.learning_runs)} />
                  <MetricCard label="AI Power" value={bootstrap.ai_power_summary.progress_label} />
                </View>

                <View style={styles.featureGrid}>
                  <FeatureCard
                    eyebrow="Recommended band"
                    title={bootstrap.recommended_band}
                    note="Start here first so the mobile learning flow can stay focused."
                  />
                  <FeatureCard
                    eyebrow="Missed words"
                    title={String(bootstrap.missed_words_count)}
                    note="These are the words most worth revisiting next."
                  />
                </View>

                <View style={[styles.card, shadows.card]}>
                  <Text style={styles.sectionEyebrow}>Vocabulary Snapshot</Text>
                  <Text style={styles.cardTitle}>Frequency bands</Text>
                  <View style={styles.chartRow}>
                    {bootstrap.hero_band_chart.map((band) => (
                      <View key={band.label} style={styles.chartColumn}>
                        <Text style={[styles.chartValue, { color: bandColors[band.tone] || colors.navSoft }]}>
                          {band.count}
                        </Text>
                        <View style={styles.chartTrack}>
                          <View
                            style={[
                              styles.chartBar,
                              {
                                height: `${band.percent}%`,
                                backgroundColor: bandColors[band.tone] || colors.navSoft,
                              },
                            ]}
                          />
                        </View>
                        <Text style={styles.chartLabel}>{band.title}</Text>
                        <Text style={styles.chartSub}>{band.label}</Text>
                      </View>
                    ))}
                  </View>
                </View>

                <View style={[styles.card, shadows.card]}>
                  <Text style={styles.sectionEyebrow}>Today&apos;s Words</Text>
                  <Text style={styles.cardTitle}>Start with a few words</Text>
                  <Text style={styles.cardNote}>Tap a word and we&apos;ll jump into Dictionary search with it.</Text>
                  {bootstrap.spotlight_words.map((word) => (
                    <Pressable key={word.id} style={styles.wordRow} onPress={() => openDictionaryWithWord(word.lemma)}>
                      <View style={styles.wordMeta}>
                        <Text style={styles.wordLemma}>{word.lemma}</Text>
                        <Text style={styles.wordChinese}>{word.chinese_headword}</Text>
                      </View>
                      <Text style={styles.wordDefinition} numberOfLines={2}>
                        {word.english_definition}
                      </Text>
                    </Pressable>
                  ))}
                </View>

                <View style={[styles.card, shadows.card]}>
                  <Text style={styles.sectionEyebrow}>AI Track</Text>
                  <Text style={styles.cardTitle}>Professional prompt vocabulary</Text>
                  <Text style={styles.cardBody}>
                    Separate from Economist frequency bands, this track focuses on prompting, work communication, and clearer AI instructions.
                  </Text>
                  <View style={styles.aiSummaryRow}>
                    <View style={styles.aiSummaryPill}>
                      <Text style={styles.aiSummaryLabel}>Progress</Text>
                      <Text style={styles.aiSummaryValue}>{bootstrap.ai_power_summary.progress_label}</Text>
                    </View>
                    <View style={styles.aiSummaryPill}>
                      <Text style={styles.aiSummaryLabel}>Categories</Text>
                      <Text style={styles.aiSummaryValue}>{bootstrap.ai_power_summary.category_count}</Text>
                    </View>
                  </View>
                  <QuickAction label="Browse AI categories" tone="primary" onPress={() => setActiveTab("ai")} />
                </View>
              </>
            )}
          </>
        )}

        {activeTab === "learning" && (
          <View style={[styles.card, shadows.card]}>
            <Text style={styles.sectionEyebrow}>Learning</Text>
            {loadingLearning ? (
              <View style={styles.learningLoading}>
                <ActivityIndicator color={colors.navSoft} />
                <Text style={styles.cardNote}>Preparing your next learning step...</Text>
              </View>
            ) : learningReview ? (
              <>
                <View style={styles.learningIntroCard}>
                  <View>
                    <Text style={styles.learningIntroEyebrow}>Review card</Text>
                    <Text style={styles.learningIntroTitle}>
                      {learningReview.review.is_correct ? "You got it." : "Let’s lock this word in."}
                    </Text>
                  </View>
                  <View style={styles.learningMiniStat}>
                    <Text style={styles.learningMiniStatValue}>
                      {learningReview.progress.answered}/{learningReview.progress.total}
                    </Text>
                    <Text style={styles.learningMiniStatLabel}>answered</Text>
                  </View>
                </View>

                <View style={styles.flashcardShell}>
                  <View style={styles.flashcardAccent} />
                  <View style={styles.flashcardBody}>
                    <View style={styles.learningHeader}>
                      <View>
                        <Text style={styles.cardTitle}>{learningReview.review.word.lemma}</Text>
                        <Text style={styles.detailMetaLine}>
                          {[
                            learningReview.review.word.ipa,
                            ...learningReview.review.word.parts_of_speech,
                          ]
                            .filter(Boolean)
                            .join("  •  ") || "Learning review"}
                        </Text>
                      </View>
                      <Pressable
                        style={styles.pronounceButton}
                        onPress={() => pronounceWord(learningReview.review.word.lemma)}
                      >
                        <Text style={styles.pronounceButtonText}>🔊</Text>
                      </Pressable>
                    </View>

                    <View style={styles.progressRow}>
                      <Text style={styles.resultBand}>{learningReview.review.question_type_label}</Text>
                      <Text style={styles.resultMeta}>
                        {learningReview.progress.answered} / {learningReview.progress.total}
                      </Text>
                    </View>
                    <View style={styles.progressTrack}>
                      <View
                        style={[
                          styles.progressFill,
                          { width: `${Math.max(10, learningReview.progress.percent)}%` },
                        ]}
                      />
                    </View>

                    <View
                      style={[
                        styles.feedbackBanner,
                        learningReview.review.is_correct ? styles.feedbackBannerCorrect : styles.feedbackBannerWrong,
                      ]}
                    >
                      <Text
                        style={[
                          styles.feedbackBannerTitle,
                          learningReview.review.is_correct ? styles.feedbackTextCorrect : styles.feedbackTextWrong,
                        ]}
                      >
                        {learningReview.review.is_correct ? "Correct" : "Not quite yet"}
                      </Text>
                      <Text style={styles.cardNote}>{learningReview.review.prompt_text}</Text>
                    </View>

                    <View style={styles.detailGrid}>
                      <View style={[styles.detailSection, styles.detailGridItem]}>
                        <Text style={styles.detailLabel}>Your Answer</Text>
                        <Text style={styles.detailBody}>{learningReview.review.user_answer || "No answer selected."}</Text>
                      </View>
                      <View style={[styles.detailSection, styles.detailGridItem]}>
                        <Text style={styles.detailLabel}>Correct Answer</Text>
                        <Text style={styles.detailBody}>{learningReview.review.correct_option}</Text>
                      </View>
                    </View>
                  </View>
                </View>

                <View style={styles.detailGrid}>
                  <View style={[styles.detailSection, styles.detailGridItem]}>
                    <Text style={styles.detailLabel}>Chinese</Text>
                    {learningReview.review.word.chinese_definitions.length ? (
                      learningReview.review.word.chinese_definitions.map((meaning, index) => (
                        <Text key={`${meaning}-${index}`} style={styles.detailBody}>
                          • {meaning}
                        </Text>
                      ))
                    ) : (
                      <Text style={styles.detailBodyMuted}>No Chinese meaning yet.</Text>
                    )}
                  </View>
                  <View style={[styles.detailSection, styles.detailGridItem]}>
                    <Text style={styles.detailLabel}>English Definition</Text>
                    <Text style={styles.detailBody}>
                      {learningReview.review.word.english_definition || "No English definition yet."}
                    </Text>
                  </View>
                </View>

                <View style={styles.detailGrid}>
                  <View style={[styles.detailSection, styles.detailGridItem]}>
                    <Text style={styles.detailLabel}>Example Sentence</Text>
                    <Text style={styles.detailBody}>
                      {learningReview.review.word.example_sentence || "No example sentence yet."}
                    </Text>
                  </View>
                  <View style={[styles.detailSection, styles.detailGridItem]}>
                    <Text style={styles.detailLabel}>Synonyms</Text>
                    {learningReview.review.word.synonyms.length ? (
                      <View style={styles.synonymWrap}>
                        {learningReview.review.word.synonyms.map((synonym) => (
                          <View key={synonym} style={styles.synonymChip}>
                            <Text style={styles.synonymChipText}>{synonym}</Text>
                          </View>
                        ))}
                      </View>
                    ) : (
                      <Text style={styles.detailBodyMuted}>No synonyms yet.</Text>
                    )}
                  </View>
                </View>

                {learningReview.review.word.notes ? (
                  <View style={styles.detailSection}>
                    <Text style={styles.detailLabel}>Saved note</Text>
                    <Text style={styles.detailBody}>{learningReview.review.word.notes}</Text>
                  </View>
                ) : null}

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Personal note</Text>
                  <Text style={styles.detailBodyMuted}>
                    Add a short memory hook, Chinese cue, or reminder for next time.
                  </Text>
                  <TextInput
                    value={noteDraft}
                    onChangeText={setNoteDraft}
                    placeholder="Example: use this in meeting summaries"
                    placeholderTextColor="#9d9488"
                    multiline
                    style={[styles.input, styles.noteInput]}
                  />
                  <View style={styles.quickActionRow}>
                    <QuickAction
                      label={savingNote ? "Saving..." : "Save note"}
                      tone="primary"
                      onPress={saveCurrentReviewNote}
                      disabled={savingNote}
                    />
                  </View>
                </View>

                {learningReview.review.explanation ? (
                  <View style={styles.detailSection}>
                    <Text style={styles.detailLabel}>Why this answer works</Text>
                    <Text style={styles.detailBody}>{learningReview.review.explanation}</Text>
                  </View>
                ) : null}

                <View style={styles.quickActionRow}>
                  <QuickAction
                    label={learningReview.is_last ? "See summary" : "Next question"}
                    tone="primary"
                    onPress={continueLearningFlow}
                  />
                  <QuickAction label="Restart session" tone="soft" onPress={startLearningFlow} />
                </View>
              </>
            ) : learningResult ? (
              <>
                <View style={styles.learningIntroCard}>
                  <View>
                    <Text style={styles.learningIntroEyebrow}>Session summary</Text>
                    <Text style={styles.learningIntroTitle}>Round finished</Text>
                  </View>
                  <View style={styles.learningMiniStat}>
                    <Text style={styles.learningMiniStatValue}>{learningResult.result.percent}%</Text>
                    <Text style={styles.learningMiniStatLabel}>accuracy</Text>
                  </View>
                </View>
                <Text style={styles.cardTitle}>Session complete</Text>
                <Text style={styles.metricValue}>
                  {learningResult.result.score} / {learningResult.result.total}
                </Text>
                <Text style={styles.cardBody}>{learningResult.result.percent}% accuracy</Text>
                <Text style={styles.cardNote}>{learningResult.result.recommendation}</Text>
                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Breakdown</Text>
                  {learningResult.result.breakdown.map((item) => (
                    <View key={item.question_type} style={styles.breakdownRow}>
                      <Text style={styles.detailBody}>{item.question_type_label}</Text>
                      <Text style={styles.resultMeta}>
                        {item.correct} / {item.total}
                      </Text>
                    </View>
                  ))}
                </View>
                {learningResult.result.breakdown.length ? (
                  <View style={styles.detailGrid}>
                    <View style={[styles.detailSection, styles.detailGridItem]}>
                      <Text style={styles.detailLabel}>Strongest area</Text>
                      <Text style={styles.detailBody}>
                        {
                          [...learningResult.result.breakdown].sort(
                            (a, b) => b.correct / Math.max(b.total, 1) - a.correct / Math.max(a.total, 1),
                          )[0].question_type_label
                        }
                      </Text>
                    </View>
                    <View style={[styles.detailSection, styles.detailGridItem]}>
                      <Text style={styles.detailLabel}>Next focus</Text>
                      <Text style={styles.detailBody}>
                        {
                          [...learningResult.result.breakdown].sort(
                            (a, b) => a.correct / Math.max(a.total, 1) - b.correct / Math.max(b.total, 1),
                          )[0].question_type_label
                        }
                      </Text>
                    </View>
                  </View>
                ) : null}
                {learningResult.result.score < learningResult.result.total ? (
                  <View style={styles.detailSection}>
                    <Text style={styles.detailLabel}>Quick next step</Text>
                    <Text style={styles.detailBody}>
                      You can start a full new round, or redo only the words you missed in this session.
                    </Text>
                  </View>
                ) : null}
                <View style={styles.quickActionRow}>
                  <QuickAction label="Start another round" tone="primary" onPress={startLearningFlow} />
                  {learningResult.result.score < learningResult.result.total ? (
                    <QuickAction label="Retry missed words" tone="soft" onPress={restartIncorrectLearning} />
                  ) : null}
                  <QuickAction label="Open Dictionary" tone="soft" onPress={() => setActiveTab("dictionary")} />
                </View>
              </>
            ) : learningQuestion ? (
              <>
                <View style={styles.learningIntroCard}>
                  <View>
                    <Text style={styles.learningIntroEyebrow}>Question {learningQuestion.progress.current}</Text>
                    <Text style={styles.learningIntroTitle}>Stay with one word at a time</Text>
                  </View>
                  <View style={styles.learningMiniStat}>
                    <Text style={styles.learningMiniStatValue}>{learningQuestion.progress.total}</Text>
                    <Text style={styles.learningMiniStatLabel}>questions</Text>
                  </View>
                </View>

                <View style={styles.flashcardShell}>
                  <View style={styles.flashcardAccent} />
                  <View style={styles.flashcardBody}>
                    <View style={styles.learningHeader}>
                      <View>
                        <Text style={styles.cardTitle}>{learningQuestion.question.word.lemma}</Text>
                        <Text style={styles.detailMetaLine}>
                          {[
                            learningQuestion.question.word.ipa,
                            ...learningQuestion.question.word.parts_of_speech,
                          ]
                            .filter(Boolean)
                            .join("  •  ") || "Learning question"}
                        </Text>
                      </View>
                      <Pressable
                        style={styles.pronounceButton}
                        onPress={() => pronounceWord(learningQuestion.question.word.lemma)}
                      >
                        <Text style={styles.pronounceButtonText}>🔊</Text>
                      </Pressable>
                    </View>

                    <View style={styles.progressRow}>
                      <Text style={styles.resultBand}>{learningQuestion.question.question_type_label}</Text>
                      <Text style={styles.resultMeta}>
                        {learningQuestion.progress.current} / {learningQuestion.progress.total}
                      </Text>
                    </View>

                    <View style={styles.progressTrack}>
                      <View
                        style={[
                          styles.progressFill,
                          { width: `${Math.max(10, learningQuestion.progress.percent)}%` },
                        ]}
                      />
                    </View>

                    <View style={styles.flashcardPrompt}>
                      <Text style={styles.detailLabel}>Word focus</Text>
                      <Text style={styles.detailBodyMuted}>
                        Listen to the word, read the prompt, then choose the best answer before moving on.
                      </Text>
                    </View>

                    <View style={styles.flashcardQuestion}>
                      <Text style={styles.detailLabel}>Question</Text>
                      <Text style={styles.flashcardQuestionText}>{learningQuestion.question.prompt_text}</Text>
                    </View>
                  </View>
                </View>

                <View style={styles.answerList}>
                  {learningQuestion.question.options.map((option) => {
                    const active = selectedLearningAnswer === option;
                    return (
                      <Pressable
                        key={option}
                        style={[styles.answerOption, active && styles.answerOptionActive]}
                        onPress={() => setSelectedLearningAnswer(option)}
                      >
                        <View style={[styles.answerDot, active && styles.answerDotActive]} />
                        <Text style={[styles.answerText, active && styles.answerTextActive]}>{option}</Text>
                      </Pressable>
                    );
                  })}
                </View>

                <View style={styles.quickActionRow}>
                  <QuickAction
                    label="Submit answer"
                    tone="primary"
                    onPress={submitCurrentLearningAnswer}
                    disabled={!selectedLearningAnswer}
                  />
                  <QuickAction label="Restart session" tone="soft" onPress={startLearningFlow} />
                </View>
              </>
            ) : (
              <>
                <Text style={styles.cardTitle}>Learning flow</Text>
                <Text style={styles.cardBody}>
                  Start a short session and we&apos;ll give you one multiple-choice question at a time, then explain the word after each answer.
                </Text>
                <QuickAction label="Start learning" tone="primary" onPress={startLearningFlow} />
              </>
            )}
          </View>
        )}

        {activeTab === "dictionary" && (
          <View style={[styles.card, shadows.card]}>
            <Text style={styles.sectionEyebrow}>Dictionary</Text>
            {selectedWord ? (
              <>
                <Pressable style={styles.backLink} onPress={closeWordDetail}>
                  <Text style={styles.backLinkText}>← Back to results</Text>
                </Pressable>
                <View style={styles.detailHeroRow}>
                  <View style={styles.detailHeroMain}>
                    <Text style={styles.cardTitle}>{selectedWord.lemma}</Text>
                    <Text style={styles.detailMetaLine}>
                      {[selectedWord.ipa, ...selectedWord.parts_of_speech].filter(Boolean).join("  •  ") || "No IPA or word type yet"}
                    </Text>
                  </View>
                  <Pressable style={styles.pronounceButton} onPress={() => pronounceWord(selectedWord.lemma)}>
                    <Text style={styles.pronounceButtonText}>🔊</Text>
                  </Pressable>
                </View>
                <View style={styles.detailTopBadges}>
                  <Text style={styles.resultBand}>{selectedWord.band_label}</Text>
                  <Text style={styles.detailStatus}>{selectedWord.status}</Text>
                  <Text style={styles.detailCounter}>✓ {selectedWord.correct_count}</Text>
                  <Text style={styles.detailCounter}>✗ {selectedWord.wrong_count}</Text>
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Chinese</Text>
                  {selectedWord.chinese_definitions.length ? (
                    selectedWord.chinese_definitions.map((meaning, index) => (
                      <Text key={`${meaning}-${index}`} style={styles.detailBody}>
                        • {meaning}
                      </Text>
                    ))
                  ) : (
                    <Text style={styles.detailBodyMuted}>No Chinese meaning yet.</Text>
                  )}
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>English Definition</Text>
                  <Text style={styles.detailBody}>
                    {selectedWord.english_definition || "No English definition yet."}
                  </Text>
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Example Sentence</Text>
                  <Text style={styles.detailBody}>
                    {selectedWord.example_sentence || "No example sentence yet."}
                  </Text>
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Synonyms</Text>
                  {selectedWord.synonyms.length ? (
                    <View style={styles.synonymWrap}>
                      {selectedWord.synonyms.map((synonym) => (
                        <View key={synonym} style={styles.synonymChip}>
                          <Text style={styles.synonymChipText}>{synonym}</Text>
                        </View>
                      ))}
                    </View>
                  ) : (
                    <Text style={styles.detailBodyMuted}>No synonyms yet.</Text>
                  )}
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Saved note</Text>
                  <Text style={styles.detailBody}>
                    {selectedWord.notes || "No notes yet."}
                  </Text>
                </View>

                <View style={styles.detailSection}>
                  <Text style={styles.detailLabel}>Personal note</Text>
                  <Text style={styles.detailBodyMuted}>
                    Add your own memory hook, Chinese cue, or usage reminder for this word.
                  </Text>
                  <TextInput
                    value={dictionaryNoteDraft}
                    onChangeText={setDictionaryNoteDraft}
                    placeholder="Example: useful in editorial writing"
                    placeholderTextColor="#9d9488"
                    multiline
                    style={[styles.input, styles.noteInput]}
                  />
                  <View style={styles.quickActionRow}>
                    <QuickAction
                      label={savingDictionaryNote ? "Saving..." : "Save note"}
                      tone="primary"
                      onPress={saveDictionaryNote}
                      disabled={savingDictionaryNote}
                    />
                  </View>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.cardTitle}>Search vocabulary fast</Text>
                <Text style={styles.cardNote}>Search by English word first, then tap a result to open the full word card.</Text>
                <TextInput
                  value={dictionaryQuery}
                  onChangeText={setDictionaryQuery}
                  placeholder="analyze"
                  placeholderTextColor="#9d9488"
                  style={styles.input}
                />
                {(loadingDictionary || loadingWordDetail) ? <ActivityIndicator color={colors.navSoft} /> : null}
                <Text style={styles.resultMeta}>
                  {dictionary ? `${dictionary.result_count} results` : "Search results will appear here"}
                </Text>
                {dictionary?.results.map((item) => (
                  <Pressable key={item.id} style={styles.resultCard} onPress={() => openWordDetail(item.id)}>
                    <Text style={styles.wordLemma}>{item.lemma}</Text>
                    <Text style={styles.wordChinese}>{item.chinese_headword}</Text>
                    <Text style={styles.wordDefinition}>{item.english_definition}</Text>
                    <Text style={styles.resultBand}>{item.band_label}</Text>
                  </Pressable>
                ))}
              </>
            )}
          </View>
        )}

        {activeTab === "ai" && (
          <View style={[styles.card, shadows.card]}>
            <Text style={styles.sectionEyebrow}>AI Track</Text>
            <Text style={styles.cardTitle}>AI instruction vocabulary</Text>
            <Text style={styles.cardBody}>
              This track is separate from Economist frequency bands and focuses on prompting, work communication, and professional precision.
            </Text>
            {loadingAi ? <ActivityIndicator color={colors.navSoft} /> : null}
            <View style={styles.resultMetaRow}>
              <Text style={styles.resultMeta}>
                {aiCategories ? `${aiCategories.categories.length} categories` : "Loading categories"}
              </Text>
              {aiCategories ? <Text style={styles.resultMeta}>{aiCategories.summary.progress_label}</Text> : null}
            </View>
            {aiCategories?.categories.map((category) => (
              <View key={category.slug} style={styles.resultCard}>
                <Text style={styles.wordLemma}>{category.title}</Text>
                <Text style={styles.wordDefinition}>{category.description}</Text>
                <Text style={styles.resultBand}>
                  {category.completed_count} / {category.starter_count}
                </Text>
              </View>
            ))}
          </View>
        )}

        {activeTab === "profile" && (
          <View style={[styles.card, shadows.card]}>
            <Text style={styles.sectionEyebrow}>Profile</Text>
            <Text style={styles.cardTitle}>{greetingName}</Text>
            <Text style={styles.cardBody}>Email: {authUser?.email || "Signed in on this device"}</Text>
            <Text style={styles.cardBody}>Persona: {persona.replaceAll("_", " ")}</Text>
            <Text style={styles.cardBody}>Language: {lang}</Text>
            <Text style={styles.cardNote}>
              {authUser
                ? "Your mobile learning uses the same account system as the web app, so records and notes stay in one place."
                : "You are using guest mode. Login or sign up when you want to save progress across mobile and web."}
            </Text>
            <View style={styles.quickActionRow}>
              {authUser ? (
                <QuickAction label={loadingAuth ? "Signing out..." : "Logout"} tone="soft" onPress={logout} disabled={loadingAuth} />
              ) : (
                <QuickAction
                  label="Login / Sign up"
                  tone="soft"
                  onPress={() => {
                    setStarted(false);
                    openAuthForm("login");
                  }}
                />
              )}
              <QuickAction label="Go to Home" tone="primary" onPress={() => setActiveTab("home")} />
            </View>
            <Text style={styles.footerMeta}>Connected to {API_BASE}</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <View style={[styles.metricCard, shadows.card]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

function FeatureCard({ eyebrow, title, note }: { eyebrow: string; title: string; note: string }) {
  return (
    <View style={[styles.featureCard, shadows.card]}>
      <Text style={styles.sectionEyebrow}>{eyebrow}</Text>
      <Text style={styles.featureTitle}>{title}</Text>
      <Text style={styles.cardNote}>{note}</Text>
    </View>
  );
}

function QuickAction({
  label,
  tone,
  onPress,
  disabled = false,
}: {
  label: string;
  tone: "primary" | "soft";
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      style={[
        styles.quickActionButton,
        tone === "primary" ? styles.quickActionPrimary : styles.quickActionSoft,
        disabled && styles.quickActionDisabled,
      ]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text
        style={[
          styles.quickActionText,
          tone === "primary" ? styles.quickActionTextPrimary : styles.quickActionTextSoft,
          disabled && styles.quickActionTextDisabled,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  onboardingWrap: {
    padding: 24,
    gap: 18,
  },
  screen: {
    padding: 18,
    gap: 16,
    paddingBottom: 44,
  },
  header: {
    paddingHorizontal: 18,
    paddingVertical: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  headerBrand: {
    fontSize: 22,
    fontWeight: "800",
    color: colors.ink,
  },
  headerMeta: {
    marginTop: 4,
    color: colors.muted,
    fontSize: 12,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "#f7ab83",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: {
    color: "#fff",
    fontWeight: "800",
  },
  navTabs: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 18,
    paddingBottom: 10,
  },
  navTab: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    backgroundColor: "#ffffffaa",
    borderWidth: 1,
    borderColor: colors.border,
  },
  navTabActive: {
    backgroundColor: colors.navSoft,
    borderColor: colors.navSoft,
  },
  navTabText: {
    color: colors.ink,
    fontWeight: "700",
  },
  navTabTextActive: {
    color: "#fff",
  },
  eyebrow: {
    color: "#d18955",
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1.2,
    fontSize: 12,
  },
  title: {
    fontSize: 36,
    fontWeight: "900",
    color: colors.ink,
    lineHeight: 42,
  },
  subtitle: {
    color: colors.muted,
    fontSize: 16,
    lineHeight: 24,
  },
  panel: {
    backgroundColor: colors.panel,
    borderRadius: 26,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    gap: 14,
    ...shadows.card,
  },
  label: {
    fontSize: 14,
    fontWeight: "700",
    color: colors.ink,
  },
  sectionLabel: {
    marginTop: 8,
  },
  input: {
    backgroundColor: colors.panelAlt,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.ink,
    fontSize: 16,
  },
  noteInput: {
    minHeight: 108,
    textAlignVertical: "top",
    lineHeight: 22,
  },
  personaCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#faf7f1",
    padding: 16,
    gap: 8,
  },
  personaCardActive: {
    borderColor: colors.navSoft,
    backgroundColor: "#eef0ff",
  },
  personaFeatured: {
    borderColor: "#d8c6a3",
  },
  personaHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  personaTitle: {
    fontSize: 17,
    fontWeight: "800",
    color: colors.ink,
  },
  personaDesc: {
    color: colors.muted,
    lineHeight: 22,
  },
  featuredTag: {
    color: colors.foundation,
    fontWeight: "700",
  },
  langRow: {
    flexDirection: "row",
    gap: 8,
  },
  langChip: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fff",
  },
  langChipActive: {
    backgroundColor: colors.navSoft,
    borderColor: colors.navSoft,
  },
  langChipText: {
    color: colors.ink,
    fontWeight: "700",
  },
  langChipTextActive: {
    color: "#fff",
  },
  authLoadingBox: {
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingVertical: 10,
  },
  authModeRow: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: "#f5efe5",
    borderRadius: 18,
    padding: 5,
  },
  authModeButton: {
    flex: 1,
    borderRadius: 14,
    paddingVertical: 11,
    alignItems: "center",
  },
  authModeButtonActive: {
    backgroundColor: colors.navSoft,
  },
  authModeText: {
    color: colors.ink,
    fontWeight: "800",
  },
  authModeTextActive: {
    color: "#fff",
  },
  authErrorText: {
    color: colors.foundation,
    fontWeight: "700",
    lineHeight: 20,
  },
  authSwitchLink: {
    alignItems: "center",
    paddingVertical: 4,
  },
  authSwitchText: {
    color: colors.navSoft,
    fontWeight: "800",
  },
  primaryButton: {
    marginTop: 10,
    backgroundColor: colors.success,
    paddingVertical: 16,
    borderRadius: 18,
    alignItems: "center",
  },
  primaryButtonDisabled: {
    opacity: 0.6,
  },
  primaryButtonText: {
    color: "#fff",
    fontWeight: "800",
    fontSize: 16,
  },
  secondaryButton: {
    backgroundColor: "#fff",
    paddingVertical: 15,
    borderRadius: 18,
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
  },
  secondaryButtonText: {
    color: colors.ink,
    fontWeight: "800",
    fontSize: 15,
  },
  loadingTitle: {
    marginTop: 8,
    fontSize: 22,
    fontWeight: "800",
    color: colors.ink,
  },
  heroCard: {
    backgroundColor: colors.panel,
    borderRadius: 26,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 22,
  },
  heroTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  heroBadge: {
    backgroundColor: "#ece6ff",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
  },
  heroBadgeText: {
    color: colors.navSoft,
    fontWeight: "800",
  },
  heroBadgeSoft: {
    backgroundColor: "#fff8eb",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
  },
  heroBadgeSoftText: {
    color: colors.foundation,
    fontWeight: "800",
  },
  quote: {
    fontSize: 34,
    lineHeight: 40,
    fontWeight: "900",
    color: colors.ink,
  },
  card: {
    backgroundColor: colors.panel,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    gap: 12,
  },
  sectionEyebrow: {
    color: "#d18955",
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    fontSize: 11,
  },
  cardTitle: {
    fontSize: 30,
    lineHeight: 34,
    color: colors.ink,
    fontWeight: "900",
  },
  cardBody: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 24,
  },
  cardNote: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  learningIntroCard: {
    backgroundColor: "#f7f2e7",
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  learningIntroEyebrow: {
    color: "#d18955",
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    fontSize: 11,
  },
  learningIntroTitle: {
    color: colors.ink,
    fontSize: 22,
    lineHeight: 26,
    fontWeight: "900",
    marginTop: 6,
  },
  learningMiniStat: {
    minWidth: 84,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 18,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    gap: 2,
  },
  learningMiniStatValue: {
    color: colors.ink,
    fontSize: 24,
    fontWeight: "900",
  },
  learningMiniStatLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
  },
  flashcardShell: {
    borderRadius: 28,
    borderWidth: 1,
    borderColor: "#e6ddff",
    backgroundColor: "#faf8ff",
    overflow: "hidden",
  },
  flashcardAccent: {
    height: 8,
    backgroundColor: colors.navSoft,
  },
  flashcardBody: {
    padding: 18,
    gap: 14,
  },
  flashcardPrompt: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#e3dcf8",
    backgroundColor: "#f4f1ff",
    padding: 16,
    gap: 8,
  },
  flashcardQuestion: {
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fffdfb",
    padding: 18,
    gap: 10,
  },
  flashcardQuestionText: {
    color: colors.ink,
    fontSize: 20,
    lineHeight: 30,
    fontWeight: "800",
  },
  metricGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  metricCard: {
    width: "48%",
    backgroundColor: colors.panel,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 8,
  },
  metricLabel: {
    color: colors.muted,
    fontWeight: "700",
  },
  metricValue: {
    color: colors.ink,
    fontSize: 28,
    fontWeight: "900",
  },
  featureGrid: {
    flexDirection: "row",
    gap: 12,
  },
  featureCard: {
    flex: 1,
    backgroundColor: colors.panel,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 8,
  },
  featureTitle: {
    color: colors.ink,
    fontSize: 24,
    lineHeight: 28,
    fontWeight: "900",
  },
  quickActionRow: {
    flexDirection: "row",
    gap: 10,
    flexWrap: "wrap",
    marginTop: 6,
  },
  quickActionButton: {
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderWidth: 1,
  },
  quickActionPrimary: {
    backgroundColor: colors.navSoft,
    borderColor: colors.navSoft,
  },
  quickActionSoft: {
    backgroundColor: "#fff",
    borderColor: colors.border,
  },
  quickActionDisabled: {
    backgroundColor: "#ebe7df",
    borderColor: "#ebe7df",
  },
  quickActionText: {
    fontWeight: "800",
    fontSize: 14,
  },
  quickActionTextPrimary: {
    color: "#fff",
  },
  quickActionTextSoft: {
    color: colors.ink,
  },
  quickActionTextDisabled: {
    color: "#9a9287",
  },
  chartRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 8,
    minHeight: 220,
  },
  chartColumn: {
    flex: 1,
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 8,
  },
  chartValue: {
    fontWeight: "800",
    fontSize: 13,
  },
  chartTrack: {
    width: 40,
    height: 132,
    justifyContent: "flex-end",
    borderRadius: 20,
    backgroundColor: "#f0ebdf",
    overflow: "hidden",
  },
  chartBar: {
    width: "100%",
    borderRadius: 20,
  },
  chartLabel: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.ink,
    textAlign: "center",
  },
  chartSub: {
    fontSize: 11,
    color: colors.muted,
    textAlign: "center",
  },
  wordRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 4,
  },
  wordMeta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  wordLemma: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "800",
  },
  wordChinese: {
    color: colors.navSoft,
    fontSize: 16,
    fontWeight: "700",
  },
  wordDefinition: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  resultCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fbf9f4",
    padding: 16,
    gap: 6,
  },
  resultBand: {
    color: colors.success,
    fontWeight: "700",
  },
  resultMeta: {
    color: colors.muted,
    fontWeight: "700",
  },
  noticeText: {
    paddingHorizontal: 18,
    color: colors.navSoft,
    fontWeight: "700",
    paddingBottom: 8,
  },
  backLink: {
    alignSelf: "flex-start",
  },
  backLinkText: {
    color: colors.navSoft,
    fontWeight: "800",
    fontSize: 14,
  },
  detailHeroRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
  },
  learningHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
  },
  learningLoading: {
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    paddingVertical: 24,
  },
  progressRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  progressTrack: {
    height: 10,
    borderRadius: 999,
    backgroundColor: "#ebe7db",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: colors.navSoft,
  },
  feedbackBanner: {
    borderRadius: 18,
    borderWidth: 1,
    padding: 16,
    gap: 6,
  },
  feedbackBannerCorrect: {
    backgroundColor: "#eff9f1",
    borderColor: "#cce8d2",
  },
  feedbackBannerWrong: {
    backgroundColor: "#fff3ef",
    borderColor: "#f4d4c7",
  },
  feedbackBannerTitle: {
    fontSize: 18,
    fontWeight: "900",
  },
  feedbackTextCorrect: {
    color: "#277a49",
  },
  feedbackTextWrong: {
    color: colors.foundation,
  },
  detailHeroMain: {
    flex: 1,
    gap: 6,
  },
  pronounceButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "#eef0ff",
    borderWidth: 1,
    borderColor: "#d9ddff",
    alignItems: "center",
    justifyContent: "center",
  },
  pronounceButtonText: {
    fontSize: 20,
  },
  detailMetaLine: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
  },
  detailTopBadges: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    flexWrap: "wrap",
  },
  detailStatus: {
    color: colors.foundation,
    fontWeight: "800",
    textTransform: "capitalize",
  },
  detailCounter: {
    color: colors.ink,
    fontWeight: "700",
  },
  detailSection: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fbf9f4",
    padding: 16,
    gap: 8,
  },
  detailGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  detailGridItem: {
    flex: 1,
    minWidth: 220,
  },
  detailLabel: {
    color: colors.ink,
    fontSize: 13,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  detailBody: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 24,
  },
  detailBodyMuted: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  synonymWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  synonymChip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d9ddff",
    backgroundColor: "#eef0ff",
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  synonymChipText: {
    color: colors.navSoft,
    fontWeight: "800",
  },
  answerList: {
    gap: 10,
  },
  answerOption: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fffdfb",
    paddingHorizontal: 16,
    paddingVertical: 16,
    ...shadows.card,
  },
  answerOptionActive: {
    borderColor: colors.navSoft,
    backgroundColor: "#eef0ff",
  },
  answerDot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: "#cfc8bc",
    marginTop: 2,
  },
  answerDotActive: {
    borderColor: colors.navSoft,
    backgroundColor: colors.navSoft,
  },
  answerText: {
    flex: 1,
    color: colors.ink,
    fontSize: 15,
    lineHeight: 22,
  },
  answerTextActive: {
    fontWeight: "700",
  },
  breakdownRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  resultMetaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  aiSummaryRow: {
    flexDirection: "row",
    gap: 12,
  },
  aiSummaryPill: {
    flex: 1,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fbf9f4",
    padding: 14,
    gap: 6,
  },
  aiSummaryLabel: {
    color: colors.muted,
    fontWeight: "700",
    fontSize: 12,
  },
  aiSummaryValue: {
    color: colors.ink,
    fontWeight: "900",
    fontSize: 22,
  },
  footerMeta: {
    marginTop: 6,
    color: colors.muted,
    fontSize: 12,
  },
  errorText: {
    paddingHorizontal: 18,
    color: colors.foundation,
    fontWeight: "700",
    paddingBottom: 8,
  },
});
