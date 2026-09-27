"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const panel = $("#student-audio-panel");
  const classControl = $("#student-class-control");
  const fileInput = $("#lesson-audio-file");
  const fileName = $("#audio-file-name");
  const preview = $("#audio-preview");
  const confirmation = $("#audio-confirm-file");
  const createButton = $("#create-summary");
  const copyButton = $("#copy-summary");
  const output = $("#summary-output");
  const status = $("#audio-status");
  const MAX_FILE_BYTES = 300 * 1024 * 1024;
  const ALLOWED_EXTENSIONS = new Set([
    "flac",
    "m4a",
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "ogg",
    "wav",
    "webm",
  ]);

  let selectedFile = null;
  let previewUrl = "";
  let busy = false;

  function updateVisibility() {
    panel.hidden = classControl.hidden;
  }

  function updateCreateButton() {
    createButton.disabled =
      busy || !selectedFile || !confirmation.checked;
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  }

  function clearPreview() {
    preview.pause();
    preview.removeAttribute("src");
    preview.load();
    preview.hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = "";
  }

  fileInput.addEventListener("change", () => {
    clearPreview();
    selectedFile = fileInput.files?.[0] || null;
    confirmation.checked = false;
    output.value = "";
    copyButton.disabled = true;

    if (!selectedFile) {
      fileName.textContent = "Файл ще не вибрано";
      showStatus("");
      updateCreateButton();
      return;
    }

    const extension = selectedFile.name.split(".").pop().toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(extension)) {
      selectedFile = null;
      fileInput.value = "";
      fileName.textContent = "Цей формат не підтримується. Обери аудіофайл.";
      showStatus("Підтримуються MP3, WAV, M4A, MP4, OGG, FLAC і WebM.", true);
      updateCreateButton();
      return;
    }
    if (selectedFile.size > MAX_FILE_BYTES) {
      selectedFile = null;
      fileInput.value = "";
      fileName.textContent = "Файл завеликий. Максимальний розмір — 300 МБ.";
      showStatus("Обери файл меншого розміру.", true);
      updateCreateButton();
      return;
    }

    fileName.textContent =
      selectedFile.name + " · " + (selectedFile.size / (1024 * 1024)).toFixed(1) + " МБ";
    previewUrl = URL.createObjectURL(selectedFile);
    preview.src = previewUrl;
    preview.hidden = false;
    showStatus("Прослухай запис, підтвердь файл і натисни «Створити конспект»." );
    updateCreateButton();
  });

  confirmation.addEventListener("change", updateCreateButton);

  createButton.addEventListener("click", async () => {
    if (!selectedFile || !confirmation.checked || busy) return;
    busy = true;
    createButton.textContent = "Обробляю аудіо…";
    fileInput.disabled = true;
    confirmation.disabled = true;
    $("#audio-transcriber").disabled = true;
    $("#summary-model").disabled = true;
    output.value = "";
    copyButton.disabled = true;
    showStatus(
      "Передаю запис на транскрипцію. Фрагменти триваліші за 8 хвилин не створюються.",
    );
    updateCreateButton();

    try {
      const response = await fetch("/api/audio-summary", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Audio-Extension": selectedFile.name.split(".").pop().toLowerCase(),
          "X-Audio-Confirmed": "true",
          "X-Transcription-Provider": $("#audio-transcriber").value,
          "X-Summary-Model": $("#summary-model").value,
          "X-Demo-Role": "student",
          "X-Student-Id": $("#student-profile").value,
        },
        body: selectedFile,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.error || "Не вдалося створити конспект.");
      }
      output.value = result.summary || "";
      copyButton.disabled = !output.value;
      showStatus(
        "Конспект готовий. Оброблено фрагментів: " + String(result.chunks || 0) + ".",
      );
    } catch (error) {
      showStatus(error.message || "Не вдалося з’єднатися із сервером.", true);
    } finally {
      busy = false;
      createButton.textContent = "Створити конспект";
      fileInput.disabled = false;
      confirmation.disabled = false;
      $("#audio-transcriber").disabled = false;
      $("#summary-model").disabled = false;
      updateCreateButton();
    }
  });

  copyButton.addEventListener("click", async () => {
    if (!output.value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(output.value);
      } else {
        output.focus();
        output.select();
        if (!document.execCommand("copy")) throw new Error("copy failed");
      }
      showStatus("Повний текст конспекту скопійовано.");
    } catch {
      output.focus();
      output.select();
      showStatus("Не вдалося скопіювати автоматично. Текст виділено для копіювання.", true);
    }
  });

  new MutationObserver(updateVisibility).observe(classControl, {
    attributes: true,
    attributeFilter: ["hidden"],
  });
  updateVisibility();
  updateCreateButton();
})();
