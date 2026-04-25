#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Moodle2AffineMD
# Based on the original `moodle2md` project by José Domingo Muñoz Rodríguez:
# https://github.com/josedom24/moodle2md
from lxml import etree
import os,shutil
import re
import json
import unicodedata
import argparse
import zipfile
import mimetypes
import hashlib
import base64
import time
import uuid
import io
import platform
import subprocess
import sys
from html import unescape, escape
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen



def _is_rosetta_translated_process():
    if sys.platform != "darwin":
        return False
    try:
        value = subprocess.check_output(["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"], text=True).strip()
        return value == "1"
    except Exception:
        return False


def assert_supported_runtime():
    if sys.platform != "darwin":
        return

    host_arch = ""
    try:
        host_arch = subprocess.check_output(["/usr/bin/uname", "-m"], text=True).strip().lower()
    except Exception:
        host_arch = platform.machine().lower()

    if host_arch in {"arm64", "aarch64"} and _is_rosetta_translated_process():
        raise RuntimeError(
            "Unsupported Python runtime: running under Rosetta (x86_64 translated) on Apple Silicon. "
            "Please use a native arm64 Python and recreate .venv."
        )


def getNombreFichero(nombre):
    nombre=elimina_tildes(nombre)
    nombre=elimina_caracteres_nombre_fichero(nombre)
    return nombre+".md"

def elimina_tildes(cadena):
    cadena = "" if cadena is None else str(cadena)
    s = ''.join(c for c in unicodedata.normalize('NFD', cadena) if unicodedata.category(c) != 'Mn')
    return s

def elimina_caracteres_nombre_fichero(nomfich):
    car=("/","?","(",")"," ")
    for c in car:
        nomfich=nomfich.replace(c,"_")
    return nomfich

def crear_fichero(fich,dir):
    with open(dir+fich, "w", encoding="utf-8"):
        pass

def escribir(dir,fich,texto="\n"):
    texto = "" if texto is None else str(texto)
    with open(dir+fich, "a", encoding="utf-8") as fichero:
        fichero.write(texto)
        if len(texto)>1 and texto[-1]!="\n":
            fichero.write("\n")

def images(html, media_prefix="img/"):
    if html is None:
        return ""
    html = str(html)
    html = html.replace("$@FILEPHP@$$@SLASH@$img$@SLASH@$", media_prefix)
    html = html.replace("$@FILEPHP@$$@SLASH@$", media_prefix)
    html = html.replace("@@PLUGINFILE@@/", media_prefix)
    return html


def encode_relative_path(path):
    if path is None:
        return ""
    path = str(path).strip().replace("\\", "/")
    if re.match(r"^[a-z]+://", path, flags=re.IGNORECASE) or path.startswith("#"):
        return path
    return "/".join(quote(part, safe="._-()") for part in path.split("/"))


def ensure_explicit_relative_path(path):
    path = "" if path is None else str(path).strip().replace("\\", "/")
    if not path:
        return ""
    if re.match(r"^[a-z]+://", path, flags=re.IGNORECASE) or path.startswith(("#", "./", "../", "/")):
        return path
    return f"./{path}"


RUNTIME_OPTIONS = {
    "pdf_text_blocks": False,
    "pdf_text_engine": "auto",
    "pdf_text_max_pages": 8,
    "pdf_text_max_chars": 20000,
    "pdf_text_ocr_fallback": False,
    "pdf_text_ocr_lang": "eng",
}

PDF_TEXT_CACHE = {}


def runtime_option(key, default=None):
    return RUNTIME_OPTIONS.get(key, default)


def configure_runtime_options(**kwargs):
    for key, value in kwargs.items():
        RUNTIME_OPTIONS[key] = value


def resolve_local_output_path(output_dir, target):
    if not output_dir or not target:
        return None
    normalized = unquote(str(target).strip().replace("\\", "/"))
    if re.match(r"^[a-z]+://", normalized, flags=re.IGNORECASE):
        return None
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while normalized.startswith("../"):
        normalized = normalized[3:]
    if not normalized:
        return None
    candidate = (Path(output_dir) / normalized).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def clean_pdf_text(text):
    text = "" if text is None else str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text_with_pymupdf(pdf_path, max_pages, max_chars):
    import fitz

    chunks = []
    total_chars = 0
    truncated = False
    with fitz.open(str(pdf_path)) as document:
        page_count = min(len(document), max_pages)
        for page_index in range(page_count):
            page_text = clean_pdf_text(document[page_index].get_text("text"))
            if not page_text:
                continue
            heading = f"### Seite {page_index + 1}"
            block = f"{heading}\n\n{page_text}"
            remaining = max_chars - total_chars
            if remaining <= 0:
                truncated = True
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip()
                truncated = True
            chunks.append(block)
            total_chars += len(block)
            if truncated:
                break
    return "\n\n".join(chunks).strip(), truncated


def extract_pdf_text_with_tika(pdf_path, max_chars):
    from tika import parser

    parsed = parser.from_file(str(pdf_path))
    text = clean_pdf_text(parsed.get("content") or "")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip()
    return text, truncated


def extract_pdf_text_with_ocr(pdf_path, max_pages, max_chars, ocr_lang="eng"):
    import fitz
    import pytesseract
    from PIL import Image

    chunks = []
    total_chars = 0
    truncated = False
    with fitz.open(str(pdf_path)) as document:
        page_count = min(len(document), max_pages)
        for page_index in range(page_count):
            pixmap = document[page_index].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            page_text = clean_pdf_text(pytesseract.image_to_string(image, lang=ocr_lang))
            if not page_text:
                continue
            heading = f"### OCR Page {page_index + 1}"
            block = f"{heading}\n\n{page_text}"
            remaining = max_chars - total_chars
            if remaining <= 0:
                truncated = True
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip()
                truncated = True
            chunks.append(block)
            total_chars += len(block)
            if truncated:
                break
    return "\n\n".join(chunks).strip(), truncated


def extract_pdf_text(pdf_path, engine="auto", max_pages=8, max_chars=20000, ocr_fallback=False, ocr_lang="eng"):
    cache_key = f"{pdf_path}:{engine}:{max_pages}:{max_chars}:{ocr_fallback}:{ocr_lang}"
    if cache_key in PDF_TEXT_CACHE:
        return PDF_TEXT_CACHE[cache_key]

    result = {
        "ok": False,
        "text": "",
        "engine": None,
        "truncated": False,
        "error": "No parser succeeded.",
    }

    tried = []
    engines = [engine] if engine and engine != "auto" else ["pymupdf", "tika"]
    for current_engine in engines:
        try:
            if current_engine == "pymupdf":
                text, truncated = extract_pdf_text_with_pymupdf(pdf_path, max_pages=max_pages, max_chars=max_chars)
            elif current_engine == "tika":
                text, truncated = extract_pdf_text_with_tika(pdf_path, max_chars=max_chars)
            else:
                continue
            if text:
                result = {
                    "ok": True,
                    "text": text,
                    "engine": current_engine,
                    "truncated": truncated,
                    "error": None,
                }
                break
            tried.append(f"{current_engine}: empty text")
        except Exception as exc:
            tried.append(f"{current_engine}: {exc}")

    if not result["ok"] and ocr_fallback:
        try:
            text, truncated = extract_pdf_text_with_ocr(
                pdf_path,
                max_pages=max_pages,
                max_chars=max_chars,
                ocr_lang=ocr_lang,
            )
            if text:
                result = {
                    "ok": True,
                    "text": text,
                    "engine": "ocr",
                    "truncated": truncated,
                    "error": None,
                }
            else:
                tried.append("ocr: empty text")
        except Exception as exc:
            tried.append(f"ocr: {exc}")

    if not result["ok"]:
        result["error"] = "; ".join(tried) or result["error"]

    PDF_TEXT_CACHE[cache_key] = result
    return result


def create_pdf_text_markdown(pdf_path, title, output_dir, extraction_result):
    output_root = Path(output_dir).resolve()
    resolved_pdf = Path(pdf_path).resolve()
    try:
        relative_pdf = resolved_pdf.relative_to(output_root).as_posix()
    except ValueError:
        relative_pdf = f"files/{resolved_pdf.name}"
    doc_dir = Path(output_dir) / "doc" / "pdf_text"
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{slugify_heading(title or resolved_pdf.stem)}_pdf_text.md"
    note_path = doc_dir / file_name
    parsed_ok = bool(extraction_result.get("ok"))
    parser_name = extraction_result.get("engine") or "none"
    extraction_error = (extraction_result.get("error") or "No readable text could be extracted.").strip()
    truncated_hint = "\n\n> Note: The text was truncated because a page or character limit is active." if extraction_result.get("truncated") else ""

    if parsed_ok:
        body = f"## Extracted Text\n\n{extraction_result.get('text', '').strip()}{truncated_hint}\n"
        status_line = "- Status: success"
    else:
        body = (
            "## Extraction Result\n\n"
            "No readable text was extracted from this PDF. This usually means the PDF is image-based (scan) or no compatible parser is available.\n\n"
            f"Error details: {extraction_error}\n"
        )
        status_line = "- Status: no text extracted"

    note_content = (
        f"# {title or resolved_pdf.stem} - Text Extract\n\n"
        f"- Source: [{resolved_pdf.name}]({ensure_explicit_relative_path(encode_relative_path(relative_pdf))})\n"
        f"- Parser: {parser_name}\n"
        f"{status_line}\n\n"
        f"{body}"
    )
    note_path.write_text(note_content, encoding="utf-8")
    return ensure_explicit_relative_path(encode_relative_path(note_path.resolve().relative_to(output_root).as_posix()))


STRUCTURED_WEEK_SECTIONS = (
    ("lernziele", "Learning Goals"),
    ("inhalte", "Content"),
    ("materialien", "Materials"),
    ("aufgaben", "Assignments"),
    ("diskussionspunkte", "Discussion Points"),
    ("literatur", "Literature"),
)


def plain_text_for_classification(text):
    text = "" if text is None else str(text)
    if not text:
        return ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\^([^\]]+)\]:\s*\{.*\}", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_section_title(raw_title, section_number):
    title = plain_text_for_classification(raw_title)
    title = re.sub(r"^[\-_:|/\\. ]+|[\-_:|/\\. ]+$", "", title)
    if not title or len(title) > 80:
        return f"Session {section_number}"
    lowered = elimina_tildes(title).lower()
    if re.match(r"^(sitzung|woche|week|session)\s+\d+", lowered):
        return title
    return f"Session {section_number}: {title}"


def detect_structured_bucket(text, fallback=None):
    normalized = elimina_tildes(plain_text_for_classification(text)).lower()
    if not normalized:
        return fallback

    keyword_groups = (
        ("lernziele", ("lernziel", "lernziele", "learning outcome", "learning outcomes", "kompetenzziel", "kompetenzen")),
        ("aufgaben", ("aufgabe", "aufgaben", "assignment", "assignments", "quiz", "abgabe", "bearbeiten", "kurzzusammenfassung", "arbeitsauftrag")),
        ("diskussionspunkte", ("diskussion", "diskussions", "forum", "debatte", "leitfrage", "leitfragen", "reflection", "reflexion", "diskutieren")),
        ("literatur", ("literatur", "lekture", "reading", "readings", "grundlagenliteratur", "weiterfuhrende literatur", "reference", "references")),
        ("materialien", ("material", "materialien", "ressource", "ressourcen", "links", "link", "slides", "handout", "video", "podcast", "tool", "tools")),
        ("inhalte", ("inhalt", "inhalte", "grundlagen", "einfuhrung", "thema", "themen", "schwerpunkt", "block", "teil")),
    )

    for bucket, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            return bucket
    return fallback


def is_bucket_heading_label(text):
    raw = "" if text is None else str(text)
    plain = plain_text_for_classification(raw)
    if not plain or len(plain) > 90:
        return False
    if "<iframe" in raw.lower() or re.search(r"\[[^\]]+\]\([^)]+\)", raw):
        return False
    line_count = len([line for line in raw.splitlines() if line.strip()])
    if line_count > 3:
        return False
    return detect_structured_bucket(plain) is not None


def append_structured_content(sections, bucket, content):
    content = "" if content is None else str(content).strip()
    if not content:
        return
    sections[bucket].append(content)


def render_structured_section(dir_path, file_name, section_heading, sections):
    escribir(dir_path, file_name)
    escribir(dir_path, file_name, f"## {section_heading}")
    escribir(dir_path, file_name)
    for bucket, heading in STRUCTURED_WEEK_SECTIONS:
        escribir(dir_path, file_name, f"### {heading}")
        escribir(dir_path, file_name)
        if sections[bucket]:
            for block in sections[bucket]:
                escribir(dir_path, file_name, block)
                escribir(dir_path, file_name)
        else:
            escribir(dir_path, file_name, "- No details provided")
            escribir(dir_path, file_name)


def render_section_overview_link(dir_path, file_name, title, target_path, heading_written):
    if not heading_written:
        escribir(dir_path, file_name)
        escribir(dir_path, file_name, "## Sessions")
        escribir(dir_path, file_name)
    escribir(dir_path, file_name, f"- [{title}]({target_path})")
    return True


def build_week_doc_name(section_heading, section_number):
    safe_heading = plain_text_for_classification(section_heading) or f"Session {section_number}"
    return f"{section_number:02d}_{slugify_heading(safe_heading)}.md"


def get_youtube_embed_url(url):
    match = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/))([A-Za-z0-9_-]{6,})",
        url or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return f"https://www.youtube.com/embed/{match.group(1)}"


def is_youtube_url(url):
    return bool(get_youtube_embed_url(url))


def build_affine_attachment_marker(title, target, output_dir, heading_level=3):
    if not output_dir or not target:
        return None

    normalized_target = unquote(str(target).strip().replace("\\", "/"))
    if re.match(r"^[a-z]+://", normalized_target, flags=re.IGNORECASE):
        return None

    while normalized_target.startswith("./"):
        normalized_target = normalized_target[2:]
    while normalized_target.startswith("../"):
        normalized_target = normalized_target[3:]

    local_path = (Path(output_dir) / normalized_target).resolve()
    if (
        not local_path.exists()
        or not local_path.is_file()
        or local_path.suffix.lower() == ".md"
        or local_path.stat().st_size == 0
    ):
        return None

    digest = hashlib.sha256(local_path.read_bytes()).digest()
    blob_id = base64.urlsafe_b64encode(digest).decode("ascii")
    mime_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    readable_title = re.sub(r"\s+", " ", str(title or local_path.stem)).strip() or local_path.stem
    readable_title = readable_title.replace("/", "-").replace("\\", "-")
    suffix = local_path.suffix or ""
    display_name = readable_title if readable_title.lower().endswith(suffix.lower()) else f"{readable_title}{suffix}"
    local_target = ensure_explicit_relative_path(encode_relative_path(normalized_target))
    footnote_id = f"att_{re.sub(r'[^A-Za-z0-9]+', '_', local_path.stem).strip('_') or 'file'}"
    metadata = {
        "type": "attachment",
        "blobId": blob_id,
        "fileName": local_path.name,
        "fileType": mime_type,
        "title": display_name,
        "url": local_target,
    }

    return (
        f"\n{'#' * max(1, heading_level)} {readable_title}\n\n"
        f"[^{footnote_id}]: {json.dumps(metadata, ensure_ascii=False)}\n"
    )


def build_affine_embed_block(title, target, kind="link", output_dir=None, heading_level=3):
    if kind == "youtube":
        embed_url = get_youtube_embed_url(target)
        if embed_url:
            return f'\n{"#" * max(1, heading_level)} {title}\n\n<iframe src="{embed_url}"></iframe>\n\n[Open on YouTube]({target})\n'
        return f"\n{'#' * max(1, heading_level)} {title}\n\n[Open link]({target})\n"
    if kind in {"pdf", "file"}:
        text_doc_target = None
        if kind == "pdf" and runtime_option("pdf_text_blocks", False):
            try:
                pdf_path = resolve_local_output_path(output_dir, target)
                if pdf_path and pdf_path.suffix.lower() == ".pdf":
                    print(f"[pdf_text] Extracting text from: {pdf_path.name}")
                    extraction = extract_pdf_text(
                        pdf_path,
                        engine=runtime_option("pdf_text_engine", "auto"),
                        max_pages=int(runtime_option("pdf_text_max_pages", 8) or 8),
                        max_chars=int(runtime_option("pdf_text_max_chars", 20000) or 20000),
                        ocr_fallback=bool(runtime_option("pdf_text_ocr_fallback", False)),
                        ocr_lang=str(runtime_option("pdf_text_ocr_lang", "eng") or "eng"),
                    )
                    text_doc_target = create_pdf_text_markdown(pdf_path, title, output_dir, extraction)
                    engine_used = extraction.get("engine") or "none"
                    ok_str = "ok" if extraction.get("ok") else "no text"
                    print(f"[pdf_text] → {ok_str} (engine: {engine_used}) → {text_doc_target}")
                else:
                    print(f"[pdf_text] Skipped '{target}': file not found in output directory")
            except Exception as exc:
                print(f"[pdf_text] Error extracting text from PDF '{title}': {exc}")
        attachment_marker = build_affine_attachment_marker(title, target, output_dir, heading_level=heading_level)
        if attachment_marker:
            if text_doc_target:
                attachment_marker += f"\n* [Readable text extract]({text_doc_target})\n"
            return attachment_marker
        if target:
            safe_target = ensure_explicit_relative_path(target)
            return f"\n{'#' * max(1, heading_level)} {title}\n\n[{title}]({safe_target})\n"
        return f"\n{'#' * max(1, heading_level)} {title}\n"
    if re.match(r"^https?://", target or "", flags=re.IGNORECASE):
        return f"* [{title}]({target})"
    return f"* [{title}]({target})"


def looks_like_downloadable_file(url):
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    downloadable_exts = (
        ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".zip",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp3", ".mp4", ".epub"
    )
    return path.lower().endswith(downloadable_exts)


def download_external_file(url, title, output_dir):
    parsed = urlparse(url)
    filename = os.path.basename(unquote(parsed.path))
    if not filename:
        filename = getNombreFichero(title).replace(".md", ".pdf")

    destination = os.path.join(output_dir, "files", filename)
    if os.path.exists(destination):
        if os.path.getsize(destination) > 0:
            return encode_relative_path("files/" + filename)
        os.remove(destination)

    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/124 Safari/537.36"})
    with urlopen(request, timeout=30) as response:
        payload = response.read()

    if not payload:
        raise ValueError("Downloaded file is empty")

    with open(destination, "wb") as out_file:
        out_file.write(payload)

    if os.path.getsize(destination) == 0:
        os.remove(destination)
        raise ValueError("Downloaded file is empty")

    return encode_relative_path("files/" + filename)


def create_external_link_note(url, title, output_dir, error_message=""):
    note_name = getNombreFichero(f"{title}_external_link")
    note_dir = os.path.join(output_dir, "doc")
    crear_fichero(note_name, note_dir + os.sep)
    escribir(note_dir + os.sep, note_name, f"# {title}")
    escribir(note_dir + os.sep, note_name)
    escribir(note_dir + os.sep, note_name, "> ⚠️ This linked file could not be mirrored locally during export.")
    escribir(note_dir + os.sep, note_name)
    escribir(note_dir + os.sep, note_name, "## What happened")
    escribir(note_dir + os.sep, note_name, "The original Moodle item points to an external downloadable resource that is currently blocked, expired, or no longer available.")
    if error_message:
        escribir(note_dir + os.sep, note_name)
        escribir(note_dir + os.sep, note_name, f"**Reason:** `{error_message}`")
    escribir(note_dir + os.sep, note_name)
    escribir(note_dir + os.sep, note_name, "## Original source")
    escribir(note_dir + os.sep, note_name, f"- {url}")
    escribir(note_dir + os.sep, note_name)
    escribir(note_dir + os.sep, note_name, "## Recommendation")
    escribir(note_dir + os.sep, note_name, "If you still need this file in Affine or GitHub, download it manually and place it into the `files/` folder.")
    return encode_relative_path("doc/" + note_name)


def normalizar_html(texto, media_prefix="img/", output_dir=None, relative_prefix=""):
    texto = images(texto, media_prefix)
    texto = unescape(texto)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")

    def replace_link(match):
        raw_url = match.group(1).strip()
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip() or raw_url
        pre_encoded = False
        url = raw_url

        if is_youtube_url(raw_url):
            embed_url = get_youtube_embed_url(raw_url)
            if embed_url:
                return f'\n\n### {label}\n\n<iframe src="{embed_url}"></iframe>\n\n[Open on YouTube]({raw_url})\n\n'

        if output_dir and looks_like_downloadable_file(raw_url):
            try:
                local_target = download_external_file(raw_url, label, output_dir)
                url = f"{relative_prefix}{local_target}" if relative_prefix else local_target
                pre_encoded = True
            except Exception as exc:
                note_target = create_external_link_note(raw_url, label, output_dir, str(exc))
                url = f"{relative_prefix}{note_target}" if relative_prefix else note_target
                pre_encoded = True

        if not pre_encoded:
            url = encode_relative_path(url)
        if not re.match(r"^[a-z]+://", url, flags=re.IGNORECASE):
            url = ensure_explicit_relative_path(url)
        return f"[{label}]({url})"

    def replace_iframe(match):
        raw_url = match.group(1).strip()
        embed_url = get_youtube_embed_url(raw_url)
        if embed_url:
            return f'\n\n<iframe src="{embed_url}"></iframe>\n\n[Open on YouTube]({raw_url})\n\n'
        if raw_url.lower().startswith("https://"):
            return f'\n\n<iframe src="{raw_url}"></iframe>\n\n'
        return f"\n\n[Embedded media]({raw_url})\n\n"

    def replace_plain_url(match):
        raw_url = match.group(1).strip()
        if is_youtube_url(raw_url):
            embed_url = get_youtube_embed_url(raw_url)
            if embed_url:
                return f'<iframe src="{embed_url}"></iframe>'

        if output_dir and looks_like_downloadable_file(raw_url):
            title = os.path.basename(unquote(urlparse(raw_url).path)) or "Downloaded file"
            try:
                local_target = download_external_file(raw_url, title, output_dir)
                rendered_target = f"{relative_prefix}{local_target}" if relative_prefix else local_target
                rendered_target = rendered_target.replace("/./", "/")
                lower_target = rendered_target.lower()
                if lower_target.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    return f'![]({rendered_target})'
                return f'[{title}]({ensure_explicit_relative_path(rendered_target)})'
            except Exception as exc:
                note_target = create_external_link_note(raw_url, title, output_dir, str(exc))
                rendered_target = f"{relative_prefix}{note_target}" if relative_prefix else note_target
                return f'[External file]({rendered_target})'

        return raw_url

    texto = re.sub(r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", replace_link, texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"<iframe[^>]*src=[\"']([^\"']+)[\"'][^>]*>.*?</iframe>", replace_iframe, texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"<img[^>]*src=[\"']([^\"']+)[\"'][^>]*alt=[\"']([^\"']*)[\"'][^>]*>", lambda m: f"\n\n![{m.group(2).strip()}]({encode_relative_path(m.group(1).strip())})\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<img[^>]*alt=[\"']([^\"']*)[\"'][^>]*src=[\"']([^\"']+)[\"'][^>]*>", lambda m: f"\n\n![{m.group(1).strip()}]({encode_relative_path(m.group(2).strip())})\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<img[^>]*src=[\"']([^\"']+)[\"'][^>]*>", lambda m: f"\n\n![]({encode_relative_path(m.group(1).strip())})\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</(p|div|section|article|h[1-6]|ul|ol)>", "\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<li[^>]*>", "- ", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</li>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"(?m)^\s*(https?://\S+)\s*$", replace_plain_url, texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    return texto.strip()


def slugify_heading(texto):
    texto = elimina_tildes(texto or "abschnitt").lower()
    texto = re.sub(r"[^a-z0-9\s_-]", "", texto)
    texto = re.sub(r"[\s_-]+", "-", texto).strip("-")
    return texto or "abschnitt"


def integrar_en_una_sola_pagina(output_dir, source_name="README.md", target_name="ALL_IN_ONE.md"):
    output_path = Path(output_dir)
    readme_path = output_path / source_name
    doc_dir = output_path / "doc"
    target_path = output_path / target_name

    contenido_principal = readme_path.read_text(encoding="utf-8")
    secciones_integradas = []

    if doc_dir.exists():
        for doc_file in sorted(doc_dir.glob("*.md")):
            contenido = doc_file.read_text(encoding="utf-8").strip()
            if not contenido:
                continue

            contenido = contenido.replace("../img/", "img/").replace("../files/", "files/")
            primera_linea = next((line for line in contenido.splitlines() if line.startswith("#")), f"# {doc_file.stem}")
            anchor = slugify_heading(primera_linea.lstrip("# ").strip())
            contenido_principal = contenido_principal.replace(f"(doc/{doc_file.name})", f"(#{anchor})")
            secciones_integradas.append(contenido)

    if secciones_integradas:
        contenido_principal = contenido_principal.rstrip() + "\n\n---\n\n## Integrated pages and assignments\n\n" + "\n\n---\n\n".join(secciones_integradas) + "\n"

    target_path.write_text(contenido_principal, encoding="utf-8")
    return str(target_path)


def markdown_inline_to_html(text):
    text = "" if text is None else str(text)
    escaped = escape(text, quote=True)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">',
        escaped,
    )

    def replace_empty_link(match):
        target = match.group(1)
        if target.lower().startswith("bookmark,"):
            target = target.split(",", 1)[1]
        label = "Open link" if re.match(r"^https?://", target, flags=re.IGNORECASE) else "Open file"
        return f'<a href="{target}">{label}</a>'

    escaped = re.sub(r"\[\]\(([^)]+)\)", replace_empty_link, escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped



def attachment_block_to_html(display_text, attachment_meta):
    file_name = str(attachment_meta.get("fileName") or "attachment").strip() or "attachment"
    file_url = str(attachment_meta.get("url") or "").strip() or encode_relative_path(f"files/{file_name}")
    file_type = str(attachment_meta.get("fileType") or "application/octet-stream")
    preferred_title = str(attachment_meta.get("title") or "").strip()
    safe_title = escape((display_text or preferred_title or file_name).strip() or file_name)

    if file_type == "application/pdf":
        return (
            '<section class="attachment-card pdf-card">'
            f"<h3>{safe_title}</h3>"
            f'<p><a href="{file_url}" target="_blank" rel="noopener">Open PDF</a></p>'
            '</section>'
        )

    return (
        '<section class="attachment-card">'
        f"<h3>{safe_title}</h3>"
        f'<p><a href="{file_url}" target="_blank" rel="noopener">Open attachment</a></p>'
        '</section>'
    )



def create_affine_html_export(output_dir, source_name=None, target_name="AFFINE_IMPORT.html"):
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Output directory not found: {output_path}")

    if source_name:
        source_path = output_path / source_name
    elif (output_path / "ALL_IN_ONE.md").exists():
        source_path = output_path / "ALL_IN_ONE.md"
    elif (output_path / "doc").exists():
        source_path = Path(integrar_en_una_sola_pagina(output_dir))
    else:
        source_path = output_path / "README.md"

    markdown_text = source_path.read_text(encoding="utf-8")
    target_path = output_path / target_name
    attachments = {}
    placeholders = {}

    def capture_obsidian_attachment(match):
        raw_payload = match.group(1).strip()
        try:
            parsed = json.loads(unquote(raw_payload))
            if parsed.get("blobId") and parsed.get("fileName"):
                placeholder = f"__ATTACHMENT_BLOCK_{len(placeholders)}__"
                label = str(parsed.get("title") or parsed.get("fileName"))
                placeholders[placeholder] = attachment_block_to_html(label, parsed)
                return placeholder
        except Exception:
            pass
        return ""

    markdown_text = re.sub(
        r"(?m)^<!--\s*obsidian-attachment\s+([^ ]+)\s*-->\s*$",
        capture_obsidian_attachment,
        markdown_text,
    )

    def capture_attachment(match):
        identifier = match.group(1)
        raw_json = match.group(2).strip()
        try:
            parsed = json.loads(raw_json)
            if parsed.get("type") == "attachment" and parsed.get("fileName"):
                attachments[identifier] = parsed
                placeholder = f"__ATTACHMENT_BLOCK_{len(placeholders)}__"
                label = str(parsed.get("title") or parsed.get("fileName") or identifier)
                placeholders[placeholder] = attachment_block_to_html(label, parsed)
                return placeholder
        except Exception:
            pass
        return ""

    markdown_text = re.sub(r"(?m)^\[\^([^\]]+)\]:\s*(\{.*\})\s*$", capture_attachment, markdown_text)
    markdown_text = re.sub(r"(?m)^<!--.*?-->\s*$", "", markdown_text)

    def inject_attachment_block(match):
        display_text = match.group(1).strip()
        footnote_id = match.group(2).strip()
        attachment_meta = attachments.get(footnote_id)
        if not attachment_meta:
            return match.group(0)
        placeholder = f"__ATTACHMENT_BLOCK_{len(placeholders)}__"
        label = display_text or str(attachment_meta.get("fileName") or footnote_id)
        placeholders[placeholder] = attachment_block_to_html(label, attachment_meta)
        return placeholder

    markdown_text = re.sub(r"(?m)^([^\n]+?)\[\^([^\]]+)\]\s*$", inject_attachment_block, markdown_text)

    body_parts = []
    paragraph_lines = []
    list_mode = None

    def flush_paragraph():
        if paragraph_lines:
            text = " ".join(part.strip() for part in paragraph_lines if part.strip()).strip()
            if text:
                body_parts.append(f"<p>{markdown_inline_to_html(text)}</p>")
            paragraph_lines.clear()

    def close_list():
        nonlocal list_mode
        if list_mode:
            body_parts.append(f"</{list_mode}>")
            list_mode = None

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped in placeholders:
            flush_paragraph()
            close_list()
            body_parts.append(placeholders[stripped])
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            continue

        if stripped == "---":
            flush_paragraph()
            close_list()
            body_parts.append("<hr>")
            continue

        if stripped.startswith("<iframe") and stripped.endswith("</iframe>"):
            flush_paragraph()
            close_list()
            body_parts.append(f'<div class="video-embed">{stripped}</div>')
            continue

        if stripped.startswith("#"):
            flush_paragraph()
            close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip()
            body_parts.append(f"<h{level}>{markdown_inline_to_html(content)}</h{level}>")
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            body_parts.append(f"<blockquote><p>{markdown_inline_to_html(stripped[1:].strip())}</p></blockquote>")
            continue

        ordered_match = re.match(r"^\d+[\.)]\s+(.*)", stripped)
        if ordered_match:
            flush_paragraph()
            if list_mode != "ol":
                close_list()
                body_parts.append("<ol>")
                list_mode = "ol"
            body_parts.append(f"<li>{markdown_inline_to_html(ordered_match.group(1))}</li>")
            continue

        unordered_match = re.match(r"^[-*]\s+(.*)", stripped)
        if unordered_match:
            flush_paragraph()
            if list_mode != "ul":
                close_list()
                body_parts.append("<ul>")
                list_mode = "ul"
            body_parts.append(f"<li>{markdown_inline_to_html(unordered_match.group(1))}</li>")
            continue

        close_list()
        paragraph_lines.append(stripped)

    flush_paragraph()
    close_list()

    title = escape(output_path.name)
    body_html = "\n".join(body_parts)
    html_text = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} – AFFiNE HTML Export</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f172a;
      --card: #111827;
      --text: #e5eefc;
      --muted: #b9c6df;
      --accent: #8bb8ff;
      --border: #2b3c5e;
    }}
    body {{ margin: 0; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0b1020; color: var(--text); }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 18px 64px; }}
    .hero, .attachment-card {{ background: rgba(17,24,39,.94); border: 1px solid var(--border); border-radius: 16px; padding: 18px; margin: 0 0 16px; }}
    h1, h2, h3, h4 {{ color: #f8fbff; }}
    p, li, blockquote {{ line-height: 1.65; }}
    a {{ color: var(--accent); }}
    img {{ max-width: 100%; height: auto; border-radius: 10px; }}
    .video-embed iframe {{ width: 100%; min-height: 360px; border: 0; border-radius: 12px; background: #000; }}
    code {{ background: rgba(139,184,255,.12); padding: 2px 6px; border-radius: 6px; }}
    hr {{ border: 0; border-top: 1px solid var(--border); margin: 24px 0; }}
    blockquote {{ margin: 12px 0; padding: 8px 14px; border-left: 4px solid var(--accent); background: rgba(139,184,255,.08); }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{title} – AFFiNE HTML Export</h1>
      <p>This file is intended for browser preview or direct HTML import into AFFiNE when Markdown ZIP import shows limited YouTube or PDF behavior.</p>
      <p><strong>Source:</strong> {escape(source_path.name)}</p>
    </section>
    {body_html}
  </main>
</body>
</html>
'''
    target_path.write_text(html_text, encoding="utf-8")
    return str(target_path)



def create_affine_zip(output_dir, archive_path=None, include_doc_pages=False, include_pdf_text_pages=False):
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Output directory not found: {output_path}")

    if archive_path is None:
        zip_path = output_path.parent / f"{output_path.name}_affine.zip"
    else:
        zip_path = Path(os.path.abspath(os.path.expanduser(archive_path)))

    zip_path.parent.mkdir(parents=True, exist_ok=True)

    preferred_main = output_path / "ALL_IN_ONE.md"
    if not preferred_main.exists():
        preferred_main = output_path / "README.md"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if preferred_main.exists():
            archive.write(preferred_main, preferred_main.name)

        for folder_name in ["files", "img"]:
            folder = output_path / folder_name
            if not folder.exists():
                continue
            for item in sorted(folder.rglob("*")):
                if item.is_dir():
                    continue
                archive.write(item, item.relative_to(output_path))

        doc_dir = output_path / "doc"
        if doc_dir.exists():
            pattern = "*.md" if include_doc_pages else "*external_link*.md"
            for item in sorted(doc_dir.glob(pattern)):
                archive.write(item, item.relative_to(output_path))
            if include_pdf_text_pages:
                for item in sorted((doc_dir / "pdf_text").glob("*.md")):
                    archive.write(item, item.relative_to(output_path))

    return str(zip_path)


def affine_block_id(prefix="block"):
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


def make_affine_rich_text(text):
    text = "" if text is None else str(text)
    return {
        "$blocksuite:internal:text$": True,
        "delta": [{"insert": text}],
    }


def make_affine_rich_text_from_markdown(text):
    source = "" if text is None else str(text)
    source = re.sub(r"\*\*([^*]+)\*\*", r"\1", source)
    source = re.sub(r"`([^`]+)`", r"\1", source)
    source = re.sub(r"\[\^([^\]]+)\]", "", source)

    delta = []
    last_index = 0
    for match in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", source):
        if match.start() > last_index:
            delta.append({"insert": source[last_index:match.start()]})

        label = (match.group(1) or match.group(2) or "").strip()
        url = (match.group(2) or "").strip()
        if label:
            chunk = {"insert": label}
            if url:
                chunk["attributes"] = {"link": url}
            delta.append(chunk)
        last_index = match.end()

    if last_index < len(source):
        delta.append({"insert": source[last_index:]})

    if not delta:
        delta = [{"insert": source}]

    return {
        "$blocksuite:internal:text$": True,
        "delta": delta,
    }


def build_affine_asset_lookup(output_path):
    lookup = {}
    assets_by_blob = {}

    for folder_name in ["files", "img"]:
        folder = output_path / folder_name
        if not folder.exists():
            continue

        for item in sorted(folder.rglob("*")):
            if item.is_dir() or not item.exists() or item.stat().st_size == 0:
                continue

            digest = hashlib.sha256(item.read_bytes()).digest()
            blob_id = base64.urlsafe_b64encode(digest).decode("ascii")
            rel_path = item.relative_to(output_path).as_posix()
            encoded_rel_path = encode_relative_path(rel_path)
            mime_type = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
            meta = {
                "path": item,
                "relative_path": rel_path,
                "encoded_relative_path": encoded_rel_path,
                "blob_id": blob_id,
                "file_name": item.name,
                "mime_type": mime_type,
                "size": item.stat().st_size,
            }

            candidates = {
                rel_path,
                encoded_rel_path,
                f"./{rel_path}",
                f"./{encoded_rel_path}",
                item.name,
                encode_relative_path(item.name),
            }
            for candidate in candidates:
                if candidate and candidate not in lookup:
                    lookup[candidate] = meta

            assets_by_blob[blob_id] = meta

    return lookup, assets_by_blob


def resolve_affine_asset(target, asset_lookup):
    if not target:
        return None

    normalized = unquote(str(target).strip().replace("\\", "/"))
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while normalized.startswith("../"):
        normalized = normalized[3:]

    candidates = [
        normalized,
        ensure_explicit_relative_path(normalized),
        encode_relative_path(normalized),
        os.path.basename(normalized),
        encode_relative_path(os.path.basename(normalized)),
    ]

    for candidate in candidates:
        if candidate in asset_lookup:
            return asset_lookup[candidate]
    return None


def create_affine_attachment_block(asset_meta, display_title=""):
    mime_type = asset_meta.get("mime_type") or "application/octet-stream"
    is_pdf = mime_type == "application/pdf"
    caption = re.sub(r"\s+", " ", str(display_title or "")).strip()
    file_name = asset_meta.get("file_name") or "attachment"

    props = {
        "name": file_name,
        "size": int(asset_meta.get("size") or 0),
        "type": mime_type,
        "sourceId": asset_meta.get("blob_id"),
        "embed": True if is_pdf else False,
        "style": "pdf" if is_pdf else "horizontalThin",
        "index": "a0",
        "xywh": "[0,0,720,480]" if is_pdf else "[0,0,0,0]",
        "rotate": 0,
        "footnoteIdentifier": None,
    }
    if caption and caption != file_name:
        props["caption"] = caption

    return {
        "type": "block",
        "id": affine_block_id("attachment"),
        "flavour": "affine:attachment",
        "props": props,
        "children": [],
    }


def create_affine_image_block(asset_meta, caption=""):
    return {
        "type": "block",
        "id": affine_block_id("image"),
        "flavour": "affine:image",
        "props": {
            "sourceId": asset_meta.get("blob_id"),
            "caption": (caption or asset_meta.get("file_name") or "").strip(),
            "width": 800,
            "height": 450,
        },
        "children": [],
    }


def create_affine_paragraph_block(text, block_type="text"):
    return {
        "type": "block",
        "id": affine_block_id("paragraph"),
        "flavour": "affine:paragraph",
        "props": {
            "type": block_type,
            "text": make_affine_rich_text_from_markdown(text),
        },
        "children": [],
    }


def create_affine_list_block(text, list_type="bulleted", order=None):
    return {
        "type": "block",
        "id": affine_block_id("list"),
        "flavour": "affine:list",
        "props": {
            "type": list_type,
            "text": make_affine_rich_text_from_markdown(text),
            "checked": False,
            "collapsed": False,
            "order": order,
        },
        "children": [],
    }


def create_affine_surface_block():
    return {
        "type": "block",
        "id": affine_block_id("surface"),
        "flavour": "affine:surface",
        "props": {
            "elements": {},
        },
        "children": [],
    }


def create_affine_note_block(children, index="a0"):
    return {
        "type": "block",
        "id": affine_block_id("note"),
        "flavour": "affine:note",
        "props": {
            "xywh": "[0,0,800,95]",
            "background": "rgba(255,255,255,0)",
            "index": index,
            "hidden": False,
            "displayMode": "both",
        },
        "children": children,
    }


def create_affine_page_block(title, blocks, index="a0"):
    return {
        "type": "block",
        "id": affine_block_id("page"),
        "flavour": "affine:page",
        "props": {
            "title": make_affine_rich_text(title),
        },
        "children": [
            create_affine_surface_block(),
            create_affine_note_block(blocks, index=index),
        ],
    }


def remove_week_overview_from_markdown(markdown_text):
    lines = markdown_text.splitlines()
    kept_lines = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Sitzungen":
            skipping = True
            continue
        if skipping and re.match(r"^##\s+", stripped):
            skipping = False
        if not skipping:
            kept_lines.append(line)
    cleaned = "\n".join(kept_lines).strip()
    return cleaned or markdown_text


def merge_week_markdown_into_main(main_markdown_text, output_dir, week_pages_manifest):
    output_path = Path(output_dir)
    merged_parts = [main_markdown_text.strip()]
    for page_meta in week_pages_manifest or []:
        relative_path = page_meta.get("relative_path") or ""
        week_path = output_path / relative_path
        if not week_path.exists():
            continue
        week_markdown = week_path.read_text(encoding="utf-8").strip()
        if not week_markdown:
            continue
        merged_parts.append(week_markdown)
    return "\n\n---\n\n".join(part for part in merged_parts if part).strip() or main_markdown_text


def try_build_native_attachment_block(display_title, line, asset_lookup):
    stripped = (line or "").strip()
    if not stripped:
        return None

    footnote_match = re.match(r"^\[\^([^\]]+)\]:\s*(\{.*\})\s*$", stripped)
    if footnote_match:
        try:
            meta = json.loads(footnote_match.group(2))
        except Exception:
            return None
        if meta.get("type") != "attachment":
            return None
        asset_meta = (
            resolve_affine_asset(meta.get("url"), asset_lookup)
            or resolve_affine_asset(f"files/{meta.get('fileName', '')}", asset_lookup)
            or resolve_affine_asset(meta.get("fileName"), asset_lookup)
        )
        if not asset_meta:
            return None
        return create_affine_attachment_block(
            asset_meta,
            display_title or meta.get("title") or meta.get("fileName") or "",
        )

    link_match = re.match(r"^\[([^\]]+)\]\(([^)]+)\)\s*$", stripped)
    if not link_match:
        return None

    label = (link_match.group(1) or "").strip()
    target = (link_match.group(2) or "").strip()
    if re.match(r"^[a-z]+://", target, flags=re.IGNORECASE):
        return None

    asset_meta = resolve_affine_asset(target, asset_lookup)
    if not asset_meta or asset_meta.get("mime_type") == "text/markdown":
        return None

    return create_affine_attachment_block(asset_meta, display_title or label)


def build_affine_native_blocks(markdown_text, output_dir):
    output_path = Path(output_dir)
    asset_lookup, assets_by_blob = build_affine_asset_lookup(output_path)
    blocks = []
    paragraph_lines = []
    lines = markdown_text.splitlines()

    def flush_paragraph():
        if not paragraph_lines:
            return
        text = " ".join(part.strip() for part in paragraph_lines if part.strip()).strip()
        paragraph_lines.clear()
        text = re.sub(r"\[\^([^\]]+)\]", "", text).strip()
        if text:
            blocks.append(create_affine_paragraph_block(text, "text"))

    index = 0
    while index < len(lines):
        raw_line = lines[index].rstrip()
        stripped = raw_line.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1
        next_stripped = lines[next_index].strip() if next_index < len(lines) else ""

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            # AFFiNE snapshot paragraph headings are most compatible up to h3.
            level = min(len(heading_match.group(1)), 3)
            heading_text = heading_match.group(2).strip()
            attachment_block = try_build_native_attachment_block(heading_text, next_stripped, asset_lookup)
            if attachment_block:
                blocks.append(attachment_block)
                index = next_index + 1
                continue
            blocks.append(create_affine_paragraph_block(heading_text, f"h{level}"))
            index += 1
            continue

        if stripped == "---":
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("[^"):
            flush_paragraph()
            attachment_block = try_build_native_attachment_block("", stripped, asset_lookup)
            if attachment_block:
                blocks.append(attachment_block)
            index += 1
            continue

        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if image_match:
            flush_paragraph()
            alt_text = (image_match.group(1) or "").strip()
            target = (image_match.group(2) or "").strip()
            asset_meta = resolve_affine_asset(target, asset_lookup)
            if asset_meta and (asset_meta.get("mime_type") or "").startswith("image/"):
                blocks.append(create_affine_image_block(asset_meta, alt_text))
            elif alt_text:
                blocks.append(create_affine_paragraph_block(f"[Image] {alt_text}", "text"))
            index += 1
            continue

        if "<iframe" in stripped and "src=" in stripped:
            flush_paragraph()
            iframe_match = re.search(r'src=["\']([^"\']+)["\']', stripped, flags=re.IGNORECASE)
            if iframe_match:
                blocks.append(create_affine_paragraph_block(f"[Open embedded media]({iframe_match.group(1)})", "text"))
            index += 1
            continue

        link_only_match = re.match(r"^\[([^\]]+)\]\(([^)]+)\)\s*$", stripped)
        if link_only_match:
            flush_paragraph()
            attachment_block = try_build_native_attachment_block("", stripped, asset_lookup)
            if attachment_block:
                blocks.append(attachment_block)
            else:
                blocks.append(create_affine_paragraph_block(stripped, "text"))
            index += 1
            continue

        ordered_match = re.match(r"^(\d+)[\.)]\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            blocks.append(create_affine_list_block(ordered_match.group(2).strip(), "numbered", int(ordered_match.group(1))))
            index += 1
            continue

        unordered_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if unordered_match:
            flush_paragraph()
            blocks.append(create_affine_list_block(unordered_match.group(1).strip(), "bulleted"))
            index += 1
            continue

        paragraph_lines.append(re.sub(r"<[^>]+>", "", stripped))
        index += 1

    flush_paragraph()

    if not blocks:
        blocks.append(create_affine_paragraph_block("Imported course content", "text"))

    return blocks, assets_by_blob


def create_affine_native_zip(output_dir, archive_path=None, source_name=None, week_pages_manifest=None, native_week_pages=False):
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Output directory not found: {output_path}")

    if archive_path is None:
        zip_path = output_path.parent / f"{output_path.name}_affine_native.zip"
    else:
        zip_path = Path(os.path.abspath(os.path.expanduser(archive_path)))

    if source_name:
        source_path = output_path / source_name
    elif (output_path / "ALL_IN_ONE.md").exists():
        source_path = output_path / "ALL_IN_ONE.md"
    elif (output_path / "doc").exists():
        source_path = Path(integrar_en_una_sola_pagina(output_dir))
    else:
        source_path = output_path / "README.md"

    markdown_text = source_path.read_text(encoding="utf-8")
    main_markdown_text = remove_week_overview_from_markdown(markdown_text) if native_week_pages else markdown_text
    if native_week_pages and week_pages_manifest:
        # AFFiNE snapshot import is more reliable when all content lives in one page tree.
        main_markdown_text = merge_week_markdown_into_main(main_markdown_text, output_dir, week_pages_manifest)
    blocks, assets_by_blob = build_affine_native_blocks(main_markdown_text, output_dir)
    first_heading = next(
        (line.lstrip("# ").strip() for line in main_markdown_text.splitlines() if line.strip().startswith("#")),
        output_path.name,
    )
    title = re.sub(r"\s+", " ", first_heading).strip() or output_path.name
    now_ms = int(time.time() * 1000)

    page_children = [
        create_affine_surface_block(),
        create_affine_note_block(blocks),
    ]

    snapshot = {
        "type": "page",
        "meta": {
            "id": affine_block_id("page"),
            "title": title,
            "createDate": now_ms,
            "tags": [],
        },
        "blocks": {
            "type": "block",
            "id": affine_block_id("root"),
            "flavour": "affine:page",
            "props": {
                "title": make_affine_rich_text(title),
            },
            "children": page_children,
        },
    }

    snapshot_name = f"{getNombreFichero(title).replace('.md', '')}.snapshot.json"
    snapshot_path = output_path / "AFFINE_NATIVE.snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot_path, snapshot_name)
        written_assets = set()
        for asset_meta in sorted(assets_by_blob.values(), key=lambda item: item["relative_path"]):
            blob_id = asset_meta.get("blob_id")
            if not blob_id or blob_id in written_assets:
                continue
            suffix = asset_meta["path"].suffix or mimetypes.guess_extension(asset_meta.get("mime_type") or "") or ""
            archive.write(asset_meta["path"], f"assets/{blob_id}{suffix}")
            written_assets.add(blob_id)

    return str(snapshot_path), str(zip_path)


def extract_markdown_links(markdown_text):
    text = "" if markdown_text is None else str(markdown_text)
    return re.findall(r"\[([^\]]*)\]\(([^)]+)\)", text)


def resolve_relative_output_file(output_root, base_relative_path, target):
    raw_target = "" if target is None else str(target).strip()
    if not raw_target:
        return None

    raw_target = raw_target.split("#", 1)[0].split("?", 1)[0].strip()
    if not raw_target:
        return None

    decoded_target = unquote(raw_target).replace("\\", "/")
    if re.match(r"^[a-z]+://", decoded_target, flags=re.IGNORECASE):
        return None

    base_dir = Path(base_relative_path).parent
    normalized_target = decoded_target
    while normalized_target.startswith("./"):
        normalized_target = normalized_target[2:]

    candidates = []
    if decoded_target.startswith("/"):
        candidates.append((output_root / decoded_target.lstrip("/")).resolve())
    else:
        candidates.append((output_root / base_dir / decoded_target).resolve())
        candidates.append((output_root / normalized_target).resolve())

    output_root_resolved = output_root.resolve()
    for candidate in candidates:
        try:
            candidate.relative_to(output_root_resolved)
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def extract_attachment_targets(markdown_text):
    text = "" if markdown_text is None else str(markdown_text)
    targets = []
    for line in text.splitlines():
        match = re.match(r"^\[\^[^\]]+\]:\s*(\{.*\})\s*$", line.strip())
        if not match:
            continue
        try:
            metadata = json.loads(match.group(1))
        except Exception:
            continue
        if metadata.get("type") != "attachment":
            continue
        url = str(metadata.get("url") or "").strip()
        if not url:
            continue
        targets.append((url, str(metadata.get("fileType") or "").strip().lower()))
    return targets


def dedupe_link_pairs(pairs):
    seen = set()
    result = []
    for label, url in pairs:
        key = (str(label).strip(), str(url).strip())
        if key in seen:
            continue
        seen.add(key)
        result.append((str(label).strip() or str(url).strip(), str(url).strip()))
    return result


def collect_notebooklm_week_assets(output_root, base_relative_path, base_markdown_path):
    markdown_targets = {base_markdown_path}
    pdf_targets = set()
    youtube_links = []
    external_links = []

    queue = [(base_relative_path, base_markdown_path)]
    seen_markdown_paths = set()

    while queue:
        current_relative_path, current_markdown_path = queue.pop(0)
        if current_markdown_path in seen_markdown_paths:
            continue
        seen_markdown_paths.add(current_markdown_path)

        current_markdown = current_markdown_path.read_text(encoding="utf-8")

        for label, link_target in extract_markdown_links(current_markdown):
            cleaned_target = (link_target or "").strip()
            if not cleaned_target:
                continue

            if re.match(r"^https?://", cleaned_target, flags=re.IGNORECASE):
                if is_youtube_url(cleaned_target):
                    youtube_links.append((label or "YouTube", cleaned_target))
                else:
                    external_links.append((label or cleaned_target, cleaned_target))
                continue

            resolved_file = resolve_relative_output_file(output_root, current_relative_path, cleaned_target)
            if not resolved_file:
                continue

            suffix = resolved_file.suffix.lower()
            if suffix == ".md":
                if resolved_file not in markdown_targets:
                    markdown_targets.add(resolved_file)
                    try:
                        rel_path = resolved_file.relative_to(output_root).as_posix()
                    except Exception:
                        rel_path = current_relative_path
                    queue.append((rel_path, resolved_file))
            elif suffix == ".pdf":
                pdf_targets.add(resolved_file)

        for attachment_target, attachment_type in extract_attachment_targets(current_markdown):
            resolved_file = resolve_relative_output_file(output_root, current_relative_path, attachment_target)
            if not resolved_file:
                continue
            if attachment_type == "application/pdf" or resolved_file.suffix.lower() == ".pdf":
                pdf_targets.add(resolved_file)

    return {
        "markdown_targets": markdown_targets,
        "pdf_targets": pdf_targets,
        "youtube_links": dedupe_link_pairs(youtube_links),
        "external_links": dedupe_link_pairs(external_links),
    }


def copy_files_unique(file_paths, target_dir):
    copied = []
    for source_path in sorted(file_paths, key=lambda item: str(item).lower()):
        base_name = source_path.name
        destination = target_dir / base_name
        if destination.exists():
            stem = source_path.stem
            suffix = source_path.suffix
            counter = 2
            while destination.exists():
                destination = target_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.copy2(source_path, destination)
        copied.append(destination)
    return copied


def build_notebooklm_import_bundle(output_dir, week_pages_manifest, create_zip=True):
    output_root = Path(output_dir).resolve()
    bundle_root = output_root / "notebooklm_import"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    week_count = 0
    index_rows = []
    for week_index, page_meta in enumerate(week_pages_manifest or [], start=1):
        week_title = str(page_meta.get("title") or f"Week {week_index}").strip() or f"Week {week_index}"
        week_rel_path = str(page_meta.get("relative_path") or "").strip().replace("\\", "/")
        if not week_rel_path:
            continue

        week_md_path = (output_root / week_rel_path).resolve()
        if not week_md_path.exists() or not week_md_path.is_file():
            continue

        week_folder_name = f"week_{week_index:02d}_{slugify_heading(week_title)}"
        week_folder = bundle_root / week_folder_name
        md_folder = week_folder / "md"
        pdf_folder = week_folder / "pdf"
        md_folder.mkdir(parents=True, exist_ok=True)
        pdf_folder.mkdir(parents=True, exist_ok=True)

        assets = collect_notebooklm_week_assets(output_root, week_rel_path, week_md_path)
        markdown_targets = assets["markdown_targets"]
        pdf_targets = assets["pdf_targets"]
        youtube_links = assets["youtube_links"]
        external_links = assets["external_links"]

        copy_files_unique(markdown_targets, md_folder)
        copy_files_unique(pdf_targets, pdf_folder)

        youtube_page = week_folder / "youtube_links.md"
        if youtube_links:
            youtube_lines = [f"- [{(label or url).strip()}]({url})" for label, url in youtube_links]
            youtube_page.write_text(
                f"# {week_title} - YouTube Links\n\n" + "\n".join(youtube_lines) + "\n",
                encoding="utf-8",
            )
        else:
            youtube_page.write_text(
                f"# {week_title} - YouTube Links\n\nNo YouTube links found in this week.\n",
                encoding="utf-8",
            )

        external_page = week_folder / "external_links.md"
        if external_links:
            external_lines = [f"- [{(label or url).strip()}]({url})" for label, url in external_links]
            external_page.write_text(
                f"# {week_title} - External Links\n\n" + "\n".join(external_lines) + "\n",
                encoding="utf-8",
            )
        else:
            external_page.write_text(
                f"# {week_title} - External Links\n\nNo external links found in this week.\n",
                encoding="utf-8",
            )

        week_count += 1
        index_rows.append({
            "folder": week_folder_name,
            "title": week_title,
            "md_count": len(markdown_targets),
            "pdf_count": len(pdf_targets),
            "youtube_count": len(youtube_links),
            "external_count": len(external_links),
        })

    if week_count == 0:
        fallback_title = "Course Overview"
        fallback_rel_path = "README.md"
        fallback_md_path = (output_root / fallback_rel_path).resolve()
        if fallback_md_path.exists() and fallback_md_path.is_file():
            fallback_folder = bundle_root / "week_00_course_overview"
            md_folder = fallback_folder / "md"
            pdf_folder = fallback_folder / "pdf"
            md_folder.mkdir(parents=True, exist_ok=True)
            pdf_folder.mkdir(parents=True, exist_ok=True)

            assets = collect_notebooklm_week_assets(output_root, fallback_rel_path, fallback_md_path)
            markdown_targets = assets["markdown_targets"]
            pdf_targets = assets["pdf_targets"]
            youtube_links = assets["youtube_links"]
            external_links = assets["external_links"]

            copy_files_unique(markdown_targets, md_folder)
            copy_files_unique(pdf_targets, pdf_folder)

            youtube_page = fallback_folder / "youtube_links.md"
            if youtube_links:
                youtube_lines = [f"- [{(label or url).strip()}]({url})" for label, url in youtube_links]
                youtube_page.write_text(
                    f"# {fallback_title} - YouTube Links\n\n" + "\n".join(youtube_lines) + "\n",
                    encoding="utf-8",
                )
            else:
                youtube_page.write_text(
                    f"# {fallback_title} - YouTube Links\n\nNo YouTube links found in this overview.\n",
                    encoding="utf-8",
                )

            external_page = fallback_folder / "external_links.md"
            if external_links:
                external_lines = [f"- [{(label or url).strip()}]({url})" for label, url in external_links]
                external_page.write_text(
                    f"# {fallback_title} - External Links\n\n" + "\n".join(external_lines) + "\n",
                    encoding="utf-8",
                )
            else:
                external_page.write_text(
                    f"# {fallback_title} - External Links\n\nNo external links found in this overview.\n",
                    encoding="utf-8",
                )

            week_count = 1
            index_rows.append({
                "folder": "week_00_course_overview",
                "title": fallback_title,
                "md_count": len(markdown_targets),
                "pdf_count": len(pdf_targets),
                "youtube_count": len(youtube_links),
                "external_count": len(external_links),
            })

    if index_rows:
        week_total = len(index_rows)
        total_md = sum(int(row.get("md_count") or 0) for row in index_rows)
        total_pdf = sum(int(row.get("pdf_count") or 0) for row in index_rows)
        total_youtube = sum(int(row.get("youtube_count") or 0) for row in index_rows)
        total_external = sum(int(row.get("external_count") or 0) for row in index_rows)
        avg_md = (total_md / week_total) if week_total else 0.0
        avg_pdf = (total_pdf / week_total) if week_total else 0.0
        avg_youtube = (total_youtube / week_total) if week_total else 0.0
        avg_external = (total_external / week_total) if week_total else 0.0
        lines = [
            "# NotebookLM Import Index",
            "",
            "| Week | Folder | Markdown | PDFs | YouTube Links | External Links |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for row in index_rows:
            lines.append(
                f"| {row['title']} | [{row['folder']}](./{row['folder']}/) | {row['md_count']} | {row['pdf_count']} | {row['youtube_count']} | {row['external_count']} |"
            )
        lines.append(
            f"| **Total** | - | **{total_md}** | **{total_pdf}** | **{total_youtube}** | **{total_external}** |"
        )
        lines.append(
            f"| **Average / week** | - | **{avg_md:.2f}** | **{avg_pdf:.2f}** | **{avg_youtube:.2f}** | **{avg_external:.2f}** |"
        )
        lines.append("")
        (bundle_root / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    bundle_zip_path = None
    has_bundle_files = any(item.is_file() for item in bundle_root.rglob("*"))
    if create_zip and has_bundle_files:
        bundle_zip_path = output_root / "notebooklm_import.zip"
        with zipfile.ZipFile(bundle_zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(bundle_root.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(output_root))

    return {
        "folder": str(bundle_root),
        "zip": str(bundle_zip_path) if bundle_zip_path else None,
        "weeks": week_count,
    }


def copiar_imagenes(DIR_COPIA,DIR):
    filesdoc=etree.parse(DIR_COPIA+"/files.xml")
    imagenes=filesdoc.xpath("//file/filename[contains(text(),'.jpg') or contains(text(),'.png')  or contains(text(),'.gif') ]/..")
    for img in imagenes:
        shutil.copyfile(DIR_COPIA+"/files/%s/%s"%(img.find("contenthash").text[0:2],img.find("contenthash").text),DIR+"img/%s"%img.find("filename").text) 



def crear_directorios(DIR,FICHERO):
    try:
        shutil.rmtree(DIR)
    except:
        pass

    os.makedirs(DIR, exist_ok=True)
    crear_fichero(FICHERO,DIR)
    os.makedirs(os.path.join(DIR, "files"), exist_ok=True)
    os.makedirs(os.path.join(DIR, "doc"), exist_ok=True)
    os.makedirs(os.path.join(DIR, "img"), exist_ok=True)

def getTituloDescripcion(DIR_COPIA,DIR,FICHERO):
    cursodoc=etree.parse(DIR_COPIA+'/course/course.xml')
    titulo=normalizar_html(cursodoc.findtext("fullname"))
    descripcion=normalizar_html(cursodoc.findtext("summary"), "img/", DIR, "")
    escribir(DIR,FICHERO,"# %s" % titulo)
    if descripcion:
        escribir(DIR,FICHERO)
        escribir(DIR,FICHERO,descripcion)
        escribir(DIR,FICHERO)

def getLabel(actividad,DIR_COPIA,DIR,FICHERO):
    intro = render_label_content(actividad, DIR_COPIA, DIR)
    if intro:
        escribir(DIR,FICHERO)
        escribir(DIR,FICHERO, intro)
        escribir(DIR,FICHERO)


def render_label_content(actividad, DIR_COPIA, DIR):
    doclabel=etree.parse(DIR_COPIA+"/%s/label.xml" % actividad.find("directory").text)
    intro = normalizar_html(doclabel.findtext("label/intro"), "img/", DIR, "")
    return intro

def getUrl(actividad,DIR_COPIA,DIR,FICHERO):
    content = render_url_content(actividad, DIR_COPIA, DIR)
    if content:
        escribir(DIR,FICHERO, content)


def render_url_content(actividad, DIR_COPIA, DIR, heading_level=3):
    docactivity=etree.parse(DIR_COPIA+"/%s/url.xml" % actividad.find("directory").text)
    titulo = normalizar_html(actividad.find("title").text)
    external_url = docactivity.find("url/externalurl").text

    link_target = external_url
    kind = "link"
    if is_youtube_url(external_url):
        kind = "youtube"
    elif looks_like_downloadable_file(external_url):
        try:
            link_target = download_external_file(external_url, titulo, DIR)
            lower_target = link_target.lower()
            if lower_target.endswith('.pdf'):
                kind = "pdf"
            else:
                kind = "file"
        except Exception as exc:
            link_target = create_external_link_note(external_url, titulo, DIR, str(exc))
            kind = "file"

    return build_affine_embed_block(titulo, link_target, kind, DIR, heading_level=heading_level)

def getAssign(actividad,DIR_COPIA,DIR,FICHERO):
    content = render_assign_content(actividad, DIR_COPIA, DIR)
    if content:
        escribir(DIR,FICHERO, content)


def render_assign_content(actividad, DIR_COPIA, DIR):
    docassign=etree.parse(DIR_COPIA+"/%s/calendar.xml" % actividad.find("directory").text)
    titulo = normalizar_html(actividad.find("title").text)
    nomfich=getNombreFichero(titulo)
    textos = []

    if len(docassign.getroot())>0:
        for event in docassign.getroot():
            descripcion = normalizar_html(event.findtext("description"), "../img/", DIR, "../")
            if descripcion and descripcion not in textos:
                textos.append(descripcion)
    else:
        docassign=etree.parse(DIR_COPIA+"/%s/assign.xml" % actividad.find("directory").text)
        descripcion = normalizar_html(docassign.findtext("assign/intro"), "../img/", DIR, "../")
        if descripcion:
            textos.append(descripcion)

    if len(textos)>0:
        crear_fichero(nomfich, DIR+"doc/")
        escribir(DIR+"doc/",nomfich,"# %s" % titulo)
        for texto in textos:
            escribir(DIR+"doc/",nomfich)
            escribir(DIR+"doc/",nomfich,texto)
    return "* [%s](%s)"%(titulo, ensure_explicit_relative_path(encode_relative_path("doc/"+nomfich)))

def getResource(actividad,DIR_COPIA,DIR,FICHERO):
    content = render_resource_content(actividad, DIR_COPIA, DIR)
    if content:
        escribir(DIR,FICHERO, content)


def render_resource_content(actividad, DIR_COPIA, DIR, heading_level=3):
    docresource=etree.parse(DIR_COPIA+"/%s/resource.xml" % actividad.find("directory").text)
    fileid=docresource.getroot().get("contextid")
    docfiles=etree.parse(DIR_COPIA+"/files.xml")
    fichero=docfiles.xpath("//file[contextid=%s]"%fileid)
    titulo = normalizar_html(actividad.find("title").text)
    try:
        shutil.copyfile(DIR_COPIA+"/files/%s/%s"%(fichero[0].find("contenthash").text[0:2],fichero[0].find("contenthash").text),DIR+"files/%s"%fichero[0].find("filename").text)
        target = encode_relative_path("files/"+fichero[0].find("filename").text)
        kind = "pdf" if target.lower().endswith('.pdf') else "file"
        return build_affine_embed_block(titulo, target, kind, DIR, heading_level=heading_level)
    except:
        print("File not found.")
        print(actividad.find("directory").text, fileid)
        return None

def getPage(actividad,DIR_COPIA,DIR,FICHERO):
    content = render_page_content(actividad, DIR_COPIA, DIR)
    if content:
        escribir(DIR,FICHERO, content)


def render_page_content(actividad, DIR_COPIA, DIR):
    docpage=etree.parse(DIR_COPIA+"/%s/page.xml" % actividad.find("directory").text)
    titulo = normalizar_html(actividad.find("title").text)
    nomfich=getNombreFichero(titulo)
    contenido = normalizar_html(docpage.findtext("page/content"), "../img/", DIR, "../")
    if contenido:
        crear_fichero(nomfich, DIR+"doc/")
        escribir(DIR+"doc/",nomfich,"# %s" % titulo)
        escribir(DIR+"doc/",nomfich)
        escribir(DIR+"doc/",nomfich,contenido)
    return "* [%s](%s)"%(titulo, ensure_explicit_relative_path(encode_relative_path("doc/"+nomfich)))


def build_structured_activity_entry(actividad, DIR_COPIA, DIR, current_bucket):
    tipo = actividad.find("modulename").text
    titulo = normalizar_html(actividad.findtext("title") or "")
    plain_title = plain_text_for_classification(titulo)
    explicit_bucket = detect_structured_bucket(plain_title)

    if tipo == "label":
        intro = render_label_content(actividad, DIR_COPIA, DIR)
        if not intro:
            return None, current_bucket
        if is_bucket_heading_label(intro):
            return None, detect_structured_bucket(intro, current_bucket or "inhalte")
        return {
            "bucket": explicit_bucket or current_bucket or detect_structured_bucket(intro, "inhalte") or "inhalte",
            "content": intro,
        }, current_bucket

    if tipo == "url":
        content = render_url_content(actividad, DIR_COPIA, DIR, heading_level=4)
        default_bucket = "materialien"
    elif tipo == "assign":
        content = render_assign_content(actividad, DIR_COPIA, DIR)
        default_bucket = "aufgaben"
    elif tipo == "resource":
        content = render_resource_content(actividad, DIR_COPIA, DIR, heading_level=4)
        default_bucket = "materialien"
    elif tipo == "page":
        content = render_page_content(actividad, DIR_COPIA, DIR)
        default_bucket = "inhalte"
    elif tipo in {"forum", "wiki", "chat"}:
        content = "* %s" % plain_title if plain_title else None
        default_bucket = "diskussionspunkte"
    elif tipo in {"quiz", "feedback", "workshop"}:
        content = "* %s (%s)" % (plain_title, tipo) if plain_title else None
        default_bucket = "aufgaben"
    else:
        content = "* %s (%s)" % (plain_title, tipo) if plain_title else None
        default_bucket = "inhalte"

    if not content:
        return None, current_bucket

    bucket = explicit_bucket or current_bucket or default_bucket
    if default_bucket == "materialien" and detect_structured_bucket(plain_title) == "literatur":
        bucket = "literatur"
    return {"bucket": bucket, "content": content}, current_bucket


def write_structured_section(DIR_COPIA, DIR, FICHERO, section_heading, summary, actividades):
    sections = {key: [] for key, _ in STRUCTURED_WEEK_SECTIONS}

    if summary:
        summary_blocks = [block.strip() for block in re.split(r"\n\s*\n", summary) if block.strip()]
        for block in summary_blocks:
            append_structured_content(sections, detect_structured_bucket(block, "inhalte"), block)

    current_bucket = None
    for actividad in actividades:
        entry, current_bucket = build_structured_activity_entry(actividad, DIR_COPIA, DIR, current_bucket)
        if entry:
            append_structured_content(sections, entry["bucket"], entry["content"])

    render_structured_section(DIR, FICHERO, section_heading, sections)


def write_classic_section(DIR_COPIA, DIR, FICHERO, section_title, summary, actividades):
    if section_title:
        escribir(DIR,FICHERO)
        escribir(DIR,FICHERO,"## %s" % section_title)
        escribir(DIR,FICHERO)
    if summary:
        escribir(DIR,FICHERO,summary)
        escribir(DIR,FICHERO)

    for actividad in actividades:
        tipo = actividad.find("modulename").text
        if tipo=="label":
            getLabel(actividad,DIR_COPIA,DIR,FICHERO)
        elif tipo=="url":
            getUrl(actividad,DIR_COPIA,DIR,FICHERO)
        elif tipo=="assign":
            getAssign(actividad,DIR_COPIA,DIR,FICHERO)
        elif tipo=="resource":
            getResource(actividad,DIR_COPIA,DIR,FICHERO)
        elif tipo=="page":
            getPage(actividad,DIR_COPIA,DIR,FICHERO)
        else:
            escribir(DIR,FICHERO, "* %s (%s)" % (normalizar_html(actividad.find("title").text), actividad.find("modulename").text))


def getSeccionesActividades(DIR_COPIA,DIR,FICHERO, structured_weeks=False, week_pages=False):

    doc = etree.parse(DIR_COPIA+'/moodle_backup.xml')
    secciones=doc.find("information/contents/sections")
    overview_heading_written = False
    generated_week_pages = []
    for section_number, seccion in enumerate(secciones, start=1):
        docseccion=etree.parse(DIR_COPIA+"/%s/section.xml" % seccion.find("directory").text)
        raw_title = docseccion.findtext("title") or docseccion.findtext("name")
        nombre=normalizar_html(raw_title)
        summary=normalizar_html(docseccion.findtext("summary"), "img/", DIR, "")
        section_heading = normalize_section_title(raw_title or nombre, section_number) if structured_weeks else (nombre or f"Session {section_number}")

        sectionid=seccion.find("sectionid").text
        actividades=doc.xpath("//activity[sectionid=%s]"%sectionid)

        if week_pages:
            week_doc_name = build_week_doc_name(section_heading, section_number)
            week_dir = DIR + "doc/"
            crear_fichero(week_doc_name, week_dir)
            if structured_weeks:
                write_structured_section(
                    DIR_COPIA,
                    DIR,
                    f"doc/{week_doc_name}",
                    section_heading,
                    summary,
                    actividades,
                )
            else:
                write_classic_section(DIR_COPIA, DIR, f"doc/{week_doc_name}", section_heading, summary, actividades)
            overview_heading_written = render_section_overview_link(
                DIR,
                FICHERO,
                section_heading,
                ensure_explicit_relative_path(encode_relative_path(f"doc/{week_doc_name}")),
                overview_heading_written,
            )
            generated_week_pages.append({
                "title": section_heading,
                "relative_path": f"doc/{week_doc_name}",
            })
            continue

        if structured_weeks:
            write_structured_section(
                DIR_COPIA,
                DIR,
                FICHERO,
                section_heading,
                summary,
                actividades,
            )
            continue

        write_classic_section(DIR_COPIA, DIR, FICHERO, section_heading, summary, actividades)

    return generated_week_pages


def convert_course(
    source_dir,
    output_dir=None,
    single_page=False,
    zip_output=False,
    html_output=False,
    structured_weeks=False,
    week_pages=False,
    native_week_pages=False,
    pdf_text_blocks=False,
    pdf_text_engine="auto",
    pdf_text_max_pages=8,
    pdf_text_max_chars=20000,
    pdf_text_ocr_fallback=None,
    pdf_text_ocr_lang="eng",
    notebooklm_export=False,
    notebooklm_zip=None,
):
    assert_supported_runtime()
    dir_copia = os.path.abspath(os.path.expanduser(source_dir))
    if not os.path.isdir(dir_copia):
        raise FileNotFoundError(f"Source directory not found: {dir_copia}")

    if output_dir:
        target_dir = os.path.abspath(os.path.expanduser(output_dir))
    else:
        target_dir = os.path.join(os.getcwd(), "course")

    DIR = target_dir.rstrip(os.sep) + os.sep
    FICHERO="README.md"
    effective_week_pages = week_pages or native_week_pages or notebooklm_export
    effective_notebooklm_zip = bool(notebooklm_export) if notebooklm_zip is None else bool(notebooklm_zip)
    effective_pdf_text_ocr_fallback = bool(pdf_text_blocks) if pdf_text_ocr_fallback is None else bool(pdf_text_ocr_fallback)
    configure_runtime_options(
        pdf_text_blocks=bool(pdf_text_blocks),
        pdf_text_engine=str(pdf_text_engine or "auto").strip().lower(),
        pdf_text_max_pages=max(1, int(pdf_text_max_pages or 8)),
        pdf_text_max_chars=max(500, int(pdf_text_max_chars or 20000)),
        pdf_text_ocr_fallback=effective_pdf_text_ocr_fallback,
        pdf_text_ocr_lang=str(pdf_text_ocr_lang or "eng").strip() or "eng",
    )
    PDF_TEXT_CACHE.clear()
    crear_directorios(DIR,FICHERO)
    copiar_imagenes(dir_copia,DIR)
    getTituloDescripcion(dir_copia,DIR,FICHERO)
    week_pages_manifest = getSeccionesActividades(
        dir_copia,
        DIR,
        FICHERO,
        structured_weeks=structured_weeks,
        week_pages=effective_week_pages,
    )

    readme_path = os.path.join(target_dir, FICHERO)
    main_file = readme_path
    if single_page:
        main_file = integrar_en_una_sola_pagina(target_dir)

    html_file = None
    if html_output:
        source_name = Path(main_file).name if single_page else None
        html_file = create_affine_html_export(target_dir, source_name=source_name)

    zip_file = None
    native_snapshot_file = None
    native_zip_file = None
    if zip_output:
        zip_file = create_affine_zip(
            target_dir,
            include_doc_pages=week_pages,
            include_pdf_text_pages=bool(pdf_text_blocks),
        )
        native_snapshot_file, native_zip_file = create_affine_native_zip(
            target_dir,
            source_name=Path(main_file).name if main_file else None,
            week_pages_manifest=week_pages_manifest,
            native_week_pages=native_week_pages,
        )

    notebooklm_folder = None
    notebooklm_zip_file = None
    notebooklm_weeks = 0
    notebooklm_error = None
    if notebooklm_export:
        try:
            notebooklm_result = build_notebooklm_import_bundle(
                target_dir,
                week_pages_manifest=week_pages_manifest,
                create_zip=effective_notebooklm_zip,
            )
            notebooklm_folder = notebooklm_result.get("folder")
            notebooklm_zip_file = notebooklm_result.get("zip")
            notebooklm_weeks = int(notebooklm_result.get("weeks") or 0)
        except Exception as exc:
            notebooklm_error = f"NotebookLM export failed: {exc}"
            print(notebooklm_error)

    return {
        "output_dir": target_dir,
        "readme": readme_path,
        "main_file": main_file,
        "html_file": html_file,
        "zip_file": zip_file,
        "native_snapshot_file": native_snapshot_file,
        "native_zip_file": native_zip_file,
        "single_page": single_page,
        "html_output": html_output,
        "structured_weeks": structured_weeks,
        "week_pages": week_pages,
        "native_week_pages": native_week_pages,
        "effective_week_pages": effective_week_pages,
        "pdf_text_blocks": bool(pdf_text_blocks),
        "pdf_text_engine": str(pdf_text_engine or "auto"),
        "pdf_text_max_pages": max(1, int(pdf_text_max_pages or 8)),
        "pdf_text_max_chars": max(500, int(pdf_text_max_chars or 20000)),
        "pdf_text_ocr_fallback": effective_pdf_text_ocr_fallback,
        "pdf_text_ocr_lang": str(pdf_text_ocr_lang or "eng").strip() or "eng",
        "notebooklm_export": bool(notebooklm_export),
        "notebooklm_zip": effective_notebooklm_zip,
        "notebooklm_folder": notebooklm_folder,
        "notebooklm_zip_file": notebooklm_zip_file,
        "notebooklm_weeks": notebooklm_weeks,
        "notebooklm_error": notebooklm_error,
    }


def main():
    parser = argparse.ArgumentParser(description='Convert a Moodle backup into Markdown')
    parser.add_argument('-d',  type=str, required=True, help='path to the unpacked Moodle backup directory')
    parser.add_argument('-o',  type=str, help='output directory')
    parser.add_argument('--single-page', action='store_true', help='also create a combined single Markdown page')
    parser.add_argument('--zip', dest='zip_output', action='store_true', help='also create an Affine-ready ZIP package with media files')
    parser.add_argument('--html', dest='html_output', action='store_true', help='also create an AFFiNE-friendly HTML export')
    parser.add_argument('--structured-weeks', action='store_true', help='group each course week into fixed sections like Learning Goals, Content, Materials and Assignments')
    parser.add_argument('--week-pages', action='store_true', help='keep the course description on the main page and export each week as a linked Markdown subpage')
    parser.add_argument('--native-week-pages', action='store_true', help='for the AFFiNE Snapshot export, keep the course description as the main page and add weeks as native child pages')
    parser.add_argument('--pdf-text-blocks', action='store_true', help='extract text from local PDF files and create readable markdown text blocks under doc/pdf_text')
    parser.add_argument('--pdf-text-engine', type=str, default='auto', choices=['auto', 'pymupdf', 'tika'], help='parser engine for PDF text extraction')
    parser.add_argument('--pdf-text-max-pages', type=int, default=8, help='maximum number of PDF pages to extract per file')
    parser.add_argument('--pdf-text-max-chars', type=int, default=20000, help='maximum number of extracted characters per PDF')
    parser.add_argument('--pdf-text-ocr-fallback', dest='pdf_text_ocr_fallback', action='store_true', help='enable OCR fallback with Tesseract for image-based PDFs')
    parser.add_argument('--no-pdf-text-ocr-fallback', dest='pdf_text_ocr_fallback', action='store_false', help='disable OCR fallback even when PDF text blocks are enabled')
    parser.set_defaults(pdf_text_ocr_fallback=None)
    parser.add_argument('--pdf-text-ocr-lang', type=str, default='eng', help='OCR language for Tesseract, e.g. eng, deu, eng+deu')
    parser.add_argument('--notebooklm-export', action='store_true', help='create a NotebookLM import folder with per-week subfolders and grouped files')
    parser.add_argument('--notebooklm-zip', dest='notebooklm_zip', action='store_true', help='also create notebooklm_import.zip when NotebookLM export is enabled')
    parser.add_argument('--no-notebooklm-zip', dest='notebooklm_zip', action='store_false', help='do not create notebooklm_import.zip')
    parser.set_defaults(notebooklm_zip=None)
    args = parser.parse_args()
    result = convert_course(
        args.d,
        args.o,
        single_page=args.single_page,
        zip_output=args.zip_output,
        html_output=args.html_output,
        structured_weeks=args.structured_weeks,
        week_pages=args.week_pages,
        native_week_pages=args.native_week_pages,
        pdf_text_blocks=args.pdf_text_blocks,
        pdf_text_engine=args.pdf_text_engine,
        pdf_text_max_pages=args.pdf_text_max_pages,
        pdf_text_max_chars=args.pdf_text_max_chars,
        pdf_text_ocr_fallback=args.pdf_text_ocr_fallback,
        pdf_text_ocr_lang=args.pdf_text_ocr_lang,
        notebooklm_export=args.notebooklm_export,
        notebooklm_zip=args.notebooklm_zip,
    )
    print(f"Output directory: {result['output_dir']}")
    print(f"Main file: {result['main_file']}")
    print(f"Structured weeks: {'yes' if result['structured_weeks'] else 'no'}")
    print(f"Week pages: {'yes' if result['week_pages'] else 'no'}")
    print(f"Native week pages: {'yes' if result['native_week_pages'] else 'no'}")
    print(f"PDF text blocks: {'yes' if result['pdf_text_blocks'] else 'no'}")
    if result['pdf_text_blocks']:
        print(f"PDF text engine: {result['pdf_text_engine']}")
        print(f"PDF text max pages: {result['pdf_text_max_pages']}")
        print(f"PDF text max chars: {result['pdf_text_max_chars']}")
        print(f"PDF text OCR fallback: {'yes' if result['pdf_text_ocr_fallback'] else 'no'}")
        if result['pdf_text_ocr_fallback']:
            print(f"PDF text OCR language: {result['pdf_text_ocr_lang']}")
    print(f"NotebookLM export: {'yes' if result['notebooklm_export'] else 'no'}")
    if result['notebooklm_export']:
        print(f"NotebookLM folder: {result['notebooklm_folder'] or 'not created'}")
        print(f"NotebookLM ZIP: {result['notebooklm_zip_file'] or 'not created'}")
        print(f"NotebookLM weeks exported: {result['notebooklm_weeks']}")
        if result['notebooklm_error']:
            print(result['notebooklm_error'])
    if result['html_file']:
        print(f"AFFiNE HTML: {result['html_file']}")
    if result['zip_file']:
        print(f"Affine ZIP: {result['zip_file']}")
    if result['native_snapshot_file']:
        print(f"AFFiNE Snapshot JSON: {result['native_snapshot_file']}")
    if result['native_zip_file']:
        print(f"AFFiNE Native ZIP (import via Snapshot): {result['native_zip_file']}")


if __name__ == '__main__':
    main()
    

        



