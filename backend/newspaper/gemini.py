"""Google Gemini as a free alternative AI editor (Gemini API free tier).

Talks to the public REST API with the standard library, so there is no extra
dependency. Free-tier limits are low (roughly 10 requests/minute and a few
hundred a day, set per project), so calls are paced and 429s are retried.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta"
MIN_INTERVAL_S = 6.5          # stay under ~10 requests/minute
UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties"}


class GeminiError(Exception):
    pass


def _strip(schema):
    """`responseSchema` (the older OpenAPI-style field) rejects a few JSON Schema keys."""
    if isinstance(schema, dict):
        return {k: _strip(v) for k, v in schema.items() if k not in UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [_strip(v) for v in schema]
    return schema


class GeminiClient:
    def __init__(self, api_key: str, model: str, base_url: str = API, min_interval: float = MIN_INTERVAL_S):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._schema_mode = "json_schema"   # → "openapi" → "prompt" if the API rejects a form

    # ── HTTP ──
    def _request(self, method: str, path: str, body: dict | None = None, timeout: int = 300) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _pace(self) -> None:
        with self._lock:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _generate(self, body: dict) -> dict:
        for attempt in range(5):
            self._pace()
            try:
                return self._request("POST", f"models/{self.model}:generateContent", body)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:2000]
                if exc.code == 404 and attempt == 0:
                    self.model = self.discover_model()
                    continue
                if exc.code == 429:
                    if "PerDay" in detail or "per day" in detail.lower():
                        raise GeminiError("Gemini free-tier daily quota used up") from exc
                    delay = re.search(r'"retryDelay":\s*"(\d+)', detail)
                    time.sleep(int(delay.group(1)) + 1 if delay else 15 * (attempt + 1))
                    continue
                if exc.code in (500, 502, 503, 504):
                    time.sleep(10 * (attempt + 1))
                    continue
                raise GeminiError(f"HTTP {exc.code}: {detail[:400]}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 4:
                    raise GeminiError(f"connection error: {exc}") from exc
                time.sleep(10 * (attempt + 1))
        raise GeminiError("Gemini kept rate-limiting; giving up for now")

    def discover_model(self) -> str:
        """Picks the newest general-purpose Flash model if the configured one is gone."""
        data = self._request("GET", "models?pageSize=200")
        names = [
            m["name"].removeprefix("models/") for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        flash = [n for n in names if "flash" in n and not re.search(r"lite|image|tts|live|audio|exp|preview|thinking", n)]
        if not flash:
            raise GeminiError(f"no Flash model available (found {names[:10]})")

        def version(n):
            return [int(x) for x in re.findall(r"\d+", n)] or [0]

        choice = max(flash, key=version)
        log.warning("Gemini model %s not found; using %s instead", self.model, choice)
        return choice

    # ── public ──
    def ask_json(self, system: str, prompt: str, schema: dict, max_tokens: int = 16000) -> tuple[dict, dict]:
        """Returns (parsed JSON, usage metadata)."""
        while True:
            mode = self._schema_mode
            config: dict = {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}
            text = prompt
            if mode == "json_schema":
                config["responseJsonSchema"] = schema
            elif mode == "openapi":
                config["responseSchema"] = _strip(schema)
            else:
                text += "\n\nReply with JSON only, matching this JSON Schema exactly:\n" + json.dumps(schema)
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": config,
            }
            try:
                data = self._generate(body)
                break
            except GeminiError as exc:
                if str(exc).startswith("HTTP 400") and mode != "prompt":
                    with self._lock:      # concurrent requests must advance only once per form
                        if self._schema_mode == mode:
                            self._schema_mode = "openapi" if mode == "json_schema" else "prompt"
                            log.info("Gemini rejected schema form %s; now using %s", mode, self._schema_mode)
                    continue
                raise

        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise GeminiError(f"Gemini returned nothing ({reason})")
        cand = candidates[0]
        finish = cand.get("finishReason", "STOP")
        if finish == "MAX_TOKENS":
            raise GeminiError("response was cut off (max tokens)")
        if finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise GeminiError(f"Gemini stopped early ({finish})")
        out = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        out = re.sub(r"^```(?:json)?\s*|\s*```$", "", out.strip())
        try:
            return json.loads(out), data.get("usageMetadata", {})
        except json.JSONDecodeError as exc:
            raise GeminiError(f"invalid JSON from Gemini: {exc}") from exc


def from_env(model: str) -> GeminiClient | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return GeminiClient(key, model) if key else None
