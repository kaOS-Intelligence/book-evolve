#!/usr/bin/env python3
"""Run Book Evolution experiment."""
import argparse
import os
import sys

# CRITICAL: Disable fast-path researcher that generates jacket code
os.environ["ASI_EVOLVE_FAST_RESEARCHER"] = "0"
os.environ["ASI_EVOLVE_FAST_ANALYZER"] = "0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
from pathlib import Path

# Bootstrap the Evolve package
project_root = Path(os.path.dirname(os.path.abspath(__file__)))
package_name = "Evolve"
if package_name not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        package_name,
        project_root / "__init__.py",
        submodule_search_locations=[str(project_root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)

import shutil
from Evolve.pipeline.main import Pipeline


def _wipe_state(experiment_dir: Path) -> None:
    for name in ("steps", "logs", "database_data"):
        target = experiment_dir / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    state = experiment_dir / "pipeline_state.json"
    if state.exists():
        state.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Book Evolution ASI-Evolve pipeline"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10,
        help="Evolution steps after the seed (default: 10)",
    )
    parser.add_argument(
        "--experiment",
        default="book_evolution",
        help="Experiment name / directory under experiments/ (default: book_evolution)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yaml (default: experiments/<experiment>/config.yaml)",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=1,
        help="Chapter number to evolve; sets BOOK_EVOLUTION_CHAPTER_N (default: 1)",
    )
    parser.add_argument(
        "--target-score",
        type=float,
        default=None,
        help="Stop early once the best score reaches this value (e.g. 0.95)",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=None,
        help="Stop early after this many consecutive steps with no improvement",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Wipe prior steps/logs/db/state before running (default: resume)",
    )
    args = parser.parse_args()

    evolve_root = Path(__file__).resolve().parent
    os.environ["BOOK_EVOLUTION_CHAPTER_N"] = str(args.chapter)

    config_path = (
        args.config
        or str(evolve_root / f"experiments/{args.experiment}/config.yaml")
    )

    try:
        experiment_dir = evolve_root / "experiments" / args.experiment

        if args.fresh:
            print(f"--fresh: wiping prior state under {experiment_dir}")
            _wipe_state(experiment_dir)

        p = Pipeline(
            experiment_name=args.experiment,
            config_path=config_path,
        )
        eval_script = str(experiment_dir / "evaluator.py")

        mode = "resume" if p.is_resume else "fresh"
        conv = ""
        if args.target_score is not None or args.patience is not None:
            conv = (
                f" (target_score={args.target_score}, patience={args.patience})"
            )
        print(
            f"Pipeline created [{mode}] — chapter {args.chapter}, "
            f"up to {args.max_steps} step(s) with council{conv}..."
        )
        p.run(
            max_steps=args.max_steps,
            eval_script=eval_script,
            target_score=args.target_score,
            patience=args.patience,
        )
        print("DONE")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
