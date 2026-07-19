"""LiteLLM proxy client for the standalone book-evolve pipeline.

Speaks to any OpenAI-compatible chat-completions endpoint. Defaults target a
local LiteLLM proxy, but everything is overridable — nothing is hardcoded:

  LITELLM_BASE_URL   endpoint base (default http://127.0.0.1:4000/v1)
  LITELLM_API_KEY    API key. Falls back to ~/.litellm-master-key if present,
                     then to "EMPTY" (for proxies without auth).

Role → model defaults (each overridable by env, or per-experiment via
config.yaml → api.role_models):

  COUNCIL_MODEL_1    researcher seat 1 / judge council seat 1
  COUNCIL_MODEL_2    researcher seat 2 / judge council seat 2
  COUNCIL_MODEL_3    researcher seat 3 / judge council seat 3
  JUDGE_MODEL        judge + manager
  FAST_MODEL         engineer + analyzer (cheap, high-volume roles)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

from .utils.llm import LLMClient

DEFAULT_BASE_URL = "http://127.0.0.1:4000/v1"
DEFAULT_API_KEY = "EMPTY"

# Built-in defaults for a LiteLLM proxy with these routes. Override with the
# env vars above or config.yaml — these are conventions, not requirements.
_ENV_ROLE_DEFAULTS: dict[str, tuple[str, str]] = {
    # role: (env var, built-in default)
    "researcher": ("COUNCIL_MODEL_1", "deepseek-v4-pro-cloud"),
    "engineer": ("FAST_MODEL", "deepseek-v4-flash-cloud"),
    "analyzer": ("FAST_MODEL", "deepseek-v4-flash-cloud"),
    "manager": ("JUDGE_MODEL", "deepseek-v4-pro-cloud"),
    "judge": ("JUDGE_MODEL", "deepseek-v4-pro-cloud"),
}


def resolve_role_model(role: str, fallback: str | None = None) -> str:
    """Resolve a pipeline role to a model name: env override, then default."""
    env_var, default = _ENV_ROLE_DEFAULTS.get(role, ("", fallback or ""))
    value = os.environ.get(env_var, "") if env_var else ""
    return value or fallback or default


def default_role_models() -> dict[str, str]:
    """The full role → model map after env resolution."""
    return {role: resolve_role_model(role) for role in _ENV_ROLE_DEFAULTS}


# Backwards-compatible module constant (pre-1.2 callers import this).
ROLE_MODELS: dict[str, str] = default_role_models()


def _default_key() -> str:
    """LITELLM_API_KEY, else ~/.litellm-master-key, else "EMPTY"."""
    env_key = os.environ.get("LITELLM_API_KEY", "").strip()
    if env_key:
        return env_key
    key_file = os.path.expanduser("~/.litellm-master-key")
    if os.path.exists(key_file):
        try:
            key = open(key_file, "r", encoding="utf-8").read().strip()
            if key:
                return key
        except OSError:
            pass
    return DEFAULT_API_KEY


def _default_base() -> str:
    return os.environ.get("LITELLM_BASE_URL", "").strip() or DEFAULT_BASE_URL


class LiteLLMClient(LLMClient):
    """OpenAI-compatible client with role-aware model selection.

    ``role_models`` entries from experiment config win over env defaults.
    Dict-valued entries (e.g. a researcher council spec) are resolved to
    their ``default`` model for role lookups; the council itself is handled
    by the Researcher agent directly from config.
    """

    def __init__(self, **kwargs: Any) -> None:
        config_roles = kwargs.pop("role_models", None) or {}
        merged: Dict[str, str] = dict(default_role_models())
        for role, value in config_roles.items():
            if isinstance(value, dict):
                value = value.get("default", "")
            if value:
                merged[str(role)] = str(value)
        self.role_models: Dict[str, str] = merged

        super().__init__(
            api_key=kwargs.pop("api_key", None) or _default_key(),
            base_url=kwargs.pop("base_url", None) or _default_base(),
            model=kwargs.pop("model", None) or self.role_models["engineer"],
            **kwargs,
        )

    def model_for_role(self, role: str) -> str:
        """Return the configured model for a pipeline agent role."""
        return self.role_models.get(role, self.model)


def create_litellm_client(api_config: Dict[str, Any]) -> LiteLLMClient:
    """Create a role-aware LiteLLM client from the pipeline api config."""
    framework_keys = {
        "provider",
        "base_url",
        "api_key",
        "model",
        "timeout",
        "retry_times",
        "retry_delay",
        "role_models",
    }
    extra_params = {k: v for k, v in api_config.items() if k not in framework_keys}

    return LiteLLMClient(
        api_key=_configured_key(api_config),
        base_url=api_config.get("base_url") or _default_base(),
        model=api_config.get("model") or None,
        timeout=api_config.get("timeout", 120),
        retry_times=api_config.get("retry_times", 3),
        retry_delay=api_config.get("retry_delay", 5),
        role_models=api_config.get("role_models", {}),
        **extra_params,
    )


def _configured_key(api_config: Dict[str, Any]) -> str:
    configured = api_config.get("api_key")
    if configured and configured != "EMPTY":
        return configured
    return _default_key()


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    role: str = "researcher",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 300,
) -> str:
    """One-shot chat completion helper (stdlib only, no client object)."""
    url = (base_url or _default_base()).rstrip("/") + "/chat/completions"
    key = api_key or _default_key()
    body = json.dumps({
        "model": model or resolve_role_model(role),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise RuntimeError(f"LiteLLM HTTP {e.code}: {detail}") from e
