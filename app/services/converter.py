"""Moodle converter service.

Wraps the existing ``moodle2md.convert_course()`` function and maps its
output into the ``CourseManifest`` / ``WeekPage`` domain models.

The conversion function is synchronous and CPU-intensive, so it is always
executed in a thread-pool executor to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

from app.core.exceptions import ConversionError, SourceDirectoryNotFound
from app.models.course import CourseManifest, WeekPage

logger = logging.getLogger(__name__)


def _markdown_to_plain(markdown: str) -> str:
    """Strip Markdown formatting to produce plain text for summarisation."""
    text = re.sub(r"```[\s\S]*?```", " ", markdown)
    text = re.sub(r"`[^`]+`", lambda m: m.group(0).strip("`"), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\*\-\+]\s+", "  ", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "  ", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{3,}", "  ", text)
    return text.strip()


def _run_conversion(source_dir: str, output_dir: str | None, options: dict) -> dict:
    """Call convert_course() synchronously. Runs in a thread executor."""
    # Ensure the project root is importable regardless of working directory.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from moodle2md import convert_course
    except ImportError as exc:
        raise ConversionError(f"moodle2md module not found: {exc}") from exc

    if not Path(source_dir).is_dir():
        raise SourceDirectoryNotFound(f"Source directory not found: {source_dir}")

    try:
        return convert_course(
            source_dir,
            output_dir or None,
            week_pages=options.get("week_pages", True),
            structured_weeks=options.get("structured_weeks", True),
            single_page=options.get("single_page", False),
            native_week_pages=options.get("native_week_pages", False),
            pdf_text_blocks=options.get("pdf_text_blocks", True),
            pdf_text_max_pages=int(options.get("pdf_text_max_pages", 8)),
            pdf_text_max_chars=int(options.get("pdf_text_max_chars", 20000)),
            # Disable cloud AI/TTS for the local pipeline – handled by services.
            ai_week_summary=False,
            gemini_tts=False,
            elevenlabs_tts=False,
        )
    except Exception as exc:
        raise ConversionError(str(exc)) from exc


def _build_manifest(result: dict) -> CourseManifest:
    output_dir = result.get("output_dir", "")
    raw_manifest: list[dict] = []

    # The converter returns week pages via the AI pipeline manifest.
    # Extract them from the week_pages_manifest stored in the doc/ folder.
    doc_dir = Path(output_dir) / "doc"
    week_pages: list[WeekPage] = []

    if doc_dir.is_dir():
        md_files = sorted(doc_dir.glob("*.md"))
        for idx, md_path in enumerate(md_files, start=1):
            raw_md = md_path.read_text(encoding="utf-8", errors="replace")
            plain = _markdown_to_plain(raw_md)
            # Extract title from first H1 heading or filename stem.
            title_match = re.search(r"^#\s+(.+)$", raw_md, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else md_path.stem
            week_pages.append(
                WeekPage(
                    index=idx,
                    title=title,
                    relative_path=str(md_path.relative_to(output_dir)),
                    plain_text=plain,
                )
            )

    return CourseManifest(
        output_dir=output_dir,
        week_pages=week_pages,
        raw_result=result,
    )


class ConverterService:
    """Async wrapper around the synchronous Moodle converter."""

    async def convert(
        self,
        source_dir: str,
        output_dir: str | None,
        options: dict,
    ) -> CourseManifest:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,  # default thread pool
            _run_conversion,
            source_dir,
            output_dir,
            options,
        )
        return _build_manifest(result)
