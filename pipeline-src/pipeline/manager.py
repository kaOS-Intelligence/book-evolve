"""Manager agent for optional prompt generation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .base import BaseAgent
from ..sacred_guard import guard_inputs


class Manager(BaseAgent):
    """Generate simple prompt templates when an experiment asks for them."""

    def __init__(self, llm, prompt_manager):
        super().__init__(llm, prompt_manager, name="manager")

    def run(self, **kwargs) -> Dict[str, str]:
        task_description = kwargs.get("task_description", "")
        eval_criteria = kwargs.get("eval_criteria", "")
        prompt_dir = Path(kwargs["prompt_dir"])

        guard_inputs(text_blocks=[task_description, eval_criteria])
        prompt_dir.mkdir(parents=True, exist_ok=True)

        researcher = prompt_dir / "researcher.jinja2"
        analyzer = prompt_dir / "analyzer.jinja2"

        if not researcher.exists():
            researcher.write_text(
                "Task:\n{{ task_description }}\n\n"
                "Context nodes:\n{{ context_nodes }}\n\n"
                "Cognition:\n{{ cognition_items }}\n\n"
                "Base code:\n{{ base_code }}\n\n"
                "Return <name>, <motivation>, and <code> tags.",
                encoding="utf-8",
            )
        if not analyzer.exists():
            analyzer.write_text(
                "Task:\n{{ task_description }}\n\n"
                "Results:\n{{ results }}\n\n"
                "Code:\n{{ code }}\n\n"
                "Write the lesson for the next round.",
                encoding="utf-8",
            )

        return {
            "researcher_prompt": str(researcher),
            "analyzer_prompt": str(analyzer),
        }
