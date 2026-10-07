"""Independent API provider: any OpenAI-compatible ``/chat/completions`` endpoint over HTTPS.

One adapter covers OpenAI, NVIDIA NIM (``integrate.api.nvidia.com``), OpenRouter, vLLM / Ollama and other
servers that speak the same wire format. No SDK dependency (stdlib ``urllib``); the API key is read from
an environment variable at call time and never stored, logged or recorded.

Structured output modes (``structured_mode``):

* ``json_schema`` — ``response_format = {"type": "json_schema", ...}`` (native constrained decoding),
* ``json_object`` — ``response_format = {"type": "json_object"}`` + the schema in the instruction,
* ``prompt``      — the schema in the instruction only.

The Harness re-validates every output against the same schema regardless (``Reasoner``). Transport-level
transient failures (HTTP 429 / 5xx) get a bounded, provider-local backoff; anything still failing is
returned as PROVIDER_ERROR so the Reasoner's bounded retry / fallback chain decides what happens next.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..interface import ProviderTimeout, ReasoningRequest, ReasoningResponse, ReasoningStatus

# transport(url, headers, body, timeout) -> (status, response headers, response body)
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, dict[str, str], bytes]]

_TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 — https url
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read()
    except TimeoutError as exc:
        raise ProviderTimeout(f"HTTP request exceeded {timeout}s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ProviderTimeout(f"HTTP request exceeded {timeout}s") from exc
        raise


def extract_json(text: str) -> Any:
    """Parse a JSON object from model text: tolerate ``<think>`` blocks and code fences, nothing else."""
    body = _FENCE.sub("", _THINK.sub("", text).strip()).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(body[start : end + 1])


@dataclass
class OpenAICompatibleProvider:
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    name: str = "openai-compat"
    structured_mode: str = "json_schema"
    strict_schema: bool = False
    temperature: float | None = 0.2
    max_tokens: int = 8192
    timeout_seconds: float = 240.0
    max_http_retries: int = 2  # provider-local, transient HTTP only (429 / 5xx)
    backoff_seconds: float = 8.0
    max_backoff_seconds: float = 60.0
    extra_body: dict[str, Any] = field(default_factory=dict)
    transport: Transport = urllib_transport
    sleep: Callable[[float], None] = time.sleep
    usage_log: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ request

    def _body(self, request: ReasoningRequest) -> dict[str, Any]:
        user = request.prompt()
        if self.structured_mode != "json_schema":
            user += "\nOUTPUT JSON SCHEMA:\n" + json.dumps(request.output_schema, separators=(",", ":"))
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.structured_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^a-zA-Z0-9_-]", "_", request.skill)[:64],
                    "schema": request.output_schema,
                    "strict": self.strict_schema,
                },
            }
        elif self.structured_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra_body)
        return body

    def _error(self, error: str, **kw: Any) -> ReasoningResponse:
        return ReasoningResponse(
            ReasoningStatus.PROVIDER_ERROR, provider=self.name, model=self.model, error=error, **kw
        )

    # ------------------------------------------------------------------ call

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            return self._error(f"API key environment variable {self.api_key_env} is not set")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps(self._body(request)).encode("utf-8")
        http_retries = 0
        t0 = time.monotonic()
        while True:
            try:
                status, resp_headers, raw = self.transport(url, headers, payload, self.timeout_seconds)
            except ProviderTimeout:
                raise
            except Exception as exc:  # noqa: BLE001 — network failure is data for the Reasoner
                return self._error(f"transport {type(exc).__name__}: {exc}")
            if status in _TRANSIENT and http_retries < self.max_http_retries:
                http_retries += 1
                self.sleep(self._backoff(resp_headers, http_retries))
                continue
            break
        usage: dict[str, Any] = {
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "http_status": status,
            "http_retries": http_retries,
        }
        if status != 200:
            snippet = raw[:300].decode("utf-8", "replace")
            kind = "rate_limited" if status == 429 else "http_error"
            usage["error_kind"] = kind
            self.usage_log.append(usage)
            return self._error(f"HTTP {status} ({kind}): {snippet}", usage=usage)
        try:
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            message = choice.get("message") or {}
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            self.usage_log.append(usage)
            return self._error(
                "response envelope is not a chat completion",
                raw=raw[:2000].decode("utf-8", "replace"),
                usage=usage,
            )
        tokens = envelope.get("usage") or {}
        usage.update(
            prompt_tokens=tokens.get("prompt_tokens"),
            completion_tokens=tokens.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )
        self.usage_log.append(usage)
        resolved = str(envelope.get("model") or self.model)
        text = message.get("content") or ""
        if not text.strip():
            return ReasoningResponse(
                ReasoningStatus.INVALID_SCHEMA,
                provider=self.name,
                model=resolved,
                error=f"empty content (finish_reason={choice.get('finish_reason')})",
                usage=usage,
            )
        try:
            output = extract_json(text)
        except json.JSONDecodeError as exc:
            truncated = choice.get("finish_reason") == "length"
            return ReasoningResponse(
                ReasoningStatus.INVALID_SCHEMA,
                provider=self.name,
                model=resolved,
                error=("output truncated at max_tokens: " if truncated else "output is not JSON: ")
                + str(exc),
                raw=text[:2000],
                usage=usage,
            )
        if not isinstance(output, dict):
            return ReasoningResponse(
                ReasoningStatus.INVALID_SCHEMA,
                provider=self.name,
                model=resolved,
                error="output is not a JSON object",
                raw=text[:2000],
                usage=usage,
            )
        return ReasoningResponse(
            ReasoningStatus.SUCCESS, output=output, provider=self.name, model=resolved, usage=usage
        )

    def _backoff(self, headers: dict[str, str], n: int) -> float:
        retry_after = {k.lower(): v for k, v in headers.items()}.get("retry-after")
        try:
            wait = float(retry_after) if retry_after is not None else self.backoff_seconds * (2 ** (n - 1))
        except ValueError:
            wait = self.backoff_seconds * (2 ** (n - 1))
        return max(0.0, min(wait, self.max_backoff_seconds))
