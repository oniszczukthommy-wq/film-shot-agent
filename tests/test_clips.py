"""Export guard rails. ffmpeg itself is replaced by a stub, so this runs offline."""

import pytest

from film_shot_agent.services import clips


def test_rejects_unknown_format(session):
    with pytest.raises(clips.ExportError):
        clips.export_shot(session, "alpha-000", "webm")


def test_rejects_unknown_shot(session):
    with pytest.raises(clips.ExportError):
        clips.export_shot(session, "ghost", "mp4")


def test_reports_missing_source_file(session):
    with pytest.raises(clips.ExportError):
        clips.export_shot(session, "alpha-000", "mp4")


def test_export_calls_ffmpeg_once_and_reuses_cache(session, tmp_path, monkeypatch):
    source = tmp_path / "alpha.mp4"
    source.write_bytes(b"fake")
    title = session.get(clips.Title, "t-alpha")
    title.source_file = str(source)
    session.flush()

    calls = []

    def fake_clip(path, start_ms, end_ms, out):
        calls.append((start_ms, end_ms, out))
        out.write_bytes(b"mp4")

    monkeypatch.setattr(clips.ffmpeg, "make_clip", fake_clip)
    first, media = clips.export_shot(session, "alpha-000", "mp4")
    second, _ = clips.export_shot(session, "alpha-000", "mp4")

    assert media == "video/mp4"
    assert first == second
    assert len(calls) == 1, "同一镜头同一格式只应渲染一次"


def test_gif_uses_the_requested_width(session, tmp_path, monkeypatch):
    source = tmp_path / "alpha.mp4"
    source.write_bytes(b"fake")
    session.get(clips.Title, "t-alpha").source_file = str(source)
    session.flush()

    widths: list[int] = []

    def fake_gif(path, start, end, out, width):
        widths.append(width)
        out.write_bytes(b"gif")

    monkeypatch.setattr(clips.ffmpeg, "make_gif", fake_gif)
    _, media = clips.export_shot(session, "alpha-002", "gif-l")
    assert media == "image/gif"
    assert widths == [960]
