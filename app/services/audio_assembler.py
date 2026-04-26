"""Audio assembly service – concatenate per-week WAV files into a
chapterized MP3 using ffmpeg, with proper ID3 chapter metadata.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

from app.core.exceptions import AudioAssemblyError, FfmpegNotFound
from app.models.audio import ChapterEntry, ChapterizedAudio

logger = logging.getLogger(__name__)


def _require_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise FfmpegNotFound(
            "ffmpeg binary not found on PATH. "
            "Install it with: brew install ffmpeg  or  apt-get install ffmpeg"
        )
    except subprocess.CalledProcessError as exc:
        raise FfmpegNotFound(f"ffmpeg check failed: {exc}") from exc


def _wav_duration(path: Path) -> float:
    """Read duration in seconds from a WAV file header (no ffprobe needed)."""
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate) if rate > 0 else 0.0
    except Exception:
        return 0.0


def _probe_duration(path: Path, ffmpeg_fallback: bool = True) -> float:
    """Probe audio duration in seconds, WAV-native first then ffprobe."""
    suffix = path.suffix.lower()
    if suffix == ".wav":
        dur = _wav_duration(path)
        if dur > 0:
            return dur

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", str(path),
            ],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            dur_str = stream.get("duration") or ""
            if dur_str:
                return float(dur_str)
    except Exception as exc:
        logger.debug("ffprobe failed for %s: %s", path.name, exc)
    return 0.0


def assemble_chapterized_mp3(
    audio_paths: list[tuple[str, Path]],  # [(chapter_title, audio_path), ...]
    output_path: Path,
    audio_quality: str = "4",
) -> ChapterizedAudio:
    """Concatenate audio files and embed chapter metadata into a single MP3.

    Args:
        audio_paths:   Ordered list of (chapter title, audio file path) tuples.
        output_path:   Destination MP3 file path.
        audio_quality: libmp3lame -q:a value (2=highest, 9=lowest, 4=default).

    Returns:
        ChapterizedAudio with output path, total duration, and chapter list.
    """
    if not audio_paths:
        raise AudioAssemblyError("No audio segments provided for assembly")

    _require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Build chapter entries with cumulative timestamps ──────────────────────
    chapters: list[ChapterEntry] = []
    cumulative_ms = 0
    for title, path in audio_paths:
        if not path.exists():
            logger.warning("Audio segment not found, skipping: %s", path)
            continue
        dur = _probe_duration(path)
        dur_ms = max(1, int(dur * 1000))
        chapters.append(
            ChapterEntry(
                title=title,
                audio_path=str(path),
                start_ms=cumulative_ms,
                end_ms=cumulative_ms + dur_ms,
            )
        )
        cumulative_ms += dur_ms

    if not chapters:
        raise AudioAssemblyError("All audio segments were missing or unreadable")

    total_seconds = cumulative_ms / 1000.0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        concat_file = tmp / "concat.txt"
        meta_file = tmp / "chapters.ini"
        concat_raw = tmp / "concat_raw.mp3"

        # ── ffmpeg concat list ────────────────────────────────────────────────
        with concat_file.open("w", encoding="utf-8") as f:
            for ch in chapters:
                safe = ch.audio_path.replace("'", r"'\''")
                f.write(f"file '{safe}'\n")

        # ── ffmetadata chapter block ──────────────────────────────────────────
        with meta_file.open("w", encoding="utf-8") as f:
            f.write(";FFMETADATA1\n")
            for ch in chapters:
                escaped = (
                    ch.title
                    .replace("\\", "\\\\")
                    .replace("=", r"\=")
                    .replace(";", r"\;")
                    .replace("#", r"\#")
                )
                f.write(
                    f"\n[CHAPTER]\nTIMEBASE=1/1000\n"
                    f"START={ch.start_ms}\nEND={ch.end_ms}\ntitle={escaped}\n"
                )

        # ── Pass 1: concatenate to raw MP3 ────────────────────────────────────
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c:a", "libmp3lame", "-q:a", audio_quality,
                    str(concat_raw),
                ],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")[-500:]
            raise AudioAssemblyError(f"ffmpeg concat failed: {stderr}") from exc

        # ── Pass 2: embed chapter metadata ────────────────────────────────────
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(concat_raw),
                    "-i", str(meta_file),
                    "-map_metadata", "1",
                    "-codec", "copy",
                    str(output_path),
                ],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")[-500:]
            raise AudioAssemblyError(f"ffmpeg chapter embed failed: {stderr}") from exc

    logger.info("Chapterized MP3 created: %s (%.1fs, %d chapters)", output_path, total_seconds, len(chapters))
    return ChapterizedAudio(
        output_path=str(output_path),
        total_duration_seconds=total_seconds,
        chapters=chapters,
    )
