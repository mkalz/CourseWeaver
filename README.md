# CourseWeaver

[![CI](https://github.com/mkalz/CourseWeaver/actions/workflows/ci.yml/badge.svg)](https://github.com/mkalz/CourseWeaver/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

CourseWeaver converts unpacked Moodle course backups into structured knowledge bundles for Markdown, AFFiNE, and NotebookLM workflows.

It is the successor to Moodle2Affine and extends the original converter with a local Web UI, structured week exports, AFFiNE ZIP and Snapshot output, PDF text extraction with OCR fallback, and NotebookLM-ready folder bundles.

1. Download a Moodle course as archive (.mbz)
2. Rename the file from .mbz to .zip.
3. Unpack the zip file.
4. Rename the folder to a shorter name.
5. Covert to markdown and import the resulting zip-file as Snapshot into Affine.

> The CLI entry point remains `moodle2md.py` for backward compatibility.

## ✨ Features

- Converts Moodle course content into readable Markdown
- Creates structured course bundles for Markdown, AFFiNE, and NotebookLM
- Cleans HTML-heavy Moodle exports for better publishing quality
- Copies media into local `img/` and `files/` folders
- Creates `README.md` plus optional `doc/*.md` pages
- Creates an optional single-page export: `ALL_IN_ONE.md`
- Creates an AFFiNE Markdown ZIP: `*_affine.zip`
- Creates a native AFFiNE Snapshot ZIP: `*_affine_native.zip`
- Creates an HTML fallback export: `AFFINE_IMPORT.html`
- Extracts text from PDFs with optional OCR fallback
- Creates NotebookLM import bundles with per-week folders
- Includes a local browser-based Web UI

## 🚀 Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output --single-page --zip --html --structured-weeks --week-pages --native-week-pages --pdf-text-blocks
```

## 🔧 CLI usage

### Standard export

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output
```

### Full export for GitHub + AFFiNE

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output --single-page --zip --html --structured-weeks --week-pages --native-week-pages --pdf-text-blocks --notebooklm-export
```

### Structured week layout

Use `--structured-weeks` if you want each imported Moodle section to be reorganized into a clearer AFFiNE- and Markdown-friendly layout such as:

```md
## Session 4: Media Critique

### Learning Goals
- ...

### Content
- ...

### Materials
- PDFs, Links, Videos

### Assignments
- ...

### Discussion Points
- ...

### Literature
- ...
```

The converter uses the section summary, labels, and activity types to sort existing content into these buckets heuristically while keeping the classic output unchanged unless the flag is enabled.

### Course page with weekly subpages

Use `--week-pages` if the course description should remain the main page while each Moodle week is exported as its own Markdown page in `doc/` and linked from `README.md`.

This is useful for AFFiNE Markdown ZIP imports when you want a course landing page plus separate week pages instead of one long root document.

### Native AFFiNE child pages

Use `--native-week-pages` if the native AFFiNE Snapshot export should keep the course description and merge each exported week into the main snapshot page structure for maximum import compatibility.

This option is designed to work alongside `--zip`, and it can be combined with `--structured-weeks` and `--week-pages`.

### Optional PDF to text blocks

Use `--pdf-text-blocks` if local PDF resources should be parsed into readable Markdown text blocks.

The converter keeps the original PDF attachment and additionally creates linked text pages in `doc/pdf_text/`.

Available parser options:

- `--pdf-text-engine auto` (default, tries `pymupdf`, then optional `tika`)
- `--pdf-text-engine pymupdf`
- `--pdf-text-engine tika` (requires `tika` package and Java runtime)

Extraction limits can be tuned per file:

- `--pdf-text-max-pages 8`
- `--pdf-text-max-chars 20000`

Optional OCR fallback for scanned/image-based PDFs:

- `--pdf-text-ocr-fallback` (enabled by default when `--pdf-text-blocks` is used)
- `--no-pdf-text-ocr-fallback` (explicitly disable OCR fallback)
- `--pdf-text-ocr-lang eng` (examples: `deu`, `eng+deu`)

OCR requires the system binary `tesseract` to be installed and available in `PATH`.

In the Web UI, the default OCR language is inferred from your system locale (for example `deu+eng` on German systems) and can still be edited manually.

Example:

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output --zip --pdf-text-blocks --pdf-text-engine auto --pdf-text-max-pages 10 --pdf-text-max-chars 30000 --pdf-text-ocr-fallback --pdf-text-ocr-lang eng+deu
```

### NotebookLM import bundle

Use `--notebooklm-export` to create a dedicated NotebookLM folder structure under `notebooklm_import/`.

For each week, the converter creates a separate folder containing:

- `md/` with the week Markdown page and linked local Markdown pages
- `pdf/` with linked local PDF files
- `youtube_links.md` with all YouTube links found in the week page
- `external_links.md` with all other external HTTP links

By default, `notebooklm_import.zip` is also generated when NotebookLM export is enabled.

Options:

- `--notebooklm-export`
- `--notebooklm-zip` (explicitly enable ZIP output)
- `--no-notebooklm-zip` (disable ZIP output)

## 🌐 Web UI

Start the local interface with:

```bash
./start_webui.command
```

or:

```bash
./.venv/bin/python webui.py
```

Then open:

```text
http://127.0.0.1:8765
```

## 📦 Output files

```text
README.md
ALL_IN_ONE.md
AFFINE_IMPORT.html
doc/
doc/pdf_text/
files/
img/
<output_name>_affine.zip
<output_name>_affine_native.zip
```

## 📥 How to import into AFFiNE

| File | Import mode in AFFiNE | Purpose |
| --- | --- | --- |
| `*_affine.zip` | `Markdown with media files (.zip)` | Standard Markdown + assets import |
| `*_affine_native.zip` | `Snapshot` | Native AFFiNE import with PDF blocks prepared for embed mode |
| `AFFINE_IMPORT.html` | `HTML files` | Fallback if Markdown import limits media behavior |

## 🧱 Project structure

```text
moodle2md.py        CLI converter
webui.py            local web server
webui/index.html    browser UI
start_webui.command macOS launcher
requirements.txt    Python dependencies
```

## Upstream origin and attribution

CourseWeaver is the successor to Moodle2Affine and remains a modernization and extension of the original project:

- **Original repository:** `josedom24/moodle2md`
- **URL:** `https://github.com/josedom24/moodle2md`
- **Original author:** José Domingo Muñoz Rodríguez

The current project adds Python 3 compatibility, GitHub-oriented documentation, a local Web UI, structured week exports, AFFiNE ZIP export, AFFiNE native Snapshot export, PDF extraction with OCR fallback, NotebookLM bundles, and HTML fallback export.

## 📄 License and compliance note

At the time of review, the checked upstream repository contents showed the source files and `README.md`, but **no explicit `LICENSE` file** was visible in that repository listing.

Because of that:

- this repository now **explicitly references the original project and author**
- the included `LICENSE` applies to **new additions and modifications only, where licensable**
- the original upstream portions remain attributed to their original author and subject to the upstream licensing status
- for broad public redistribution, **upstream permission or explicit license clarification is recommended**
