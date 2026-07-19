"""Analyzer agent for ASI-Evolve."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseAgent
from ..sacred_guard import guard_inputs


class Analyzer(BaseAgent):
    """Turn one candidate outcome into a reusable lesson."""

    def __init__(self, llm, prompt_manager):
        super().__init__(llm, prompt_manager, name="analyzer")

    def run(self, **kwargs) -> Dict[str, Any]:
        code = kwargs.get("code", "")
        results = kwargs.get("results", {})
        task_description = kwargs.get("task_description", "")
        best_sampled_node = kwargs.get("best_sampled_node")

        guard_inputs(text_blocks=[code, task_description, str(results)])

        prompt = self._build_prompt(
            code=code,
            results=results,
            task_description=task_description,
            best_sampled_node=best_sampled_node,
        )
        model = (
            self.llm.model_for_role("analyzer")
            if hasattr(self.llm, "model_for_role")
            else None
        )
        try:
            response = self.llm.generate(
                prompt,
                system_prompt=(
                    "You are the ASI-Evolve Analyzer. Distill outcomes into "
                    "specific, reusable lessons for the next round. Do not "
                    "quote sacred identity material."
                ),
                call_name="analyzer",
                model=model,
            )
            lesson = response.content.strip()
        except Exception as error:
            lesson = _fallback_lesson(results, error)

        guard_inputs(text_blocks=[lesson])
        return {"analysis": lesson}

    def _build_prompt(
        self,
        *,
        code: str,
        results: dict[str, Any],
        task_description: str,
        best_sampled_node,
    ) -> str:
        comparison = ""
        if best_sampled_node is not None:
            comparison = (
                f"Best sampled parent: {best_sampled_node.name} "
                f"score={best_sampled_node.score:.4f}\n"
                f"Parent lesson: {best_sampled_node.analysis[:1000]}"
            )

        return f"""Task:
{task_description}

Evaluation result:
{results}

{comparison}

Candidate code excerpt:
```python
{code[:6000]}
```

Write a concise lesson for the next Researcher. Include what changed, why it
helped or failed, and what the next candidate should try.
"""


def _fallback_lesson(results: dict[str, Any], error: Exception) -> str:
    score = results.get("score", 0.0)
    success = results.get("success", False)
    return (
        f"Analyzer fallback: candidate success={success}, score={score}. "
        f"LLM analysis failed with {type(error).__name__}: {error}."
    )
