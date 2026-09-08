from unittest.mock import AsyncMock

import pytest

import bot


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def test_strip_query_removes_trackers():
    url = "https://www.tiktok.com/@user/video/123?is_from_webapp=1&sender_device=pc"
    assert bot._strip_query(url) == "https://www.tiktok.com/@user/video/123"


def test_strip_query_no_query_is_unchanged():
    url = "https://youtu.be/abc123"
    assert bot._strip_query(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123?si=xyz",
        "https://m.youtube.com/watch?v=abc123",
        "https://music.youtube.com/watch?v=abc123",
    ],
)
def test_youtube_regex_matches(url):
    assert bot.YOUTUBE_RE.search(url)


@pytest.mark.parametrize(
    "text",
    ["https://www.tiktok.com/@user/video/123", "just some text", "https://vimeo.com/123"],
)
def test_youtube_regex_does_not_match(text):
    assert bot.YOUTUBE_RE.search(text) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@user/video/123",
        "https://vm.tiktok.com/ZMabcdef/",
    ],
)
def test_tiktok_regex_matches(url):
    assert bot.TIKTOK_RE.search(url)


def test_tiktok_regex_does_not_match_youtube():
    assert bot.TIKTOK_RE.search("https://youtu.be/abc123") is None


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def test_available_heights_ignores_formats_without_height():
    info = {"formats": [{"height": 720}, {"height": None}, {}, {"height": 1080}]}
    assert bot.available_heights(info) == {720, 1080}


def test_available_heights_empty_when_no_formats():
    assert bot.available_heights({}) == set()


# ---------------------------------------------------------------------------
# _base_opts
# ---------------------------------------------------------------------------

def test_base_opts_without_cookies_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "COOKIES_FILE", tmp_path / "missing.txt")
    opts = bot._base_opts(tmp_path)
    assert "cookiefile" not in opts
    assert opts["noplaylist"] is True


def test_base_opts_with_cookies_file(tmp_path, monkeypatch):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("cookie data")
    monkeypatch.setattr(bot, "COOKIES_FILE", cookies_file)
    opts = bot._base_opts(tmp_path)
    assert opts["cookiefile"] == str(cookies_file)


# ---------------------------------------------------------------------------
# _finished_file
# ---------------------------------------------------------------------------

def test_finished_file_prefers_requested_downloads(tmp_path):
    wanted = tmp_path / "video.mp4"
    wanted.write_bytes(b"data")
    other = tmp_path / "other.mp4"
    other.write_bytes(b"more data than the wanted file")

    info = {"requested_downloads": [{"filepath": str(wanted)}]}
    assert bot._finished_file(info, tmp_path) == wanted


def test_finished_file_falls_back_to_largest_file(tmp_path):
    small = tmp_path / "small.part"
    small.write_bytes(b"x")
    large = tmp_path / "large.mp4"
    large.write_bytes(b"x" * 100)

    assert bot._finished_file({}, tmp_path) == large


def test_finished_file_raises_when_dir_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        bot._finished_file({}, tmp_path)


# ---------------------------------------------------------------------------
# download_video format selection (yt_dlp itself is mocked out)
# ---------------------------------------------------------------------------

class FakeYoutubeDL:
    captured_opts: dict = {}

    def __init__(self, opts):
        FakeYoutubeDL.captured_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download):
        return {"requested_downloads": []}


def test_download_video_caps_height_when_requested(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(bot, "_finished_file", lambda info, job_dir: tmp_path / "out.mp4")

    bot.download_video("https://youtu.be/abc", tmp_path, max_height=720)

    assert "height<=720" in FakeYoutubeDL.captured_opts["format"]


def test_download_video_uses_best_when_no_height_given(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(bot, "_finished_file", lambda info, job_dir: tmp_path / "out.mp4")

    bot.download_video("https://youtu.be/abc", tmp_path, max_height=None)

    assert "height" not in FakeYoutubeDL.captured_opts["format"]


def test_download_mp3_sets_ffmpeg_extract_audio_postprocessor(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(bot, "_finished_file", lambda info, job_dir: tmp_path / "out.mp3")

    bot.download_mp3("https://youtu.be/abc", tmp_path)

    postprocessors = FakeYoutubeDL.captured_opts["postprocessors"]
    assert postprocessors[0]["key"] == "FFmpegExtractAudio"
    assert postprocessors[0]["preferredcodec"] == "mp3"


# ---------------------------------------------------------------------------
# handle_message routing
# ---------------------------------------------------------------------------

async def test_handle_message_routes_tiktok_to_deliver(monkeypatch):
    deliver_mock = AsyncMock()
    monkeypatch.setattr(bot, "deliver", deliver_mock)

    update = AsyncMock()
    update.message.text = "check this out https://www.tiktok.com/@user/video/123?x=1"
    context = AsyncMock()

    await bot.handle_message(update, context)

    deliver_mock.assert_awaited_once()
    args, kwargs = deliver_mock.call_args
    assert args[1] == "https://www.tiktok.com/@user/video/123"
    assert kwargs == {"kind": "video"}


async def test_handle_message_routes_youtube_to_quality_prompt(monkeypatch):
    ask_mock = AsyncMock()
    monkeypatch.setattr(bot, "ask_youtube_quality", ask_mock)

    update = AsyncMock()
    update.message.text = "https://youtu.be/abc123"
    context = AsyncMock()

    await bot.handle_message(update, context)

    ask_mock.assert_awaited_once_with(update.message, context, "https://youtu.be/abc123")


async def test_handle_message_replies_when_no_link_found():
    update = AsyncMock()
    update.message.text = "hello there"
    context = AsyncMock()

    await bot.handle_message(update, context)

    update.message.reply_text.assert_awaited_once()
    assert "doesn't look like" in update.message.reply_text.call_args.args[0]
