"""Tiny built-in HTTP server for the Vocabuildary pod UI."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.services.word_service import get_recent_reminders, send_test_notification

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
      --bg: #f5efe4;
      --panel: #fffaf0;
      --ink: #1f2933;
      --muted: #52606d;
      --accent: #146356;
      --accent-strong: #0f4c43;
      --border: #d9cbb3;
      --shadow: 0 18px 40px rgba(31, 41, 51, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.85), transparent 38%),
        linear-gradient(135deg, #e8dcc7 0%, var(--bg) 60%, #efe6d5 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .shell {
      width: min(760px, 100%);
      background: rgba(255, 250, 240, 0.96);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3rem);
      line-height: 1;
    }
    p {
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.6;
    }
    .actions {
      display: flex;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      margin: 26px 0 18px;
    }
    button {
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-size: 1rem;
      padding: 14px 22px;
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease;
    }
    button:hover { background: var(--accent-strong); transform: translateY(-1px); }
    button:disabled { opacity: 0.7; cursor: wait; transform: none; }
    .status {
      min-height: 24px;
      font-size: 0.95rem;
      color: var(--muted);
    }
    .card {
      margin-top: 22px;
      padding: 20px;
      border: 1px solid var(--border);
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
    }
    h2 {
      margin: 0 0 14px;
      font-size: 1.2rem;
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 12px;
    }
    li {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(217, 203, 179, 0.7);
    }
    li:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    .word {
      font-size: 1.1rem;
      font-weight: 700;
    }
    .time {
      color: var(--muted);
      white-space: nowrap;
      text-align: right;
    }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    @media (max-width: 640px) {
      .shell { padding: 22px; }
      li { flex-direction: column; gap: 4px; }
      .time { text-align: left; white-space: normal; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <h1>Vocabuildary Control</h1>
    <p>Send a test reminder using the same LLM-backed format as a real notification and inspect the last five real reminder words from this pod.</p>
    <div class="actions">
      <button id="test-trigger">Send Test Notification</button>
      <span class="status" id="status">Ready.</span>
    </div>
    <section class="card">
      <h2>Last 5 Reminded Words</h2>
      <ul id="recent-list">
        <li class="empty">Loading...</li>
      </ul>
    </section>
  </main>
  <script>
    const button = document.getElementById("test-trigger");
    const status = document.getElementById("status");
    const list = document.getElementById("recent-list");

    function formatDate(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    }

    function renderReminders(items) {
      if (!items.length) {
        list.innerHTML = '<li class="empty">No reminders have been sent yet.</li>';
        return;
      }
      list.innerHTML = items.map(item => `
        <li>
          <span class="word">${item.word}</span>
          <span class="time">${formatDate(item.reminded_at)}</span>
        </li>
      `).join("");
    }

    async function loadRecent() {
      try {
        const response = await fetch("/api/recent-reminders");
        if (!response.ok) throw new Error("Failed to load reminder history.");
        const data = await response.json();
        renderReminders(data.items || []);
      } catch (error) {
        list.innerHTML = `<li class="empty">${error.message}</li>`;
      }
    }

    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "Sending test notification...";
      try {
        const response = await fetch("/api/test-trigger", { method: "POST" });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "Test notification failed.");
        }
        status.textContent = data.message || "Test notification sent.";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });

    loadRecent();
  </script>
</body>
</html>
"""


def _serialize_reminder(item: Any) -> dict[str, str]:
    reminded_at = item.reminded_at
    if isinstance(reminded_at, datetime):
        reminded_at_text = reminded_at.isoformat()
    else:
        reminded_at_text = str(reminded_at)
    return {"word": item.word_text, "reminded_at": reminded_at_text}


class _UIRequestHandler(BaseHTTPRequestHandler):
    server_version = "VocabuildaryUI/1.0"

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_html(HTML_PAGE)
            return
        if self.path == "/api/recent-reminders":
            try:
                items = [_serialize_reminder(item) for item in get_recent_reminders(limit=5)]
                self._send_json({"items": items})
            except Exception as exc:
                logger.error("Failed to fetch recent reminders: %s", exc, exc_info=True)
                self._send_json(
                    {"error": "Failed to fetch recent reminders."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/test-trigger":
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            success, word = send_test_notification()
            if not success or word is None:
                self._send_json(
                    {"error": "No word available to send a test notification."},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json(
                {"message": f"Test notification sent to Telegram for {word.word}."}
            )
        except Exception as exc:
            logger.error("Failed to send test notification: %s", exc, exc_info=True)
            self._send_json(
                {"error": "Failed to send test notification."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

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
