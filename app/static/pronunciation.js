let currentAudio = null;
let currentAudioUrl = null;
let pronunciationNotice = null;
let availableVoices = [];

function cleanupCurrentAudio() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if (currentAudioUrl) {
    URL.revokeObjectURL(currentAudioUrl);
    currentAudioUrl = null;
  }
}

function ensurePronunciationNotice() {
  if (pronunciationNotice) {
    return pronunciationNotice;
  }
  pronunciationNotice = document.createElement("div");
  pronunciationNotice.className = "pronunciation-notice";
  pronunciationNotice.hidden = true;
  document.body.appendChild(pronunciationNotice);
  return pronunciationNotice;
}

function showPronunciationNotice(message) {
  const notice = ensurePronunciationNotice();
  notice.textContent = message;
  notice.hidden = false;
  window.clearTimeout(showPronunciationNotice.timeoutId);
  showPronunciationNotice.timeoutId = window.setTimeout(() => {
    notice.hidden = true;
  }, 2600);
}

function loadVoices() {
  if (!("speechSynthesis" in window)) {
    return [];
  }
  availableVoices = window.speechSynthesis.getVoices();
  return availableVoices;
}

function pickEnglishVoice() {
  const voices = availableVoices.length ? availableVoices : loadVoices();
  if (!voices.length) {
    return null;
  }

  const scoreVoice = (voice) => {
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
    return score;
  };

  const englishVoices = voices.filter((voice) => (voice.lang || "").toLowerCase().startsWith("en"));
  if (!englishVoices.length) {
    return null;
  }
  return englishVoices.sort((a, b) => scoreVoice(b) - scoreVoice(a))[0];
}

function speakWithBrowserVoice(text) {
  if (!("speechSynthesis" in window) || !text) {
    showPronunciationNotice("Browser pronunciation is not available on this device.");
    return;
  }

  const synth = window.speechSynthesis;
  synth.cancel();
  cleanupCurrentAudio();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.rate = 0.76;
  utterance.pitch = 0.92;
  utterance.volume = 1;

  const preferredVoice = pickEnglishVoice();
  if (preferredVoice) {
    utterance.voice = preferredVoice;
    utterance.lang = preferredVoice.lang || "en-US";
  } else {
    showPronunciationNotice("Using your browser's basic English voice.");
  }

  synth.speak(utterance);
}

function bindPronunciationButtons() {
  document.querySelectorAll("[data-pronounce]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const text = button.getAttribute("data-pronounce");
      speakWithBrowserVoice(text);
    });
  });
}

if ("speechSynthesis" in window) {
  loadVoices();
  window.speechSynthesis.onvoiceschanged = () => {
    loadVoices();
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindPronunciationButtons);
} else {
  bindPronunciationButtons();
}
