"""LLM backend: Google Gemini API (cloud).

The manuscript is sent to Google for analysis; the author enables this by putting
``GEMINI_API_KEY`` into ``Backend/.env``. The key travels only in a request header — never in a
URL, a log line or a response to the browser. Logs contain status codes and error types only,
never manuscript text.

Free-tier friendly: requests are spaced out (``GEMINI_MIN_INTERVAL_SECONDS``), rate limits (429)
wait for the delay Google asks for, overloads (5xx) are retried and may fall back to a lighter
model. A daily quota that is used up raises ``AIUnavailable`` — a book scan then stops and the
next run continues where it stopped.
"""
import json
import logging
import re
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger("worldweaver.ai")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
# Novels contain violence, death and cruelty; the filters must not stop literary analysis.
SAFETY = [
    {"category": c, "threshold": "BLOCK_NONE"}
    for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
]
RETRY_DELAY_RE = re.compile(r"(\d+(?:\.\d+)?)s")


class AIError(Exception):
    code = "ai_error"


class AIUnavailable(AIError):
    code = "ai_unavailable"


class AIConfigError(AIError):
    code = "ai_config"


class AIResponseError(AIError):
    code = "ai_bad_response"


class GeminiBackend:
    name = "gemini"
    _pace_lock = threading.Lock()
    _last_call = 0.0  # shared by all instances: the rate limit is per API key

    def __init__(self, api_key=None, model=None, fallback_model=None, timeout=None, min_interval=None, thinking=None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        fallback = fallback_model if fallback_model is not None else settings.GEMINI_FALLBACK_MODEL
        self.fallback_model = fallback if fallback and fallback != self.model else ""
        self.timeout = timeout or settings.GEMINI_TIMEOUT_SECONDS
        self.min_interval = settings.GEMINI_MIN_INTERVAL_SECONDS if min_interval is None else min_interval
        self.thinking = settings.GEMINI_THINKING if thinking is None else thinking
        self.session = requests.Session()

    # --- transport -------------------------------------------------------------------
    def _headers(self):
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _pace(self):
        with GeminiBackend._pace_lock:
            wait = GeminiBackend._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            GeminiBackend._last_call = time.monotonic()

    def _generate(self, model, body):
        """POST generateContent with retries. Returns the parsed JSON response."""
        if not self.api_key:
            raise AIUnavailable("Немає ключа Gemini: додайте GEMINI_API_KEY у Backend/.env.")
        url = f"{API_ROOT}/models/{model}:generateContent"
        overloaded = 0
        for attempt in range(6):
            self._pace()
            try:
                response = self.session.post(url, headers=self._headers(), json=body, timeout=self.timeout)
            except requests.Timeout:
                overloaded += 1
                logger.warning("Gemini timeout (model %s, attempt %d)", model, attempt + 1)
                if overloaded >= 3:
                    raise AIUnavailable("Gemini не відповідає. Спробуйте пізніше.") from None
                continue
            except requests.RequestException as exc:
                raise AIUnavailable("Немає зʼєднання з Gemini (перевірте інтернет).") from exc
            status = response.status_code
            if status == 200:
                return response.json()
            message = _error_message(response)
            logger.warning("Gemini HTTP %s (model %s, attempt %d)", status, model, attempt + 1)
            if status == 429:
                if "per day" in message.lower() or "perday" in message.lower().replace(" ", ""):
                    raise AIUnavailable("Денний безкоштовний ліміт Gemini вичерпано. Запустіть перевірку завтра — вона продовжиться з місця зупинки.")
                time.sleep(min(_retry_delay(response, default=20 * (attempt + 1)), 90))
                continue
            if status in (500, 502, 503, 504):
                overloaded += 1
                if overloaded >= 2 and self.fallback_model and model != self.fallback_model:
                    model = self.fallback_model  # the main model is overloaded: use the lighter one
                    url = f"{API_ROOT}/models/{model}:generateContent"
                    continue
                time.sleep(min(5 * overloaded, 30))
                continue
            if status in (401, 403):
                raise AIUnavailable("Gemini відхилив ключ API (перевірте GEMINI_API_KEY у Backend/.env).")
            if status == 404:
                raise AIUnavailable(f"Модель «{model}» недоступна для цього ключа (змініть GEMINI_MODEL у Backend/.env).")
            raise AIResponseError(f"Gemini повернув помилку HTTP {status}.")
        raise AIUnavailable("Gemini перевантажений або ліміт запитів вичерпано. Спробуйте пізніше.")

    # --- API used by AIService -------------------------------------------------------------
    def health(self):
        """Whether the key works and the model is available (one cheap metadata request)."""
        info = {"available": False, "server": False, "model": self.model, "provider": "gemini", "models": []}
        if not self.api_key:
            return {**info, "error": "Немає GEMINI_API_KEY у Backend/.env."}
        try:
            response = self.session.get(f"{API_ROOT}/models/{self.model}", headers=self._headers(), timeout=10)
        except requests.RequestException:
            return {**info, "error": "Немає зʼєднання з Gemini (перевірте інтернет)."}
        if response.status_code == 200:
            return {**info, "available": True, "server": True, "model_installed": True}
        if response.status_code in (401, 403):
            return {**info, "server": True, "error": "Ключ GEMINI_API_KEY не прийнято."}
        return {**info, "server": True, "error": f"Модель «{self.model}» недоступна."}

    def chat_json(self, system, user, schema=None, temperature=0.1, max_tokens=None):
        """One request constrained to JSON (optionally to ``schema``). Returns the parsed object."""
        config = {"responseMimeType": "application/json", "temperature": temperature}
        if schema:
            config["responseJsonSchema"] = schema
        if max_tokens:
            config["maxOutputTokens"] = max_tokens
        if self.thinking:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
            "safetySettings": SAFETY,
        }
        data = self._generate(self.model, body)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "")
            raise AIResponseError(f"Gemini не обробив фрагмент{' (' + reason + ')' if reason else ''}.")
        candidate = candidates[0]
        text = "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", []) if not p.get("thought"))
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            if candidate.get("finishReason") == "MAX_TOKENS":
                # The answer hit the output limit mid-JSON: keep the complete items instead of losing them all.
                repaired = close_truncated_json(text)
                if repaired is not None:
                    return repaired
            logger.warning("Gemini returned non-JSON output (%d chars, finish %s)", len(text), candidate.get("finishReason"))
            raise AIResponseError("Модель повернула невалідний JSON.") from exc


def _error_message(response):
    try:
        return str(response.json().get("error", {}).get("message", ""))
    except ValueError:
        return ""


def _retry_delay(response, default):
    """Seconds Google asks to wait (RetryInfo.retryDelay like "37s"), or ``default``."""
    try:
        for detail in response.json().get("error", {}).get("details", []):
            match = RETRY_DELAY_RE.fullmatch(str(detail.get("retryDelay", "")))
            if match:
                return float(match.group(1)) + 1
    except ValueError:
        pass
    return default


def close_truncated_json(text):
    """Parse JSON cut off mid-way: drop the unfinished tail after the last complete object and close the
    open brackets. Returns None when nothing usable is left."""
    for cut in range(len(text) - 1, 0, -1):
        if text[cut] != "}":
            continue
        head = text[:cut + 1]
        stack, in_string, escaped = [], False, False
        for ch in head:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in "[{":
                stack.append("]" if ch == "[" else "}")
            elif ch in "]}" and stack:
                stack.pop()
        if in_string:
            continue
        try:
            return json.loads(head + "".join(reversed(stack)))
        except json.JSONDecodeError:
            continue
    return None


def get_backend():
    return GeminiBackend()
