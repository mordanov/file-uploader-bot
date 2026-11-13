import os
import logging
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ARCHIVE_URL = os.environ["ARCHIVE_URL"]
ARCHIVE_FOLDER = os.environ["ARCHIVE_FOLDER"]
ARCHIVE_API_KEY = os.environ.get("ARCHIVE_API_KEY", "")


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    file_obj = msg.document or msg.video or msg.audio or msg.voice
    if msg.photo:
        file_obj = msg.photo[-1]  # largest size

    if not file_obj:
        return

    tg_file = await context.bot.get_file(file_obj.file_id)
    file_bytes = await tg_file.download_as_bytearray()
    filename = getattr(file_obj, "file_name", None) or tg_file.file_path.split("/")[-1]

    headers = {"X-API-Key": ARCHIVE_API_KEY} if ARCHIVE_API_KEY else {}

    async with aiohttp.ClientSession() as session:
        form = aiohttp.FormData()
        form.add_field("file", bytes(file_bytes), filename=filename)
        form.add_field("folder", ARCHIVE_FOLDER)
        async with session.post(ARCHIVE_URL, data=form, headers=headers) as resp:
            if resp.status >= 400:
                logger.error("Upload failed: %s %s", resp.status, await resp.text())
            else:
                logger.info("Uploaded %s → %s (HTTP %s)", filename, ARCHIVE_FOLDER, resp.status)


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ChatType.GROUPS, handle_channel_post))
app.run_polling()
