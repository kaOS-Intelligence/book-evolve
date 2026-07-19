"""Engineer agent for ASI-Evolve."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .base import BaseAgent
from ..sacred_guard import SacredGuardError, check_candidate


class Engineer(BaseAgent):
    """Materialize a candidate and execute the evaluator script."""

    def __init__(self, llm, prompt_manager):
        super().__init__(llm, prompt_manager, name="engineer")

    def run(self, **kwargs) -> Dict[str, Any]:
        code = kwargs.get("code", "")
        experiment_dir = Path(kwargs["experiment_dir"])
        eval_script = kwargs.get("eval_script")
        timeout = int(kwargs.get("timeout", 1800))

        try:
            check_candidate(code)
        except SacredGuardError as error:
            return {
                "success": False,
                "score": 0.0,
                "eval_score": 0.0,
                "error": str(error),
                "guard_trip": error.trip.to_dict(),
            }

        experiment_dir.mkdir(parents=True, exist_ok=True)
        program_path = experiment_dir / "candidate.py"
        output_path = experiment_dir / "eval_result.json"
        program_path.write_text(code, encoding="utf-8")

        if not eval_script:
            return {
                "success": True,
                "score": 0.0,
                "eval_score": 0.0,
                "runtime": 0.0,
                "program_path": str(program_path),
            }

        start = time.time()
        if str(eval_script).endswith(".sh"):
            command = ["bash", str(eval_script), str(program_path), str(output_path)]
        elif str(eval_script).endswith(".py"):
            command = ["python3", str(eval_script), str(program_path), str(output_path)]
        else:
            command = [str(eval_script), str(program_path), str(output_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(experiment_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            runtime = time.time() - start
        except subprocess.TimeoutExpired as error:
            return {
                "success": False,
                "score": 0.0,
                "eval_score": 0.0,
                "runtime": float(timeout),
                "error": f"Evaluator timed out after {timeout}s: {error}",
                "program_path": str(program_path),
            }

        result: Dict[str, Any] = {
            "success": completed.returncode == 0,
            "score": 0.0,
            "eval_score": 0.0,
            "runtime": runtime,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "program_path": str(program_path),
        }

        if output_path.exists():
            try:
                result.update(json.loads(output_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError as error:
                result["success"] = False
                result["error"] = f"Invalid evaluator JSON: {error}"
        elif completed.returncode != 0:
            result["error"] = completed.stderr or completed.stdout or "Evaluator failed"
        else:
            result["error"] = "Evaluator produced no JSON output"
            result["success"] = False

        result["score"] = float(result.get("score", result.get("eval_score", 0.0)) or 0.0)
        result["eval_score"] = float(result.get("eval_score", result["score"]) or 0.0)
        return result
