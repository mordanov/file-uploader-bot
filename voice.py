"""Audio message → Spanish transcript + Russian summary via OpenAI."""

AUDIO_EXTENSIONS = (".opus", ".ogg", ".oga", ".m4a", ".mp3", ".wav", ".aac", ".flac", ".webm")
TELEGRAM_LIMIT = 4096


def audio_attachment(msg):
    """Return the voice/audio/audio-document attachment of a Telegram message, or None."""
    if msg.voice:
        return msg.voice
    if msg.audio:
        return msg.audio
    doc = msg.document
    if doc and ((doc.mime_type or "").startswith("audio/")
                or (doc.file_name or "").lower().endswith(AUDIO_EXTENSIONS)):
        return doc
    return None


def openai_filename(name: str) -> str:
    """Filename with an extension OpenAI transcription accepts (Ogg/Opus variants → .ogg)."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name + ".ogg"
    if ext.lower() in ("oga", "opus"):
        return stem + ".ogg"
    return name


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into chunks of at most `limit` chars, preferring newline boundaries."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


SUMMARY_PROMPT = (
    "Ты получаешь расшифровку голосового сообщения на испанском. "
    "Кратко перескажи его смысл на русском языке. "
    "Если сообщение короткое — 1–3 предложения. "
    "Если длинное — ключевые пункты списком, затем отдельно действия/просьбы, даты, время, суммы и места, если они есть. "
    "Не добавляй вступлений и ничего, чего нет в сообщении."
)


async def transcribe(client, data: bytes, filename: str) -> str:
    """Spanish speech-to-text."""
    resp = await client.audio.transcriptions.create(
        model="gpt-4o-transcribe",
        file=(openai_filename(filename), data),
        language="es",
    )
    return resp.text.strip()


async def summarize_ru(client, text: str) -> str:
    """Adaptive-length Russian summary of a transcript."""
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content.strip()
