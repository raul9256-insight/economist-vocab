function renderMasteryError(target, message) {
  target.innerHTML = `<p class="mastery-error">${escapeHtml(message)}</p>`;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderPronunciationResult(target, data, labels) {
  target.innerHTML = `
    <div class="mastery-score-line">
      <strong>${escapeHtml(labels.score)}: ${escapeHtml(data.score)}/100</strong>
      <span>${escapeHtml(labels.status)}: ${escapeHtml(data.status)}</span>
    </div>
    <p><strong>${escapeHtml(labels.transcript)}:</strong> ${escapeHtml(data.transcript || "—")}</p>
    <p>${escapeHtml(data.feedback || "")}</p>
  `;
}

function renderSentenceResult(target, data, labels) {
  target.innerHTML = `
    <div class="mastery-score-line">
      <strong>${escapeHtml(labels.score)}: ${escapeHtml(data.overall_score)}/100</strong>
      <span>${escapeHtml(labels.status)}: ${escapeHtml(data.status)}</span>
    </div>
    <p><strong>${escapeHtml(labels.feedback)}:</strong> ${escapeHtml(data.feedback || "")}</p>
    ${data.corrected_sentence ? `<p><strong>${escapeHtml(labels.corrected)}:</strong> ${escapeHtml(data.corrected_sentence)}</p>` : ""}
    ${data.suggested_upgrade ? `<p><strong>${escapeHtml(labels.upgrade)}:</strong> ${escapeHtml(data.suggested_upgrade)}</p>` : ""}
    <p><strong>${escapeHtml(labels.dseUsefulness)}:</strong> ${escapeHtml(data.exam_usefulness_score)}/100</p>
  `;
}

function bindWordMasteryLab() {
  document.querySelectorAll("[data-word-mastery]").forEach((root) => {
    const wordId = root.getAttribute("data-word-id");
    const lang = root.getAttribute("data-lang") || "en";
    const recordButton = root.querySelector(".mastery-record-button");
    const sentenceButton = root.querySelector(".mastery-sentence-button");
    const sentenceInput = root.querySelector(".mastery-sentence-input");
    const pronunciationTarget = root.querySelector("[data-pronunciation-result]");
    const sentenceTarget = root.querySelector("[data-sentence-result]");
    const labels = {
      score: document.documentElement.lang === "en" ? "Score" : lang === "zh-Hans" ? "分数" : "分數",
      status: document.documentElement.lang === "en" ? "Status" : lang === "zh-Hans" ? "状态" : "狀態",
      transcript: document.documentElement.lang === "en" ? "AI heard" : "AI 聽到",
      feedback: document.documentElement.lang === "en" ? "AI feedback" : lang === "zh-Hans" ? "AI 反馈" : "AI 回饋",
      corrected: document.documentElement.lang === "en" ? "Corrected sentence" : "修正版句子",
      upgrade: document.documentElement.lang === "en" ? "Suggested upgrade" : lang === "zh-Hans" ? "升级版句子" : "升級版句子",
      dseUsefulness: document.documentElement.lang === "en" ? "DSE writing usefulness" : lang === "zh-Hans" ? "DSE 写作实用度" : "DSE 寫作實用度",
    };
    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    if (recordButton) {
      recordButton.addEventListener("click", async () => {
        if (!navigator.mediaDevices || !window.MediaRecorder) {
          renderMasteryError(pronunciationTarget, root.getAttribute("data-unsupported-message"));
          return;
        }
        if (!isRecording) {
          try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunks = [];
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.addEventListener("dataavailable", (event) => {
              if (event.data.size > 0) {
                audioChunks.push(event.data);
              }
            });
            mediaRecorder.addEventListener("stop", async () => {
              stream.getTracks().forEach((track) => track.stop());
              recordButton.textContent = root.getAttribute("data-checking-label");
              recordButton.disabled = true;
              const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
              const formData = new FormData();
              formData.append("audio", audioBlob, "pronunciation.webm");
              formData.append("lang", lang);
              try {
                const response = await fetch(`/api/word/${wordId}/deep-learning/pronunciation`, {
                  method: "POST",
                  body: formData,
                });
                const data = await response.json();
                if (!response.ok) {
                  throw new Error(data.detail || "Pronunciation check failed.");
                }
                renderPronunciationResult(pronunciationTarget, data, labels);
              } catch (error) {
                renderMasteryError(pronunciationTarget, error.message);
              } finally {
                recordButton.disabled = false;
                recordButton.textContent = root.getAttribute("data-retry-label");
              }
            });
            mediaRecorder.start();
            isRecording = true;
            recordButton.textContent = root.getAttribute("data-stop-label");
            pronunciationTarget.innerHTML = `<p class="section-note">${escapeHtml(root.getAttribute("data-recording-label"))}</p>`;
          } catch (error) {
            renderMasteryError(pronunciationTarget, error.message);
          }
          return;
        }
        isRecording = false;
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
          mediaRecorder.stop();
        }
      });
    }

    if (sentenceButton && sentenceInput) {
      sentenceButton.addEventListener("click", async () => {
        const sentence = sentenceInput.value.trim();
        if (!sentence) {
          renderMasteryError(sentenceTarget, root.getAttribute("data-sentence-required"));
          return;
        }
        sentenceButton.disabled = true;
        const originalLabel = sentenceButton.textContent;
        sentenceButton.textContent = root.getAttribute("data-checking-label");
        sentenceTarget.innerHTML = `<p class="section-note">${escapeHtml(root.getAttribute("data-checking-label"))}</p>`;
        const formData = new FormData();
        formData.append("sentence", sentence);
        formData.append("lang", lang);
        try {
          const response = await fetch(`/api/word/${wordId}/deep-learning/sentence`, {
            method: "POST",
            body: formData,
          });
          const data = await response.json();
          if (!response.ok) {
            throw new Error(data.detail || "Sentence check failed.");
          }
          renderSentenceResult(sentenceTarget, data, labels);
        } catch (error) {
          renderMasteryError(sentenceTarget, error.message);
        } finally {
          sentenceButton.disabled = false;
          sentenceButton.textContent = originalLabel;
        }
      });
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindWordMasteryLab);
} else {
  bindWordMasteryLab();
}
