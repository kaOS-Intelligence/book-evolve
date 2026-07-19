"""Researcher agent for ASI-Evolve.

Supports two modes:
1. Single-model: one model generates one candidate (legacy).
2. Council: multiple models each generate an independent candidate
   from the same prompt. The pipeline then evaluates all candidates
   and lets evolution select the fittest.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .base import BaseAgent
from ..sacred_guard import SacredGuardError, check_candidate, guard_inputs
from ..utils.structures import CognitionItem, Node


def _chapter_n_from_env() -> int:
    """Read BOOK_EVOLUTION_CHAPTER_N (default 1). Set by run_book_evolution.py."""
    try:
        return int(os.environ.get("BOOK_EVOLUTION_CHAPTER_N", "1"))
    except ValueError:
        return 1


def _used_titles_for_chapter() -> List[str]:
    """Load already-used chapter titles for cross-chapter uniqueness.

    The service orchestrator (run_book_evolution_service.py) writes a
    ``used_titles.txt`` file — one title per line — into the experiment
    directory before evolving each chapter, sourced from the book's toc.json.
    Returns an empty list if absent (first chapter, or running standalone).
    """
    path = Path(os.environ.get("BOOK_EVOLUTION_USED_TITLES", "used_titles.txt"))
    if not path.is_absolute():
        # Look next to the prompt dir the manager already wired up.
        cwd = Path.cwd()
        path = cwd / path
    if not path.exists():
        return []
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        return []



class Researcher(BaseAgent):
    """Propose the next candidate program (or programs, in council mode)."""

    def __init__(self, llm, prompt_manager, config: dict[str, Any] | None = None):
        super().__init__(llm, prompt_manager, name="researcher")
        self.config = config or {}

    def _resolve_council_models(self) -> List[Dict[str, str]]:
        """Resolve the council model list from config."""
        role_models = self.config.get("role_models") or self.config
        researcher_cfg = role_models.get("researcher", {})
        
        if isinstance(researcher_cfg, dict) and "council" in researcher_cfg:
            return researcher_cfg["council"]
        # Fallback: single model
        model_name = researcher_cfg.get("default", researcher_cfg) if isinstance(researcher_cfg, dict) else str(researcher_cfg)
        if not model_name:
            model_name = self.llm.model_for_role("researcher") if hasattr(self.llm, "model_for_role") else None
        return [{"model": model_name, "name": "Researcher"}]

    def run(self, **kwargs) -> List[Dict[str, Any]]:
        """Run the researcher, returning a list of candidate dicts (one per model in council mode, or one in single mode)."""
        task_description = kwargs.get("task_description", "")
        context_nodes = kwargs.get("context_nodes", [])
        cognition_items = kwargs.get("cognition_items", [])
        base_code = kwargs.get("base_code")
        greek_source = kwargs.get("greek_source")
        dictation_source = kwargs.get("dictation_source")
        style_samples = kwargs.get("style_samples", [])
        source_text = kwargs.get("source_text")

        council_models = self._resolve_council_models()
        
        if len(council_models) == 1:
            return [self._run_single(
                model_info=council_models[0],
                task_description=task_description,
                context_nodes=context_nodes,
                cognition_items=cognition_items,
                base_code=base_code,
                greek_source=greek_source,
                dictation_source=dictation_source,
                style_samples=style_samples,
                source_text=source_text,
            )]
        
        # Council mode: parallel calls
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(council_models)) as executor:
            futures = {
                executor.submit(
                    self._run_single,
                    model_info=mi,
                    task_description=task_description,
                    context_nodes=context_nodes,
                    cognition_items=cognition_items,
                    base_code=base_code,
                    greek_source=greek_source,
                    dictation_source=dictation_source,
                    style_samples=style_samples,
                    source_text=source_text,
                ): mi
                for mi in council_models
            }
            for future in concurrent.futures.as_completed(futures):
                mi = futures[future]
                try:
                    result = future.result(timeout=600)
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Council seat {mi.get('name', mi.get('model'))} failed: {e}")
        return results if results else [
            {"name": "council_failed", "motivation": "All council seats failed", "code": ""}
        ]

    def _run_single(
        self,
        model_info: Dict[str, str],
        task_description: str,
        context_nodes: Iterable[Node],
        cognition_items: Iterable[CognitionItem],
        base_code: str | None,
        greek_source: str | None = None,
        dictation_source: str | None = None,
        style_samples: list[dict] | None = None,
        source_text: str | None = None,
    ) -> Dict[str, Any]:
        """Generate one candidate from a single model."""
        model_name = model_info.get("model")
        seat_name = model_info.get("name", model_name)
        
        guard_inputs(
            text_blocks=[
                task_description,
                _format_nodes(context_nodes),
                _format_cognition(cognition_items),
                base_code or "",
            ]
        )

        prompt = self._build_prompt(
            task_description=task_description,
            context_nodes=context_nodes,
            cognition_items=cognition_items,
            base_code=base_code,
            greek_source=greek_source,
            dictation_source=dictation_source,
            style_samples=style_samples,
            source_text=source_text,
        )

        system_prompt = model_info.get("system_prompt") or self.config.get(
            "system_prompt",
            f"You are the Researcher — {seat_name}. "
            "Propose one candidate translation and return exactly "
            "<name>, <motivation>, and <code> tags.",
        )
        
        self.logger.info(f"Council [{seat_name}] calling model={model_name}...")
        result = self.llm.extract_tags(
            prompt,
            system_prompt=system_prompt,
            call_name=f"researcher_{seat_name.lower().replace(' ', '_')}",
            model=model_name,
        )
        code = result.get("code", "").strip()
        try:
            check_candidate(code)
        except SacredGuardError:
            raise

        return {
            "name": f"{seat_name}: {result.get('name', 'candidate').strip()[:120]}",
            "motivation": result.get("motivation", "").strip(),
            "code": code,
            "model": model_name,
        }

    def _build_prompt(
        self,
        *,
        task_description: str,
        context_nodes: Iterable[Node],
        cognition_items: Iterable[CognitionItem],
        base_code: str | None,
        greek_source: str | None = None,
        dictation_source: str | None = None,
        style_samples: list[dict] | None = None,
        source_text: str | None = None,
    ) -> str:
        if self.prompt_manager.has_template("researcher"):
            return self.prompt_manager.render(
                "researcher",
                task_description=task_description,
                context_nodes=list(context_nodes),
                cognition_items=list(cognition_items),
                base_code=base_code,
                greek_source=greek_source,
                dictation_source=dictation_source,
                style_samples=style_samples or [],
                source_text=source_text,
                chapter_n=_chapter_n_from_env(),
                used_titles=_used_titles_for_chapter(),
            )

        return f"""Task:
{task_description}

Relevant prior candidates:
{_format_nodes(context_nodes)}

Cognition lessons:
{_format_cognition(cognition_items)}

Base code, if any:
```
{base_code or "# No base code. Produce a complete candidate from the provided context."}
```

Return exactly:
<name>short_candidate_name</name>
<motivation>why this candidate should improve the score</motivation>
<code>complete candidate content</code>
"""


def _format_nodes(nodes: Iterable[Node]) -> str:
    parts = []
    for node in nodes:
        parts.append(
            f"- id={node.id} name={node.name} score={node.score:.4f}\n"
            f"  motivation={node.motivation[:500]}\n"
            f"  lesson={node.analysis[:500]}"
        )
    return "\n".join(parts) if parts else "None yet."


def _format_cognition(items: Iterable[CognitionItem]) -> str:
    parts = []
    for item in items:
        source = f" ({item.source})" if item.source else ""
        parts.append(f"-{source} {item.content}")
    return "\n".join(parts) if parts else "No cognition items retrieved."
