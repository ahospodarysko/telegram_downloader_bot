# Telegram Video Downloader Bot

Downloads YouTube and TikTok videos, and extracts MP3 audio from YouTube videos.

## Usage

Send the bot any YouTube or TikTok link — no commands needed.

- **YouTube** → pick 720p, 1080p, or MP3 (audio only)
- **TikTok** → downloaded automatically in the best available quality

The format buttons stay active after a download, so you can grab the same link
in another quality (or as MP3) without re-sending it. Tapping a format that is
already downloading is ignored — no duplicate downloads.

Videos are delivered as H.264 MP4 with streaming metadata, so they play
directly in Telegram's in-app player (no black screen, no need to download
the file first).

Telegram bots can only upload files up to **50 MB**; larger downloads are rejected
with a message suggesting a lower quality.

## Setup

```bash
brew install ffmpeg   # required for merging streams and MP3 extraction
cp .env.example .env  # then paste your token from @BotFather
./start.sh            # creates the venv, installs deps, starts the bot
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="<your token from @BotFather>"
python3 bot.py
```

## Notes

- The bot token is read from a gitignored `.env` file (or the
  `TELEGRAM_BOT_TOKEN` environment variable) — never commit it to source code.
- Downloads happen in per-request temp folders under `downloads/` and are
  deleted after the file is sent.
- YouTube downloads prefer H.264 (`avc1`) streams; AV1/VP9 renders as a black
  screen in Telegram's in-app player on most devices.

## License

[MIT](LICENSE)
