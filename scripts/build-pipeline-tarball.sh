#!/bin/bash
# Build the embedded pipeline tarball for @kaos-intelligence/book-evolve.
#
# The pipeline source is vendored, pre-sanitized, at packages/book-evolve/
# pipeline-src/ — the single source of truth for what ships. No runtime
# rewriting or regex surgery happens here; if a file needs to change, change
# it in pipeline-src/ and rebuild.
#
# Gates (the build FAILS if any trips):
#   1. Python compile gate  — every .py must byte-compile (a shipped
#      SyntaxError killed v1.1.0; never again).
#   2. Content-safety gate  — no personal or Sovereign-internal content.
#   3. Cache gate           — no __pycache__/.pyc/seeded cognition ships.
#
# Usage: ./build-pipeline-tarball.sh   (from anywhere)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$PKG_DIR/pipeline-src"
OUT="$PKG_DIR/assets/pipeline/pipeline.tar.gz"

if [ ! -d "$SRC" ]; then
  echo "FATAL: pipeline source not found at $SRC" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "Staging pipeline from $SRC"
rsync -a \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'cognition.json' \
  --exclude 'faiss' \
  --exclude 'steps' \
  --exclude 'logs' \
  --exclude 'database_data' \
  --exclude 'pipeline_state.json' \
  "$SRC/" "$STAGE/"

chmod +x "$STAGE/setup.sh" \
  "$STAGE/experiments/seed_chapter_cognition.sh" \
  "$STAGE/experiments/book_evolution/eval.sh" 2>/dev/null || true

# ── Gate 1: every Python file must compile ───────────────────────────────
echo "Compile gate: byte-compiling every .py in the stage..."
if ! python3 -m compileall -q "$STAGE"; then
  echo "FATAL: Python compile errors in staged pipeline — fix pipeline-src/." >&2
  exit 1
fi
# compileall writes __pycache__; strip before packaging.
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# ── Gate 2: refuse to ship personal/internal content ─────────────────────
echo "Content-safety gate: scanning for personal or internal references..."
LEAKS=$(grep -rIl \
  -e "Angela Doll" \
  -e "Blessing of Now" \
  -e "Garden in the East" \
  -e "kaleeghainsworth" \
  -e "Kaleeg" \
  -e "Hainsworth" \
  -e "Malaika" \
  -e "malaika" \
  -e "SOUL.md" \
  -e "MEMORY.md" \
  -e "USER.md" \
  -e "WRITING-STYLE.md" \
  -e "family.yaml" \
  -e "X-Malaika-Broker-Key" \
  -e "SOVEREIGN_CORPUS" \
  -e "sovereign-corpus" \
  "$STAGE" 2>/dev/null || true)
if [ -n "$LEAKS" ]; then
  echo "FATAL: personal or Sovereign-internal content detected:" >&2
  echo "$LEAKS" >&2
  exit 1
fi

# ── Gate 3: no caches or seeded data ─────────────────────────────────────
if find "$STAGE" \( -name '__pycache__' -o -name '*.pyc' -o -name 'cognition.json' \) | grep -q .; then
  echo "FATAL: caches or seeded cognition detected in staged tarball." >&2
  exit 1
fi

# ── Package ──────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$OUT")"
tar -czf "$OUT" -C "$STAGE" .
SIZE=$(du -h "$OUT" | cut -f1)
COUNT=$(tar -tzf "$OUT" | wc -l | tr -d ' ')
echo "Built $OUT ($SIZE, $COUNT entries)"
echo ""
echo "Sanity check — engine present:"
tar -tzf "$OUT" | grep -E "^\./(pipeline/main.py|__init__.py|requirements.txt|setup.sh|run_book_evolution_service.py|litellm_client.py)$" || {
  echo "FATAL: engine files missing from tarball." >&2
  exit 1
}
echo "OK"
