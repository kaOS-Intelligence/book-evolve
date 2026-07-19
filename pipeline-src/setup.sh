#!/bin/bash
# Book Evolution pipeline bootstrap — creates the Python venv and installs
# dependencies. Run once from the extracted pipeline root.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (3.10+). Install it and re-run." >&2
  exit 1
fi

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip --quiet
echo "Installing dependencies (this can take a few minutes)..."
./.venv/bin/pip install -r requirements.txt --quiet
echo ""
echo "Pipeline ready. Next:"
echo "  1. Configure your model endpoint in experiments/book_evolution/config.yaml"
echo "     (or run a local LiteLLM proxy at 127.0.0.1:4000)"
echo "  2. Drop dictation .txt files into your project's dictation/ folder"
echo "  3. Run: .venv/bin/python3 run_book_evolution_service.py \\"
echo "           --start-chapter 1 --end-chapter 1 \\"
echo "           --dictation-dir ./dictation --reference-dir ./author-style"
