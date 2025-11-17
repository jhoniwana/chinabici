import asyncio
import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
import yt_dlp
import aiofiles
from gallery_dl import config as gdl_config, job as gdl_job
import tempfile
import shutil
from bs4 import BeautifulSoup
import aiohttp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

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

def get_ydl_opts(url='', format_type='video'):
    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    base_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 3,
    }

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
        base_opts.update({
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
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

def is_image_platform(url: str) -> bool:
    """Check if URL is from a platform that might have images"""
    return 'instagram.com' in url or 'facebook.com' in url

def is_instagram_reel(url: str) -> bool:
    """Check if URL is an Instagram reel (video)"""
    return 'instagram.com' in url and '/reel/' in url

def is_instagram_story(url: str) -> bool:
    """Check if URL is an Instagram story"""
    return 'instagram.com' in url and ('/stories/' in url or '/story/' in url)

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

async def scrape_facebook_images(url: str, temp_dir: str):
    """Scrape images directly from Facebook HTML (fallback method)"""
    try:
        # Use curl via subprocess since aiohttp is being blocked by Facebook
        import subprocess

        curl_command = [
            'curl', '-L', '-A',
            'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
            url
        ]

        result = await asyncio.to_thread(
            subprocess.run,
            curl_command,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"curl failed with return code: {result.returncode}")
            return [], None

        html = result.stdout
        logger.info(f"Fetched {len(html)} bytes of HTML via curl")

        soup = BeautifulSoup(html, 'lxml')

        # Find images and description from Open Graph meta tags
        images = []
        description = None

        # Extract description from og:description
        og_description = soup.find('meta', property='og:description')
        if og_description and og_description.get('content'):
            description = og_description['content']
            logger.info(f"Found description: {description[:100]}")

        # Extract image URLs from og:image meta tags
        og_images = soup.find_all('meta', property='og:image')

        if not og_images:
            logger.info("No og:image tags found")
            return [], None

        for idx, og_img in enumerate(og_images):
            img_url = og_img.get('content')

            if img_url and 'fbcdn.net' in img_url:
                # Unescape HTML entities in the URL
                img_url = img_url.replace('&amp;', '&')

                # Download the image using curl
                try:
                    import subprocess

                    img_filename = os.path.join(temp_dir, f"facebook_image_{idx}.jpg")

                    curl_img_command = [
                        'curl', '-L', '-o', img_filename,
                        '-A', 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                        img_url
                    ]

                    img_result = await asyncio.to_thread(
                        subprocess.run,
                        curl_img_command,
                        capture_output=True,
                        timeout=30
                    )

                    if img_result.returncode == 0 and os.path.exists(img_filename):
                        images.append(img_filename)
                        logger.info(f"Downloaded Facebook image {idx+1} from og:image: {img_filename}")
                    else:
                        logger.error(f"Failed to download image {idx}")
                except Exception as e:
                    logger.error(f"Failed to download image {idx}: {e}")
                    continue

        return images, description

    except Exception as e:
        logger.error(f"Facebook scraping error: {e}")
        return [], None

async def scrape_instagram_images(url: str, temp_dir: str):
    """Scrape images directly from Instagram HTML"""
    try:
        import subprocess

        curl_command = [
            'curl', '-L', '-A',
            'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
            url
        ]

        result = await asyncio.to_thread(
            subprocess.run,
            curl_command,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"curl failed with return code: {result.returncode}")
            return [], None

        html = result.stdout
        logger.info(f"Fetched {len(html)} bytes of HTML via curl from Instagram")

        soup = BeautifulSoup(html, 'lxml')

        images = []
        description = None

        # Extract caption/description from various possible locations
        # Try meta description first
        og_description = soup.find('meta', property='og:description')
        if og_description and og_description.get('content'):
            description = og_description['content']
            logger.info(f"Found Instagram description: {description[:100]}")

        # Find all image tags with cdninstagram.com in src
        img_tags = soup.find_all('img', src=lambda x: x and 'cdninstagram.com' in x)

        if not img_tags:
            logger.info("No Instagram CDN images found in HTML")
            return [], None

        logger.info(f"Found {len(img_tags)} Instagram images")

        for idx, img_tag in enumerate(img_tags):
            img_url = img_tag.get('src')

            if img_url and 'cdninstagram.com' in img_url:
                # Get alt text as additional description
                alt_text = img_tag.get('alt', '')
                if alt_text and not description:
                    description = alt_text

                # Download the image using curl
                try:
                    img_filename = os.path.join(temp_dir, f"instagram_image_{idx}.jpg")

                    curl_img_command = [
                        'curl', '-L', '-o', img_filename,
                        '-A', 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                        img_url
                    ]

                    img_result = await asyncio.to_thread(
                        subprocess.run,
                        curl_img_command,
                        capture_output=True,
                        timeout=30
                    )

                    if img_result.returncode == 0 and os.path.exists(img_filename):
                        # Verify file is actually an image (not an error page)
                        if os.path.getsize(img_filename) > 1000:  # At least 1KB
                            images.append(img_filename)
                            logger.info(f"Downloaded Instagram image {idx+1}: {img_filename}")
                        else:
                            logger.warning(f"Image {idx} too small, skipping")
                            os.remove(img_filename)
                    else:
                        logger.error(f"Failed to download Instagram image {idx}")
                except Exception as e:
                    logger.error(f"Failed to download Instagram image {idx}: {e}")
                    continue

        return images, description

    except Exception as e:
        logger.error(f"Instagram scraping error: {e}")
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

@dp.message()
async def handle_url(message: types.Message):
    if not message.text:
        return

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
    elif is_instagram_reel(url) or is_instagram_story(url):
        # Instagram reels and stories are videos - skip image detection
        logger.info(f"Instagram video detected (reel/story): {url}")
        await download_and_send(message, url, 'video')
    elif is_image_platform(url):
        # For Instagram posts and Facebook, try images first
        # If it fails or has no images, it will fall back to video
        await download_and_send_images(message, url)
    else:
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

        # For Facebook, try HTML scraping
        if 'facebook.com' in url:
            logger.info("Trying Facebook HTML scraping...")
            image_files, description = await scrape_facebook_images(url, temp_dir)

        # For Instagram, try HTML scraping
        elif 'instagram.com' in url:
            logger.info("Trying Instagram HTML scraping...")
            image_files, description = await scrape_instagram_images(url, temp_dir)

        if not image_files:
            # No images found - might be a video post, try yt-dlp
            logger.info(f"No images found for {url}, trying video download")
            await status_msg.edit_text("📹 No images found. Trying video download...")
            await cleanup_directory(temp_dir)
            await download_and_send(message, url, 'video')
            return

        await status_msg.edit_text(f"📤 Sending {len(image_files)} image(s)...")

        # Filter only image files
        valid_images = [f for f in image_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]

        if not valid_images:
            # No valid images - might be a video post, try yt-dlp
            logger.info(f"No valid images for {url}, trying video download")
            await status_msg.edit_text("📹 No images found. Trying video download...")
            await cleanup_directory(temp_dir)
            await download_and_send(message, url, 'video')
            return

        # Send images
        if len(valid_images) == 1:
            # Single image
            async with aiofiles.open(valid_images[0], 'rb') as f:
                image_data = await f.read()
                photo_input = BufferedInputFile(image_data, filename="image.jpg")
                await message.answer_photo(
                    photo_input,
                    caption=description if description else None
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

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Image download error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error downloading images: {str(e)[:100]}")

    finally:
        # Cleanup temp directory
        if temp_dir:
            await cleanup_directory(temp_dir)

async def download_and_send(message: types.Message, url: str, format_type: str):
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

                if format_type == 'audio':
                    audio_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp3")
                    await message.answer_audio(
                        audio_input,
                        caption=f"**{title[:100]}**",
                        title=title[:100]
                    )
                else:
                    video_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp4")
                    if filesize > 50 * 1024 * 1024:
                        await message.answer_document(
                            video_input,
                            caption=f"**{title[:100]}**"
                        )
                    else:
                        await message.answer_video(
                            video_input,
                            caption=f"**{title[:100]}**",
                            supports_streaming=True
                        )

            await status_msg.delete()
            await cleanup_file(filename)

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {e}")
        await status_msg.edit_text(
            f"❌ Download failed\n\n"
            f"The video might be private or unavailable."
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")

@dp.callback_query(F.data.startswith("mp3:"))
async def handle_mp3(callback: types.CallbackQuery):
    await callback.answer()
    url_hash = callback.data.split(":", 1)[1]
    url = pending_downloads.get(url_hash)

    if not url:
        await callback.message.edit_text("❌ Link expired. Please send the URL again.")
        return

    await callback.message.edit_text("⏳ Downloading MP3...")
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

    await callback.message.edit_text("⏳ Downloading MP4...")
    await download_and_send(callback.message, url, 'video')

    if url_hash in pending_downloads:
        del pending_downloads[url_hash]

async def main():
    try:
        logger.info("Bot starting...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
