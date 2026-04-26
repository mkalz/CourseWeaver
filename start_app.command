#!/bin/zsh
# start_app.command – macOS launcher for the CourseBeaver FastAPI application.
# Double-click in Finder to start.
cd "$(dirname "$0")"

BOOTSTRAP_PY="/opt/homebrew/bin/python3"

# ── Load environment ──────────────────────────────────────────────────────────
for shell_file in "$HOME/.zprofile" "$HOME/.zshrc"; do
  [[ -f "$shell_file" ]] && source "$shell_file"
done

# Load .env file if present.
if [[ -f ".env" ]]; then
  echo "Loading environment from .env ..."
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && export "$line"
  done < ".env"
fi

# ── Bootstrap venv if needed ──────────────────────────────────────────────────
if [[ ! -x ./.venv/bin/python ]]; then
  echo "Creating Python environment..."
  "$BOOTSTRAP_PY" -m venv .venv || exit 1
  ./.venv/bin/python -m pip install --upgrade pip || exit 1
  ./.venv/bin/python -m pip install -r requirements-app.txt || exit 1
fi

# ── Check for Ollama ─────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo "Hint: Ollama not found. Install from https://ollama.ai and run:"
  echo "  ollama pull qwen2.5:14b"
fi

echo ""
echo "Starting CourseBeaver API on http://127.0.0.1:8766"
echo "API docs: http://127.0.0.1:8766/docs"
echo ""
./.venv/bin/python -m app.main
