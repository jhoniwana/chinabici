# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram video downloader bot built with Python that downloads videos from YouTube, Instagram, TikTok, Facebook, Twitter, and 1000+ other platforms using yt-dlp. The bot is containerized with Docker for easy VPS deployment.

## Core Technology Stack

- **Bot Framework:** Aiogram 3.15.0 (async Telegram bot framework)
- **Downloader:** yt-dlp 2024.11.18 (universal video downloader)
- **Image Extraction:** gallery-dl 1.27.0+ (image/gallery downloader)
- **Facebook Scraping:** facebook-scraper 0.2.60+ (dedicated FB scraper)
- **Web Scraping:** Selenium 4.26.0+ with Chromium (headless browser for FB/IG)
- **HTML Parsing:** BeautifulSoup4 + lxml (HTML content extraction)
- **Media Processing:** FFmpeg (audio/video conversion)
- **Async I/O:** aiofiles 24.1.0, aiohttp 3.10.11
- **Environment:** python-dotenv 1.0.1

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
   - YouTube URLs → Present inline keyboard with quality options (360p/720p/1080p) + MP3 + delete toggle
   - Reddit URLs → Try gallery download first, fallback to video
   - Instagram reels/stories → Direct video download via yt-dlp
   - Instagram posts / Facebook → Try image scraping first, fallback to video
   - Other platforms → Auto-download in best quality MP4
3. **Image Scraping (Instagram/Facebook):**
   - Facebook: Uses facebook-scraper library first, then Selenium as fallback
   - Instagram: Uses Selenium headless Chrome to render JavaScript-heavy pages
   - Extracts image URLs from `cdninstagram.com` or `fbcdn.net` domains
   - Downloads images concurrently with aiohttp
   - Filters small images (<10KB) to avoid thumbnails/icons
   - Falls back to video download if no images found
4. **Reddit Gallery Support:**
   - Uses yt-dlp to extract gallery info
   - Downloads multiple images from Reddit galleries
   - Falls back to video download if not a gallery
5. **Video Download:** yt-dlp downloads with platform-specific options to `downloads/` directory
6. **Send to Telegram:**
   - Images: Single photo or media group (max 10 per group)
   - Audio (MP3): `answer_audio()`
   - Video < 50MB: `answer_video()` with streaming support
   - Video > 50MB: `answer_document()`
7. **Cleanup:** Async file/directory deletion to prevent disk overflow
8. **Error Handling:** Error messages auto-delete after 5 seconds
9. **User Preferences:** Toggle to delete original message after download (per-user setting)

### Key Components (main.py)

- **`pending_downloads` dict:** Stores URL info with message_id, chat_id, user_id for cleanup
- **`user_delete_preference` dict:** Per-user setting to delete original message after download
- **`get_ydl_opts(url, format_type, quality)`:** Returns yt-dlp config based on platform, format, and quality
  - YouTube MP3: `bestaudio/best` → FFmpeg extract to MP3 @ 192kbps
  - YouTube MP4: Quality selection (360p/720p/1080p)
  - Reddit: `bestvideo[ext=mp4]+bestaudio/best`
  - Other: `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best`
- **`download_and_send()`:** Main video download handler with quality and delete_original support
- **`download_and_send_images()`:** Image download handler for Instagram/Facebook posts
- **`download_reddit_content()`:** Reddit gallery/video handler
- **`scrape_facebook_with_library()`:** facebook-scraper based extraction (primary)
- **`scrape_facebook_images()`:** Selenium-based Facebook image scraper (fallback)
- **`scrape_instagram_images()`:** Selenium-based Instagram image scraper
- **`download_reddit_gallery()`:** Reddit gallery image extraction using yt-dlp
- **`delete_message_after_delay()`:** Auto-delete error messages after delay
- **`cleanup_file()` / `cleanup_directory()`:** Async cleanup using `asyncio.to_thread()`
- **URL detection helpers:** `is_youtube()`, `is_reddit()`, `is_image_platform()`, `is_instagram_reel()`, `is_instagram_story()`
- **Callback handlers:** `handle_mp3()`, `handle_video_360/720/1080()`, `handle_toggle_delete()`

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
- Selenium page load timeout: 40s with popup handling for login dialogs
- Image size filter: <10KB images discarded as likely thumbnails

## Environment Configuration

Required in `.env`:
```
BOT_TOKEN=your_telegram_bot_token_from_botfather
```

Optional Docker Compose environment:
- `TZ=America/New_York` (timezone for logs)

## Important Implementation Details

1. **Async Architecture:** All I/O operations use async/await to handle multiple users concurrently without blocking
2. **BufferedInputFile:** Videos/images loaded into memory before sending to avoid Telegram API issues with file handles
3. **File Cleanup:** Critical to prevent disk overflow - cleanup happens in finally block; temp directories cleaned with `shutil.rmtree`
4. **Callback Data Format:** `mp3:{url_hash}` and `mp4:{url_hash}` for inline keyboard callbacks
5. **Title Truncation:** Video titles limited to 50 chars for filenames, 100 chars for captions
6. **Logging:** Dual handlers (file + console) with INFO level for debugging deployments
7. **Selenium Chrome Options:** Headless mode with custom user-agent, disabled GPU/sandbox for container compatibility
8. **Media Groups:** Telegram limits to 10 images per group; additional images sent individually
9. **Image Deduplication:** URLs are deduplicated by stripping query parameters to avoid duplicates

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

**Instagram/Facebook images not loading:** Selenium may fail on heavily protected pages
- Check if Chromium is installed: `which chromium`
- Verify Chrome options in `get_page_source_with_selenium()`
- Pages may require login - images from private accounts won't work

**Selenium crashes in Docker:** Ensure `--no-sandbox` and `--disable-dev-shm-usage` Chrome flags are set

## Deployment Notes

- Bot uses `restart: unless-stopped` policy - auto-restarts on crash or server reboot
- Logs limited to 10MB × 3 files with JSON driver rotation
- Downloads and logs are mounted volumes - persist across container rebuilds
- FFmpeg required in container for audio extraction (already in Dockerfile)
- Chromium + chromium-driver installed in container for Selenium web scraping
