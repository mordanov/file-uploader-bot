# Voice message transcription + Russian summary

## Goal
When an audio message (forwarded from Telegram or shared from WhatsApp) is posted in the bot's group,
the bot replies with the Spanish transcript and a Russian summary. Audio is **not** archived.

## Trigger
A group message is an *audio message* if it has:
- `voice` (Telegram voice note), or
- `audio` (audio file, e.g. WhatsApp `PTT-….opus` shared to Telegram), or
- `document` whose `mime_type` starts with `audio/`.

All other files (documents, photos, videos) keep the existing archive-upload behavior.

## Flow
1. Download audio bytes via Bot API.
2. Transcribe with OpenAI `gpt-4o-transcribe`, `language="es"`.
3. Summarize transcript in Russian with `gpt-4o-mini`. Adaptive length: 1–3 sentences for short
   messages; key points + action items/dates/numbers for long ones. No preamble.
4. Reply to the original message:
   ```
   🇪🇸 Оригинал:
   <transcript>

   🇷🇺 Кратко:
   <summary>
   ```
   Text longer than 4096 chars is split into multiple replies.

## Errors
Reply `⚠️ <reason>` and log, never archive, when:
- `OPENAI_API_KEY` is not set;
- file exceeds 20 MB (Bot API download limit; below OpenAI's 25 MB limit);
- transcription returns empty text;
- any OpenAI call fails.

## Structure
- `voice.py`: `is_audio(msg)`, `transcribe(data, filename) -> str`, `summarize_ru(text) -> str`,
  `split_message(text, limit=4096) -> list[str]`.
- `bot.py`: routes audio messages to `voice.py`, everything else to the existing upload path.

## Testing
- Unit check of `split_message`.
- Manual end-to-end: real Spanish clip through `transcribe` + `summarize_ru` with the real key.
