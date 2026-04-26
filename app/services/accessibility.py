"""Accessibility narration rewriter.

Transforms summarised text into narration-optimised plain text that is
pleasant and clear when read aloud by a TTS engine or screen reader:

  • Removes Markdown syntax (bold, italic, links, code spans, headings).
  • Expands common abbreviations and academic shorthand.
  • Replaces symbols with their spoken equivalents.
  • Inserts natural pause cues as punctuation.
  • Adds an optional spoken introduction prefix.
"""
from __future__ import annotations

import re

# ── Abbreviation expansion table ──────────────────────────────────────────────
_ABBREVS: dict[str, str] = {
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\betc\.": "and so on",
    r"\bvs\.": "versus",
    r"\bDr\.": "Doctor",
    r"\bProf\.": "Professor",
    r"\bFig\.": "Figure",
    r"\bSec\.": "Section",
    r"\bCh\.": "Chapter",
    r"\bEd\.": "Edition",
    r"\bpp\.": "pages",
    r"\bp\.": "page",
    r"\bVol\.": "Volume",
    r"\bNo\.": "Number",
    r"\bURL\b": "link",
    r"\bAPI\b": "A P I",
    r"\bSQL\b": "S Q L",
    r"\bCSS\b": "C S S",
    r"\bHTML\b": "H T M L",
    r"\bXML\b": "X M L",
    r"\bJSON\b": "J S O N",
    r"\bUI\b": "user interface",
    r"\bUX\b": "user experience",
    r"\bAI\b": "artificial intelligence",
    r"\bML\b": "machine learning",
    r"\bLLM\b": "large language model",
    r"\bNLP\b": "natural language processing",
    r"\bOCR\b": "optical character recognition",
    r"\bPDF\b": "P D F",
    r"\bKPI\b": "key performance indicator",
    r"\bROI\b": "return on investment",
}

# ── Symbol-to-word replacement table ─────────────────────────────────────────
_SYMBOLS: dict[str, str] = {
    "→": " leads to ",
    "←": " comes from ",
    "↔": " relates to ",
    "⟹": " implies ",
    "≈": " approximately ",
    "≠": " not equal to ",
    "≤": " less than or equal to ",
    "≥": " greater than or equal to ",
    "×": " times ",
    "÷": " divided by ",
    "±": " plus or minus ",
    "°": " degrees ",
    "€": " euros ",
    "$": " dollars ",
    "%": " percent ",
    "&": " and ",
    "@": " at ",
    "#": " number ",
}


def _strip_markdown(text: str) -> str:
    """Remove common Markdown formatting tokens."""
    # Fenced code blocks
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Inline code
    text = re.sub(r"`[^`]+`", lambda m: m.group(0).strip("`"), text)
    # Links: [label](url) → label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Images: ![alt](url) → alt
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Bold / italic
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # ATX headings – keep the text, drop the hashes
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    # Bullet / numbered lists – keep body text
    text = re.sub(r"^[\*\-\+]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "• ", text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _expand_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREVS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _replace_symbols(text: str) -> str:
    for symbol, word in _SYMBOLS.items():
        text = text.replace(symbol, word)
    return text


def _normalise_whitespace(text: str) -> str:
    # Collapse multiple blank lines into a single sentence pause (period + newline).
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Ensure bullet points end with a period for natural TTS pausing.
    text = re.sub(r"(•\s+[^\n.!?]+)(\n)", lambda m: m.group(1).rstrip() + ".\n", text)
    return text.strip()


def rewrite_for_accessibility(
    text: str,
    week_title: str = "",
    language: str = "de",
) -> str:
    """Return a narration-ready version of *text*.

    Args:
        text:        Summary or raw content text.
        week_title:  If provided, prepended as a spoken introduction.
        language:    Language hint (currently informational only).
    """
    if not (text or "").strip():
        return ""

    result = _strip_markdown(text)
    result = _replace_symbols(result)
    result = _expand_abbreviations(result)
    result = _normalise_whitespace(result)

    if week_title:
        result = f"{week_title}.\n\n{result}"

    return result
