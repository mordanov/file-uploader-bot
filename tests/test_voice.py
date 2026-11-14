from types import SimpleNamespace as NS

import pytest

from voice import audio_attachment, openai_filename, split_message


def msg(**kw):
    return NS(**{"voice": None, "audio": None, "document": None, "photo": None, **kw})


@pytest.mark.parametrize("m, expected_attr", [
    (msg(voice=NS(file_id="v")), "voice"),
    (msg(audio=NS(file_id="a")), "audio"),
    (msg(document=NS(mime_type="audio/ogg", file_name="x")), "document"),
    (msg(document=NS(mime_type="application/octet-stream", file_name="PTT-1.opus")), "document"),
    (msg(document=NS(mime_type="application/pdf", file_name="a.pdf")), None),
    (msg(document=NS(mime_type=None, file_name=None)), None),
    (msg(photo=[NS(file_id="p")]), None),
])
def test_audio_attachment(m, expected_attr):
    expected = getattr(m, expected_attr) if expected_attr else None
    assert audio_attachment(m) is expected


@pytest.mark.parametrize("name, expected", [
    ("file_1.oga", "file_1.ogg"),
    ("PTT-1.OPUS", "PTT-1.ogg"),
    ("a.m4a", "a.m4a"),
    ("noext", "noext.ogg"),
])
def test_openai_filename(name, expected):
    assert openai_filename(name) == expected


def test_split_short_text_is_single_chunk():
    assert split_message("hola", limit=10) == ["hola"]


def test_split_prefers_newlines_and_respects_limit():
    lines = [f"line{i:02d}" for i in range(10)]  # 6 chars each
    chunks = split_message("\n".join(lines), limit=20)
    assert all(len(c) <= 20 for c in chunks)
    assert [l for c in chunks for l in c.split("\n")] == lines


def test_split_hard_cuts_long_line():
    chunks = split_message("x" * 25, limit=10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]
