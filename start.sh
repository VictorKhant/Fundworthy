#!/usr/bin/env bash
# One command to run the whole thing. (docs/PLAN.md §1)
#
# This is the file that decides whether RISE can still use this in a month. Everything
# it does is something a person would otherwise have to be told to do in the right
# order, and getting told wrong once is how a handed-over project dies.
#
#   ./start.sh              build the dashboard if needed, then serve on :8000
#   ./start.sh --dev        also run the Vite dev server on :5173 with hot reload
#   ./start.sh --rebuild    force a fresh dashboard build
set -euo pipefail

cd "$(dirname "$0")"

PORT="${RISE_PORT:-8000}"
DEV=0
REBUILD=0
for arg in "$@"; do
  case "$arg" in
    --dev)     DEV=1 ;;
    --rebuild) REBUILD=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

# --- python ------------------------------------------------------------------
if [ ! -d .venv ]; then
  echo "→ Creating the Python environment (once)…"
  python3 -m venv .venv
fi
PY=.venv/bin/python

if ! $PY -c "import fastapi, uvicorn, cryptography" >/dev/null 2>&1; then
  echo "→ Installing Python dependencies (once)…"
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

# --- dashboard ---------------------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  if [ ! -d dashboard/node_modules ]; then
    echo "→ Installing dashboard dependencies (once)…"
    (cd dashboard && npm install --silent)
  fi
  if [ ! -d dashboard/dist ] || [ "$REBUILD" = "1" ]; then
    echo "→ Building the dashboard…"
    (cd dashboard && npm run build --silent)
  fi
else
  echo "⚠ npm was not found, so the dashboard cannot be built."
  echo "  The API will still start; install Node.js and re-run to get the page."
fi

if [ "$DEV" = "1" ]; then
  (cd dashboard && npm run dev) &
  VITE_PID=$!
  # Without this, closing the script leaves an orphaned Vite holding port 5173 —
  # and the next ./start.sh --dev fails for a reason nobody would guess.
  trap 'kill $VITE_PID 2>/dev/null || true' EXIT
  echo "→ Dev server with hot reload: http://localhost:5173"
fi

echo
echo "  RISE Fund Finder → http://localhost:${PORT}"
echo "  Stop it with Ctrl-C. Nothing is exposed to the internet."
echo
exec $PY -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
