"""Local LLM backends.

Only a local Ollama server is supported. There is deliberately no cloud provider and no
automatic fallback: if Ollama is unreachable the caller gets ``AIUnavailable`` and the rest
of the application keeps working.
"""
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger("worldweaver.ai")


class AIError(Exception):
    code = "ai_error"


class AIUnavailable(AIError):
    code = "ai_unavailable"


class AIConfigError(AIError):
    code = "ai_config"


class AIResponseError(AIError):
    code = "ai_bad_response"


def assert_local_endpoint(url, allowed_hosts=()):
    """Allow loopback addresses, or hosts the operator listed explicitly."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AIConfigError("OLLAMA_URL має бути http(s)-адресою.")
    host = parsed.hostname
    if host in allowed_hosts:
        return
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise AIConfigError(
        "OLLAMA_URL вказує на нелокальний хост. Дозволені лише loopback-адреси або хости з OLLAMA_ALLOWED_HOSTS."
    )


class OllamaBackend:
    name = "ollama"

    def __init__(self, url=None, model=None, timeout=None, num_ctx=None, allowed_hosts=None):
        self.url = (url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.num_ctx = num_ctx or settings.OLLAMA_NUM_CTX
        assert_local_endpoint(self.url, allowed_hosts if allowed_hosts is not None else settings.OLLAMA_ALLOWED_HOSTS)
        self.session = requests.Session()
        self.session.trust_env = False  # never route local traffic through a configured proxy

    def _post(self, path, payload, timeout):
        try:
            response = self.session.post(f"{self.url}{path}", json=payload, timeout=timeout)
        except (requests.ConnectionError, socket.error) as exc:
            raise AIUnavailable("Локальна модель недоступна: Ollama не запущена або недосяжна.") from exc
        except requests.Timeout as exc:
            raise AIUnavailable("Локальна модель не відповіла вчасно.") from exc
        if response.status_code == 404:
            raise AIUnavailable(f"Модель «{self.model}» не знайдена в Ollama. Виконайте: ollama pull {self.model}")
        if response.status_code >= 400:
            raise AIUnavailable(f"Ollama повернула помилку HTTP {response.status_code}.")
        return response

    def health(self):
        """Check the server and whether the configured model is installed."""
        try:
            response = self.session.get(f"{self.url}/api/tags", timeout=5)
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
        except (requests.RequestException, ValueError):
            return {"available": False, "server": False, "model": self.model, "model_installed": False, "models": []}
        installed = any(m == self.model or m.split(":")[0] == self.model for m in models)
        return {"available": installed, "server": True, "model": self.model, "model_installed": installed, "models": models}

    def chat_json(self, system, user, schema=None, temperature=0.1):
        """One chat completion constrained to JSON. Returns the parsed object."""
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema or "json",
            "options": {"temperature": temperature, "num_ctx": self.num_ctx},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        response = self._post("/api/chat", payload, self.timeout)
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AIResponseError("Некоректна відповідь Ollama.") from exc
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Model returned non-JSON output (%d chars)", len(content or ""))
            raise AIResponseError("Модель повернула невалідний JSON.") from exc


def get_backend():
    return OllamaBackend()
