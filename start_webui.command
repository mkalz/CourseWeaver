#!/bin/zsh
cd "$(dirname "$0")"

BOOTSTRAP_PY="/opt/homebrew/bin/python3"

bootstrap_venv() {
	if [[ ! -x "$BOOTSTRAP_PY" ]]; then
		echo "Native Homebrew Python not found at $BOOTSTRAP_PY"
		echo "Install it first, then run:"
		echo "  $BOOTSTRAP_PY -m venv .venv"
		echo "  ./.venv/bin/python -m pip install -r requirements.txt"
		exit 1
	fi

	echo "Creating native Python environment..."
	rm -rf .venv
	"$BOOTSTRAP_PY" -m venv .venv || exit 1
	./.venv/bin/python -m pip install --upgrade pip || exit 1
	./.venv/bin/python -m pip install -r requirements.txt || exit 1
}

if [[ ! -x ./.venv/bin/python ]]; then
	bootstrap_venv
fi

HOST_ARCH="$(/usr/bin/uname -m 2>/dev/null || echo unknown)"
PY_ARCH_LINE="$(/usr/bin/file ./.venv/bin/python 2>/dev/null || true)"

if [[ "$HOST_ARCH" == "arm64" && "$PY_ARCH_LINE" == *"x86_64"* ]]; then
	echo "Detected x86_64 Python in .venv on Apple Silicon (Rosetta)."
	echo "Rebuilding .venv with native arm64 Python..."
	bootstrap_venv
fi

./.venv/bin/python webui.py
