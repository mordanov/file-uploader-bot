# Voice message transcription + Russian translation

## Goal
When an audio message (forwarded from Telegram or shared from WhatsApp) is posted in the bot's group,
the bot replies with the Spanish transcript and a cleaned-up Russian translation. Audio is **not** archived.

## Trigger
A group message is an *audio message* if it has:
- `voice` (Telegram voice note), or
- `audio` (audio file, e.g. WhatsApp `PTT-….opus` shared to Telegram), or
- `document` whose `mime_type` starts with `audio/` or whose filename has an audio extension
  (`.opus .ogg .oga .m4a .mp3 .wav .aac .flac .webm`).

All other files (documents, photos, videos) keep the existing archive-upload behavior.

## Flow
1. Download audio bytes via Bot API.
2. Transcribe with OpenAI `gpt-4o-transcribe`, `language="es"`.
3. Translate to Russian with `gpt-4.1` (temperature 0), staying close to the original: keep order, facts, names,
   dates, amounts, tone and ты/вы. Remove only repetition, filler words, false starts and meaningless phrases;
   rephrase vague passages clearly. No retelling, shortening or preamble.
4. Reply to the original message:
   ```
   🇪🇸 Оригинал:
   <transcript>

   🇷🇺 Перевод:
   <translation>
   ```
   Text longer than 4096 chars is split into multiple replies.

## Errors
Reply `⚠️ <reason>` and log, never archive, when:
- `OPENAI_API_KEY` is not set;
- file exceeds 20 MB (Bot API download limit; below OpenAI's 25 MB limit);
- transcription returns empty text;
- any OpenAI call fails.

## Structure
- `voice.py`: `audio_attachment(msg)`, `openai_filename(name) -> str`, `transcribe(client, data, filename) -> str`,
  `translate_ru(client, text) -> str`, `split_message(text, limit=4096) -> list[str]`.
- `bot.py`: routes audio messages to `voice.py`, everything else to the existing upload path.

## Testing
- Unit check of `split_message`.
- Manual end-to-end: real Spanish clip through `transcribe` + `translate_ru` with the real key.
