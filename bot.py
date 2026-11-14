import os
import base64
import logging
import aiohttp
from urllib.parse import unquote
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ARCHIVE_URL = os.environ["ARCHIVE_URL"]
ARCHIVE_FOLDER_ID = os.environ["ARCHIVE_FOLDER_ID"]
ARCHIVE_API_KEY = os.environ.get("ARCHIVE_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


async def ocr_pdf_name(pdf_bytes: bytes) -> str | None:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        img_bytes = doc[0].get_pixmap(dpi=150).tobytes("png")
    except Exception as e:
        logger.warning("PDF render failed: %s", e)
        return None
    try:
        from openai import AsyncOpenAI
        resp = await AsyncOpenAI(api_key=OPENAI_API_KEY).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": (
                    "What is this document? Reply with ONLY a short filename (no extension, no explanation). "
                    "Use the document title or its type + key identifier. Max 80 characters. No slashes. "
                    "Keep the original language — do not transliterate."
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(img_bytes).decode()}"}},
            ]}],
            max_tokens=80,
        )
        name = unquote(resp.choices[0].message.content.strip().strip("\"'"))
        name = "".join(ch for ch in name if ch not in '/\\\0')
        return name or None
    except Exception as e:
        logger.warning("OCR name extraction failed: %s", e)
        return None


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
    filename = unquote(getattr(file_obj, "file_name", None) or tg_file.file_path.split("/")[-1])

    if OPENAI_API_KEY and filename.upper().startswith("DOC") and filename.lower().endswith(".pdf"):
        extracted = await ocr_pdf_name(bytes(file_bytes))
        if extracted:
            logger.info("OCR renamed %s → %s", filename, extracted)
            filename = extracted + ".pdf"

    if len(filename) > 255:
        ext = filename[filename.rfind("."):] if "." in filename else ""
        filename = filename[:255 - len(ext)] + ext

    headers = {"X-API-Key": ARCHIVE_API_KEY} if ARCHIVE_API_KEY else {}

    async with aiohttp.ClientSession() as session:
        form = aiohttp.FormData()
        form.add_field("file", bytes(file_bytes), filename=filename)
        form.add_field("folder_id", ARCHIVE_FOLDER_ID)
        async with session.post(ARCHIVE_URL, data=form, headers=headers) as resp:
            if resp.status >= 400:
                logger.error("Upload failed: %s %s", resp.status, await resp.text())
            else:
                logger.info("Uploaded %s → %s (HTTP %s)", filename, ARCHIVE_FOLDER_ID, resp.status)
                await context.bot.send_message(chat_id=msg.chat_id, text=f"✓ {filename} saved to archive")


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ChatType.GROUPS, handle_channel_post))
app.run_polling()
