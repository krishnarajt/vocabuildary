"""Tiny built-in HTTP server for the Vocabuildary pod UI and API."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.common import constants
from app.db.database import get_db_session
from app.services.book_service import (
    BookNotFoundError,
    BookProcessingError,
    create_book_upload,
    get_processed_word_map_url,
    list_book_words_for_user,
    list_books_for_user,
    mark_book_upload_complete,
    process_book,
    serialize_book,
    update_book_learning_settings,
)
from app.services.book_storage_service import BookStorageError, BookValidationError
from app.services.catalog_service import (
    CatalogValidationError,
    create_language,
    list_languages,
    search_words,
)
from app.services.header_identity import (
    AuthenticationRequiredError,
    extract_gateway_identity,
)
from app.services.language_skill_service import (
    LanguageQuizGenerationError,
    LanguageQuizNotFoundError,
    LanguageSkillValidationError,
    generate_language_quiz,
    get_language_quiz,
    list_language_skills,
    score_language_quiz,
    serialize_language_quiz,
    set_user_language_level,
)
from app.services.mobile_notification_service import (
    MobileDeviceValidationError,
    get_pending_mobile_notifications,
    list_mobile_devices_for_user,
    mark_mobile_notification_delivered,
    mark_mobile_notification_opened,
    register_mobile_device,
    serialize_mobile_device,
    serialize_mobile_notification,
)
from app.services.dictionary_import_service import (
    ImportValidationError,
    get_dictionary_stats,
    list_import_runs,
    serialize_import_run,
    start_frequency_import,
    start_kaikki_import,
)
from app.services.reminder_schedule_service import (
    ReminderScheduleValidationError,
    list_reminder_slots_for_user,
    process_due_reminder_slots_for_user,
    serialize_reminder_slot,
    update_reminder_slots_for_user,
)
from app.services.user_service import (
    get_or_create_user,
    serialize_user,
    update_user_settings,
)
from app.services.word_service import (
    LearningPlanLockedError,
    LearningPlanValidationError,
    get_learnt_words_for_user,
    get_recent_reminders,
    get_daily_learning_plan_preview,
    get_word_progress_for_user,
    rebuild_daily_learning_plan,
    reset_word_progress,
    send_test_notification,
    serialize_daily_learning_plan,
    serialize_word_progress,
    update_daily_learning_plan,
)

logger = logging.getLogger(__name__)

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vocabuildary</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe5;
      --panel: #fffdf8;
      --ink: #172026;
      --muted: #68757a;
      --accent: #0f766e;
      --accent-strong: #0d665f;
      --clay: #ad6b4b;
      --border: rgba(23, 32, 38, 0.12);
      --shadow: 0 24px 70px rgba(22, 34, 42, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        linear-gradient(120deg, rgba(15, 118, 110, 0.12), transparent 34%),
        linear-gradient(315deg, rgba(173, 107, 75, 0.16), transparent 42%),
        var(--bg);
      padding: 24px;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.35;
      background-image:
        linear-gradient(rgba(23, 32, 38, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(23, 32, 38, 0.035) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(to bottom, black, transparent 82%);
    }
    .shell {
      position: relative;
      z-index: 1;
      display: grid;
      width: min(1080px, 100%);
      gap: 18px;
      margin: 0 auto;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 4px 0;
    }
    .eyebrow {
      margin: 0;
      color: var(--accent);
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    h1, h2, p { margin: 0; }
    h1 {
      margin-top: 6px;
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: clamp(2.4rem, 6vw, 5.2rem);
      line-height: 0.92;
    }
    .pill {
      display: inline-flex;
      min-height: 40px;
      align-items: center;
      border: 1px solid rgba(15, 118, 110, 0.22);
      border-radius: 999px;
      background: rgba(251, 247, 239, 0.78);
      color: var(--accent);
      padding: 0 14px;
      box-shadow: 0 10px 30px rgba(23, 32, 38, 0.08);
      font-size: 0.92rem;
      font-weight: 800;
    }
    .hero, .card {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 253, 248, 0.78);
      box-shadow: var(--shadow);
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: end;
      gap: 28px;
      min-height: 260px;
      overflow: hidden;
      padding: clamp(24px, 5vw, 42px);
    }
    .hero h2 {
      max-width: 10em;
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: clamp(2.1rem, 6vw, 4.4rem);
      line-height: 0.98;
    }
    .hero p {
      margin-top: 12px;
      max-width: 56ch;
      color: var(--muted);
      line-height: 1.6;
    }
    .actions {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    button {
      display: inline-flex;
      min-height: 48px;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 850;
      padding: 0 18px;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease;
    }
    button:hover { background: var(--accent-strong); transform: translateY(-1px); }
    button:disabled { opacity: 0.62; cursor: wait; transform: none; }
    .secondary {
      border: 1px solid var(--border);
      background: rgba(255, 253, 248, 0.85);
      color: var(--ink);
    }
    .secondary:hover { background: #fff; }
    .mini {
      min-height: 34px;
      padding: 0 10px;
      font-size: 0.82rem;
      white-space: nowrap;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
      gap: 18px;
    }
    .card { padding: clamp(18px, 4vw, 26px); }
    .card h2 {
      margin: 6px 0 18px;
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: clamp(1.45rem, 3vw, 2.2rem);
      line-height: 1;
    }
    .field {
      display: grid;
      gap: 8px;
      margin-bottom: 14px;
    }
    label {
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    input, select, textarea {
      width: 100%;
      min-height: 46px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--ink);
      font: inherit;
      padding: 0 12px;
    }
    textarea {
      min-height: 92px;
      padding: 12px;
      resize: vertical;
    }
    input:focus, select:focus, textarea:focus {
      border-color: rgba(15, 118, 110, 0.5);
      outline: 3px solid rgba(15, 118, 110, 0.12);
    }
    .hint {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0;
    }
    li {
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) auto;
      align-items: center;
      gap: 14px;
      min-height: 64px;
      border-bottom: 1px solid rgba(23, 32, 38, 0.08);
    }
    li:last-child { border-bottom: 0; }
    .idx {
      color: rgba(23, 32, 38, 0.36);
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: 1.2rem;
      font-weight: 700;
    }
    .word {
      overflow-wrap: anywhere;
      font-family: Georgia, Cambria, "Times New Roman", serif;
      font-size: 1.35rem;
      font-weight: 700;
    }
    .time {
      color: var(--muted);
      font-size: 0.92rem;
      font-weight: 700;
      white-space: nowrap;
      text-align: right;
    }
    .progress-row {
      grid-template-columns: minmax(0, 1fr) 74px auto;
    }
    .progress-meta {
      display: grid;
      gap: 4px;
      min-width: 0;
    }
    .progress-meta .word {
      font-size: 1.15rem;
    }
    .meaning {
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .percent {
      color: var(--accent);
      font-weight: 900;
      text-align: right;
    }
    .empty {
      display: flex;
      min-height: 120px;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      font-weight: 750;
      text-align: center;
    }
    .status {
      min-height: 24px;
      color: var(--clay);
      font-size: 0.92rem;
      font-weight: 750;
    }
    @media (max-width: 820px) {
      .topbar, .hero { align-items: flex-start; flex-direction: column; }
      .hero, .grid { grid-template-columns: 1fr; }
      .actions { width: 100%; }
      button { flex: 1; }
      li { grid-template-columns: 38px minmax(0, 1fr); }
      .progress-row { grid-template-columns: minmax(0, 1fr) auto; }
      .progress-row button { grid-column: 1 / -1; }
      .time { grid-column: 2; text-align: left; white-space: normal; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Vocabulary relay</p>
        <h1>Vocabuildary</h1>
      </div>
      <span class="pill" id="user-pill">Checking session</span>
    </header>

    <section class="hero">
      <div>
        <p class="eyebrow">Control Room</p>
        <h2>Keep the daily word ritual moving.</h2>
        <p>Configure your notification destination once, then send a test reminder or inspect your latest reminder history.</p>
      </div>
      <div class="actions">
        <button id="test-trigger">Send Test</button>
        <button class="secondary" id="refresh-trigger">Refresh</button>
      </div>
    </section>

    <section class="grid">
      <section class="card">
        <p class="eyebrow">Your Settings</p>
        <h2>Delivery</h2>
        <form id="settings-form">
          <div class="field">
            <label for="provider">Delivery provider</label>
            <select id="provider" name="notification_provider">
              <option value="telegram">Telegram</option>
              <option value="apprise">Apprise</option>
            </select>
          </div>
          <div class="field">
            <label for="bot-token">Bot token</label>
            <input id="bot-token" name="telegram_bot_token" autocomplete="off" placeholder="Paste a new token to replace the saved one">
          </div>
          <div class="field">
            <label for="chat-id">Chat id</label>
            <input id="chat-id" name="telegram_chat_id" autocomplete="off" placeholder="123456789">
          </div>
          <div class="field">
            <label for="apprise-urls">Apprise URLs</label>
            <textarea id="apprise-urls" name="apprise_urls" autocomplete="off" placeholder="One Apprise URL per line"></textarea>
          </div>
          <div class="field">
            <label for="review-words">Review words per day</label>
            <input id="review-words" name="daily_review_words" inputmode="numeric" placeholder="3">
          </div>
          <div class="field">
            <label for="cloze-words">Blank prompts per day</label>
            <input id="cloze-words" name="daily_cloze_words" inputmode="numeric" placeholder="1">
          </div>
          <div class="field">
            <label for="mastery-encounters">Encounters for 100%</label>
            <input id="mastery-encounters" name="mastery_encounters" inputmode="numeric" placeholder="8">
          </div>
          <div class="field">
            <label for="review-intervals">Review intervals</label>
            <input id="review-intervals" name="review_intervals" autocomplete="off" placeholder="1,3,7,14,30,60,120">
          </div>
          <div class="actions">
            <button type="submit">Save Settings</button>
            <button type="button" class="secondary" id="clear-token">Clear Token</button>
          </div>
        </form>
        <p class="hint" id="settings-hint">Loading saved settings...</p>
      </section>

      <section class="card">
        <p class="eyebrow">Newest first</p>
        <h2>Last 5 Reminded Words</h2>
        <p class="status" id="status">Ready.</p>
        <ul id="recent-list">
          <li class="empty">Loading...</li>
        </ul>
      </section>

      <section class="card">
        <p class="eyebrow">Least mastered first</p>
        <h2>Word Progress</h2>
        <ul id="progress-list">
          <li class="empty">Loading...</li>
        </ul>
      </section>
    </section>
  </main>

  <script>
    const userPill = document.getElementById("user-pill");
    const status = document.getElementById("status");
    const list = document.getElementById("recent-list");
    const progressList = document.getElementById("progress-list");
    const testButton = document.getElementById("test-trigger");
    const refreshButton = document.getElementById("refresh-trigger");
    const form = document.getElementById("settings-form");
    const provider = document.getElementById("provider");
    const botToken = document.getElementById("bot-token");
    const chatId = document.getElementById("chat-id");
    const appriseUrls = document.getElementById("apprise-urls");
    const reviewWords = document.getElementById("review-words");
    const clozeWords = document.getElementById("cloze-words");
    const masteryEncounters = document.getElementById("mastery-encounters");
    const reviewIntervals = document.getElementById("review-intervals");
    const hint = document.getElementById("settings-hint");
    const clearToken = document.getElementById("clear-token");

    function apiPrefix() {
      const parts = window.location.pathname.split("/").filter(Boolean);
      if (parts[0] === "api" && parts[1]) return `/api/${parts[1]}`;
      return "";
    }

    async function apiFetch(path, options = {}) {
      const response = await fetch(`${apiPrefix()}${path}`, {
        credentials: "include",
        ...options,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.message || "Request failed.");
      return data;
    }

    function formatDate(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    }

    function escapeHtml(value) {
      const el = document.createElement("span");
      el.textContent = value ?? "";
      return el.innerHTML;
    }

    function renderReminders(items) {
      if (!items.length) {
        list.innerHTML = '<li class="empty">No reminders have been sent yet.</li>';
        return;
      }
      list.innerHTML = items.map((item, index) => `
        <li>
          <span class="idx">${String(index + 1).padStart(2, "0")}</span>
          <span class="word">${escapeHtml(item.word)}</span>
          <span class="time">${escapeHtml(formatDate(item.reminded_at))}</span>
        </li>
      `).join("");
    }

    function renderProgress(items) {
      if (!items.length) {
        progressList.innerHTML = '<li class="empty">No learned words yet.</li>';
        return;
      }
      progressList.innerHTML = items.map((item) => `
        <li class="progress-row">
          <span class="progress-meta">
            <span class="word">${escapeHtml(item.word)}</span>
            <span class="meaning">${escapeHtml(item.meaning)}</span>
          </span>
          <span class="percent">${Number(item.progress_percent || 0)}%</span>
          <button class="secondary mini" data-reset-word="${Number(item.word_id)}">Reset</button>
        </li>
      `).join("");
    }

    function renderUser(payload) {
      const user = payload.user;
      const name = user.name || user.email || user.gateway_sub || "Signed in";
      const configured = user.notifications?.configured ?? user.telegram.configured;
      userPill.textContent = name;
      provider.value = user.notifications?.provider || "telegram";
      chatId.value = user.telegram.chat_id || "";
      appriseUrls.value = "";
      reviewWords.value = user.learning.daily_review_words ?? 3;
      clozeWords.value = user.learning.daily_cloze_words ?? 1;
      masteryEncounters.value = user.learning.mastery_encounters ?? 8;
      reviewIntervals.value = (user.learning.review_intervals || []).join(",");
      botToken.value = "";
      botToken.placeholder = user.telegram.bot_token_set
        ? `Saved token (${user.telegram.bot_token_hint})`
        : "Paste your Telegram bot token";
      appriseUrls.placeholder = user.apprise?.urls_set
        ? `Saved Apprise URL (${user.apprise.urls_hint})`
        : "One Apprise URL per line";
      hint.textContent = configured
        ? "Notification delivery is configured for your Authentik user."
        : "Choose a provider and save its destination before sending reminders.";
      testButton.disabled = !configured;
    }

    async function loadMe() {
      const data = await apiFetch("/me");
      renderUser(data);
      return data;
    }

    async function loadRecent() {
      try {
        const data = await apiFetch("/recent-reminders");
        renderReminders(data.items || []);
      } catch (error) {
        list.innerHTML = `<li class="empty">${error.message}</li>`;
      }
    }

    async function loadProgress() {
      try {
        const data = await apiFetch("/word-progress?limit=25");
        renderProgress(data.items || []);
      } catch (error) {
        progressList.innerHTML = `<li class="empty">${error.message}</li>`;
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      status.textContent = "Saving settings...";
      try {
        const payload = {
          notification_provider: provider.value,
          telegram_chat_id: chatId.value.trim(),
          learning: {
            daily_review_words: reviewWords.value.trim(),
            daily_cloze_words: clozeWords.value.trim(),
            mastery_encounters: masteryEncounters.value.trim(),
            review_intervals: reviewIntervals.value.trim(),
          },
        };
        if (botToken.value.trim()) payload.telegram_bot_token = botToken.value.trim();
        if (appriseUrls.value.trim()) payload.apprise_urls = appriseUrls.value.trim();
        const data = await apiFetch("/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        renderUser(data);
        status.textContent = "Settings saved.";
      } catch (error) {
        status.textContent = error.message;
      }
    });

    clearToken.addEventListener("click", async () => {
      status.textContent = "Clearing token...";
      try {
        const data = await apiFetch("/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clear_telegram_bot_token: true }),
        });
        renderUser(data);
        status.textContent = "Token cleared.";
      } catch (error) {
        status.textContent = error.message;
      }
    });

    testButton.addEventListener("click", async () => {
      testButton.disabled = true;
      status.textContent = "Sending test notification...";
      try {
        const data = await apiFetch("/test-trigger", { method: "POST" });
        status.textContent = data.message || "Test notification sent.";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        await loadMe().catch(() => {});
      }
    });

    refreshButton.addEventListener("click", async () => {
      status.textContent = "Refreshing...";
      await Promise.all([loadMe(), loadRecent(), loadProgress()]).catch((error) => {
        status.textContent = error.message;
      });
      if (status.textContent === "Refreshing...") status.textContent = "Ready.";
    });

    progressList.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-reset-word]");
      if (!button) return;
      const wordId = Number(button.dataset.resetWord);
      if (!wordId) return;
      button.disabled = true;
      status.textContent = "Resetting progress...";
      try {
        await apiFetch(`/word-progress/${wordId}/reset`, { method: "POST" });
        await loadProgress();
        status.textContent = "Progress reset.";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });

    (async function init() {
      try {
        await loadMe();
        await loadRecent();
        await loadProgress();
        status.textContent = "Ready.";
      } catch (error) {
        userPill.textContent = "Sign in required";
        status.textContent = error.message;
        list.innerHTML = '<li class="empty">Open this UI through API Get Away after signing in.</li>';
      }
    })();
  </script>
</body>
</html>
"""


def _serialize_reminder(item: Any) -> dict[str, Any]:
    reminded_at = item.reminded_at
    if isinstance(reminded_at, datetime):
        reminded_at_text = reminded_at.isoformat()
    else:
        reminded_at_text = str(reminded_at)
    word = getattr(item, "word", None)
    return {
        "word_id": getattr(item, "word_id", None),
        "word": item.word_text,
        "meaning": word.meaning if word is not None else "",
        "example": word.example if word is not None else "",
        "language_code": word.language_code if word is not None else "",
        "reminded_at": reminded_at_text,
    }


class _UIRequestHandler(BaseHTTPRequestHandler):
    server_version = "VocabuildaryUI/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = self._service_path(parsed.path)
        if path in ("/", "/index.html"):
            self._send_html(HTML_PAGE)
            return
        if path == "/health":
            self._send_json({"status": "ok"})
            return
        if path == "/me":
            self._handle_me()
            return
        if path == "/recent-reminders":
            self._handle_recent_reminders(parsed.query)
            return
        if path == "/word-progress":
            self._handle_word_progress(parsed.query)
            return
        if path == "/learnt-words":
            self._handle_learnt_words(parsed.query)
            return
        if path == "/learning-plan":
            self._handle_learning_plan()
            return
        if path == "/language-skills":
            self._handle_language_skills()
            return
        if path.startswith("/language-skills/") and path.endswith("/quiz"):
            self._handle_language_quiz(path)
            return
        if path == "/books":
            self._handle_books()
            return
        if path == "/languages":
            self._handle_languages()
            return
        if path == "/words":
            self._handle_words(parsed.query)
            return
        if path == "/reminder-slots":
            self._handle_reminder_slots()
            return
        if path == "/imports":
            self._handle_imports(parsed.query)
            return
        if path == "/mobile/devices":
            self._handle_mobile_devices()
            return
        if path == "/mobile/notifications":
            self._handle_mobile_notifications(parsed.query)
            return
        if path.startswith("/books/") and path.endswith("/words"):
            self._handle_book_words(path, parsed.query)
            return
        if path.startswith("/books/") and path.endswith("/processed-words"):
            self._handle_processed_words(path)
            return
        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = self._service_path(parsed.path)
        if path == "/test-trigger":
            self._handle_test_trigger()
            return
        if path.startswith("/word-progress/") and path.endswith("/reset"):
            self._handle_reset_word_progress(path)
            return
        if path == "/learning-plan/rebuild":
            self._handle_rebuild_learning_plan()
            return
        if path.startswith("/language-skills/") and path.endswith("/quiz/generate"):
            self._handle_generate_language_quiz(path)
            return
        if path.startswith("/language-skills/") and path.endswith("/quiz/score"):
            self._handle_score_language_quiz(path)
            return
        if path == "/books/uploads":
            self._handle_create_book_upload()
            return
        if path == "/languages":
            self._handle_create_language()
            return
        if path.startswith("/books/") and path.endswith("/upload-complete"):
            self._handle_book_upload_complete(path)
            return
        if path.startswith("/books/") and path.endswith("/process"):
            self._handle_process_book(path)
            return
        if path == "/imports/frequency":
            self._handle_start_frequency_import()
            return
        if path == "/imports/kaikki":
            self._handle_start_kaikki_import()
            return
        if path == "/mobile/devices":
            self._handle_register_mobile_device()
            return
        if path == "/mobile/notifications/sync-due":
            self._handle_sync_due_mobile_notifications()
            return
        if path.startswith("/mobile/notifications/") and path.endswith("/delivered"):
            self._handle_mobile_notification_delivered(path)
            return
        if path.startswith("/mobile/notifications/") and path.endswith("/opened"):
            self._handle_mobile_notification_opened(path)
            return
        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = self._service_path(parsed.path)
        if path == "/settings":
            self._handle_update_settings()
            return
        if path == "/learning-plan":
            self._handle_update_learning_plan()
            return
        if path == "/reminder-slots":
            self._handle_update_reminder_slots()
            return
        if path.startswith("/language-skills/") and path.count("/") == 2:
            self._handle_update_language_skill(path)
            return
        if path.startswith("/books/") and path.count("/") == 2:
            self._handle_update_book(path)
            return
        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
        self.end_headers()

    def _handle_me(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                self._send_json({"user": serialize_user(user)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch current user: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch current user."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_recent_reminders(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = int(params.get("limit", ["5"])[0])
            limit = max(1, min(limit, 500))
        except ValueError:
            limit = 5
        try:
            raw_days = params.get("days", [""])[0]
            days = max(1, min(int(raw_days), 3650)) if raw_days else None
        except ValueError:
            days = None

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                items = [
                    _serialize_reminder(item)
                    for item in get_recent_reminders(limit=limit, days=days, db=db, user=user)
                ]
                self._send_json({"items": items, "days": days})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch recent reminders: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch recent reminders."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_learnt_words(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = int(params.get("limit", ["200"])[0])
            limit = max(1, min(limit, 500))
        except ValueError:
            limit = 200
        try:
            offset = int(params.get("offset", ["0"])[0])
            offset = max(0, offset)
        except ValueError:
            offset = 0

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                items = [
                    serialize_word_progress(item)
                    for item in get_learnt_words_for_user(
                        db,
                        user,
                        limit=limit,
                        offset=offset,
                    )
                ]
                self._send_json({"items": items, "limit": limit, "offset": offset})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch learnt words: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch learnt words."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_word_progress(self, query: str) -> None:
        try:
            limit = int(parse_qs(query).get("limit", ["100"])[0])
            limit = max(1, min(limit, 500))
        except ValueError:
            limit = 100

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                items = [
                    serialize_word_progress(item)
                    for item in get_word_progress_for_user(db, user, limit=limit)
                ]
                self._send_json({"items": items})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch word progress: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch word progress."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_learning_plan(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                plan = get_daily_learning_plan_preview(db, user)
                if plan is None:
                    self._send_json(
                        {"error": "No word available for today's learning plan."},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                self._send_json({"plan": serialize_daily_learning_plan(plan)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch learning plan: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch learning plan."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_language_skills(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                self._send_json(list_language_skills(db, user))
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch language skills: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch language skills."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_update_language_skill(self, path: str) -> None:
        try:
            language_code = self._language_code_from_skill_path(path)
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                set_user_language_level(
                    db,
                    user,
                    language_code,
                    str(payload.get("level_code") or ""),
                    source="manual",
                )
                skills = list_language_skills(db, user)
                skill = self._skill_from_items(skills["items"], language_code)
                self._send_json({"skill": skill, "levels": skills["levels"]})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LanguageSkillValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to update language skill: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to update language skill."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_language_quiz(self, path: str) -> None:
        try:
            language_code = self._language_code_from_skill_path(path, suffix="quiz")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                self._current_user(db)
                quiz = get_language_quiz(db, language_code)
                self._send_json({"quiz": serialize_language_quiz(quiz)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LanguageQuizNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.error("Failed to fetch language quiz: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch language quiz."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_generate_language_quiz(self, path: str) -> None:
        try:
            language_code = self._language_code_from_skill_path(path, suffix="quiz/generate")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                quiz, generated = generate_language_quiz(db, user, language_code)
                self._send_json(
                    {
                        "quiz": serialize_language_quiz(quiz),
                        "generated": generated,
                        "message": "Quiz generated." if generated else "A quiz already exists.",
                    },
                    status=HTTPStatus.CREATED if generated else HTTPStatus.OK,
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LanguageQuizGenerationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            logger.error("Failed to generate language quiz: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to generate language quiz."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_score_language_quiz(self, path: str) -> None:
        try:
            language_code = self._language_code_from_skill_path(path, suffix="quiz/score")
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                self._send_json(score_language_quiz(db, user, language_code, payload))
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LanguageQuizNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except LanguageSkillValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to score language quiz: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to score language quiz."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_books(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                books = [serialize_book(book) for book in list_books_for_user(db, user)]
                self._send_json({"items": books})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch books: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch books."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_languages(self) -> None:
        try:
            with self._db_session() as db:
                self._current_user(db)
                self._send_json({"items": list_languages(db)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch languages: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch languages."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_create_language(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                self._current_user(db)
                language = create_language(db, payload)
                self._send_json({"language": language}, status=HTTPStatus.CREATED)
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except CatalogValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to create language: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to create language."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_words(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = int(params.get("limit", ["50"])[0])
            offset = int(params.get("offset", ["0"])[0])
        except ValueError:
            limit = 50
            offset = 0
        search_query = params.get("query", [""])[0]
        language_code = params.get("language_code", [None])[0] or None

        try:
            with self._db_session() as db:
                self._current_user(db)
                self._send_json(
                    search_words(
                        db,
                        query=search_query,
                        language_code=language_code,
                        limit=limit,
                        offset=offset,
                    )
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except CatalogValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to search words: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to search words."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_reminder_slots(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                slots = [
                    serialize_reminder_slot(slot)
                    for slot in list_reminder_slots_for_user(db, user)
                ]
                self._send_json({"items": slots})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch reminder slots: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch reminder slots."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_update_reminder_slots(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                slots = [
                    serialize_reminder_slot(slot)
                    for slot in update_reminder_slots_for_user(db, user, payload)
                ]
                self._send_json({"items": slots})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except ReminderScheduleValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to update reminder slots: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to update reminder slots."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_update_book(self, path: str) -> None:
        try:
            book_id = self._book_id_from_path(path)
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                book = update_book_learning_settings(db, user, book_id, payload)
                self._send_json({"book": serialize_book(book)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except (BookValidationError, CatalogValidationError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to update book: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to update book."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_book_words(self, path: str, query: str) -> None:
        try:
            book_id = self._book_id_from_path(path)
            params = parse_qs(query)
            limit = int(params.get("limit", ["200"])[0])
            offset = int(params.get("offset", ["0"])[0])
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                self._send_json(list_book_words_for_user(db, user, book_id, limit=limit, offset=offset))
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.error("Failed to fetch book words: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch book words."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_imports(self, query: str) -> None:
        try:
            params = parse_qs(query)
            language_code = (params.get("language_code", ["en"])[0] or "en").strip().lower()
            limit = int(params.get("limit", ["20"])[0])
            limit = max(1, min(limit, 100))
        except ValueError:
            language_code = "en"
            limit = 20

        try:
            with self._db_session() as db:
                self._current_user(db)
                runs = [serialize_import_run(run) for run in list_import_runs(db, limit=limit)]
                stats = get_dictionary_stats(db, language_code=language_code)
                self._send_json({"stats": stats, "items": runs})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch imports: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch imports."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_mobile_devices(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                devices = [
                    serialize_mobile_device(device)
                    for device in list_mobile_devices_for_user(db, user)
                ]
                self._send_json({"items": devices})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch mobile devices: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch mobile devices."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_register_mobile_device(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                device = register_mobile_device(db, user, payload)
                self._send_json({"device": serialize_mobile_device(device)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except MobileDeviceValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to register mobile device: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to register mobile device."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_mobile_notifications(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = int(params.get("limit", ["20"])[0])
        except ValueError:
            limit = 20
        device_id = params.get("device_id", [""])[0].strip() or None

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                notifications = [
                    serialize_mobile_notification(notification)
                    for notification in get_pending_mobile_notifications(
                        db,
                        user,
                        device_id=device_id,
                        limit=limit,
                    )
                ]
                self._send_json({"items": notifications})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to fetch mobile notifications: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to fetch mobile notifications."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_sync_due_mobile_notifications(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                if payload.get("device_id"):
                    register_mobile_device(db, user, payload)
                results = process_due_reminder_slots_for_user(db, user)
                notifications = [
                    serialize_mobile_notification(notification)
                    for notification in get_pending_mobile_notifications(
                        db,
                        user,
                        device_id=str(payload.get("device_id") or "").strip() or None,
                        limit=int(payload.get("limit") or 20),
                    )
                ]
                self._send_json({"results": results, "items": notifications})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except MobileDeviceValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to sync due mobile notifications: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to sync mobile notifications."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_mobile_notification_delivered(self, path: str) -> None:
        try:
            notification_id = self._mobile_notification_id_from_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                notification = mark_mobile_notification_delivered(db, user, notification_id)
                self._send_json({"notification": serialize_mobile_notification(notification)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LookupError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.error("Failed to mark mobile notification delivered: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to mark mobile notification delivered."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_mobile_notification_opened(self, path: str) -> None:
        try:
            notification_id = self._mobile_notification_id_from_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                notification = mark_mobile_notification_opened(db, user, notification_id)
                self._send_json({"notification": serialize_mobile_notification(notification)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LookupError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.error("Failed to mark mobile notification opened: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to mark mobile notification opened."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_start_frequency_import(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                run, started = start_frequency_import(db, user, payload)
                self._send_json(
                    {
                        "run": serialize_import_run(run),
                        "started": started,
                        "message": "Frequency import started."
                        if started
                        else "An import is already running.",
                    },
                    status=HTTPStatus.CREATED if started else HTTPStatus.OK,
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except ImportValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to start frequency import: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to start frequency import."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_start_kaikki_import(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                run, started = start_kaikki_import(db, user, payload)
                self._send_json(
                    {
                        "run": serialize_import_run(run),
                        "started": started,
                        "message": "Kaikki import started."
                        if started
                        else "An import is already running.",
                    },
                    status=HTTPStatus.CREATED if started else HTTPStatus.OK,
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except ImportValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to start Kaikki import: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to start Kaikki import."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_create_book_upload(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                book, upload = create_book_upload(db, user, payload)
                self._send_json(
                    {"book": serialize_book(book), "upload": upload},
                    status=HTTPStatus.CREATED,
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except BookStorageError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            logger.error("Failed to create book upload: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to create book upload."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_book_upload_complete(self, path: str) -> None:
        try:
            book_id = self._book_id_from_path(path)
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                book = mark_book_upload_complete(db, user, book_id, payload)
                self._send_json({"book": serialize_book(book)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except BookValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to mark book upload complete: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to mark book upload complete."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_process_book(self, path: str) -> None:
        try:
            book_id = self._book_id_from_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                book = process_book(db, user, book_id)
                self._send_json({"book": serialize_book(book)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except BookValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except BookProcessingError as exc:
            logger.error("Failed to process book: %s", exc, exc_info=True)
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:
            logger.error("Failed to process book: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to process book."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_processed_words(self, path: str) -> None:
        try:
            book_id = self._book_id_from_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                book, url = get_processed_word_map_url(db, user, book_id)
                self._send_json(
                    {
                        "book": serialize_book(book),
                        "url": url,
                        "expires_in": constants.BOOK_DOWNLOAD_URL_EXPIRATION_SECONDS,
                    }
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except BookNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except BookValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except BookStorageError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            logger.error("Failed to create processed word URL: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to create processed word URL."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_update_settings(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                user = update_user_settings(db, user, payload)
                self._send_json({"user": serialize_user(user)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to update settings: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to update settings."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_rebuild_learning_plan(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                plan = rebuild_daily_learning_plan(db, user)
                if plan is None:
                    self._send_json(
                        {"error": "No word available for today's learning plan."},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                self._send_json({"plan": serialize_daily_learning_plan(plan)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LearningPlanLockedError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except Exception as exc:
            logger.error("Failed to rebuild learning plan: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to rebuild learning plan."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_update_learning_plan(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                plan = update_daily_learning_plan(db, user, payload)
                if plan is None:
                    self._send_json(
                        {"error": "No word available for today's learning plan."},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                self._send_json({"plan": serialize_daily_learning_plan(plan)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LearningPlanLockedError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except LearningPlanValidationError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.error("Failed to update learning plan: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to update learning plan."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_reset_word_progress(self, path: str) -> None:
        try:
            word_id = self._word_progress_id_from_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with self._db_session() as db:
                user = self._current_user(db)
                progress = reset_word_progress(db, user, word_id)
                self._send_json({"item": serialize_word_progress(progress)})
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except LookupError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.error("Failed to reset word progress: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to reset word progress."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_test_trigger(self) -> None:
        try:
            with self._db_session() as db:
                user = self._current_user(db)
                if not user.notifications_configured:
                    self._send_json(
                        {"error": "Configure a notification provider first."},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

                success, word = send_test_notification(db=db, user=user)
                if not success or word is None:
                    self._send_json(
                        {"error": "No word available to send a test notification."},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                self._send_json(
                    {"message": f"Test notification sent for {word.word}."}
                )
        except AuthenticationRequiredError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.error("Failed to send test notification: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to send test notification."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _current_user(self, db):
        identity = extract_gateway_identity(dict(self.headers.items()))
        return get_or_create_user(db, identity)

    @staticmethod
    def _service_path(path: str) -> str:
        if path == "/api":
            return "/"
        if path.startswith("/api/"):
            return path[4:]
        return path

    def _book_id_from_path(self, path: str) -> int:
        parts = self._service_path(path).strip("/").split("/")
        if len(parts) < 2 or parts[0] != "books":
            raise ValueError("Book id is required.")
        try:
            return int(parts[1])
        except ValueError as exc:
            raise ValueError("Book id must be a number.") from exc

    def _language_code_from_skill_path(self, path: str, suffix: str | None = None) -> str:
        parts = self._service_path(path).strip("/").split("/")
        expected_suffix = suffix.split("/") if suffix else []
        if len(parts) != 2 + len(expected_suffix) or parts[0] != "language-skills":
            raise ValueError("Language code is required.")
        if expected_suffix and parts[2:] != expected_suffix:
            raise ValueError("Language skill path is not valid.")
        language_code = parts[1].strip().lower()
        if not language_code:
            raise ValueError("Language code is required.")
        return language_code

    @staticmethod
    def _skill_from_items(items: list[dict[str, Any]], language_code: str) -> dict[str, Any] | None:
        for item in items:
            if item.get("language", {}).get("code") == language_code:
                return item
        return None

    def _word_progress_id_from_path(self, path: str) -> int:
        parts = self._service_path(path).strip("/").split("/")
        if len(parts) != 3 or parts[0] != "word-progress":
            raise ValueError("Word id is required.")
        try:
            return int(parts[1])
        except ValueError as exc:
            raise ValueError("Word id must be a number.") from exc

    def _mobile_notification_id_from_path(self, path: str) -> int:
        parts = self._service_path(path).strip("/").split("/")
        if len(parts) != 4 or parts[0] != "mobile" or parts[1] != "notifications":
            raise ValueError("Notification id is required.")
        try:
            return int(parts[2])
        except ValueError as exc:
            raise ValueError("Notification id must be a number.") from exc

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    class _db_session:
        def __enter__(self):
            self.db = get_db_session()
            return self.db

        def __exit__(self, exc_type, exc, tb):
            self.db.close()
            return False

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("UI %s - %s", self.address_string(), format % args)

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class UIServer:
    """Wrapper that runs ThreadingHTTPServer in a background thread."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        self._server = ThreadingHTTPServer((host, port), _UIRequestHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="vocabuildary-ui",
            daemon=True,
        )
        self.host = host
        self.port = port

    def start(self) -> None:
        logger.info("Starting UI server on %s:%s", self.host, self.port)
        self._thread.start()

    def stop(self) -> None:
        logger.info("Stopping UI server")
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
