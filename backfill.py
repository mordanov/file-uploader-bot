#!/usr/bin/env python3
"""
One-time backfill: send all PDFs from a Telegram group to the family archive.

Usage:
    pip install telethon
    python backfill.py <group_username_or_id>

Required env (same .env as the bot):
    TELEGRAM_API_ID, TELEGRAM_API_HASH
    ARCHIVE_URL, ARCHIVE_FOLDER_ID
Optional:
    ARCHIVE_API_KEY
    OPENAI_API_KEY  — enables OCR rename for files whose name starts with DOC
"""
import asyncio
import base64
import mimetypes
import os
import sys
from urllib.parse import unquote

import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

load_dotenv()

# On VPS the shared .env uses FILE_UPLOADER_BOT_* prefixes; fall back to bare names for local dev.
def _e(name, default=""):
    return os.environ.get(f"FILE_UPLOADER_BOT_{name}") or os.environ.get(name, default)

API_ID     = int(_e("TELEGRAM_API_ID") or sys.exit("Missing TELEGRAM_API_ID / FILE_UPLOADER_BOT_TELEGRAM_API_ID"))
API_HASH   = _e("TELEGRAM_API_HASH") or sys.exit("Missing TELEGRAM_API_HASH / FILE_UPLOADER_BOT_TELEGRAM_API_HASH")
# ARCHIVE_URL has a docker-internal default; for backfill supply the public URL via FILE_UPLOADER_BOT_ARCHIVE_URL
ARCHIVE_URL       = _e("ARCHIVE_URL") or sys.exit("Missing ARCHIVE_URL / FILE_UPLOADER_BOT_ARCHIVE_URL")
ARCHIVE_FOLDER_ID = _e("ARCHIVE_FOLDER_ID") or sys.exit("Missing ARCHIVE_FOLDER_ID / FILE_UPLOADER_BOT_ARCHIVE_FOLDER_ID")
# On VPS the key lives under ARCHIVE_SORTOUT_API_KEY (shared across services)
ARCHIVE_API_KEY   = _e("ARCHIVE_API_KEY") or os.environ.get("ARCHIVE_SORTOUT_API_KEY", "")
OPENAI_API_KEY    = _e("OPENAI_API_KEY")


async def ocr_name(pdf_bytes: bytes) -> str | None:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        img_bytes = doc[0].get_pixmap(dpi=150).tobytes("png")
    except Exception as e:
        print(f"  [ocr] render failed: {e}")
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
        print(f"  [ocr] failed: {e}")
        return None


async def upload(filename: str, file_bytes: bytes) -> bool:
    if len(filename) > 255:
        ext = filename[filename.rfind("."):] if "." in filename else ""
        filename = filename[:255 - len(ext)] + ext
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    req_headers = {"X-API-Key": ARCHIVE_API_KEY} if ARCHIVE_API_KEY else {}
    async with aiohttp.ClientSession() as session:
        with aiohttp.MultipartWriter("form-data") as mp:
            mp.append(file_bytes, {
                "Content-Type": content_type,
                "Content-Disposition": f'form-data; name="file"; filename="{filename}"',
            })
            mp.append(ARCHIVE_FOLDER_ID, {"Content-Disposition": 'form-data; name="folder_id"'})
        async with session.post(ARCHIVE_URL, data=mp, headers=req_headers) as resp:
            body = await resp.text()
            if resp.status >= 400:
                print(f"  ERROR {resp.status}: {body}")
                return False
            print(f"  → {filename}")
            return True


async def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python backfill.py <group_username_or_id>")
    group = sys.argv[1]
    try:
        group = int(group)
    except ValueError:
        pass

    async with TelegramClient("backfill_session", API_ID, API_HASH) as client:
        total = ok = 0
        async for msg in client.iter_messages(group):
            if not msg.document:
                continue
            attr = next((a for a in msg.document.attributes if isinstance(a, DocumentAttributeFilename)), None)
            if not attr or not attr.file_name.lower().endswith(".pdf"):
                continue

            total += 1
            filename = attr.file_name
            print(f"[msg {msg.id}] {filename}")

            file_bytes = await msg.download_media(bytes)

            if OPENAI_API_KEY and filename.upper().startswith("DOC") and filename.lower().endswith(".pdf"):
                extracted = await ocr_name(file_bytes)
                if extracted:
                    print(f"  OCR: {filename} → {extracted}")
                    filename = extracted + ".pdf"

            if await upload(filename, file_bytes):
                ok += 1

        print(f"\nDone: {ok}/{total} PDFs uploaded")


asyncio.run(main())
