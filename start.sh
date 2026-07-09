#!/usr/bin/env bash
# Start the Telegram downloader bot.
# Usage: ./start.sh
# Put your token in a .env file next to this script (see .env.example),
# or export TELEGRAM_BOT_TOKEN before running.
set -euo pipefail
cd "$(dirname "$0")"

# Load token (and any other vars) from .env if present
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo "Error: TELEGRAM_BOT_TOKEN is not set." >&2
    echo "Create a .env file with:  TELEGRAM_BOT_TOKEN=\"<token from @BotFather>\"" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Error: ffmpeg not found. Install it with:  brew install ffmpeg" >&2
    exit 1
fi

# Create the venv and install dependencies on first run
if [[ ! -x .venv/bin/python ]]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

echo "Starting bot (Ctrl+C to stop)..."
exec .venv/bin/python bot.py
