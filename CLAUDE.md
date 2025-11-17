# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram video downloader bot built with Python that downloads videos from YouTube, Instagram, TikTok, Facebook, Twitter, and 1000+ other platforms using yt-dlp. The bot is containerized with Docker for easy VPS deployment.

## Core Technology Stack

- **Bot Framework:** Aiogram 3.15.0 (async Telegram bot framework)
- **Downloader:** yt-dlp 2024.11.18 (universal video downloader)
- **Media Processing:** FFmpeg (audio/video conversion)
- **Async I/O:** aiofiles 24.1.0
- **Environment:** python-dotenv 1.0.1
- **HTTP Client:** aiohttp 3.10.11

## Development Commands

### Local Development
```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate  # or 'china/bin/activate' if using existing venv

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add BOT_TOKEN=your_token_here

# Run bot locally
python main.py
```

### Docker Development
```bash
# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Restart bot
docker-compose restart

# Stop bot
docker-compose down

# Rebuild after code changes
docker-compose down && docker-compose build && docker-compose up -d

# Update yt-dlp without rebuild
docker-compose exec bot pip install -U yt-dlp && docker-compose restart
```

### Deployment
```bash
# Quick deploy script (builds, stops old container, starts new one)
./deploy.sh

# Manual deployment
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

## Architecture

### Bot Flow

1. **URL Detection:** User sends any URL → regex pattern `https?://[^\s]+` extracts first URL
2. **Platform Detection:**
   - YouTube URLs → Present inline keyboard with MP3/MP4 choice buttons
   - Other platforms → Auto-download in best quality MP4
3. **Download:** yt-dlp downloads with platform-specific options to `downloads/` directory
4. **Send to Telegram:**
   - Audio (MP3): `answer_audio()`
   - Video < 50MB: `answer_video()` with streaming support
   - Video > 50MB: `answer_document()`
5. **Cleanup:** Async file deletion to prevent disk overflow

### Key Components (main.py)

- **`pending_downloads` dict:** Temporary storage for YouTube URLs awaiting format choice (keyed by MD5 hash)
- **`get_ydl_opts(url, format_type)`:** Returns yt-dlp config based on platform and format
  - YouTube MP3: `bestaudio/best` → FFmpeg extract to MP3 @ 192kbps
  - YouTube MP4: `bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]` → merged MP4
  - Other: `best[ext=mp4]/best`
- **`download_and_send()`:** Main download handler with error handling and file cleanup
- **`cleanup_file()`:** Async file deletion using `asyncio.to_thread()`
- **Callback handlers:** `handle_mp3()` and `handle_mp4()` for YouTube format selection

### File Structure

```
downloads/        # Temporary video storage (mounted volume, auto-cleaned)
logs/bot.log      # Application logs (mounted volume)
main.py           # Single-file bot implementation
.env              # BOT_TOKEN configuration (not in git)
```

### yt-dlp Options Strategy

**YouTube videos use conservative format selection:**
- Max 720p video to balance quality/size
- Prefer MP4 container for Telegram compatibility
- Audio at 192kbps for MP3 downloads

**Non-YouTube platforms:**
- Simple `best[ext=mp4]/best` to let yt-dlp choose optimal format
- No post-processing to minimize download time

### Error Handling

- `yt_dlp.utils.DownloadError`: User-friendly message about private/unavailable videos
- Generic `Exception`: Logged with traceback, first 100 chars shown to user
- Socket timeout: 30s with 3 automatic retries
- File detection fallback: Checks multiple extensions (mp4, webm, mkv, avi, mov, mp3, m4a)

## Environment Configuration

Required in `.env`:
```
BOT_TOKEN=your_telegram_bot_token_from_botfather
```

Optional Docker Compose environment:
- `TZ=America/New_York` (timezone for logs)

## Important Implementation Details

1. **Async Architecture:** All I/O operations use async/await to handle multiple users concurrently without blocking
2. **BufferedInputFile:** Videos loaded into memory before sending to avoid Telegram API issues with file handles
3. **File Cleanup:** Critical to prevent disk overflow - cleanup happens in finally block equivalent
4. **Callback Data Format:** `mp3:{url_hash}` and `mp4:{url_hash}` for inline keyboard callbacks
5. **Title Truncation:** Video titles limited to 50 chars for filenames, 100 chars for captions
6. **Logging:** Dual handlers (file + console) with INFO level for debugging deployments

## Testing

Create `test_urls.txt` with various platform URLs and test manually:
```bash
python main.py
# Send each URL to bot via Telegram
# Verify downloads work and cleanup happens
```

No automated tests currently - manual testing required for bot functionality.

## Common Issues

**Bot not responding:** Check `docker-compose logs` for token errors or network issues

**Downloads failing:** yt-dlp may need update - platforms change their APIs frequently
```bash
docker-compose exec bot pip install -U yt-dlp
docker-compose restart
```

**Disk full:** Downloads not being cleaned up - check cleanup_file() execution in logs

**Large file send failures:** Telegram has 2GB limit - already handled by sending as document vs video based on 50MB threshold

## Deployment Notes

- Bot uses `restart: unless-stopped` policy - auto-restarts on crash or server reboot
- Logs limited to 10MB × 3 files with JSON driver rotation
- Downloads and logs are mounted volumes - persist across container rebuilds
- FFmpeg required in container for audio extraction (already in Dockerfile)
