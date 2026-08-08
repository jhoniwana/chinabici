import asyncio
import json
import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
import yt_dlp
import aiofiles
from gallery_dl import config as gdl_config, job as gdl_job
import tempfile
import shutil
import facebook_scraper

from bs4 import BeautifulSoup

import websockets
import aiohttp

import markov_service

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
COBALT_URL = os.getenv("COBALT_URL", "http://cobalt-api:9000")
LIGHTPANDA_URL = os.getenv("LIGHTPANDA_URL", "ws://lightpanda:9222")

# Markov configuration
MARKOV_ENABLED = os.getenv("MARKOV_ENABLED", "false").lower() in ("true", "1", "yes", "on")
MARKOV_CHAT_ID_RAW = os.getenv("MARKOV_CHAT_ID", "").strip()
MARKOV_CHAT_ID = MARKOV_CHAT_ID_RAW if MARKOV_CHAT_ID_RAW else None
MARKOV_INTERVAL_MINUTES = int(os.getenv("MARKOV_INTERVAL_MINUTES", "120"))
MARKOV_MODEL_PATH = os.getenv("MARKOV_MODEL_PATH", "./model.json")
MARKOV_LEARN_ENABLED = os.getenv("MARKOV_LEARN_ENABLED", "true").lower() in ("true", "1", "yes", "on")
MARKOV_RETRAIN_INTERVAL_HOURS = int(os.getenv("MARKOV_RETRAIN_INTERVAL_HOURS", "24"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

Path("downloads").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

pending_downloads = {}
# Store original message info for delete button
original_messages = {}
# Store status messages for scheduled cleanup
status_messages = {}

async def delete_message_after_delay(message: types.Message, delay: int = 5):
    """Delete a message after specified delay in seconds"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def schedule_message_deletion(message: types.Message, chat_id: int, msg_id: int, delay_minutes: int = 20):
    """Schedule message deletion after X minutes"""
    key = f"{chat_id}:{msg_id}"
    status_messages[key] = message
    asyncio.create_task(_delete_scheduled(key, delay_minutes * 60))

async def _delete_scheduled(key: str, delay_seconds: int):
    """Internal scheduled deletion"""
    await asyncio.sleep(delay_seconds)
    msg = status_messages.pop(key, None)
    if msg:
        try:
            await msg.delete()
        except:
            pass

def get_ydl_opts(url='', format_type='video', progress_cb=None):
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    is_reddit = 'reddit.com' in url or 'redd.it' in url

    base_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
        # NOTE: do NOT set 'impersonate' explicitly — yt-dlp 2026.07.4 has a
        # bug (AssertionError) with explicit impersonate targets on py3.11.
        # curl_cffi (pinned 0.11.0) is installed so TikTok's JS challenge is
        # solved via the native path that works.
    }

    if progress_cb:
        def _hook(d):
            if d.get('status') == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes') or 0
                if total:
                    pct = int(downloaded / total * 100)
                    asyncio.create_task(progress_cb(pct))
            elif d.get('status') == 'finished':
                asyncio.create_task(progress_cb(100))
        base_opts['progress_hooks'] = [_hook]

    # Add cookies if available (for YouTube bot detection bypass)
    cookies_path = '/app/cookies.txt'
    if os.path.exists(cookies_path):
        base_opts['cookiefile'] = cookies_path
        logger.info(f"Using cookies for YouTube authentication")
        # Don't specify player_client when using cookies
        # Let yt-dlp use its default: tv_downgraded,web_safari,web

    if is_youtube and format_type == 'audio':
        base_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    elif is_youtube and format_type == 'video':
        # iOS client provides different formats, use simple 'best' format
        base_opts['format'] = 'best'
    elif is_reddit:
        # Reddit needs more flexible format - video and audio are separate
        base_opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
        })
    else:
        # Prefer h264 (TikTok's h264 variants carry a real muxed audio track;
        # the bytevc1 1080p variant is video-only despite the format table)
        base_opts['format'] = 'h264[ext=mp4]/best[ext=mp4]/best'

    return base_opts

async def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            await asyncio.to_thread(os.remove, filepath)
            logger.info(f"Cleaned up: {filepath}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

async def cleanup_directory(dirpath: str):
    try:
        if os.path.exists(dirpath):
            await asyncio.to_thread(shutil.rmtree, dirpath)
            logger.info(f"Cleaned up directory: {dirpath}")
    except Exception as e:
        logger.error(f"Directory cleanup error: {e}")

def is_youtube(url: str) -> bool:
    return 'youtube.com' in url or 'youtu.be' in url

def is_facebook(url: str) -> bool:
    """Check if URL is from Facebook"""
    return 'facebook.com' in url

def is_facebook_video(url: str) -> bool:
    """Check if URL is a Facebook video (reel, watch, video post)"""
    if 'fb.watch' in url:
        return True
    if not is_facebook(url):
        return False
    video_patterns = ['/reel/', '/watch', '/videos/', '/video.php', 'story_fbid=', '/share/r/', '/share/v/']
    return any(pattern in url for pattern in video_patterns)

def is_twitter(url: str) -> bool:
    """Check if URL is from Twitter/X"""
    return 'twitter.com' in url or 'x.com' in url or 't.co' in url

def is_reddit(url: str) -> bool:
    """Check if URL is from Reddit"""
    return 'reddit.com' in url or 'redd.it' in url

def is_tiktok(url: str) -> bool:
    """Check if URL is from TikTok"""
    return 'tiktok.com' in url or 'vm.tiktok' in url

def is_image_platform(url: str) -> bool:
    """Check if URL is from a platform that has images (posts, not videos)"""
    # Facebook posts (not reels) and Instagram posts
    if 'instagram.com' in url and '/reel/' not in url and '/stories/' not in url and '/story/' not in url:
        return True
    if 'facebook.com' in url and not is_facebook_video(url):
        return True
    if is_reddit(url):
        return True
    return False

def is_instagram_reel(url: str) -> bool:
    """Check if URL is an Instagram reel (video)"""
    return 'instagram.com' in url and '/reel/' in url

def is_instagram_story(url: str) -> bool:
    """Check if URL is an Instagram story"""
    return 'instagram.com' in url and ('/stories/' in url or '/story/' in url)

async def download_via_cobalt(url: str, output_dir: str = "downloads") -> str | None:
    """Download a video using cobalt-api (internal Docker service)."""
    try:
        logger.info(f"Trying cobalt for: {url}")

        async with aiohttp.ClientSession() as session:
            payload = {
                "url": url,
                "downloadMode": "auto",
                "vcodec": "h264",
                "acodec": "mp3",
            }

            async with session.post(
                f"{COBALT_URL}/",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Cobalt responded HTTP {resp.status}")
                    return None

                data = await resp.json()

        status = data.get("status")

        if status == "error":
            error_code = data.get("error", {}).get("code", "unknown")
            logger.error(f"Cobalt error: {error_code}")
            return None

        if status not in ("redirect", "tunnel", "stream"):
            logger.error(f"Cobalt unexpected status: {status}")
            return None

        download_url = data.get("url")
        filename_hint = data.get("filename", "cobalt_video.mp4")

        if not download_url:
            logger.error("Cobalt returned no download URL")
            return None

        output_path = os.path.join(output_dir, filename_hint)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_url,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Error downloading from cobalt URL: {resp.status}")
                    return None

                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        await f.write(chunk)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Cobalt downloaded: {output_path} ({os.path.getsize(output_path)} bytes)")
            return output_path

        return None

    except aiohttp.ClientConnectorError:
        logger.error("Could not connect to cobalt-api. Is the service running?")
        return None
    except asyncio.TimeoutError:
        logger.error("Timeout connecting to cobalt-api")
        return None
    except Exception as e:
        logger.error(f"Error in cobalt: {e}", exc_info=True)
        return None

async def download_instagram_via_ultraigdl(url: str, output_dir: str = "downloads") -> tuple[str | None, str | None]:
    """Download Instagram video via ultra-igdl (Node.js package). Returns (filepath, caption)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'node', 'igdl_helper.js', url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.error(f"ultra-igdl failed (exit {proc.returncode}): {stderr.decode()[:200]}")
            return None, None

        result = json.loads(stdout.decode())
        if "error" in result:
            logger.error(f"ultra-igdl error: {result['error']}")
            return None, None

        code = result.get("code", 0)
        if code != 200:
            logger.error(f"ultra-igdl API error (code {code}): {result.get('message', 'unknown')}")
            return None, None

        caption = result.get("caption", "") or ""
        username = result.get("username", "") or ""

        media = result.get("media", [])
        if not media:
            logger.error("ultra-igdl: no media in result")
            return None, None

        media_url = media[0].get("url")
        if not media_url:
            logger.error("ultra-igdl: no url in media[0]")
            return None, None

        logger.info(f"ultra-igdl got direct URL: {media_url[:80]}...")

        from urllib.parse import urlparse
        parsed = urlparse(media_url)
        path = parsed.path
        ext = path.split('.')[-1].split('?')[0] if '.' in path else 'mp4'
        output_path = os.path.join(output_dir, f"ig_ultra.{ext}")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                media_url,
                timeout=aiohttp.ClientTimeout(total=120),
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                if resp.status != 200:
                    logger.error(f"ultra-igdl download failed: HTTP {resp.status}")
                    return None, None
                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        await f.write(chunk)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"ultra-igdl saved: {output_path} ({os.path.getsize(output_path)} bytes)")
            return output_path, caption
        return None, None

    except asyncio.TimeoutError:
        logger.error("ultra-igdl timeout")
        return None, None
    except Exception as e:
        logger.error(f"ultra-igdl error: {e}", exc_info=True)
        return None, None

MAX_TELEGRAM_BYTES = 48 * 1024 * 1024   # target under the 50 MB Bot API limit
AUDIO_BITRATE = 96 * 1000                # aac 96k
VAAPI_DEVICE = "/dev/dri/renderD128"


def render_progress_bar(pct: int, width: int = 14) -> str:
    """Returns a text progress bar like '▓▓▓▓▓▓▓░░░░░░░ 58%'."""
    pct = max(0, min(100, int(pct)))
    filled = round(pct / 100 * width)
    bar = "▓" * filled + "░" * (width - filled)
    return f"{bar} {pct}%"


async def update_status(status_msg: types.Message, emoji: str, text: str, pct: int | None = None):
    """Edit the single per-download status message (rich streaming state)."""
    try:
        bar = f" {render_progress_bar(pct)}" if pct is not None else ""
        await status_msg.edit_text(f"{emoji} {text}{bar}")
    except Exception:
        # Message may have been deleted already or edit raced — ignore
        pass


async def _ffprobe_duration(input_file: str) -> float | None:
    """Returns the duration in seconds, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', input_file,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return float(out.decode().strip())
    except Exception:
        return None


async def _vaapi_available() -> bool:
    """Checks whether h264_vaapi can actually be used (vainfo + device)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'vainfo', '--display', 'drm', '--device', VAAPI_DEVICE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        return b'h264' in out.lower() or b'h264' in _.lower()
    except Exception:
        return False


def _pick_resolution(video_bitrate: int) -> str:
    """Resolution based on available video bitrate (lower = safer size)."""
    if video_bitrate >= 2_000_000:
        return "scale=1080:-2"
    if video_bitrate >= 1_100_000:
        return "scale=720:-2"
    return "scale=540:-2"


async def _video_codec(filepath: str) -> str | None:
    """Return the video codec name (e.g. 'h264', 'hevc') via ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', filepath,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return out.decode().strip().lower() or None
    except Exception:
        return None


async def _run_ffmpeg(args: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    return proc.returncode == 0


async def compress_video(input_file: str, target_mb: int = 48, progress_cb=None) -> str | None:
    """Compress a video so it always fits under Telegram's 50 MB upload limit.

    Strategy:
      1. ffprobe the duration, compute a video bitrate so the whole file
         lands under `target_mb` (with room for the 96k audio track).
      2. Use h264_vaapi (hardware, ~5x faster) when the GPU is available,
         otherwise fall back to libx264 (software).
      3. If the result is still too big, retry with a lower bitrate and a
         smaller resolution until it fits (max 4 attempts).
      4. When `progress_cb` is given, stream the encode progress (%).
    """
    try:
        base_name = os.path.splitext(input_file)[0]
        duration = await _ffprobe_duration(input_file)
        if not duration or duration <= 0:
            logger.warning(f"compress: could not read duration of {input_file}, using CRF fallback")
            duration = None

        vaapi = await _vaapi_available()
        logger.info(f"compress: duration={duration}s vaapi={vaapi}")

        # video bitrate = (target_bytes * 8) / seconds - audio
        video_bps = 1_200_000
        if duration:
            video_bps = int(target_mb * 1024 * 1024 * 8 / duration) - AUDIO_BITRATE
            video_bps = max(250_000, video_bps)

        # Intel iHD driver only supports CQP rate control, so VAAPI attempts
        # step the quality (QP) instead of the bitrate; libx264 uses bitrate.
        attempts = [
            {"vbr": video_bps, "qp": 32, "res": _pick_resolution(video_bps)},
            {"vbr": int(video_bps * 0.7), "qp": 36, "res": "scale=540:-2"},
            {"vbr": int(video_bps * 0.45), "qp": 40, "res": "scale=480:-2"},
            {"vbr": 300_000, "qp": 44, "res": "scale=360:-2"},
        ]

        for i, attempt in enumerate(attempts):
            output_file = f"{base_name}_compressed.mp4"
            vf = attempt["res"]
            if vaapi:
                # For h264 inputs the whole pipeline can run on the GPU
                # (decode + scale + encode) — ~30x faster than CPU decode.
                codec = await _video_codec(input_file)
                if codec == 'h264':
                    vf = vf.replace('scale=', 'scale_vaapi=')
                    args = ['ffmpeg', '-y',
                            '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
                            '-init_hw_device', 'vaapi=va:/dev/dri/renderD128',
                            '-filter_hw_device', 'va',
                            '-i', input_file, '-vf', vf,
                            '-c:v', 'h264_vaapi', '-global_quality', str(attempt["qp"]),
                            '-c:a', 'aac', '-b:a', '96k',
                            '-movflags', '+faststart', output_file]
                else:
                    # HEVC/other inputs have no GPU decoder on this Intel
                    # driver — decode on CPU, encode on GPU.
                    vf = f"{vf},format=nv12,hwupload"
                    args = ['ffmpeg', '-y',
                            '-init_hw_device', 'vaapi=va:/dev/dri/renderD128',
                            '-filter_hw_device', 'va',
                            '-i', input_file, '-vf', vf,
                            '-c:v', 'h264_vaapi', '-global_quality', str(attempt["qp"]),
                            '-c:a', 'aac', '-b:a', '96k',
                            '-movflags', '+faststart', output_file]
            else:
                vf = vf + ",format=yuv420p"
                args = ['ffmpeg', '-y', '-i', input_file, '-vf', vf,
                        '-c:v', 'libx264', '-preset', 'fast',
                        '-b:v', str(attempt["vbr"]),
                        '-maxrate', str(int(attempt["vbr"] * 1.3)),
                        '-bufsize', str(int(attempt["vbr"] * 2)),
                        '-c:a', 'aac', '-b:a', '96k',
                        '-movflags', '+faststart', output_file]

            # Stream encode progress through ffmpeg -progress pipe:1
            args += ['-progress', 'pipe:1']
            total_us = int(duration * 1_000_000) if duration else None
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                if total_us and progress_cb and line.startswith(b'out_time_us='):
                    try:
                        us = int(line.split(b'=', 1)[1].strip())
                        await progress_cb(min(99, int(us / total_us * 100)))
                    except Exception:
                        pass
            await proc.wait()
            ok_run = proc.returncode == 0
            if ok_run and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                size = os.path.getsize(output_file)
                if size <= MAX_TELEGRAM_BYTES or i == len(attempts) - 1:
                    logger.info(f"Compressed (attempt {i + 1}, vaapi={vaapi}): "
                                f"{os.path.getsize(input_file)} -> {size} bytes")
                    return output_file
                os.remove(output_file)
            else:
                logger.warning(f"compress: attempt {i + 1} failed")
        return None
    except Exception as e:
        logger.error(f"Compression error: {e}")
        return None

async def extract_images_info(url: str):
    """Extract image information using gallery-dl"""
    try:
        # Create a custom DataJob to extract info without downloading
        class InfoExtractor(gdl_job.DataJob):
            def __init__(self, url):
                super().__init__(url)
                self.results = []

            def handle_url(self, url, kwdict):
                self.results.append(kwdict)

        job = InfoExtractor(url)
        await asyncio.to_thread(job.run)

        return job.results if job.results else None
    except Exception as e:
        logger.error(f"gallery-dl info extraction error: {e}")
        return None

async def fetch_html_via_lightpanda(url: str) -> str | None:
    """Get full page HTML from Lightpanda browser via CDP WebSocket"""
    try:
        async with websockets.connect(LIGHTPANDA_URL, max_size=10_000_000) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank"}}))
            r = json.loads(await ws.recv())
            r = json.loads(await ws.recv())
            target_id = r["result"]["targetId"]

            await ws.send(json.dumps({"id": 2, "method": "Target.attachToTarget", "params": {"targetId": target_id}}))
            r = json.loads(await ws.recv())
            session_id = r["params"]["sessionId"]
            r = json.loads(await ws.recv())

            logger.info(f"Lightpanda navigating to: {url}")
            await ws.send(json.dumps({
                "id": 3, "sessionId": session_id,
                "method": "Page.navigate", "params": {"url": url}
            }))

            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if r.get("method") in ("Page.frameStoppedLoading", "Page.loadEventFired"):
                    logger.info(f"Lightpanda {r['method']}")
                    break
                elif r.get("method") == "Page.frameNavigated":
                    logger.info("Lightpanda frame navigated")

            await asyncio.sleep(3)

            await ws.send(json.dumps({
                "id": 10, "sessionId": session_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML", "returnByValue": True}
            }))

            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if r.get("id") == 10 and "result" in r:
                    html = r["result"]["result"]["value"]
                    logger.info(f"Lightpanda fetched {len(html)} bytes of HTML")
                    return html
                elif r.get("id") == 10:
                    logger.error(f"Lightpanda evaluate error: {str(r)[:200]}")
                    return None
    except asyncio.TimeoutError:
        logger.error("Lightpanda page load timeout")
        return None
    except websockets.WebSocketException as e:
        logger.error(f"Lightpanda connection error: {e}")
        return None

async def scrape_facebook_images(url: str, temp_dir: str):
    """Scrape images from Facebook using Lightpanda browser (via CDP over WebSocket)"""
    try:
        html = await fetch_html_via_lightpanda(url)
        if not html:
            return [], None

        soup = BeautifulSoup(html, 'lxml')

        # Find images and description
        images = []
        description = None

        # Try to get full description from the page content
        # Look for the post text container
        post_text_selectors = [
            'div[data-ad-preview="message"]',
            'div[data-ad-comet-preview="message"]',
            'div[dir="auto"]',
            'div[role="article"] p',  # Article post text
            'article p',
            'div[aria-label="Story"] p',  # Story text
        ]

        # Also try to get text from span elements
        text_selectors = [
            'span[dir="auto"]',
            'span[data-ad-preview="message"]',
        ]

        for selector in post_text_selectors:
            text_divs = soup.select(selector)
            for div in text_divs:
                text = div.get_text(strip=True)
                if text and len(text) > 50:  # Likely the main post text
                    if not description or len(text) > len(description):
                        description = text
                        break
            if description and len(description) > 100:
                break

        # Also try spans
        if not description or len(description) < 50:
            for selector in text_selectors:
                text_spans = soup.select(selector)
                for span in text_spans:
                    text = span.get_text(strip=True)
                    if text and len(text) > 50:
                        if not description or len(text) > len(description):
                            description = text
                            break
                if description and len(description) > 100:
                    break

        # Fallback to og:description if no better text found
        if not description or len(description) < 50:
            og_description = soup.find('meta', property='og:description')
            if og_description and og_description.get('content'):
                fallback_desc = og_description['content']
                if not description or len(fallback_desc) > len(description):
                    description = fallback_desc

        if description:
            logger.info(f"Found description ({len(description)} chars): {description[:100]}...")

        # Extract image URLs — prefer og:image (canonical main image)
        og_images = []
        og_meta = soup.find('meta', property='og:image')
        if og_meta and og_meta.get('content'):
            main_img = og_meta['content']
            logger.info(f"Found og:image: {main_img[:80]}...")
            og_images.append({'content': main_img})
        else:
            # Fallback: find all scontent img tags
            img_tags = soup.find_all('img')
            logger.info(f"No og:image, found {len(img_tags)} img tags")

            seen_urls = set()
            for img in img_tags:
                src = img.get('src', '')
                if not src or src in seen_urls:
                    continue

                if '/v/t' in src and 'scontent' in src:
                    seen_urls.add(src)
                    og_images.append({'content': src})

        logger.info(f"Total images to download: {len(og_images)}")

        if not og_images:
            logger.info("No images found")
            return [], description

        # Download images
        for idx, og_img in enumerate(og_images[:10]):
            img_url = og_img.get('content') if isinstance(og_img, dict) else og_img.get('content')
            if not img_url:
                continue
            img_url = img_url.replace('&amp;', '&')
            img_result = await _download_image_curl(img_url, temp_dir, f"facebook_image_{idx}")
            if img_result:
                images.append(img_result)

        return images, description

    except Exception as e:
        logger.error(f"Facebook scraping error: {e}", exc_info=True)
        return [], None

async def scrape_instagram_images_ultraigdl(url: str, temp_dir: str):
    """Scrape images from Instagram using ultra-igdl (Node.js)."""
    try:
        import aiohttp
        proc = await asyncio.create_subprocess_exec(
            'node', 'igdl_helper.js', url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return [], None

        result = json.loads(stdout.decode())
        if result.get("code") != 200:
            return [], None

        caption = result.get("caption", "") or ""
        images = []
        async with aiohttp.ClientSession() as session:
            for idx, item in enumerate(result.get("media", [])):
                if item.get("type") != "image":
                    continue
                img_url = item.get("url")
                if not img_url:
                    continue
                img_path = os.path.join(temp_dir, f"ig_ultra_image_{idx}.jpg")
                try:
                    async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(img_path, 'wb') as f:
                                async for chunk in resp.content.iter_chunked(1024 * 1024):
                                    await f.write(chunk)
                            if os.path.getsize(img_path) > 5000:
                                images.append(img_path)
                except Exception as e:
                    logger.warning(f"ultra-igdl image {idx} download failed: {e}")

        logger.info(f"ultra-igdl: {len(images)} images, caption={len(caption)} chars")
        return images, caption

    except Exception as e:
        logger.error(f"scrape_instagram_images_ultraigdl error: {e}", exc_info=True)
        return [], None

async def scrape_instagram_images_via_lightpanda(url: str, temp_dir: str):
    """Scrape images from Instagram using Lightpanda (CDP over WebSocket).
    Navigates to the Instagram post, extracts the real post image URL from the
    rendered DOM (filters profile pics/thumbnails), and downloads via aiohttp."""
    try:
        async with websockets.connect(LIGHTPANDA_URL, max_size=10_000_000) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank"}}))
            await ws.recv()
            r = json.loads(await ws.recv())
            target_id = r["result"]["targetId"]

            await ws.send(json.dumps({"id": 2, "method": "Target.attachToTarget", "params": {"targetId": target_id}}))
            r = json.loads(await ws.recv())
            session_id = r["params"]["sessionId"]
            await ws.recv()

            logger.info(f"Lightpanda navigating to Instagram: {url}")
            await ws.send(json.dumps({
                "id": 3, "sessionId": session_id,
                "method": "Page.navigate", "params": {"url": url}
            }))

            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if r.get("method") in ("Page.frameStoppedLoading", "Page.loadEventFired"):
                    break

            await asyncio.sleep(5)

            extract_js = """
(() => {
    const imgs = Array.from(document.querySelectorAll('img'));
    const postImages = imgs.filter(i => i.src && i.src.includes('fna.fbcdn'));
    if (postImages.length > 0) {
        return JSON.stringify(postImages.map(i => ({
            src: i.src,
            alt: i.alt || ''
        })));
    }
    const allImgs = imgs.filter(i => i.src && !i.src.includes('static.cdninstagram.com'));
    return JSON.stringify(allImgs.map(i => ({ src: i.src, alt: i.alt || '' })));
})()
"""
            await ws.send(json.dumps({
                "id": 10, "sessionId": session_id,
                "method": "Runtime.evaluate",
                "params": {"expression": extract_js, "returnByValue": True}
            }))

            result = None
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if r.get("id") == 10 and "result" in r:
                    result = r["result"]
                    break

            if not result:
                logger.error("Lightpanda evaluate returned no result")
                return [], None

            val = result["result"].get("value", "[]")
            imgs = json.loads(val) if isinstance(val, str) else val

            if not imgs:
                logger.info("Lightpanda found no images on Instagram page")
                return [], None

            profile_patterns = ['profile picture', 'profile_ pic', 'avatar']
            candidate = None
            fallback = None

            for img in imgs:
                alt_lower = (img.get('alt') or '').lower()
                is_profile = any(p in alt_lower for p in profile_patterns)

                if not is_profile and 'fna.fbcdn' in img.get('src', ''):
                    candidate = img
                    break
                if not is_profile and not fallback:
                    fallback = img

            target_img = candidate or fallback or imgs[0]
            img_url = target_img.get('src', '')
            if not img_url:
                logger.error("Lightpanda: extracted image has no src")
                return [], None

            logger.info(f"Lightpanda selected IG image: {img_url[:100]}...")

            import aiohttp
            img_path = os.path.join(temp_dir, "ig_lightpanda_image.jpg")
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        logger.error(f"Lightpanda image download HTTP {resp.status}")
                        return [], None
                    async with aiofiles.open(img_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(1024 * 1024):
                            await f.write(chunk)

            if os.path.getsize(img_path) > 5000:
                logger.info(f"Lightpanda downloaded Instagram image: {img_path}")
                return [img_path], target_img.get('alt') or None
            return [], None

    except asyncio.TimeoutError:
        logger.error("Lightpanda timeout for Instagram")
        return [], None
    except websockets.WebSocketException as e:
        logger.error(f"Lightpanda WS error for Instagram: {e}")
        return [], None
    except Exception as e:
        logger.error(f"Lightpanda Instagram scraper error: {e}", exc_info=True)
        return [], None

async def scrape_instagram_images(url: str, temp_dir: str):
    """Scrape images from Instagram using instaloader"""
    try:
        import instaloader

        shortcode_match = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', url)
        if not shortcode_match:
            logger.error(f"Could not extract shortcode from Instagram URL: {url}")
            return [], None
        shortcode = shortcode_match.group(1)
        logger.info(f"Instagram shortcode: {shortcode}")

        loader = instaloader.Instaloader(
            download_videos=False,
            download_video_thumbnails=False,
            compress_json=False,
            save_metadata=True,
            max_connection_attempts=3,
            dirname_pattern=temp_dir,
        )

        post = await asyncio.to_thread(
            instaloader.Post.from_shortcode, loader.context, shortcode
        )
        description = post.caption or ""

        await asyncio.to_thread(loader.download_post, post, temp_dir)

        # Find downloaded files
        images = []
        for f in sorted(os.listdir(temp_dir)):
            fp = os.path.join(temp_dir, f)
            if f.endswith('.jpg') and os.path.isfile(fp) and os.path.getsize(fp) > 5000:
                images.append(fp)

        # Read caption from .txt file if instaloader created one
        txt_files = [f for f in os.listdir(temp_dir) if f.endswith('.txt')]
        if txt_files:
            txt_path = os.path.join(temp_dir, txt_files[0])
            try:
                async with aiofiles.open(txt_path, 'r') as f:
                    txt_content = await f.read()
                    if txt_content.strip():
                        description = txt_content.strip()
            except Exception:
                pass

        logger.info(f"Instaloader: {len(images)} images, description={len(description)} chars")
        return images, description

    except Exception as e:
        logger.error(f"Instaloader error: {e}", exc_info=True)
        return [], None

async def _download_image_curl(img_url: str, temp_dir: str, filename_base: str) -> str | None:
    """Download a single image via curl"""
    import subprocess
    try:
        img_filename = os.path.join(temp_dir, f"{filename_base}.jpg")
        curl_cmd = [
            'curl', '-L', '-o', img_filename,
            '-A', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            img_url
        ]
        result = await asyncio.to_thread(
            subprocess.run, curl_cmd, capture_output=True, timeout=30
        )
        if result.returncode == 0 and os.path.exists(img_filename) and os.path.getsize(img_filename) > 5000:
            logger.info(f"Downloaded {filename_base}: {img_filename}")
            return img_filename
        if os.path.exists(img_filename):
            os.remove(img_filename)
        return None
    except Exception as e:
        logger.error(f"Failed to download {filename_base}: {e}")
        return None

async def scrape_reddit_images(url: str, temp_dir: str):
    """Scrape images from Reddit using Lightpanda browser"""
    try:
        html = await fetch_html_via_lightpanda(url)
        if not html:
            return [], None

        soup = BeautifulSoup(html, 'lxml')

        images = []
        description = None

        for meta_attrs in [{'property': 'og:description'}, {'name': 'description'}]:
            meta = soup.find('meta', attrs=meta_attrs)
            if meta and meta.get('content'):
                description = meta['content']
                break

        for meta_attrs in [{'property': 'og:image'}, {'name': 'twitter:image'}]:
            meta = soup.find('meta', attrs=meta_attrs)
            if meta and meta.get('content'):
                main_img = meta['content']
                logger.info(f"Found Reddit {meta_attrs}: {main_img[:80]}...")
                img_result = await _download_image_curl(main_img, temp_dir, "reddit_image_0")
                if img_result:
                    images.append(img_result)
                return images, description

        img_tags = soup.find_all('img')
        logger.info(f"No og:image, scanning {len(img_tags)} img tags for Reddit...")
        seen = set()
        for img in img_tags:
            src = img.get('src', '')
            if not src or src in seen:
                continue
            if any(x in src for x in ['preview.redd.it', 'i.redd.it', 'external-preview.redd.it']):
                seen.add(src)
                title = img.get('alt', '')
                if title and not description:
                    description = title
                img_result = await _download_image_curl(src, temp_dir, f"reddit_image_{len(images)}")
                if img_result:
                    images.append(img_result)

        return images, description
    except Exception as e:
        logger.error(f"Reddit scraping error: {e}", exc_info=True)
        return [], None

async def download_images(url: str, temp_dir: str):
    """Download images using gallery-dl to a temporary directory"""
    try:
        # Configure gallery-dl
        gdl_config.set(("extractor",), "base-directory", temp_dir)
        gdl_config.set(("extractor",), "directory", ["."])

        # Create download job
        job = gdl_job.DownloadJob(url)
        await asyncio.to_thread(job.run)

        # Get all downloaded files
        files = []
        for root, dirs, filenames in os.walk(temp_dir):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                files.append(filepath)

        return files
    except Exception as e:
        logger.error(f"gallery-dl download error: {e}")
        return []

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "**Video & Image Downloader Bot**\n\n"
        "Send me any video or image link and I'll download it for you.\n\n"
        "**YouTube:** Choose MP3 (audio) or MP4 (video)\n"
        "**Instagram/Facebook:** Download images with captions or videos\n"
        "**Others:** Auto-download best quality\n\n"
        "Supported: YouTube, Instagram, TikTok, Facebook, Twitter, and 1000+ sites"
    )

@dp.message(Command("xd"))
async def cmd_xd(message: types.Message):
    """Generate and send a Markov sentence."""
    logger.info(f"/xd command received from chat_id={message.chat.id}")

    if not markov_service.is_model_available():
        await message.answer("El modo Markov no está disponible ahora mismo.")
        return

    # Extract optional seed from command arguments
    args = message.text.split(maxsplit=1)
    seed = args[1].strip() if len(args) > 1 else None

    sentence = markov_service.generate_markov_sentence(seed=seed)
    await message.answer(sentence)
    logger.info(f"/xd response sent to chat_id={message.chat.id}")

@dp.message()
async def handle_url(message: types.Message):
    # Learn from messages for Markov model (non-blocking)
    if MARKOV_LEARN_ENABLED and message.text and not (message.from_user and message.from_user.is_bot):
        try:
            await markov_service.learn_message(message.text)
        except Exception as e:
            logger.error(f"Markov learn error: {e}")

    if not message.text:
        return

    logger.info(f"handle_url received: {message.text[:60]}...")
    text = message.text.strip()
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)

    if not urls:
        return

    url = urls[0]

    if is_youtube(url):
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        pending_downloads[url_hash] = url

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎵 MP3 (Audio)", callback_data=f"mp3:{url_hash}"),
                InlineKeyboardButton(text="🎬 MP4 (Video)", callback_data=f"mp4:{url_hash}")
            ]
        ])
        await message.answer(
            "**YouTube detected!**\n\nChoose format:",
            reply_markup=keyboard
        )
    elif is_facebook_video(url):
        # Facebook videos (reels, watch, video posts) - download as video
        logger.info(f"Facebook video detected: {url}")
        status_msg = await message.answer("📹 Facebook video detectado ⏳")
        await download_and_send(message, url, 'video', status_msg=status_msg, platform_emoji="📹")
    elif is_tiktok(url):
        # TikTok videos
        logger.info(f"TikTok detected: {url}")
        status_msg = await message.answer("🎵 TikTok detectado ⏳")
        await download_and_send(message, url, 'video', status_msg=status_msg, platform_emoji="🎵")
    elif is_reddit(url):
        # Reddit images and videos — try images first, fallback to video
        logger.info(f"Reddit detected (images/video): {url}")
        await message.answer("🤖 Reddit detectado! Descargando...")
        await download_and_send_images(message, url)
    elif is_twitter(url):
        # Twitter/X videos and images
        logger.info(f"Twitter/X detected: {url}")
        status_msg = await message.answer("🐦 Twitter/X detectado ⏳")
        await download_and_send(message, url, 'video', status_msg=status_msg, platform_emoji="🐦")
    elif is_instagram_reel(url) or is_instagram_story(url):
        # Instagram reels/stories — try video first via ultra-igdl, then yt-dlp/cobalt
        # If video fails, try image extraction as last resort (photo-reels)
        logger.info(f"Instagram video detected (reel/story): {url}")
        status_msg = await message.answer("⏳ Downloading Instagram video...")
        ig_file, ig_caption = await download_instagram_via_ultraigdl(url)
        if ig_file:
            await status_msg.edit_text("📤 Sending...")
            await _send_video_file(message, ig_file, status_msg, original_url=url, caption=ig_caption)
            return
        # Schedule the retry message for auto-deletion
        retry_msg = await status_msg.edit_text("⏳ ultra-igdl failed, trying video fallback...")
        asyncio.create_task(delete_message_after_delay(retry_msg, 10))
        video_ok = await download_and_send(message, url, 'video')
        if not video_ok:
            logger.info("Video download failed, trying image extraction as last resort...")
            await download_and_send_images(message, url)
    elif is_image_platform(url):
        # For Instagram posts and Facebook posts, try images first
        # If it fails or has no images, it will fall back to video
        await download_and_send_images(message, url)
    else:
        # Generic video download for other platforms (1000+ sites)
        logger.info(f"Generic video download: {url}")
        status_msg = await message.answer("⏳ Descargando...")
        await download_and_send(message, url, 'video', status_msg=status_msg)

async def download_and_send_images(message: types.Message, url: str):
    """Download and send images from Instagram/Facebook posts"""
    status_msg = await message.answer("⏳ Downloading images...")

    temp_dir = None
    try:
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix="images_", dir="downloads")

        description = ""
        image_files = []

        # For Facebook /share/p/ URLs (images), use Lightpanda directly
        if 'facebook.com' in url and '/share/p/' in url:
            logger.info("Facebook image detected, using Lightpanda...")
            await status_msg.edit_text("⏳ Scraping with Lightpanda...")
            image_files, description = await scrape_facebook_images(url, temp_dir)

        # Other Facebook URLs (videos or legacy URLs)
        elif 'facebook.com' in url:
            logger.info("Trying cobalt for Facebook...")
            await status_msg.edit_text("⏳ Downloading via cobalt...")
            cobalt_file = await download_via_cobalt(url, temp_dir)

            # Check if cobalt returned an image or video
            if cobalt_file and cobalt_file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                image_files = [cobalt_file]
                description = "Downloaded via cobalt"
            elif cobalt_file:
                # It's a video, download normally
                await status_msg.edit_text("📹 Found video, downloading...")
                await cleanup_directory(temp_dir)
                await download_and_send(message, url, 'video', original_msg_id=message.message_id)
                return
            else:
                # Try facebook-scraper library (uses m.facebook.com)
                await status_msg.edit_text("⏳ Trying facebook-scraper...")
                try:
                    images_list = []
                    fb_description = ""
                    for post in facebook_scraper.get_posts(post_urls=[url], pages=1):
                        if hasattr(post, 'images') and post.images:
                            images_list = [img.get('url') for img in post.images if img.get('url')]
                        if hasattr(post, 'text') and post.text:
                            fb_description = post.text
                    if images_list:
                        # Download images from URLs
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            for idx, img_url in enumerate(images_list[:10]):  # Max 10
                                try:
                                    img_path = os.path.join(temp_dir, f"fb_image_{idx}.jpg")
                                    async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                                        if resp.status == 200:
                                            content = await resp.read()
                                            async with aiofiles.open(img_path, 'wb') as f:
                                                await f.write(content)
                                            image_files.append(img_path)
                                except Exception as e:
                                    logger.warning(f"Failed to download image {idx}: {e}")
                        description = fb_description
                except Exception as e:
                    logger.error(f"facebook-scraper failed: {e}")

                if not image_files:
                    # Fallback to Lightpanda
                    logger.info("facebook-scraper failed, trying Lightpanda...")
                    image_files, description = await scrape_facebook_images(url, temp_dir)

        # For Reddit, try Lightpanda first (og:image), fallback to video
        elif 'reddit.com' in url or 'redd.it' in url:
            logger.info("Trying Lightpanda for Reddit...")
            await status_msg.edit_text("⏳ Scraping with Lightpanda...")
            image_files, description = await scrape_reddit_images(url, temp_dir)

        # For Instagram, try ultra-igdl first, then Lightpanda, then instaloader
        elif 'instagram.com' in url:
            logger.info("Trying ultra-igdl for Instagram...")
            await status_msg.edit_text("⏳ Downloading via ultra-igdl...")
            image_files, description = await scrape_instagram_images_ultraigdl(url, temp_dir)
            if not image_files:
                logger.info("ultra-igdl failed, trying Lightpanda...")
                await status_msg.edit_text("⏳ Scraping with Lightpanda...")
                image_files, description = await scrape_instagram_images_via_lightpanda(url, temp_dir)
            if not image_files:
                logger.info("Lightpanda failed, trying instaloader...")
                await status_msg.edit_text("⏳ Downloading via instaloader...")
                image_files, description = await scrape_instagram_images(url, temp_dir)
            if not image_files:
                logger.info("instaloader failed, trying gallery-dl...")
                await status_msg.edit_text("⏳ Downloading via gallery-dl...")
                image_files = await download_images(url, temp_dir)

        if 'facebook.com' in url and '/share/p/' in url and not image_files:
            # Facebook image posts should NOT fall back to video
            await status_msg.edit_text("❌ No se pudieron obtener las imágenes. La publicación podría requerir login o estar privada.")
            await cleanup_directory(temp_dir)
            return

        if not image_files:
            # No images found - might be a video post, try yt-dlp
            logger.info(f"No images found for {url}, trying video download")
            info_msg = await status_msg.edit_text("📹 No images found. Trying video download...")
            # Auto-delete info message after 5 seconds
            asyncio.create_task(delete_message_after_delay(info_msg, 5))
            await cleanup_directory(temp_dir)
            await download_and_send(message, url, 'video', original_msg_id=message.message_id)
            return

        await status_msg.edit_text(f"📤 Sending {len(image_files)} image(s)...")

        # Filter only image files
        valid_images = [f for f in image_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]

        if not valid_images:
            # No valid images - might be a video post, try yt-dlp
            logger.info(f"No valid images for {url}, trying video download")
            info_msg = await status_msg.edit_text("📹 No images found. Trying video download...")
            # Auto-delete info message after 5 seconds
            asyncio.create_task(delete_message_after_delay(info_msg, 5))
            await cleanup_directory(temp_dir)
            await download_and_send(message, url, 'video', original_msg_id=message.message_id)
            return

        # Create delete button for original message
        import hashlib
        delete_hash = hashlib.md5(f"{message.chat.id}:{message.message_id}".encode()).hexdigest()[:8]
        original_messages[delete_hash] = {
            'chat_id': message.chat.id,
            'message_id': message.message_id
        }
        delete_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Delete original message", callback_data=f"del_orig:{delete_hash}")]
        ])

        # Send images
        if len(valid_images) == 1:
            # Single image
            async with aiofiles.open(valid_images[0], 'rb') as f:
                image_data = await f.read()
                photo_input = BufferedInputFile(image_data, filename="image.jpg")
                await message.answer_photo(
                    photo_input,
                    caption=description[:1024] if description else None,
                    reply_markup=delete_keyboard
                )
        else:
            # Multiple images - use media group (max 10 images per Telegram limitation)
            media_group = []
            for idx, img_path in enumerate(valid_images[:10]):  # Telegram max 10 media per group
                async with aiofiles.open(img_path, 'rb') as f:
                    image_data = await f.read()
                    photo_input = BufferedInputFile(image_data, filename=f"image_{idx}.jpg")

                    # Add caption only to first image
                    if idx == 0 and description:
                        media_group.append(InputMediaPhoto(media=photo_input, caption=description[:1024]))
                    else:
                        media_group.append(InputMediaPhoto(media=photo_input))

            await message.answer_media_group(media_group)

            # If more than 10 images, send the rest
            if len(valid_images) > 10:
                for idx, img_path in enumerate(valid_images[10:], start=10):
                    async with aiofiles.open(img_path, 'rb') as f:
                        image_data = await f.read()
                        photo_input = BufferedInputFile(image_data, filename=f"image_{idx}.jpg")
                        await message.answer_photo(photo_input)

            # Send delete button as separate message for media groups
            await message.answer("✅ Images downloaded", reply_markup=delete_keyboard)

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Image download error: {e}", exc_info=True)
        error_msg = await status_msg.edit_text(f"❌ Error downloading images: {str(e)[:100]}")
        # Auto-delete error message after 5 seconds
        asyncio.create_task(delete_message_after_delay(error_msg, 5))

    finally:
        # Cleanup temp directory
        if temp_dir:
            await cleanup_directory(temp_dir)

async def _send_video_file(message: types.Message, filepath: str, status_msg: types.Message, original_url: str = None, caption: str = None):
    """Send a video file from a local path with proper formatting and cleanup."""
    try:
        filesize = os.path.getsize(filepath)
        title = os.path.splitext(os.path.basename(filepath))[0]

        import hashlib
        delete_hash = hashlib.md5(f"{message.chat.id}:{message.message_id}".encode()).hexdigest()[:8]
        original_messages[delete_hash] = {
            'chat_id': message.chat.id,
            'message_id': message.message_id
        }
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Delete original message", callback_data=f"del_orig:{delete_hash}")]
        ])

        if filesize > 50 * 1024 * 1024:
            await update_status(status_msg, "🗜️", "Comprimiendo", 0)
            compressed = await compress_video(
                filepath,
                progress_cb=lambda pct: update_status(status_msg, "🗜️", "Comprimiendo", pct))
            if compressed:
                await cleanup_file(filepath)
                filepath = compressed
                filesize = os.path.getsize(filepath)

        async with aiofiles.open(filepath, 'rb') as f:
            file_data = await f.read()

        video_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp4")

        if original_url:
            video_hash = hashlib.md5(f"{message.chat.id}:{filepath}".encode()).hexdigest()[:8]
            pending_downloads[f"conv:{video_hash}"] = original_url
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎵 Convert to MP3", callback_data=f"convert_mp3:{video_hash}")],
                [InlineKeyboardButton(text="🗑️ Delete original", callback_data=f"del_orig:{delete_hash}")]
            ])

        final_caption = caption[:1024] if caption else None

        if filesize > 50 * 1024 * 1024:
            await message.answer_document(video_input, caption=final_caption, reply_markup=keyboard)
        else:
            await message.answer_video(video_input, caption=final_caption, supports_streaming=True, reply_markup=keyboard)

        # Single status message: show a brief confirmation, then self-delete
        await update_status(status_msg, "✅", "Enviado")
        asyncio.create_task(delete_message_after_delay(status_msg, 10))
    except Exception as e:
        logger.error(f"_send_video_file error: {e}", exc_info=True)
        error_msg = await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
        asyncio.create_task(delete_message_after_delay(error_msg, 10))
    finally:
        await cleanup_file(filepath)

async def _file_has_audio(filepath: str) -> bool:
    """True if the file has an audio stream (ffprobe)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-select_streams', 'a',
            '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', filepath,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return bool(out.decode().strip())
    except Exception:
        return True  # if we can't probe, assume it has audio


async def _best_h264_format_id(url: str) -> str | None:
    """Extract format list and return the best h264 format_id that has a real
    audio track (TikTok's h264 variants carry audio; bytevc1 -1 is video-only)."""
    try:
        opts = {'quiet': True, 'no_warnings': True, 'socket_timeout': 30}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get('formats') or []
        candidates = [f for f in formats
                      if f.get('vcodec') == 'h264' and f.get('acodec') not in (None, 'none')]
        if not candidates:
            candidates = [f for f in formats
                          if (f.get('vcodec') or '').startswith('h264')
                          and f.get('acodec') not in (None, 'none')]
        if not candidates:
            return None
        # pick the highest resolution candidate
        best = max(candidates, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0))
        return best.get('format_id')
    except Exception as e:
        logger.warning(f"_best_h264_format_id error: {e}")
        return None


async def _resolve_filename(ydl, info) -> str | None:
    """Find the actual downloaded file (yt-dlp can pick another extension)."""
    filename = ydl.prepare_filename(info)
    if os.path.exists(filename):
        return filename
    base_name = os.path.splitext(filename)[0]
    for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov', 'mp3', 'm4a']:
        test_file = f"{base_name}.{ext}"
        if os.path.exists(test_file):
            return test_file
    return None


async def download_and_send(message: types.Message, url: str, format_type: str, original_msg_id: int = None, status_msg: types.Message = None, platform_emoji: str = "⏳") -> bool:
    """Download and send a video/audio file. Returns True on success, False on failure.

    Uses a single `status_msg` (created here or passed by the caller) that is
    edited in place with progress bars during download/compress/send, then
    auto-deleted — so status messages never pile up in the group.
    """
    if status_msg is None:
        status_msg = await message.answer(f"{platform_emoji} Descargando...")
    downloaded_file = None

    try:
        ydl_opts = get_ydl_opts(
            url, format_type,
            progress_cb=lambda pct: update_status(status_msg, "⬇️", "Descargando", pct))

        # TikTok's extractor is flaky (intermittent 'universal data for
        # rehydration' errors, and sometimes only video-only formats are
        # listed) — retry up to 3 times, preferring a file WITH audio.
        info = None
        filename = None
        last_file = None
        for intento in range(3):
            try:
                # After a silent attempt, force the best h264+audio format
                # (TikTok's h264 variants carry a real audio track).
                opts = dict(ydl_opts)
                if intento > 0:
                    fmt = await _best_h264_format_id(url)
                    if fmt:
                        opts['format'] = fmt
                        logger.info(f"Retry {intento + 1} forcing h264+audio format: {fmt}")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = await _resolve_filename(ydl, info)
                if filename and await _file_has_audio(filename):
                    break
                if filename:
                    # Downloaded but no audio track (TikTok bytevc1 quirk) — retry
                    last_file = filename
                    if intento < 2:
                        logger.warning(f"Download without audio (attempt {intento + 1}), retrying...")
                        await update_status(status_msg, "🔁", f"Buscando versión con audio ({intento + 2}/3)")
                        filename = None
                    else:
                        # Last attempt still silent — send it anyway
                        filename = last_file
                else:
                    raise yt_dlp.utils.DownloadError("No downloaded file found")
            except yt_dlp.utils.DownloadError as e:
                if intento < 2 and ("universal data" in str(e) or "rehydration" in str(e)):
                    await update_status(status_msg, "🔁", f"Reintentando ({intento + 2}/3)")
                    await asyncio.sleep(3)
                    continue
                raise
        if filename is None:
            filename = last_file

        filesize = os.path.getsize(filename)
        title = info.get('title', 'video')
        downloaded_file = filename

        await update_status(status_msg, "📤", "Enviando")

        async with aiofiles.open(filename, 'rb') as f:
            file_data = await f.read()

            # Create delete button for original message
            import hashlib
            delete_hash = hashlib.md5(f"{message.chat.id}:{original_msg_id or message.message_id}".encode()).hexdigest()[:8]
            original_messages[delete_hash] = {
                'chat_id': message.chat.id,
                'message_id': original_msg_id or message.message_id
            }

            delete_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑️ Delete original message", callback_data=f"del_orig:{delete_hash}")]
            ])

            if format_type == 'audio':
                audio_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp3")
                await message.answer_audio(
                    audio_input,
                    caption=f"**{title[:100]}**",
                    title=title[:100],
                    reply_markup=delete_keyboard
                )
            else:
                # Video - add MP3 convert button and schedule cleanup
                import hashlib
                video_hash = hashlib.md5(f"{message.chat.id}:{filename}".encode()).hexdigest()[:8]
                pending_downloads[f"conv:{video_hash}"] = url

                keyboard_with_mp3 = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🎵 Convert to MP3", callback_data=f"convert_mp3:{video_hash}"),
                        InlineKeyboardButton(text="🗑️ Delete original", callback_data=f"del_orig:{delete_hash}")
                    ]
                ])

                video_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp4")

                if filesize > 50 * 1024 * 1024:
                    # Compress video with ffmpeg (with live progress bar)
                    await update_status(status_msg, "🗜️", "Comprimiendo", 0)
                    compressed_file = await compress_video(
                        filename,
                        progress_cb=lambda pct: update_status(status_msg, "🗜️", "Comprimiendo", pct))
                    if compressed_file:
                        async with aiofiles.open(compressed_file, 'rb') as f:
                            file_data = await f.read()
                        filesize = len(file_data)
                        await cleanup_file(filename)
                        filename = compressed_file
                        title = f"{title[:50]} (compressed)"

                    video_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp4")

                if filesize > 50 * 1024 * 1024:
                    await message.answer_document(
                        video_input,
                        caption=f"**{title[:100]}**",
                        reply_markup=keyboard_with_mp3
                    )
                else:
                    await message.answer_video(
                        video_input,
                        caption=f"**{title[:100]}**",
                        supports_streaming=True,
                        reply_markup=keyboard_with_mp3
                    )

        # Single status message: brief confirmation, then self-delete
        await update_status(status_msg, "✅", "Enviado")
        asyncio.create_task(delete_message_after_delay(status_msg, 10))
        await cleanup_file(filename)
        return True

    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp failed ({e}), trying cobalt...")
        await update_status(status_msg, "🔁", "Intentando método alternativo")

        cobalt_file = await download_via_cobalt(url)

        if cobalt_file:
            filesize = os.path.getsize(cobalt_file)
            title = url.split('/')[-1] or "video"

            await update_status(status_msg, "📤", "Enviando")

            video_input = FSInputFile(cobalt_file, filename="video.mp4")

            if filesize > 50 * 1024 * 1024:
                await message.answer_document(video_input, caption="📥 Downloaded via cobalt")
            else:
                await message.answer_video(
                    video_input,
                    caption="📥 Downloaded via cobalt",
                    supports_streaming=True
                )

            await update_status(status_msg, "✅", "Enviado (cobalt)")
            asyncio.create_task(delete_message_after_delay(status_msg, 10))
            await cleanup_file(cobalt_file)
            return True
        else:
            error_msg = await status_msg.edit_text(
                "❌ Could not download the video.\n\n"
                "It may be private or require login."
            )
            asyncio.create_task(delete_message_after_delay(error_msg, 10))
            return False

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        error_msg = await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
        asyncio.create_task(delete_message_after_delay(error_msg, 10))
        return False

    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            await cleanup_file(downloaded_file)

@dp.callback_query(F.data.startswith("mp3:"))
async def handle_mp3(callback: types.CallbackQuery):
    await callback.answer()
    url_hash = callback.data.split(":", 1)[1]
    url = pending_downloads.get(url_hash)

    if not url:
        await callback.message.edit_text("❌ Link expired. Please send the URL again.")
        return

    # Delete the selection message - download_and_send will create its own status
    await callback.message.delete()
    await download_and_send(callback.message, url, 'audio')

    if url_hash in pending_downloads:
        del pending_downloads[url_hash]

@dp.callback_query(F.data.startswith("mp4:"))
async def handle_mp4(callback: types.CallbackQuery):
    await callback.answer()
    url_hash = callback.data.split(":", 1)[1]
    url = pending_downloads.get(url_hash)

    if not url:
        await callback.message.edit_text("❌ Link expired. Please send the URL again.")
        return

    # Delete the selection message - download_and_send will create its own status
    await callback.message.delete()
    await download_and_send(callback.message, url, 'video')

    if url_hash in pending_downloads:
        del pending_downloads[url_hash]

@dp.callback_query(F.data.startswith("del_orig:"))
async def handle_delete_original(callback: types.CallbackQuery):
    """Handle delete original message button"""
    await callback.answer()
    delete_hash = callback.data.split(":", 1)[1]
    msg_info = original_messages.get(delete_hash)

    if not msg_info:
        await callback.answer("Message info expired", show_alert=True)
        return

    try:
        # Delete the original message
        await bot.delete_message(msg_info['chat_id'], msg_info['message_id'])
        # Remove the delete button from the media message
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Original message deleted!")
    except Exception as e:
        logger.error(f"Failed to delete original message: {e}")
        await callback.answer("Could not delete message", show_alert=True)

    # Clean up
    if delete_hash in original_messages:
        del original_messages[delete_hash]

@dp.callback_query(F.data.startswith("convert_mp3:"))
async def handle_convert_mp3(callback: types.CallbackQuery):
    """Convert downloaded video to MP3"""
    await callback.answer("🎵 Converting to MP3...")

    video_hash = callback.data.split(":", 1)[1]
    url = pending_downloads.get(f"conv:{video_hash}")

    if not url:
        await callback.message.answer("❌ Link expired. Please download again.")
        return

    try:
        temp_dir = tempfile.mkdtemp(prefix="mp3_conv_", dir="downloads")

        status_msg = await callback.message.answer("⏳ Downloading video for conversion...")

        ydl_opts = get_ydl_opts(url, 'video')
        ydl_opts['format'] = 'bestaudio/best'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            if not os.path.exists(filename):
                possible_exts = ['mp4', 'webm', 'mkv', 'avi', 'mov', 'm4a']
                base_name = os.path.splitext(filename)[0]
                for ext in possible_exts:
                    test_file = f"{base_name}.{ext}"
                    if os.path.exists(test_file):
                        filename = test_file
                        break

        # Convert to MP3 using ffmpeg
        await status_msg.edit_text("🎵 Converting to MP3...")

        title = info.get('title', 'audio')[:50]
        mp3_file = os.path.join(temp_dir, f"{title}.mp3")

        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', filename, '-vn', '-acodec', 'libmp3lame',
            '-ab', '192k', '-y', mp3_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if not os.path.exists(mp3_file):
            await status_msg.edit_text("❌ Failed to convert. Video may not have audio.")
            await cleanup_directory(temp_dir)
            return

        # Send MP3
        async with aiofiles.open(mp3_file, 'rb') as f:
            mp3_data = await f.read()

        audio_input = BufferedInputFile(mp3_data, filename=f"{title}.mp3")

        await callback.message.answer_audio(
            audio_input,
            caption=f"🎵 {info.get('title', 'audio')[:100]}"
        )

        await status_msg.edit_text("✅ Converted to MP3!")

        await cleanup_file(filename)
        await cleanup_directory(temp_dir)

    except Exception as e:
        logger.error(f"MP3 conversion error: {e}")
        if 'status_msg' in locals():
            await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")

    if f"conv:{video_hash}" in pending_downloads:
        del pending_downloads[f"conv:{video_hash}"]

async def markov_auto_sender():
    """Background task that sends a Markov-generated message every N minutes."""
    if not MARKOV_ENABLED:
        logger.info("Markov auto-sender is disabled (MARKOV_ENABLED=false)")
        return

    if not MARKOV_CHAT_ID:
        logger.warning("Markov auto-sender cannot start: MARKOV_CHAT_ID is not set")
        return

    if not markov_service.is_model_available():
        logger.warning("Markov auto-sender cannot start: model not available")
        return

    interval_seconds = max(1, MARKOV_INTERVAL_MINUTES) * 60
    logger.info(
        f"Markov auto-sender started: chat={MARKOV_CHAT_ID}, "
        f"interval={MARKOV_INTERVAL_MINUTES}min"
    )

    # Optional: small initial delay so the bot has time to fully connect
    await asyncio.sleep(30)

    while True:
        try:
            sentence = markov_service.generate_markov_sentence()
            await bot.send_message(chat_id=MARKOV_CHAT_ID, text=sentence)
            logger.info(f"Markov auto-message sent to {MARKOV_CHAT_ID}")
        except Exception as e:
            logger.error(f"Markov auto-sender error: {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)


async def markov_retrain_job():
    """Background task that retrains the Markov model periodically."""
    if not MARKOV_LEARN_ENABLED:
        logger.info("Markov learning is disabled")
        return

    if not markov_service.is_model_available():
        logger.warning("Markov retrain job cannot start: model not available")
        return

    interval_seconds = max(1, MARKOV_RETRAIN_INTERVAL_HOURS) * 3600
    logger.info(f"Markov retrain job started (every {MARKOV_RETRAIN_INTERVAL_HOURS}h)")

    # Wait a bit before first retrain so the bot settles in
    await asyncio.sleep(interval_seconds)

    while True:
        try:
            success = await markov_service.retrain_model(model_path=MARKOV_MODEL_PATH)
            if success:
                logger.info("Markov model retrained and hot-reloaded")
            else:
                logger.warning("Markov retraining produced no new model")
        except Exception as e:
            logger.error(f"Markov retrain job error: {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)


async def main():
    try:
        logger.info("Bot starting...")

        # Load Markov model once at startup
        if MARKOV_ENABLED:
            markov_service.load_markov_model(MARKOV_MODEL_PATH)
        else:
            logger.info("Markov feature is disabled")

        # Start background auto-sender if configured
        if MARKOV_ENABLED and markov_service.is_model_available() and MARKOV_CHAT_ID:
            asyncio.create_task(markov_auto_sender())

        # Start background retrain job if learning is enabled
        if MARKOV_ENABLED and MARKOV_LEARN_ENABLED and markov_service.is_model_available():
            asyncio.create_task(markov_retrain_job())

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
