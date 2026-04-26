#!/bin/zsh
cd "$(dirname "$0")"

BOOTSTRAP_PY="/opt/homebrew/bin/python3"

load_shell_environment() {
	# Finder-launched shells are non-interactive; load user env explicitly.
	for shell_file in "$HOME/.zprofile" "$HOME/.zshrc"; do
		if [[ -f "$shell_file" ]]; then
			source "$shell_file"
		fi
	done
}

load_dotenv() {
	local dotenv_file="$(dirname "$0")/.env"
	if [[ ! -f "$dotenv_file" ]]; then
		return 0
	fi
	echo "Loading environment from .env ..."
	while IFS= read -r line || [[ -n "$line" ]]; do
		# Skip blank lines and comments
		[[ -z "$line" || "$line" == \#* ]] && continue
		# Only process KEY=VALUE lines
		if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
			export "$line"
		fi
	done < "$dotenv_file"
}

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

load_shell_environment
load_dotenv

HOST_ARCH="$(/usr/bin/uname -m 2>/dev/null || echo unknown)"
PY_ARCH_LINE="$(/usr/bin/file ./.venv/bin/python 2>/dev/null || true)"

if [[ "$HOST_ARCH" == "arm64" && "$PY_ARCH_LINE" == *"x86_64"* ]]; then
	echo "Detected x86_64 Python in .venv on Apple Silicon (Rosetta)."
	echo "Rebuilding .venv with native arm64 Python..."
	bootstrap_venv
fi

if [[ -z "${ELEVENLABS_API_KEY:-}" ]]; then
	echo "Hint: ELEVENLABS_API_KEY is not set in this shell environment."
fi

if [[ -z "${ELEVENLABS_VOICE_ID:-}" ]]; then
	echo "Hint: ELEVENLABS_VOICE_ID is not set in this shell environment."
fi

./.venv/bin/python webui.py
