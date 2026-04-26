"""Semantic Markdown chunker.

Splits a Markdown document into semantically coherent chunks by:
  1. Detecting heading boundaries (ATX-style # / ## / ###).
  2. Respecting a configurable max_chars limit per chunk.
  3. Carrying a breadcrumb of parent headings into each chunk for LLM context.
  4. Optionally overlapping adjacent chunks by a fixed number of characters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RawSection:
    heading_path: str       # "H1 > H2 > H3" breadcrumb
    level: int              # heading depth (1-6); 0 = document preamble
    content: str = ""       # body text under this heading


@dataclass
class Chunk:
    heading_path: str
    content: str
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.char_count = len(self.content)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _split_into_sections(markdown: str) -> list[RawSection]:
    """Parse Markdown into a list of (heading, body) sections."""
    sections: list[RawSection] = []
    lines = markdown.splitlines(keepends=True)
    heading_stack: list[str] = []   # tracks current heading breadcrumb per level
    current_level = 0
    current_heading_path = ""
    buffer: list[str] = []

    def flush(hp: str, lvl: int) -> None:
        body = "".join(buffer).strip()
        if body or hp:
            sections.append(RawSection(heading_path=hp, level=lvl, content=body))
        buffer.clear()

    for line in lines:
        m = _HEADING_RE.match(line.rstrip())
        if m:
            flush(current_heading_path, current_level)
            level = len(m.group(1))
            title = m.group(2).strip()
            # Trim stack to current depth and update
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_level = level
            current_heading_path = " > ".join(heading_stack)
        else:
            buffer.append(line)

    flush(current_heading_path, current_level)
    return sections


def _merge_sections_into_chunks(
    sections: list[RawSection],
    max_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Greedily merge consecutive sections into chunks that respect max_chars."""
    chunks: list[Chunk] = []
    pending_parts: list[str] = []
    pending_hp: str = ""
    pending_len: int = 0
    overlap_tail: str = ""

    def emit(hp: str, parts: list[str]) -> None:
        nonlocal overlap_tail
        body = "\n\n".join(p for p in parts if p).strip()
        if overlap_tail:
            body = overlap_tail.strip() + "\n\n" + body
        if body:
            chunks.append(Chunk(heading_path=hp, content=body))
        # Keep the tail of this chunk for overlap with the next one.
        overlap_tail = body[-overlap_chars:] if overlap_chars > 0 else ""

    for section in sections:
        header_line = (
            f"{'#' * section.level} {section.heading_path.split(' > ')[-1]}\n\n"
            if section.level > 0
            else ""
        )
        block = (header_line + section.content).strip()
        block_len = len(block)

        if block_len > max_chars:
            # Section is larger than the chunk limit: sub-split at paragraph level.
            if pending_parts:
                emit(pending_hp, pending_parts)
                pending_parts, pending_hp, pending_len = [], section.heading_path, 0

            paragraphs = re.split(r"\n{2,}", block)
            sub_buf: list[str] = []
            sub_len = 0
            for para in paragraphs:
                para_len = len(para)
                if sub_len + para_len > max_chars and sub_buf:
                    emit(section.heading_path, sub_buf)
                    sub_buf, sub_len = [], 0
                sub_buf.append(para)
                sub_len += para_len
            if sub_buf:
                emit(section.heading_path, sub_buf)
            continue

        if pending_len + block_len > max_chars and pending_parts:
            emit(pending_hp, pending_parts)
            pending_parts, pending_hp, pending_len = [], section.heading_path, 0

        if not pending_parts:
            pending_hp = section.heading_path
        pending_parts.append(block)
        pending_len += block_len

    if pending_parts:
        emit(pending_hp, pending_parts)

    return chunks


def chunk_markdown(
    markdown: str,
    max_chars: int = 8000,
    overlap_chars: int = 200,
    min_chars: int = 100,
) -> list[Chunk]:
    """Public entry point: returns a list of Chunk objects."""
    if not (markdown or "").strip():
        return []
    sections = _split_into_sections(markdown)
    chunks = _merge_sections_into_chunks(sections, max_chars=max_chars, overlap_chars=overlap_chars)
    # Drop chunks that are too short to be meaningful.
    return [c for c in chunks if c.char_count >= min_chars]
