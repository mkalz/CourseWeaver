#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Moodle2AffineMD
# Based on the original `moodle2md` project by José Domingo Muñoz Rodríguez:
# https://github.com/josedom24/moodle2md
from lxml import etree
from sys import argv
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
from html import unescape, escape
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen



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


def build_affine_attachment_marker(title, target, output_dir):
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
        f"\n### {readable_title}\n\n"
        f"[^{footnote_id}]: {json.dumps(metadata, ensure_ascii=False)}\n"
    )


def build_affine_embed_block(title, target, kind="link", output_dir=None):
    if kind == "youtube":
        embed_url = get_youtube_embed_url(target)
        if embed_url:
            return f'\n### {title}\n\n<iframe src="{embed_url}"></iframe>\n\n[Open on YouTube]({target})\n'
        return f"\n### {title}\n\n[Open link]({target})\n"
    if kind in {"pdf", "file"}:
        attachment_marker = build_affine_attachment_marker(title, target, output_dir)
        if attachment_marker:
            return attachment_marker
        if target:
            safe_target = ensure_explicit_relative_path(target)
            return f"\n### {title}\n\n[{title}]({safe_target})\n"
        return f"\n### {title}\n"
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



def create_affine_zip(output_dir, archive_path=None):
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
            for item in sorted(doc_dir.glob("*external_link*.md")):
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
            level = min(len(heading_match.group(1)), 6)
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


def create_affine_native_zip(output_dir, archive_path=None, source_name=None):
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
    blocks, assets_by_blob = build_affine_native_blocks(markdown_text, output_dir)
    first_heading = next(
        (line.lstrip("# ").strip() for line in markdown_text.splitlines() if line.strip().startswith("#")),
        output_path.name,
    )
    title = re.sub(r"\s+", " ", first_heading).strip() or output_path.name
    now_ms = int(time.time() * 1000)

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
            "children": [
                {
                    "type": "block",
                    "id": affine_block_id("surface"),
                    "flavour": "affine:surface",
                    "props": {
                        "elements": {},
                    },
                    "children": [],
                },
                {
                    "type": "block",
                    "id": affine_block_id("note"),
                    "flavour": "affine:note",
                    "props": {
                        "xywh": "[0,0,800,95]",
                        "background": "rgba(255,255,255,0)",
                        "index": "a0",
                        "hidden": False,
                        "displayMode": "both",
                    },
                    "children": blocks,
                },
            ],
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

def getSeccionesActividades(DIR_COPIA,DIR,FICHERO):

    doc = etree.parse(DIR_COPIA+'/moodle_backup.xml')
    secciones=doc.find("information/contents/sections")
    for seccion in secciones:
        docseccion=etree.parse(DIR_COPIA+"/%s/section.xml" % seccion.find("directory").text)
        nombre=normalizar_html(docseccion.findtext("title") or docseccion.findtext("name"))
        summary=normalizar_html(docseccion.findtext("summary"), "img/", DIR, "")

        if nombre:
            escribir(DIR,FICHERO)
            escribir(DIR,FICHERO,"## %s" % nombre)
            escribir(DIR,FICHERO)
        if summary:
            escribir(DIR,FICHERO,summary)
            escribir(DIR,FICHERO)

        sectionid=seccion.find("sectionid").text
        actividades=doc.xpath("//activity[sectionid=%s]"%sectionid)
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

def getLabel(actividad,DIR_COPIA,DIR,FICHERO):
    doclabel=etree.parse(DIR_COPIA+"/%s/label.xml" % actividad.find("directory").text)
    intro = normalizar_html(doclabel.findtext("label/intro"), "img/", DIR, "")
    if intro:
        escribir(DIR,FICHERO)
        escribir(DIR,FICHERO, intro)
        escribir(DIR,FICHERO)

def getUrl(actividad,DIR_COPIA,DIR,FICHERO):
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

    escribir(DIR,FICHERO, build_affine_embed_block(titulo, link_target, kind, DIR))

def getAssign(actividad,DIR_COPIA,DIR,FICHERO):
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
    escribir(DIR,FICHERO,"* [%s](%s)"%(titulo, ensure_explicit_relative_path(encode_relative_path("doc/"+nomfich))))

def getResource(actividad,DIR_COPIA,DIR,FICHERO):
    docresource=etree.parse(DIR_COPIA+"/%s/resource.xml" % actividad.find("directory").text)
    fileid=docresource.getroot().get("contextid")
    docfiles=etree.parse(DIR_COPIA+"/files.xml")
    fichero=docfiles.xpath("//file[contextid=%s]"%fileid)
    titulo = normalizar_html(actividad.find("title").text)
    try:
        shutil.copyfile(DIR_COPIA+"/files/%s/%s"%(fichero[0].find("contenthash").text[0:2],fichero[0].find("contenthash").text),DIR+"files/%s"%fichero[0].find("filename").text)
        target = encode_relative_path("files/"+fichero[0].find("filename").text)
        kind = "pdf" if target.lower().endswith('.pdf') else "file"
        escribir(DIR,FICHERO, build_affine_embed_block(titulo, target, kind, DIR))
    except:
        print("Fichero no encontrado.")
        print(actividad.find("directory").text, fileid)

def getPage(actividad,DIR_COPIA,DIR,FICHERO):
    docpage=etree.parse(DIR_COPIA+"/%s/page.xml" % actividad.find("directory").text)
    titulo = normalizar_html(actividad.find("title").text)
    nomfich=getNombreFichero(titulo)
    contenido = normalizar_html(docpage.findtext("page/content"), "../img/", DIR, "../")
    if contenido:
        crear_fichero(nomfich, DIR+"doc/")
        escribir(DIR+"doc/",nomfich,"# %s" % titulo)
        escribir(DIR+"doc/",nomfich)
        escribir(DIR+"doc/",nomfich,contenido)
    escribir(DIR,FICHERO,"* [%s](%s)"%(titulo, ensure_explicit_relative_path(encode_relative_path("doc/"+nomfich))))


def convert_course(source_dir, output_dir=None, single_page=False, zip_output=False, html_output=False):
    dir_copia = os.path.abspath(os.path.expanduser(source_dir))
    if not os.path.isdir(dir_copia):
        raise FileNotFoundError(f"Source directory not found: {dir_copia}")

    if output_dir:
        target_dir = os.path.abspath(os.path.expanduser(output_dir))
    else:
        target_dir = os.path.join(os.getcwd(), "course")

    DIR = target_dir.rstrip(os.sep) + os.sep
    FICHERO="README.md"
    crear_directorios(DIR,FICHERO)
    copiar_imagenes(dir_copia,DIR)
    getTituloDescripcion(dir_copia,DIR,FICHERO)
    getSeccionesActividades(dir_copia,DIR,FICHERO)

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
        zip_file = create_affine_zip(target_dir)
        native_snapshot_file, native_zip_file = create_affine_native_zip(
            target_dir,
            source_name=Path(main_file).name if main_file else None,
        )

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
    }


def main():
    parser = argparse.ArgumentParser(description='Convert a Moodle backup into Markdown')
    parser.add_argument('-d',  type=str, required=True, help='path to the unpacked Moodle backup directory')
    parser.add_argument('-o',  type=str, help='output directory')
    parser.add_argument('--single-page', action='store_true', help='also create a combined single Markdown page')
    parser.add_argument('--zip', dest='zip_output', action='store_true', help='also create an Affine-ready ZIP package with media files')
    parser.add_argument('--html', dest='html_output', action='store_true', help='also create an AFFiNE-friendly HTML export')
    args = parser.parse_args()
    result = convert_course(
        args.d,
        args.o,
        single_page=args.single_page,
        zip_output=args.zip_output,
        html_output=args.html_output,
    )
    print(f"Output directory: {result['output_dir']}")
    print(f"Main file: {result['main_file']}")
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
    

        



