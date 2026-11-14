import os
import base64
import logging
import mimetypes
import aiohttp
from urllib.parse import unquote
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

import voice

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


MAX_AUDIO_BYTES = 20 * 1024 * 1024  # Bot API download limit


async def handle_audio(msg, audio, context: ContextTypes.DEFAULT_TYPE):
    """Reply with the Spanish transcript and a Russian summary; audio is not archived."""
    if not OPENAI_API_KEY:
        await msg.reply_text("⚠️ OPENAI_API_KEY не задан — расшифровка недоступна")
        return
    if (audio.file_size or 0) > MAX_AUDIO_BYTES:
        await msg.reply_text("⚠️ Файл больше 20 МБ — Telegram не даёт боту его скачать")
        return
    try:
        tg_file = await context.bot.get_file(audio.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        filename = getattr(audio, "file_name", None) or tg_file.file_path.split("/")[-1]

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        transcript = await voice.transcribe(client, data, filename)
        if not transcript:
            await msg.reply_text("⚠️ Не удалось распознать речь")
            return
        summary = await voice.summarize_ru(client, transcript)
    except Exception as e:
        logger.exception("Audio processing failed")
        await msg.reply_text(f"⚠️ Ошибка обработки аудио: {e}")
        return

    logger.info("Transcribed %s (%d chars)", filename, len(transcript))
    text = f"🇪🇸 Оригинал:\n{transcript}\n\n🇷🇺 Кратко:\n{summary}"
    for chunk in voice.split_message(text):
        await msg.reply_text(chunk)


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    audio = voice.audio_attachment(msg)
    if audio:
        await handle_audio(msg, audio, context)
        return

    file_obj = msg.document or msg.video
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
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with aiohttp.MultipartWriter("form-data") as mp:
            mp.append(bytes(file_bytes), {
                "Content-Type": content_type,
                "Content-Disposition": f'form-data; name="file"; filename="{filename}"',
            })
            mp.append(ARCHIVE_FOLDER_ID, {
                "Content-Disposition": 'form-data; name="folder_id"',
            })
        async with session.post(ARCHIVE_URL, data=mp, headers=headers) as resp:
            if resp.status >= 400:
                logger.error("Upload failed: %s %s", resp.status, await resp.text())
            else:
                logger.info("Uploaded %s → %s (HTTP %s)", filename, ARCHIVE_FOLDER_ID, resp.status)
                await context.bot.send_message(chat_id=msg.chat_id, text=f"✓ {filename} saved to archive")


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ChatType.GROUPS, handle_channel_post))
app.run_polling()
