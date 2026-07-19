#!/usr/bin/env python3
"""Book Evolution service — evolve chapters sequentially through the council + judge cycle.

For each chapter in [--start-chapter, --end-chapter] this orchestrator:

  1. Seeds the shared cognition store with THAT chapter's dictation and the
     author's reference samples (seed_book_evolution_cognition.py) — when
     --dictation-dir is provided. Chapter N maps to the Nth .txt file in the
     directory, sorted by name.
  2. Provisions an isolated per-chapter experiment dir (prepare_chapter.py).
  3. Evolves it through the full council + judge cycle (run_book_evolution.py),
     resuming by default and stopping early on convergence (--target-score) or
     maxing out (--patience).
  4. Promotes the best candidate into the sovereign files corpus
     (promote_best_to_productions.py), merging into one multi-chapter book.

It then stops after --end-chapter.

This file orchestrates; it performs no evolution itself. Heavy inference runs
through the cloud models behind the local LiteLLM proxy.

Usage:
  python3 run_book_evolution_service.py --start-chapter 1 --end-chapter 5 \\
    --dictation-dir ./dictation --reference-dir ./author-style
  python3 run_book_evolution_service.py --start-chapter 1 --end-chapter 12 \\
    --dictation-dir ./dictation --target-score 0.95 --patience 5 --max-steps 30
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

EVOLVE_ROOT = Path(__file__).resolve().parent
EXPERIMENTS_DIR = EVOLVE_ROOT / "experiments"
TEMPLATE = "book_evolution"


def _emit(event: str, payload: dict) -> None:
    """Best-effort service-level progress event for host UIs."""
    try:
        sys.path.insert(0, str(EVOLVE_ROOT))
        from experiment_supabase import emit_evolve_event

        emit_evolve_event(event, payload)
    except Exception:
        pass


def _python() -> str:
    venv = EVOLVE_ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _run(cmd: list[str], *, env: dict | None = None) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(
        cmd, cwd=str(EVOLVE_ROOT), env=env, check=False
    ).returncode


def _txt_files(directory: Path) -> list[Path]:
    """Sorted .txt files in a directory (non-recursive)."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix == ".txt" and p.is_file())


def seed_chapter(
    chapter_n: int,
    dictation_dir: Path,
    reference_dir: Path | None,
) -> None:
    """Seed the shared cognition store with chapter N's dictation.

    Chapter N maps to the Nth .txt file (1-based) in dictation_dir, sorted
    by name. Every .txt file in reference_dir becomes an author style sample
    (source title = file stem).
    """
    dictation_files = _txt_files(dictation_dir)
    if chapter_n > len(dictation_files):
        raise SystemExit(
            f"Chapter {chapter_n} requested but only {len(dictation_files)} "
            f"dictation .txt files found in {dictation_dir}"
        )
    dictation_file = dictation_files[chapter_n - 1]

    cmd = [
        _python(),
        str(EXPERIMENTS_DIR / "seed_book_evolution_cognition.py"),
        "--dictation",
        str(dictation_file),
        "--output-dir",
        str(EXPERIMENTS_DIR / TEMPLATE / "cognition_data"),
    ]
    for ref in _txt_files(reference_dir) if reference_dir else []:
        cmd += ["--reference", str(ref), ref.stem.replace("-", " ").title()]

    print(f"Seeding chapter {chapter_n} cognition from {dictation_file.name}")
    rc = _run(cmd)
    if rc != 0:
        raise SystemExit(
            f"cognition seeding failed for chapter {chapter_n} (rc={rc})"
        )


def provision(chapter_n: int, force: bool) -> str:
    nn = f"{chapter_n:02d}"
    exp_name = f"book_evolution_chapter_{nn}"
    cmd = [
        _python(),
        str(EXPERIMENTS_DIR / "prepare_chapter.py"),
        "--chapter",
        str(chapter_n),
    ]
    if force:
        cmd.append("--force")
    rc = _run(cmd)
    if rc != 0:
        raise SystemExit(
            f"prepare_chapter failed for chapter {chapter_n} (rc={rc})"
        )
    return exp_name


def evolve(exp_name: str, chapter_n: int, args, *, used_titles_path: Path | None = None) -> int:
    cmd = [
        _python(),
        str(EVOLVE_ROOT / "run_book_evolution.py"),
        "--experiment",
        exp_name,
        "--chapter",
        str(chapter_n),
        "--max-steps",
        str(args.max_steps),
    ]
    if args.target_score is not None:
        cmd += ["--target-score", str(args.target_score)]
    if args.patience is not None:
        cmd += ["--patience", str(args.patience)]
    if args.fresh:
        cmd.append("--fresh")
    env = None
    if used_titles_path and used_titles_path.exists():
        # Forward the absolute path so the researcher helper finds the file
        # regardless of the subprocess cwd.
        env = dict(os.environ)
        env["BOOK_EVOLUTION_USED_TITLES"] = str(used_titles_path)
    return _run(cmd, env=env)


def _title_from_filename(path: Path) -> str:
    """Derive a human chapter title from a dictation filename.

    "01-may-14.txt" -> "May 14"; "02_the_generator.txt" -> "The Generator".
    """
    import re

    stem = re.sub(r"^[0-9]+[-_. ]*", "", path.stem)
    words = re.split(r"[-_]+", stem)
    return " ".join(w.capitalize() for w in words if w).strip()


def _corpus_toc_path() -> Path | None:
    """Locate the promoted book's toc.json (used for title uniqueness).

    Mirrors promote_best_to_productions.py's output resolution exactly:
      1. BOOK_EVOLUTION_OUTPUT_DIR — the standalone CLI's direct output dir
         (toc.json lives at its root).
      2. BOOK_EVOLUTION_OUTPUT_ROOT/files/<contentId>__<slug> — corpus mode.
      3. <project>/output — the promote script's own default.
    No filesystem globbing: the earlier repo-wide fallback scanned whatever
    sat two directories above the project (often $HOME) on every chapter and
    crashed outright on shallow project paths.
    """
    import re
    import uuid

    direct = os.environ.get("BOOK_EVOLUTION_OUTPUT_DIR", "").strip()
    if direct:
        c = Path(direct).expanduser() / "toc.json"
        return c if c.exists() else None

    title = os.environ.get("BOOK_EVOLUTION_TITLE", "Untitled Evolved Book")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    cid = os.environ.get("BOOK_EVOLUTION_CONTENT_ID", "").strip() or str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"book-evolve://{title.lower()}")
    )
    folder = f"{cid}__{slug}"

    env_root = os.environ.get("BOOK_EVOLUTION_OUTPUT_ROOT", "").strip()
    if env_root:
        c = Path(env_root).expanduser() / "files" / folder / "toc.json"
        if c.exists():
            return c
    c = EVOLVE_ROOT / "output" / "toc.json"
    if c.exists():
        return c
    return None


def _write_used_titles(experiment_dir: Path, *, self_chapter_id: str) -> None:
    """Write already-used chapter titles into the experiment dir.

    The researcher template reads this file (via the BOOK_EVOLUTION_USED_TITLES
    env or a sibling used_titles.txt) to avoid cross-chapter title collisions.
    The chapter being promoted (matched by zero-padded number) is excluded so
    a re-run can re-claim its own title.
    """
    import json

    # A stale used_titles.txt from a prior run must not leak into this one.
    stale = experiment_dir / "used_titles.txt"
    stale.unlink(missing_ok=True)

    toc_path = _corpus_toc_path()
    if not toc_path:
        return
    try:
        entries = json.loads(toc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(entries, list):
        return
    titles = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if str(e.get("chapterId")) == str(self_chapter_id):
            continue
        t = (e.get("title") or "").strip()
        if t:
            titles.append(t)
    if not titles:
        return
    out = experiment_dir / "used_titles.txt"
    out.write_text("\n".join(titles) + "\n", encoding="utf-8")
    print(f"  wrote used_titles.txt ({len(titles)} titles) for uniqueness check")


def promote(exp_name: str, chapter_n: int, chapter_title: str | None = None) -> int:
    steps_dir = EXPERIMENTS_DIR / exp_name / "steps"
    env = dict(os.environ)
    env["BOOK_EVOLUTION_CHAPTER_N"] = str(chapter_n)
    env["BOOK_EVOLUTION_STEPS_DIR"] = str(steps_dir)
    if chapter_title and "BOOK_EVOLUTION_CHAPTER_TITLE" not in env:
        env["BOOK_EVOLUTION_CHAPTER_TITLE"] = chapter_title
    cmd = [
        _python(),
        str(EXPERIMENTS_DIR / TEMPLATE / "promote_best_to_productions.py"),
    ]
    return _run(cmd, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Book Evolution service (multi-chapter)"
    )
    parser.add_argument("--start-chapter", type=int, default=1)
    parser.add_argument("--end-chapter", type=int, default=1)
    parser.add_argument(
        "--max-steps", type=int, default=30,
        help="Max evolution steps per chapter before maxing out (default: 30)",
    )
    parser.add_argument(
        "--target-score", type=float, default=0.95,
        help="Stop a chapter early once the best score reaches this (default: 0.95)",
    )
    parser.add_argument(
        "--patience", type=int, default=5,
        help="Stop a chapter after this many no-improvement steps (default: 5)",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Wipe each chapter's prior state before evolving (default: resume)",
    )
    parser.add_argument(
        "--force-provision", action="store_true",
        help="Refresh per-chapter symlinks/copies even if present",
    )
    parser.add_argument(
        "--no-promote", action="store_true",
        help="Evolve only; skip promotion into the files corpus",
    )
    parser.add_argument(
        "--dictation-dir", type=Path, default=None,
        help=(
            "Directory of per-chapter dictation .txt files. When set, the "
            "service re-seeds the cognition store for EACH chapter (chapter N "
            "= Nth file, sorted by name). Without it, the existing cognition "
            "store is used as-is — correct only for single-chapter runs."
        ),
    )
    parser.add_argument(
        "--reference-dir", type=Path, default=None,
        help="Directory of author style reference .txt files (used with --dictation-dir)",
    )
    args = parser.parse_args()

    if args.start_chapter < 1 or args.end_chapter < 1:
        raise SystemExit("chapter numbers must be >= 1")
    if args.end_chapter < args.start_chapter:
        raise SystemExit("--end-chapter must be >= --start-chapter")

    print(
        f"=== Book Evolution Service: chapters {args.start_chapter}.."
        f"{args.end_chapter} (max_steps={args.max_steps}, "
        f"target={args.target_score}, patience={args.patience}) ==="
    )

    if args.dictation_dir is None and args.end_chapter > args.start_chapter:
        print(
            "WARNING: multi-chapter run without --dictation-dir. All chapters "
            "will evolve against whatever dictation is already seeded in the "
            "shared cognition store. Pass --dictation-dir to seed each "
            "chapter correctly.",
            file=sys.stderr,
        )

    for chapter_n in range(args.start_chapter, args.end_chapter + 1):
        print(f"\n########## CHAPTER {chapter_n} ##########")
        _emit(
            "evolve.chapter.start",
            {
                "experiment": f"book_evolution_chapter_{chapter_n:02d}",
                "chapter": chapter_n,
                "end_chapter": args.end_chapter,
            },
        )

        chapter_title: str | None = None
        if args.dictation_dir is not None:
            dictation_dir = args.dictation_dir.expanduser().resolve()
            dictation_files = _txt_files(dictation_dir)
            if chapter_n <= len(dictation_files):
                chapter_title = _title_from_filename(
                    dictation_files[chapter_n - 1]
                )
            seed_chapter(
                chapter_n,
                dictation_dir,
                args.reference_dir.expanduser().resolve()
                if args.reference_dir
                else None,
            )

        exp_name = provision(chapter_n, args.force_provision)

        # Cross-chapter title uniqueness: write the list of titles already used
        # in this book so the researcher template can avoid colliding.
        used_titles_path = EXPERIMENTS_DIR / exp_name / "used_titles.txt"
        _write_used_titles(
            EXPERIMENTS_DIR / exp_name, self_chapter_id=f"{chapter_n:02d}"
        )

        rc = evolve(
            exp_name, chapter_n, args,
            used_titles_path=used_titles_path if used_titles_path.exists() else None,
        )
        if rc != 0:
            print(
                f"Chapter {chapter_n} evolution failed (rc={rc}); stopping service.",
                file=sys.stderr,
            )
            _emit(
                "evolve.chapter.failed",
                {"experiment": exp_name, "chapter": chapter_n, "rc": rc},
            )
            return rc

        if args.no_promote:
            print(f"Chapter {chapter_n} done (promotion skipped).")
            continue

        rc = promote(exp_name, chapter_n, chapter_title)
        if rc != 0:
            print(
                f"Chapter {chapter_n} promotion failed (rc={rc}); stopping service.",
                file=sys.stderr,
            )
            _emit(
                "evolve.chapter.failed",
                {
                    "experiment": exp_name,
                    "chapter": chapter_n,
                    "rc": rc,
                    "stage": "promote",
                },
            )
            return rc
        print(f"Chapter {chapter_n} complete and promoted.")
        _emit(
            "evolve.chapter.promoted",
            {
                "experiment": exp_name,
                "chapter": chapter_n,
                "title": chapter_title or f"Chapter {chapter_n}",
            },
        )

    print(
        f"\n=== Service finished: chapters {args.start_chapter}.."
        f"{args.end_chapter} done. ==="
    )
    _emit(
        "evolve.run.finished",
        {
            "experiment": TEMPLATE,
            "start_chapter": args.start_chapter,
            "end_chapter": args.end_chapter,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
