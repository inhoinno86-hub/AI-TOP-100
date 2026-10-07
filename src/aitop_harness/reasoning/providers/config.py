"""Provider configuration: runtime config dict / environment variables → ``ReasoningProvider``.

No provider is hard-coded into the Core: runners and the CLI build one from configuration. Secrets are
never part of the configuration — only the *name* of the environment variable that holds the key.

Runtime config (dict / JSON)::

    {"kind": "openai-compat", "preset": "nvidia-nim", "model": "nvidia/nemotron-3-super-120b-a12b",
     "base_url": "...", "api_key_env": "NVIDIA_API_KEY", "structured_mode": "json_schema",
     "timeout_seconds": 240, "temperature": 0.2, "max_tokens": 8192}
    {"kind": "claude-cli", "model": "sonnet", "effort": "medium"}

Environment (``AITOP_REASONER_*``, see ``.env.example``): ``PROVIDER`` (kind or preset), ``MODEL``,
``BASE_URL``, ``API_KEY_ENV``, ``STRUCTURED_MODE``, ``TIMEOUT``, ``TEMPERATURE``, ``MAX_TOKENS``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..interface import ReasoningProvider
from .claude_cli import ClaudeCLIProvider
from .openai_compat import OpenAICompatibleProvider

PRESETS: dict[str, dict[str, Any]] = {
    "nvidia-nim": {
        "kind": "openai-compat",
        "name": "nvidia-nim",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "openai": {
        "kind": "openai-compat",
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4.1",
    },
    "claude-cli": {"kind": "claude-cli", "model": "sonnet"},
}

_OPENAI_FIELDS = {
    "name",
    "base_url",
    "api_key_env",
    "structured_mode",
    "strict_schema",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "max_http_retries",
    "backoff_seconds",
    "extra_body",
}


def resolve_config(config: Mapping[str, Any]) -> dict[str, Any]:
    cfg = dict(config)
    preset = cfg.pop("preset", None)
    if preset is None and cfg.get("kind") in PRESETS:
        preset = cfg.pop("kind")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"unknown provider preset {preset!r}")
    merged = {**PRESETS.get(preset or "", {}), **{k: v for k, v in cfg.items() if v is not None}}
    if "api_key" in merged:
        raise ValueError(
            "provider config must name the key's environment variable (api_key_env), not the key"
        )
    merged.setdefault("kind", "openai-compat")
    return merged


def provider_from_config(config: Mapping[str, Any]) -> ReasoningProvider:
    cfg = resolve_config(config)
    kind = cfg.pop("kind")
    if kind == "claude-cli":
        return ClaudeCLIProvider(
            model=cfg.get("model", "sonnet"),
            effort=cfg.get("effort", "medium"),
            timeout_seconds=float(cfg.get("timeout_seconds", 420.0)),
        )
    if kind == "openai-compat":
        if not cfg.get("model"):
            raise ValueError("openai-compat provider needs a model")
        kw = {k: v for k, v in cfg.items() if k in _OPENAI_FIELDS}
        for k in ("temperature", "timeout_seconds", "backoff_seconds"):
            if k in kw and kw[k] is not None:
                kw[k] = float(kw[k])
        for k in ("max_tokens", "max_http_retries"):
            if k in kw:
                kw[k] = int(kw[k])
        return OpenAICompatibleProvider(model=str(cfg["model"]), **kw)
    raise ValueError(f"unknown provider kind {kind!r}")


def config_from_env(
    prefix: str = "AITOP_REASONER",
    env: Mapping[str, str] | None = None,
    *,
    default: str | None = "claude-cli",
) -> dict[str, Any]:
    src = os.environ if env is None else env

    def get(name: str) -> str | None:
        value = src.get(f"{prefix}_{name}")
        return value if value not in (None, "") else None

    provider = get("PROVIDER") or default
    if provider is None:
        raise ValueError(f"{prefix}_PROVIDER is not set (see .env.example)")
    cfg: dict[str, Any] = {"preset": provider} if provider in PRESETS else {"kind": provider}
    for env_name, key in (
        ("MODEL", "model"),
        ("BASE_URL", "base_url"),
        ("API_KEY_ENV", "api_key_env"),
        ("STRUCTURED_MODE", "structured_mode"),
        ("TIMEOUT", "timeout_seconds"),
        ("TEMPERATURE", "temperature"),
        ("MAX_TOKENS", "max_tokens"),
    ):
        value = get(env_name)
        if value is not None:
            cfg[key] = value
    return cfg


def provider_from_env(prefix: str = "AITOP_REASONER") -> ReasoningProvider:
    return provider_from_config(config_from_env(prefix))


def describe(provider: Any) -> dict[str, Any]:
    """Non-secret provenance of a provider configuration (for run records)."""
    out = {"name": getattr(provider, "name", "?"), "model": getattr(provider, "model", "?")}
    for attr in (
        "base_url",
        "api_key_env",
        "structured_mode",
        "temperature",
        "max_tokens",
        "timeout_seconds",
        "effort",
    ):
        if hasattr(provider, attr):
            out[attr] = getattr(provider, attr)
    return out
