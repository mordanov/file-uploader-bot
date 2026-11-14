#!/usr/bin/env python3
"""
One-time backfill: send all PDFs from a Telegram group to the family archive.

Usage:
    pip install telethon aiohttp python-dotenv qrcode
    python backfill.py [--env /path/to/.env] <group_username_or_id>

On VPS:
    python backfill.py --env ~/web-folders/.env @your_group
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
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import DocumentAttributeFilename

# parse optional --env /path/.env before the positional group arg
_args = sys.argv[1:]
if len(_args) >= 2 and _args[0] == "--env":
    load_dotenv(_args[1])
    sys.argv = [sys.argv[0]] + _args[2:]
else:
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


_CODE_TYPES = {
    "SentCodeTypeApp": "Telegram app — open the 'Telegram' service chat (blue checkmark) on a logged-in device",
    "SentCodeTypeSms": "SMS",
    "SentCodeTypeCall": "phone call",
    "SentCodeTypeFlashCall": "flash call (code is the last digits of the calling number)",
    "SentCodeTypeMissedCall": "missed call (code is the last digits of the calling number)",
    "SentCodeTypeEmailCode": "your login email",
    "SentCodeTypeFragmentSms": "Fragment (fragment.com) anonymous number",
    "SentCodeTypeFirebaseSms": "SMS (Firebase) — usually not delivered to third-party apps",
}


def _describe(code_type) -> str:
    name = type(code_type).__name__
    return _CODE_TYPES.get(name, name)


async def qr_login(client: TelegramClient):
    """Login by scanning a QR code in the Telegram app — no login code needed."""
    import qrcode
    qr = await client.qr_login()
    while True:
        q = qrcode.QRCode(border=1)
        q.add_data(qr.url)
        q.print_ascii(invert=True)
        print("Telegram app → Settings → Devices → Link Desktop Device → scan the QR above")
        try:
            await qr.wait(timeout=30)
            return
        except asyncio.TimeoutError:
            print("QR expired, generating a new one...\n")
            await qr.recreate()


async def login(client: TelegramClient):
    """Interactive login. Defaults to QR; phone-code login reports where Telegram sent the code (start() hides this)."""
    await client.connect()
    if await client.is_user_authorized():
        return
    phone = input("Phone number in international format (e.g. +4917...), or Enter for QR login: ").strip()
    if not phone:
        try:
            await qr_login(client)
        except SessionPasswordNeededError:
            await client.sign_in(password=input("2FA password: "))
        return
    sent = await client.send_code_request(phone)
    while True:
        print(f"Code sent via: {_describe(sent.type)}")
        if sent.next_type:
            print(f"  (type 'r' to resend via: {_describe(sent.next_type)}"
                  + (f", available after {sent.timeout}s)" if sent.timeout else ")"))
        code = input("Enter code: ").strip()
        if code.lower() == "r":
            sent = await client.send_code_request(phone)  # Telethon issues ResendCodeRequest on repeat
            continue
        break
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        await client.sign_in(password=input("2FA password: "))


async def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python backfill.py <group_username_or_id>")
    group = sys.argv[1]
    try:
        group = int(group)
    except ValueError:
        pass

    session = os.environ.get("TELEGRAM_SESSION", "backfill_session")
    client = TelegramClient(session, API_ID, API_HASH)
    await login(client)
    # Message IDs already uploaded; lets a re-run resume after a crash without duplicates
    done_path = f"{session}.{group}.done"
    done = set()
    if os.path.exists(done_path):
        with open(done_path) as f:
            done = {int(line) for line in f if line.strip()}
        print(f"Skipping {len(done)} already uploaded message(s) listed in {done_path}")

    async with client:
        total = ok = 0
        failed = []
        async for msg in client.iter_messages(group):
            if not msg.document or msg.id in done:
                continue
            attr = next((a for a in msg.document.attributes if isinstance(a, DocumentAttributeFilename)), None)
            if not attr:
                continue
            filename = attr.file_name
            # Files without an extension (e.g. WhatsApp "DOC-...-WA0001.") are assumed to be PDFs
            stem, dot, ext = filename.rpartition(".")
            if not dot or not ext:
                filename = (stem or ext) + ".pdf"
            elif ext.lower() != "pdf":
                continue

            total += 1
            print(f"[msg {msg.id}] {filename}")

            file_bytes = None
            for attempt in range(1, 4):
                try:
                    file_bytes = await msg.download_media(bytes)
                    break
                except Exception as e:
                    print(f"  download attempt {attempt}/3 failed: {e}")
                    await asyncio.sleep(10 * attempt)
            if file_bytes is None:
                failed.append(msg.id)
                continue

            if OPENAI_API_KEY and filename.upper().startswith("DOC") and filename.lower().endswith(".pdf"):
                extracted = await ocr_name(file_bytes)
                if extracted:
                    print(f"  OCR: {filename} → {extracted}")
                    filename = extracted + ".pdf"

            if await upload(filename, file_bytes):
                ok += 1
                with open(done_path, "a") as f:
                    f.write(f"{msg.id}\n")
            else:
                failed.append(msg.id)

        print(f"\nDone: {ok}/{total} PDFs uploaded")
        if failed:
            print(f"Failed message IDs (re-run to retry): {failed}")


asyncio.run(main())
