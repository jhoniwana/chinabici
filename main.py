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

def get_ydl_opts(url='', format_type='video'):
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    is_reddit = 'reddit.com' in url or 'redd.it' in url

    base_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
    }

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
        base_opts['format'] = 'best[ext=mp4]/best'

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

async def compress_video(input_file: str) -> str | None:
    """Compress video using ffmpeg to reduce size for Telegram"""
    try:
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}_compressed.mp4"

        # Compress: reduce resolution to 720p, lower bitrate
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', input_file,
            '-vf', 'scale=-2:720',
            '-vcodec', 'libx264', '-preset', 'fast',
            '-acodec', 'aac', '-ab', '128k',
            '-crf', '28', '-y', output_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            logger.info(f"Compressed: {os.path.getsize(input_file)} -> {os.path.getsize(output_file)}")
            return output_file

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
        await message.answer("📹 Facebook video detected! Downloading...")
        await download_and_send(message, url, 'video')
    elif is_tiktok(url):
        # TikTok videos
        logger.info(f"TikTok detected: {url}")
        await message.answer("🎵 TikTok detected! Downloading...")
        await download_and_send(message, url, 'video')
    elif is_reddit(url):
        # Reddit images and videos — try images first, fallback to video
        logger.info(f"Reddit detected (images/video): {url}")
        await message.answer("🤖 Reddit detected! Downloading...")
        await download_and_send_images(message, url)
    elif is_twitter(url):
        # Twitter/X videos and images
        logger.info(f"Twitter/X detected: {url}")
        await message.answer("🐦 Twitter/X detected! Downloading...")
        await download_and_send(message, url, 'video')
    elif is_instagram_reel(url) or is_instagram_story(url):
        # Instagram reels and stories are videos - skip image detection
        logger.info(f"Instagram video detected (reel/story): {url}")
        await download_and_send(message, url, 'video')
    elif is_image_platform(url):
        # For Instagram posts and Facebook posts, try images first
        # If it fails or has no images, it will fall back to video
        await download_and_send_images(message, url)
    else:
        # Generic video download for other platforms (1000+ sites)
        logger.info(f"Generic video download: {url}")
        await download_and_send(message, url, 'video')

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

        # For Instagram, use instaloader
        elif 'instagram.com' in url:
            logger.info("Trying instaloader for Instagram...")
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
                    caption=description if description else None,
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
                        media_group.append(InputMediaPhoto(media=photo_input, caption=description))
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

async def download_and_send(message: types.Message, url: str, format_type: str, original_msg_id: int = None):
    status_msg = await message.answer("⏳ Downloading...")

    try:
        ydl_opts = get_ydl_opts(url, format_type)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            if not os.path.exists(filename):
                possible_exts = ['mp4', 'webm', 'mkv', 'avi', 'mov', 'mp3', 'm4a']
                base_name = os.path.splitext(filename)[0]
                for ext in possible_exts:
                    test_file = f"{base_name}.{ext}"
                    if os.path.exists(test_file):
                        filename = test_file
                        break

            filesize = os.path.getsize(filename)
            title = info.get('title', 'video')

            await status_msg.edit_text("📤 Sending...")

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
                        # Compress video with ffmpeg
                        await status_msg.edit_text("🗜️ Compressing large video...")
                        compressed_file = await compress_video(filename)
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

                    # Schedule status message deletion
                    await schedule_message_deletion(status_msg, message.chat.id, status_msg.message_id, 20)

            await status_msg.delete()
            await cleanup_file(filename)

    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp failed ({e}), trying cobalt...")
        await status_msg.edit_text("⏳ Trying alternative method...")

        cobalt_file = await download_via_cobalt(url)

        if cobalt_file:
            filesize = os.path.getsize(cobalt_file)
            title = url.split('/')[-1] or "video"

            await status_msg.edit_text("📤 Sending...")

            video_input = FSInputFile(cobalt_file, filename="video.mp4")

            if filesize > 50 * 1024 * 1024:
                await message.answer_document(video_input, caption="📥 Downloaded via cobalt")
            else:
                await message.answer_video(
                    video_input,
                    caption="📥 Downloaded via cobalt",
                    supports_streaming=True
                )

            await status_msg.delete()
            await cleanup_file(cobalt_file)
        else:
            error_msg = await status_msg.edit_text(
                "❌ Could not download the video.\n\n"
                "It may be private or require login."
            )
            asyncio.create_task(delete_message_after_delay(error_msg, 5))

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        error_msg = await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
        # Auto-delete error message after 5 seconds
        asyncio.create_task(delete_message_after_delay(error_msg, 5))

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
