# AGENTS.md

This file provides essential context for AI coding agents working on this repository.

## Project Overview

This is a **Telegram Video & Image Downloader Bot** written in Python. It runs as a single-file async bot (`main.py`) and downloads content from YouTube, Instagram, TikTok, Facebook, Twitter/X, Reddit, and 1000+ other platforms via yt-dlp. The bot is containerized with Docker Compose for easy VPS deployment.

The bot uses **polling** (not webhooks) to receive updates from Telegram. All user-facing documentation is written in Spanish, while code comments are in English.

## Technology Stack

- **Python 3.11** (base runtime)
- **Aiogram 3.15.0** — async Telegram Bot API framework
- **yt-dlp** — universal video/audio downloader (frequently requires updates)
- **gallery-dl** — image/gallery downloader for Instagram/Facebook posts
- **facebook-scraper** — dedicated Facebook post scraper (uses m.facebook.com)
- **Selenium 4.26+** + **Chromium** — headless browser for Facebook image scraping
- **BeautifulSoup4 + lxml** — HTML parsing for scraped content
- **FFmpeg** — audio extraction (MP3) and video compression
- **aiofiles 24.1.0, aiohttp 3.10.11** — async file and HTTP I/O
- **python-dotenv 1.0.1** — environment variable loading
- **Cobalt API** — fallback video downloader (runs as a separate Docker service)

## Project Structure

```
chinabici/
├── main.py                 # Entire bot implementation (~1175 lines, single file)
├── requirements.txt        # Python dependencies
├── Dockerfile              # Bot container image (python:3.11-slim + ffmpeg + chromium)
├── docker-compose.yml      # Orchestrates bot + cobalt-api + watchtower services
├── deploy.sh               # One-command deploy script for VPS
├── start.sh                # Local startup script (activates venv)
├── .env                    # BOT_TOKEN and optional COBALT_URL (not in git)
├── .env.example            # Template for required env vars
├── cookies.txt             # Optional YouTube cookies (bypasses bot detection)
├── downloads/              # Temporary video/image storage (mounted volume, auto-cleaned)
├── logs/bot.log            # Application logs (mounted volume)
├── test_fb_images.py       # Standalone test script for Facebook/Instagram scraping
├── test_urls.txt           # Sample URLs for manual testing
├── README.md               # Spanish user-facing README
├── DEPLOY.md               # Spanish VPS deployment guide
├── COMO_FUNCIONA.md        # Spanish technical explanation
├── MP3_MP4_GUIDE.md        # Spanish format selection guide
├── YOUTUBE_GUIDE.md        # Spanish YouTube usage guide
└── CLAUDE.md               # English agent guide (legacy, may have inaccuracies)
```

## Build & Run Commands

### Local Development

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate   # start.sh also tries 'china/bin/activate'

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set BOT_TOKEN=your_token_from_botfather

# Run bot
python main.py
```

### Docker (Production / Recommended)

```bash
# Quick deploy (builds from scratch, no cache)
chmod +x deploy.sh
./deploy.sh

# Manual Docker Compose commands
docker-compose up -d               # Start all services
docker-compose logs -f             # Follow logs
docker-compose restart             # Restart bot
docker-compose down                # Stop all services
docker-compose build --no-cache    # Rebuild image
docker-compose exec bot bash       # Enter running container

# Update yt-dlp without rebuild (platform APIs change often)
docker-compose exec bot pip install -U yt-dlp
docker-compose restart
```

## Architecture

### Single-File Design

The entire bot lives in `main.py`. There is no package/module split. All handlers, scrapers, downloaders, and utilities are defined in this one file.

### Docker Compose Services

1. **`bot`** (built from Dockerfile)
   - Runs `python -u main.py`
   - Mounts `./downloads` and `./logs` as volumes
   - Depends on `cobalt-api`
   - Environment: `BOT_TOKEN`, `COBALT_URL=http://cobalt-api:9000`, `TZ=America/New_York`
   - Log rotation: 10MB × 3 files

2. **`cobalt-api`** (`ghcr.io/imputnet/cobalt:10`)
   - Internal fallback downloader for videos
   - Exposes port 9000 on internal Docker network only
   - Read-only filesystem with `init: true`

3. **`watchtower`** (`ghcr.io/containrrr/watchtower`)
   - Auto-updates the cobalt container image every 15 minutes
   - Scoped only to cobalt via labels

### Bot Message Flow

1. **URL Detection** (`handle_url`) — regex `https?://[^\s]+` extracts the first URL from any message.
2. **Platform Routing:**
   - **YouTube** → inline keyboard with MP3 / MP4 buttons
   - **Facebook video** (`/reel/`, `/watch`, `/videos/`, `fb.watch`) → direct video download
   - **TikTok** → direct video download
   - **Reddit** → direct video download (yt-dlp merges video+audio)
   - **Twitter/X** → direct video download
   - **Instagram reel/story** → direct video download
   - **Instagram post / Facebook post** (`/p/`, `/share/p/`) → try image scraping first, fallback to video
   - **Everything else** → direct video download via yt-dlp
3. **Video Download** (`download_and_send`) — uses yt-dlp with platform-specific options. Falls back to Cobalt API on `yt_dlp.utils.DownloadError`.
4. **Image Download** (`download_and_send_images`) — platform-specific scraping, then sends as photo/media group.
5. **Telegram Delivery** — reads file into memory via `BufferedInputFile`, then:
   - MP3 → `answer_audio()`
   - Video < 50 MB → `answer_video()` with streaming
   - Video > 50 MB → `answer_document()`
   - Images → `answer_photo()` or `answer_media_group()` (max 10 per group)
6. **Cleanup** — async file/directory deletion in `finally` blocks.

### Key Data Structures

- `pending_downloads: dict[str, str]` — maps callback hashes to URLs for MP3/MP4 selection and MP3 conversion.
- `original_messages: dict[str, dict]` — maps delete-button hashes to `{chat_id, message_id}` for the "Delete original message" feature.
- `status_messages: dict[str, Message]` — stores status messages for scheduled deletion after 20 minutes.

### Important Functions

| Function | Purpose |
|----------|---------|
| `get_ydl_opts(url, format_type)` | Returns yt-dlp options dict. YouTube audio uses `FFmpegExtractAudio` to MP3 @ 192kbps. YouTube video uses `best`. Reddit uses `bestvideo+bestaudio/best` with `merge_output_format: mp4`. Others use `best[ext=mp4]/best`. Reads `/app/cookies.txt` if present. |
| `download_and_send(message, url, format_type)` | Main video download + Telegram send loop. Auto-compresses with ffmpeg if >50MB. Adds "Convert to MP3" inline button. |
| `download_and_send_images(message, url)` | Image scraping for Instagram/Facebook posts. Tries multiple methods (cobalt, facebook-scraper, Selenium, curl+BS4). Falls back to video if no images found. |
| `download_via_cobalt(url)` | POSTs to Cobalt API, downloads the resulting file to `downloads/`. Returns file path or `None`. |
| `scrape_facebook_images(url, temp_dir)` | Selenium + BeautifulSoup scraper for Facebook `/share/p/` posts. Finds real images by `scontent` + `/v/t` in `src`. Uses curl subprocess to download images. |
| `scrape_instagram_images(url, temp_dir)` | Uses `curl` subprocess to fetch Instagram HTML, then BeautifulSoup to find `cdninstagram.com` images. Downloads with curl subprocess. |
| `compress_video(input_file)` | Runs ffmpeg to scale to 720p, H.264, AAC 128k, CRF 28. Returns compressed file path. |
| `cleanup_file()` / `cleanup_directory()` | Async wrappers around `os.remove` and `shutil.rmtree` via `asyncio.to_thread()`. |
| `delete_message_after_delay()` / `schedule_message_deletion()` | Auto-delete status/error messages after timeouts. |

### Callback Data Format

- `mp3:{url_hash}` — Download YouTube as MP3
- `mp4:{url_hash}` — Download YouTube as MP4
- `convert_mp3:{video_hash}` — Convert already-downloaded video to MP3
- `del_orig:{delete_hash}` — Delete the original user message

Hashes are 8-char MD5 prefixes.

## Code Style Guidelines

- **Single file:** Prefer keeping changes in `main.py`. Do not introduce new modules unless the feature is large and clearly separable.
- **Async everywhere:** All I/O must use `async`/`await`. Use `asyncio.to_thread()` to wrap blocking libraries (yt-dlp, gallery-dl, Selenium, subprocess).
- **File loading:** Always read media files into memory with `aiofiles` and send via `BufferedInputFile` or `FSInputFile`. Do not pass open file handles directly to aiogram.
- **Cleanup:** Every download path must have a `try/finally` or explicit cleanup call. Use `cleanup_file()` and `cleanup_directory()`.
- **Logging:** Use the module-level `logger` (INFO level, file + console handlers). Include `exc_info=True` in exception handlers.
- **Error UX:** Error messages shown to users should be short (`str(e)[:100]`). Auto-delete error/status messages after a delay where appropriate.
- **Platform detection:** Use simple substring checks (`'youtube.com' in url`) rather than regex for platform identification.

## Testing

There is **no automated test suite** (no pytest, no unittest). Testing is entirely manual:

1. Run the bot locally or in Docker.
2. Send URLs from `test_urls.txt` to the bot via Telegram.
3. Verify:
   - Correct platform detection
   - Download succeeds
   - File is sent correctly (video vs document vs audio vs image)
   - Temp files are cleaned up from `downloads/`
   - Logs in `logs/bot.log` show no unexpected errors

For debugging Facebook/Instagram scraping, use the standalone script:
```bash
python test_fb_images.py "https://www.facebook.com/share/p/xxxxx"
```

## Security Considerations

- **`.env` must never be committed.** It contains the live `BOT_TOKEN`.
- **`cookies.txt`** (optional) contains browser session cookies for YouTube. If present at project root, it is copied into the Docker container at `/app/cookies.txt`. Do not commit this file.
- **Downloads directory** contains temporary media from users. It is auto-cleaned but verify `cleanup_file()` executes in all code paths.
- **No input sanitization** beyond URL regex extraction. The bot trusts yt-dlp to handle malformed URLs.
- **Selenium runs headless Chromium with `--no-sandbox`** for Docker compatibility. This is necessary but less secure; do not expose the bot container to untrusted network input beyond Telegram updates.
- **No rate limiting** is implemented. Telegram's own rate limits apply.

## Deployment Notes

- The bot uses `restart: unless-stopped` in Docker Compose. It will auto-restart on crash or server reboot.
- `deploy.sh` intentionally builds with `--no-cache` to ensure fresh dependency installs.
- Disk space can fill up if cleanup fails or if many large videos queue concurrently. Monitor `downloads/` and set up a cron job if needed (`rm -rf downloads/*`).
- YouTube bot detection on VPS IPs is common. If downloads fail, provide a `cookies.txt` from a browser session and restart the container.
- yt-dlp breaks frequently when platforms change their APIs. The first troubleshooting step for any download failure is `pip install -U yt-dlp`.

## Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Could not download" / `DownloadError` | Platform API changed or video is private | Update yt-dlp; verify URL is public |
| Cobalt fallback also fails | Cobalt service not running or URL unsupported | Check `docker-compose ps`, verify cobalt logs |
| Facebook images missing | Page requires login or Selenium blocked | Try `cookies.txt`; check `test_fb_images.py` output |
| Instagram images missing | CDN URL changes or page structure changed | Update selectors in `scrape_instagram_images()` |
| `TelegramConflictError` in logs | Two bot instances running with same token | Stop old containers before starting new ones |
| Large videos fail to send | >2GB Telegram limit or memory exhausted | Compress earlier or reject oversized URLs |
| Selenium crashes in Docker | Missing Chrome flags | Ensure `--no-sandbox` and `--disable-dev-shm-usage` are set |
