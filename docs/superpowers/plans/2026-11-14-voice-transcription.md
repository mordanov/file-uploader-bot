# Voice Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audio messages in the group get a reply with the Spanish transcript and a Russian summary instead of being archived.

**Architecture:** New `voice.py` holds pure helpers (attachment detection, OpenAI filename, message splitting) and two OpenAI calls (transcribe, summarize). `bot.py` routes audio messages to a new `handle_audio` before the existing archive path.

**Tech Stack:** python-telegram-bot 21.6, openai 1.54.3 (`gpt-4o-transcribe`, `gpt-4o-mini`), pytest (dev only).

**Spec:** `docs/superpowers/specs/2026-11-14-voice-transcription-design.md`

**Assumptions:**
- OpenAI transcription accepts `flac mp3 mp4 mpeg mpga m4a ogg wav webm`; Telegram voice is `.oga`, WhatsApp is `.opus` (both Ogg/Opus) → upload as `.ogg`.
- WhatsApp audio shared to Telegram may arrive as a `document` with a non-audio MIME type, so detection also checks the file extension.

---

### Task 1: Contract — `voice.py` signatures

**Files:** Create `voice.py`

- [ ] Write module with signatures + docstrings, bodies `raise NotImplementedError`:
  `audio_attachment(msg)`, `openai_filename(name) -> str`, `split_message(text, limit=4096) -> list[str]`,
  `async transcribe(client, data, filename) -> str`, `async summarize_ru(client, text) -> str`.
- [ ] Verify: `.venv/bin/python -m py_compile voice.py`

### Task 2: Boundary tests (failing)

**Files:** Create `tests/test_voice.py`

- [ ] Tests:
  - `audio_attachment`: voice → voice; audio → audio; document `audio/ogg` → document;
    document `application/octet-stream` named `PTT-1.opus` → document; PDF document → None; photo-only → None.
  - `openai_filename`: `file_1.oga` → `file_1.ogg`; `PTT-1.opus` → `PTT-1.ogg`; `a.m4a` unchanged; `noext` → `noext.ogg`.
  - `split_message`: short text → 1 chunk; text > limit splits on newline, every chunk ≤ limit, `"".join` rebuilds content (minus split newlines); a single unbroken line > limit is hard-cut.
- [ ] Run `.venv/bin/python -m pytest tests -q` → FAIL (NotImplementedError).

### Task 3: Implement pure helpers

- [ ] Implement `audio_attachment`, `openai_filename`, `split_message`.
- [ ] Run tests → PASS. Commit `feat(voice): audio detection, filename + split helpers`.

### Task 4: Implement OpenAI calls

- [ ] `transcribe`: `client.audio.transcriptions.create(model="gpt-4o-transcribe", file=(openai_filename(filename), data), language="es")` → `.text.strip()`.
- [ ] `summarize_ru`: `client.chat.completions.create(model="gpt-4o-mini", messages=[system prompt (adaptive Russian summary, no preamble), user transcript])`.
- [ ] Verify end-to-end: generate a Spanish clip with OpenAI TTS (`opus` format, saved as `.opus`), run `transcribe` + `summarize_ru`; expect Spanish transcript matching the input text and a Russian summary.
- [ ] Commit `feat(voice): transcription and Russian summary`.

### Task 5: Wire into `bot.py`

**Files:** Modify `bot.py` (`handle_channel_post`, new `handle_audio`)

- [ ] At the top of `handle_channel_post`, after `msg` check: `audio = voice.audio_attachment(msg)`; if set → `await handle_audio(msg, audio, context)`; return.
- [ ] `handle_audio`: missing key → `⚠️ OPENAI_API_KEY не задан`; `file_size > 20 MB` → `⚠️ Файл больше 20 МБ`; download; transcribe (empty → `⚠️ Не удалось распознать речь`); summarize; reply chunks of
  `🇪🇸 Оригинал:\n{transcript}\n\n🇷🇺 Кратко:\n{summary}` via `split_message`, replying to the original. Any exception → log + `⚠️ Ошибка обработки аудио: {e}`.
- [ ] Verify: `py_compile bot.py`, tests pass.
- [ ] Update `.env.example` OPENAI comment. Commit `feat(bot): transcribe audio messages instead of archiving`.
