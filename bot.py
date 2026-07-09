"""Telegram bot that downloads YouTube / TikTok videos and extracts MP3 audio from YouTube.

Usage:
    export TELEGRAM_BOT_TOKEN="123456:ABC..."
    python3 bot.py

Just send the bot a YouTube or TikTok link — no commands needed.
Requires ffmpeg on PATH (brew install ffmpeg).
"""

import asyncio
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_FILE_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MB bot upload limit
DOWNLOAD_DIR = Path(__file__).resolve().parent / "downloads"

YOUTUBE_RE = re.compile(
    r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+", re.IGNORECASE
)
TIKTOK_RE = re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.IGNORECASE)

HELP_TEXT = (
    "Send me a YouTube or TikTok link and I'll download it for you.\n\n"
    "• YouTube: choose 720p, 1080p, or MP3 (audio only)\n"
    "• TikTok: downloaded automatically in the best quality\n\n"
    "Note: Telegram bots can only send files up to 50 MB."
)


# ---------------------------------------------------------------------------
# yt-dlp helpers (blocking — always call through asyncio.to_thread)
# ---------------------------------------------------------------------------

def _strip_query(url: str) -> str:
    """Drop query params from share links (TikTok links carry long trackers)."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _base_opts(job_dir: Path) -> dict:
    return {
        "outtmpl": str(job_dir / "%(title).80s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "nocheckcertificate": True,
    }


def probe_video(url: str) -> dict:
    """Fetch metadata (title, available formats) without downloading."""
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)


def available_heights(info: dict) -> set[int]:
    return {f["height"] for f in info.get("formats", []) if f.get("height")}


def _finished_file(info: dict, job_dir: Path) -> Path:
    """Resolve the final output file after any merging/post-processing."""
    downloads = info.get("requested_downloads") or []
    if downloads and downloads[0].get("filepath"):
        path = Path(downloads[0]["filepath"])
        if path.exists():
            return path
    # Fallback: the job dir contains only this download's output.
    files = [p for p in job_dir.iterdir() if p.is_file()]
    if not files:
        raise FileNotFoundError(f"No output file produced in {job_dir}")
    return max(files, key=lambda p: p.stat().st_size)


def download_video(url: str, job_dir: Path, max_height: int | None = None) -> tuple[Path, dict]:
    """Download best mp4 video+audio, merging streams if needed.

    Prefers H.264 (avc1): Telegram's in-app player can't decode the AV1/VP9
    streams YouTube serves for many videos, which plays as a black screen.
    """
    if max_height:
        fmt = (
            f"bestvideo[height<={max_height}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio"
            f"/bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/best[height<={max_height}][ext=mp4][vcodec^=avc1]"
            f"/best[height<={max_height}]/best"
        )
    else:
        fmt = "best[ext=mp4][vcodec^=avc1]/best[ext=mp4]/best"
    opts = _base_opts(job_dir) | {
        "format": fmt,
        "merge_output_format": "mp4",
        # moov atom up front so Telegram can stream-play before full download
        "postprocessor_args": {"merger": ["-movflags", "+faststart"]},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return _finished_file(info, job_dir), info


def download_mp3(url: str, job_dir: Path) -> Path:
    opts = _base_opts(job_dir) | {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return _finished_file(info, job_dir)


# ---------------------------------------------------------------------------
# Download + send pipeline
# ---------------------------------------------------------------------------

async def deliver(message: Message, url: str, kind: str, max_height: int | None = None) -> None:
    """Download the requested media and send it back, cleaning up afterwards."""
    job_dir = DOWNLOAD_DIR / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)
    status = await message.reply_text(
        "Downloading MP3 audio…" if kind == "mp3" else "Downloading video…"
    )
    try:
        info: dict = {}
        if kind == "mp3":
            path = await asyncio.to_thread(download_mp3, url, job_dir)
        else:
            path, info = await asyncio.to_thread(download_video, url, job_dir, max_height)

        size = path.stat().st_size
        if size > TELEGRAM_FILE_SIZE_LIMIT:
            await status.edit_text(
                f"The file is {size / 1024 / 1024:.0f} MB, above Telegram's 50 MB bot "
                "limit. Try a lower quality or a shorter video."
            )
            return

        await status.edit_text("Uploading to Telegram…")
        with open(path, "rb") as fh:
            if kind == "mp3":
                await message.reply_audio(audio=fh, title=path.stem)
            else:
                # Width/height/duration let Telegram build the player and
                # preview correctly instead of showing a black frame.
                await message.reply_video(
                    video=fh,
                    supports_streaming=True,
                    width=info.get("width"),
                    height=info.get("height"),
                    duration=int(info["duration"]) if info.get("duration") else None,
                )
        await status.delete()
    except yt_dlp.utils.DownloadError as exc:
        logger.error("Download failed for %s: %s", url, exc)
        await status.edit_text(
            "Download failed. The video may be private, region-locked, or removed."
        )
    except Exception:
        logger.exception("Unexpected error handling %s", url)
        await status.edit_text("Something went wrong. Please try again.")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""

    if match := TIKTOK_RE.search(text):
        await deliver(update.message, _strip_query(match.group(0)), kind="video")
        return

    if match := YOUTUBE_RE.search(text):
        await ask_youtube_quality(update.message, context, match.group(0))
        return

    await update.message.reply_text(
        "That doesn't look like a YouTube or TikTok link.\n\n" + HELP_TEXT
    )


async def ask_youtube_quality(
    message: Message, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    status = await message.reply_text("Checking available formats…")
    try:
        info = await asyncio.to_thread(probe_video, url)
    except yt_dlp.utils.DownloadError as exc:
        logger.error("Probe failed for %s: %s", url, exc)
        await status.edit_text(
            "Couldn't read that video. It may be private, region-locked, or removed."
        )
        return

    heights = available_heights(info)
    video_buttons = []
    if any(h >= 720 for h in heights):
        video_buttons.append(InlineKeyboardButton("720p", callback_data="dl:720"))
    if any(h >= 1080 for h in heights):
        video_buttons.append(InlineKeyboardButton("1080p", callback_data="dl:1080"))
    if not video_buttons:
        # No HD versions — offer whatever resolutions the video does have.
        video_buttons = [
            InlineKeyboardButton(f"{h}p", callback_data=f"dl:{h}")
            for h in sorted(heights, reverse=True)[:4]
        ]

    keyboard = [video_buttons] if video_buttons else []
    keyboard.append([InlineKeyboardButton("MP3 (audio only)", callback_data="dl:mp3")])

    title = info.get("title", "video")
    text = f"“{title}”\nChoose a format:"
    if video_buttons and not any(h >= 720 for h in heights):
        text = f"“{title}”\nNo HD version available — these formats exist:"
    await status.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # Key the URL by the message carrying the buttons, so several pending
    # links from the same user can't get mixed up. Keep only the newest few.
    pending = context.user_data.setdefault("pending", {})
    pending[status.message_id] = url
    while len(pending) > 10:
        pending.pop(next(iter(pending)))


async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    message = query.message
    if not isinstance(message, Message):  # message too old for Telegram to resolve
        await query.answer()
        return

    # .get, not .pop — the buttons stay usable so the user can grab the same
    # link again in another format (e.g. 720p first, then MP3).
    url = context.user_data.get("pending", {}).get(message.message_id)
    if not url:
        await query.answer()
        await query.edit_message_text("That request expired — please send the link again.")
        return

    choice = query.data.removeprefix("dl:")

    # Ignore repeat taps on a format that is already downloading.
    active = context.user_data.setdefault("active", set())
    key = (message.message_id, choice)
    if key in active:
        await query.answer("Already downloading that format — hang tight.")
        return
    await query.answer()

    active.add(key)
    try:
        if choice == "mp3":
            await deliver(message, url, kind="mp3")
        else:
            await deliver(message, url, kind="video", max_height=int(choice))
    finally:
        active.discard(key)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log update-processing and network errors without a full traceback spam."""
    logger.error("Error while handling update: %s", context.error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set.\n"
            'Run: export TELEGRAM_BOT_TOKEN="<your token from @BotFather>"'
        )

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    application = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(120)
        .write_timeout(300)  # uploads close to 50 MB need generous write timeouts
        .build()
    )

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CallbackQueryHandler(handle_quality_choice, pattern=r"^dl:(\d+|mp3)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(on_error)

    logger.info("Bot started, polling for updates…")
    application.run_polling()


if __name__ == "__main__":
    main()
