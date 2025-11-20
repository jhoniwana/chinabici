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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

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
# Store original message info for delete button
original_messages = {}

async def delete_message_after_delay(message: types.Message, delay: int = 5):
    """Delete a message after specified delay in seconds"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

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
    cookies_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
    if os.path.exists(cookies_path):
        base_opts['cookiefile'] = cookies_path
        logger.info("Using cookies for YouTube authentication")

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
    """Scrape images from Facebook using Selenium to get full description"""
    try:
        def selenium_scrape():
            chrome_options = Options()
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36')

            # Use system chromium
            chromium_path = shutil.which('chromium')
            if chromium_path:
                chrome_options.binary_location = chromium_path

            # Use system chromedriver - check multiple possible locations
            chromedriver_path = shutil.which('chromedriver')
            if not chromedriver_path:
                # Try common locations for different OS (Ubuntu/Debian vs Arch)
                for path in ['/usr/bin/chromedriver', '/usr/sbin/chromedriver', '/usr/local/bin/chromedriver']:
                    if os.path.exists(path):
                        chromedriver_path = path
                        break

            if not chromedriver_path:
                raise FileNotFoundError("chromedriver not found in system")

            driver = None
            try:
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info(f"Using ChromeDriver at: {chromedriver_path}")
                driver.set_page_load_timeout(40)

                logger.info(f"Loading Facebook page with Selenium: {url}")
                driver.get(url)

                # Wait for the body to be present
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(3)

                # Try to close login popups
                close_selectors = [
                    '[aria-label="Close"]',
                    '[aria-label="Cerrar"]',
                    'div[role="button"][aria-label="Close"]'
                ]
                for selector in close_selectors:
                    try:
                        close_btn = driver.find_element(By.CSS_SELECTOR, selector)
                        close_btn.click()
                        time.sleep(1)
                        logger.info(f"Closed popup with: {selector}")
                        break
                    except:
                        pass

                # Click "Ver más" / "See more" button to expand description
                see_more_selectors = [
                    'div[role="button"]:not([aria-label])',  # Generic button divs
                    '[role="button"]'
                ]

                # Try multiple approaches to find "Ver más" or "See more"
                see_more_clicked = False
                try:
                    # Find all role="button" elements and look for text content
                    buttons = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"]')
                    for btn in buttons:
                        btn_text = btn.text.lower().strip()
                        if btn_text in ['ver más', 'see more', 'más', 'more']:
                            try:
                                btn.click()
                                see_more_clicked = True
                                logger.info(f"Clicked 'Ver más' button")
                                time.sleep(2)
                                break
                            except:
                                pass
                except Exception as e:
                    logger.debug(f"See more click attempt failed: {e}")

                # Get full page source after clicking
                html = driver.page_source
                return html

            finally:
                if driver:
                    driver.quit()

        html = await asyncio.to_thread(selenium_scrape)

        if not html:
            logger.error("Failed to get page source from Selenium")
            return [], None

        logger.info(f"Fetched {len(html)} bytes of HTML via Selenium")

        soup = BeautifulSoup(html, 'lxml')

        # Find images and description
        images = []
        description = None

        # Try to get full description from the page content
        # Look for the post text container
        post_text_selectors = [
            'div[data-ad-preview="message"]',
            'div[data-ad-comet-preview="message"]',
            'div[dir="auto"]'
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

        # Fallback to og:description if no better text found
        if not description or len(description) < 50:
            og_description = soup.find('meta', property='og:description')
            if og_description and og_description.get('content'):
                fallback_desc = og_description['content']
                if not description or len(fallback_desc) > len(description):
                    description = fallback_desc

        if description:
            logger.info(f"Found description ({len(description)} chars): {description[:100]}...")

        # Extract image URLs from og:image meta tags
        og_images = soup.find_all('meta', property='og:image')

        if not og_images:
            # Try to find images in the page content
            img_tags = soup.find_all('img')
            for img in img_tags:
                src = img.get('src', '')
                if 'fbcdn.net' in src and 'emoji' not in src:
                    og_images.append({'content': src})

        if not og_images:
            logger.info("No images found")
            return [], description

        # Download images
        import subprocess
        for idx, og_img in enumerate(og_images[:10]):  # Limit to 10 images
            img_url = og_img.get('content') if isinstance(og_img, dict) else og_img.get('content')

            if not img_url:
                continue

            if 'fbcdn.net' in img_url:
                img_url = img_url.replace('&amp;', '&')

                try:
                    img_filename = os.path.join(temp_dir, f"facebook_image_{idx}.jpg")

                    curl_img_command = [
                        'curl', '-L', '-o', img_filename,
                        '-A', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                        img_url
                    ]

                    img_result = await asyncio.to_thread(
                        subprocess.run,
                        curl_img_command,
                        capture_output=True,
                        timeout=30
                    )

                    if img_result.returncode == 0 and os.path.exists(img_filename):
                        # Check file size to filter out tiny images
                        if os.path.getsize(img_filename) > 5000:
                            images.append(img_filename)
                            logger.info(f"Downloaded Facebook image {idx+1}: {img_filename}")
                        else:
                            os.remove(img_filename)
                except Exception as e:
                    logger.error(f"Failed to download image {idx}: {e}")

        return images, description

    except Exception as e:
        logger.error(f"Facebook scraping error: {e}", exc_info=True)
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
                    video_input = BufferedInputFile(file_data, filename=f"{title[:50]}.mp4")
                    if filesize > 50 * 1024 * 1024:
                        await message.answer_document(
                            video_input,
                            caption=f"**{title[:100]}**",
                            reply_markup=delete_keyboard
                        )
                    else:
                        await message.answer_video(
                            video_input,
                            caption=f"**{title[:100]}**",
                            supports_streaming=True,
                            reply_markup=delete_keyboard
                        )

            await status_msg.delete()
            await cleanup_file(filename)

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {e}")
        error_msg = await status_msg.edit_text(
            f"❌ Download failed\n\n"
            f"The video might be private or unavailable."
        )
        # Auto-delete error message after 5 seconds
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
