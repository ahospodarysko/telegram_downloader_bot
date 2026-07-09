# Telegram Video Downloader Bot

Downloads YouTube and TikTok videos, and extracts MP3 audio from YouTube videos.

## Usage

Send the bot any YouTube or TikTok link — no commands needed.

- **YouTube** → pick 720p, 1080p, or MP3 (audio only)
- **TikTok** → downloaded automatically in the best available quality

Telegram bots can only upload files up to **50 MB**; larger downloads are rejected
with a message suggesting a lower quality.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg   # required for merging streams and MP3 extraction

export TELEGRAM_BOT_TOKEN="<your token from @BotFather>"
python3 bot.py
```

## Notes

- The bot token is read from the `TELEGRAM_BOT_TOKEN` environment variable —
  never commit it to source code.
- Downloads happen in per-request temp folders under `downloads/` and are
  deleted after the file is sent.
