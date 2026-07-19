"""Local event mirror for the standalone book-evolve pipeline.

The pipeline emits progress events (round start, candidate, score, lesson)
through ``emit_evolve_event``. In the standalone build those events land in a
local append-only JSONL activity stream so any host UI can tail live progress:

  * ``ASI_EVOLVE_ACTIVITY_STREAM`` env var — explicit stream file path, or
  * ``<project>/experiments/activity_stream.jsonl`` by default.

The Supabase mirror itself is host-internal and is not shipped with the
public package; ``SupabaseMirror`` stays a silent no-op (via __getattr__),
so mirror call-sites in the pipeline can never break the standalone build.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _activity_stream_path() -> Path:
    env = os.environ.get("ASI_EVOLVE_ACTIVITY_STREAM", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent / "experiments" / "activity_stream.jsonl"


def _noop(*args: Any, **kwargs: Any) -> None:
    return None


class SupabaseMirror:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.enabled = False

    def __getattr__(self, name: str) -> Any:
        # Every mirror method is a no-op in the standalone build.
        return _noop

    def __bool__(self) -> bool:
        return False


def emit_evolve_event(event: str, payload: dict[str, Any] | None = None) -> None:
    """Append one pipeline event to the local activity stream.

    Best-effort by design: a progress event must never take down a run,
    so every failure (unwritable path, full disk, bad payload) is swallowed.
    """
    try:
        stream = _activity_stream_path()
        stream.parent.mkdir(parents=True, exist_ok=True)
        frame = {
            "event": event,
            "payload": {
                "surface": "asi-evolve",
                "ts": int(time.time() * 1000),
                **(payload or {}),
            },
        }
        with stream.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(frame, ensure_ascii=False) + "\n")
    except Exception:
        return None
