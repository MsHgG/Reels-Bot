# Telegram Reels/YouTube Downloader Bot

Send the bot a YouTube or Instagram link; it downloads the video and sends
it back to you in Telegram.

## Features
- YouTube and Instagram (reels/posts) via yt-dlp
- Automatic quality fallback + ffmpeg compression to fit Telegram's 50 MB
  bot upload limit
- Optional allow-list (`ALLOWED_USER_ID`) so only you can use it
- Optional cookies file for Instagram (`COOKIES_FILE`)
- Tiny health HTTP server so it can run as a free web service (Render)
- Max duration guard (`MAX_DURATION`, default 20 minutes)

## Run locally
```bash
pip install -r requirements.txt
# ffmpeg must be installed (apt install ffmpeg / brew install ffmpeg)
export BOT_TOKEN="your-token"
export ALLOWED_USER_ID="123456789"   # optional
python bot.py
```

## Run with Docker
```bash
docker build -t reels-bot .
docker run -e BOT_TOKEN="your-token" -e ALLOWED_USER_ID="123456789" reels-bot
```

## Free hosting
See the Arabic guide (dalil_bot.pdf / .docx). Short version:
1. Create the bot with @BotFather, keep the token secret.
2. Push this folder to a GitHub repo.
3. On Render.com (free, no credit card): New > Web Service > pick the repo
   (it uses the Dockerfile) > Free plan > add env vars BOT_TOKEN and
   ALLOWED_USER_ID.
4. Free services sleep after 15 idle minutes: create a free monitor on
   cron-job.org that requests https://YOUR-SERVICE.onrender.com every
   10 minutes to keep it awake.
5. Message your bot with a video link.

## Updating yt-dlp
Sites change often. Redeploying on Render rebuilds the image and installs
the latest yt-dlp automatically (Manual Deploy > Clear build cache & deploy).

## Honest limits
- Instagram often blocks datacenter IPs; YouTube sometimes does too. If a
  download fails with a block/login error, add a `cookies.txt` exported
  from your own browser and set `COOKIES_FILE` (personal use only).
- Downloading videos may violate the platforms' Terms of Service. This bot
  is meant for your own personal use.
- Telegram limits bot uploads to 50 MB; longer/bigger videos are compressed
  or refused with a message.
