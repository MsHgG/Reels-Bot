#!/usr/bin/env python3
"""
Telegram bot: send it a YouTube or Instagram (reel/post) link, it downloads
the video and sends it back.

Config (environment variables):
  BOT_TOKEN        - required, token from @BotFather (keep it secret!)
  ALLOWED_USER_ID  - optional, your Telegram numeric user ID. If set, only
                     this user can use the bot. Get it from @userinfobot.
  MAX_DURATION     - optional, max video length in seconds (default 1200).
  COOKIES_FILE     - optional, path to a cookies.txt for sites that block
                     datacenter IPs (mainly Instagram).
  PORT             - port for the tiny health web server (default 10000).
                     Render sets this automatically.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import yt_dlp
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("reels-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "").strip()
MAX_DURATION = int(os.environ.get("MAX_DURATION", "1200"))
COOKIES_FILE = os.environ.get("COOKIES_FILE", "").strip() or None

# Telegram bots can upload up to 50 MB. Keep a safety margin.
TG_LIMIT = 49 * 1024 * 1024

URL_RE = re.compile(r"https?://[^\s]+")

SUPPORTED_HINTS = (
    "youtube.com", "youtu.be", "instagram.com",
)


def extract_url(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return m.group(0) if m else None


def is_allowed(update: Update) -> bool:
    if not ALLOWED_USER_ID:
        return True
    user = update.effective_user
    return bool(user) and str(user.id) == ALLOWED_USER_ID


def base_ydl_opts(outtmpl: str) -> dict:
    opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "retries": 3,
        "socket_timeout": 30,
        "restrictfilenames": True,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def download_video(url: str, workdir: str) -> tuple[str | None, str | None]:
    """Download with yt-dlp, trying smaller formats if the file is too big.
    Returns (file_path, error_message)."""
    attempts = [
        "bv*+ba/b",                                   # best quality
        "bv*[height<=720]+ba/b[height<=720]",          # 720p
        "bv*[height<=480]+ba/b[height<=480]/w",        # 480p or worst
    ]
    last_err = None
    for fmt in attempts:
        for f in os.listdir(workdir):
            os.remove(os.path.join(workdir, f))
        opts = base_ydl_opts(os.path.join(workdir, "%(title).60s.%(ext)s"))
        opts["format"] = fmt
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                duration = info.get("duration") or 0
                if duration and duration > MAX_DURATION:
                    return None, f"too_long:{duration}"
                ydl.download([url])
            files = [f for f in os.listdir(workdir) if not f.endswith(".part")]
            if not files:
                last_err = "empty_download"
                continue
            path = os.path.join(workdir, files[0])
            size = os.path.getsize(path)
            log.info("Downloaded %s (%.1f MB) with format %s", path, size / 1e6, fmt)
            if size <= TG_LIMIT:
                return path, None
            # Too big: try to compress with ffmpeg
            compressed = compress_video(path, workdir)
            if compressed and os.path.getsize(compressed) <= TG_LIMIT:
                return compressed, None
            last_err = f"too_big:{size}"
            # try a smaller format on the next attempt
        except Exception as e:  # yt-dlp raises many exception types
            log.warning("yt-dlp attempt failed (%s): %s", fmt, e)
            last_err = str(e)[:300]
    return None, last_err or "unknown"


def compress_video(src: str, workdir: str) -> str | None:
    """Re-encode targeting ~45 MB. Returns path or None."""
    try:
        dur = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", src]).strip())
        target_bits = 45 * 1024 * 1024 * 8
        audio_bits = 96_000
        video_bitrate = max(int(target_bits / dur) - audio_bits, 150_000)
        dst = os.path.join(workdir, "compressed.mp4")
        subprocess.check_call([
            "ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", str(video_bitrate), "-c:a", "aac", "-b:a", "96k", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return dst if os.path.exists(dst) else None
    except Exception as e:
        log.warning("compression failed: %s", e)
        return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "أهلا! صيفط ليا رابط ديال فيديو من يوتيوب ولا إنستغرام (ريل) "
        "ونرجعو ليك هنا.\n\n"
        "Send me a YouTube or Instagram link and I'll send back the video."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return
    if not is_allowed(update):
        await msg.reply_text("هاد البوت خاص. This bot is private.")
        return
    url = extract_url(msg.text)
    if not url:
        await msg.reply_text("ما لقيتش رابط فالمساج. صيفط رابط ديال فيديو.")
        return
    if not any(h in url for h in SUPPORTED_HINTS):
        await msg.reply_text(
            "هاد الموقع مازال ما مدعومش. جرب رابط يوتيوب ولا إنستغرام.")
        return

    await msg.chat.send_action(ChatAction.UPLOAD_VIDEO)
    status = await msg.reply_text("كنحمل الفيديو... ⏳")
    workdir = tempfile.mkdtemp(prefix="dl_")
    try:
        path, err = await asyncio.get_running_loop().run_in_executor(
            None, download_video, url, workdir)
        if err:
            if err.startswith("too_long"):
                secs = int(err.split(":")[1])
                await status.edit_text(
                    f"الفيديو طويل بزاف ({secs // 60} دقيقة). "
                    f"الحد هو {MAX_DURATION // 60} دقيقة.")
            elif err.startswith("too_big"):
                await status.edit_text(
                    "الفيديو كبير بزاف حتى بعد الضغط (تيليغرام كيسمح غير "
                    "بـ 50 ميغا للبوتات). جرب فيديو أقصر ولا بجودة أقل.")
            else:
                await status.edit_text(
                    "ما قدرتش نحمل الفيديو. السبب المحتمل: الموقع بلوكا "
                    "السيرفر ولا الرابط خاص. جرب رابط آخر.\n"
                    f"({err[:150]})")
            return
        size_mb = os.path.getsize(path) / 1e6
        await status.edit_text(f"وجد ({size_mb:.1f} MB)، كنصيفط... 📤")
        with open(path, "rb") as fh:
            await msg.reply_video(
                video=fh, supports_streaming=True,
                caption="✅ ها هو الفيديو")
        await status.delete()
    except Exception as e:
        log.exception("send failed")
        try:
            await status.edit_text(f"وقع خطأ فالإرسال: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def run_health_server() -> None:
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info("health server on port %d", port)
    server.serve_forever()


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Put it in the environment or a .env file.")
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("bot starting (polling)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
