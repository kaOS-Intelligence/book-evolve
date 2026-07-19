"""Contract test for the shipped pipeline, run against a scaffolded project.

Usage: python3 pipeline_contract.py <project_dir>

Verifies (with stubbed third-party deps, so it runs on bare python3):
  1. The Evolve package loads the way run_book_evolution.py loads it.
  2. litellm_client exposes create_litellm_client / LiteLLMClient / chat.
  3. COUNCIL_MODEL_* / JUDGE_MODEL env overrides are honored.
  4. The config loader resolves ${VAR:-default} placeholders.
Prints CONTRACT-OK on success.
"""
import importlib.util
import os
import pathlib
import sys
import types

# Stub third-party deps so this runs without the project venv.
for name in ("openai", "yaml", "jinja2"):
    stub = types.ModuleType(name)
    if name == "openai":
        class OpenAI:  # noqa: N801 — matching the real symbol
            def __init__(self, **kw):
                pass
        stub.OpenAI = OpenAI
    if name == "jinja2":
        class _Any:
            def __init__(self, *a, **kw):
                pass
        stub.Environment = _Any
        stub.FileSystemLoader = _Any
        stub.Template = _Any
    if name == "yaml":
        stub.safe_load = lambda *a, **kw: {}
    sys.modules[name] = stub

root = pathlib.Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location(
    "Evolve", root / "__init__.py", submodule_search_locations=[str(root)]
)
mod = importlib.util.module_from_spec(spec)
sys.modules["Evolve"] = mod
spec.loader.exec_module(mod)

os.environ["COUNCIL_MODEL_1"] = "my-custom-model"
os.environ["JUDGE_MODEL"] = "my-judge"

from Evolve.litellm_client import (  # noqa: E402
    LiteLLMClient,
    chat,
    create_litellm_client,
    resolve_role_model,
)

assert callable(chat)
assert resolve_role_model("researcher") == "my-custom-model"
assert resolve_role_model("judge") == "my-judge"
client = create_litellm_client({"provider": "litellm"})
assert isinstance(client, LiteLLMClient)
assert client.model_for_role("researcher") == "my-custom-model"

from Evolve.utils.config import _resolve_env_vars  # noqa: E402

assert _resolve_env_vars("${BOOKEVOLVE_TEST_UNSET:-fallback}") == "fallback"
os.environ["BOOKEVOLVE_TEST_SET"] = "real"
assert _resolve_env_vars("${BOOKEVOLVE_TEST_SET:-fallback}") == "real"

print("CONTRACT-OK")
