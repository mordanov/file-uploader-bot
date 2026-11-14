"""Audio message → Spanish transcript + cleaned-up Russian translation via OpenAI."""

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


TRANSLATE_PROMPT = (
    "Ты получаешь расшифровку голосового сообщения на испанском. "
    "Переведи его на русский язык максимально близко к оригиналу: сохрани порядок мыслей, все факты, "
    "просьбы, имена, даты, время, суммы и места, а также тон и обращение (ты/вы). "
    "Убери только повторы, слова-паразиты, оговорки и бессмысленные фразы: "
    "повтор слов и фраз («во вторник, во вторник» → «во вторник»), "
    "вставки вроде eh, bueno, o sea, mira, pues, nada, ¿vale?, ¿eh?, ¿sabes? — без русских аналогов; "
    "при самоисправлении оставь только итоговый вариант («в пять, точнее в пять тридцать» → «в 17:30»). "
    "Расплывчатые или запутанные места сформулируй ясно, не меняя смысла. "
    "Не пересказывай, не сокращай содержание, не добавляй ничего от себя и не пиши вступлений. "
    "Пиши грамотным естественным русским языком, а не калькой с испанского (согласуй род и падежи по-русски). "
    "Ответ — только текст перевода."
)


async def transcribe(client, data: bytes, filename: str) -> str:
    """Spanish speech-to-text."""
    resp = await client.audio.transcriptions.create(
        model="gpt-4o-transcribe",
        file=(openai_filename(filename), data),
        language="es",
    )
    return resp.text.strip()


async def translate_ru(client, text: str) -> str:
    """Russian translation close to the original, cleaned of repetition and filler."""
    resp = await client.chat.completions.create(
        model="gpt-4.1",
        temperature=0,
        messages=[
            {"role": "system", "content": TRANSLATE_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content.strip()
