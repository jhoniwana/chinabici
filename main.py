import asyncio
import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
import yt_dlp
import aiofiles

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

def get_ydl_opts():
    return {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'format': 'best[ext=mp4]/best',
        'socket_timeout': 30,
        'retries': 3,
    }

async def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            await asyncio.to_thread(os.remove, filepath)
            logger.info(f"Cleaned up: {filepath}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def is_valid_url(url: str) -> bool:
    return url.startswith(('http://', 'https://'))

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "**Video Downloader Bot**\n\n"
        "Send me any video link and I'll download it for you.\n\n"
        "Supported: YouTube, Instagram, TikTok, Facebook, Twitter, and 1000+ sites"
    )

@dp.message()
async def download_video(message: types.Message):
    if not message.text:
        return

    text = message.text.strip()

    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)

    if not urls:
        return

    url = urls[0]

    status_msg = await message.answer("⏳ Downloading...")

    try:
        ydl_opts = get_ydl_opts()

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
                video_data = await f.read()
                video_input = BufferedInputFile(video_data, filename=f"{title[:50]}.mp4")

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
