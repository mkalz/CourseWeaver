# CourseBeaver

[![CI](https://img.shields.io/github/actions/workflow/status/mkalz/CourseBeaver/ci.yml?branch=main&label=CI)](https://github.com/mkalz/CourseBeaver/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-16a34a.svg)](LICENSE)

![CourseBeaver logo](webui/coursebeaver-logo.svg)

CourseBeaver converts unpacked Moodle course backups into structured knowledge bundles for Markdown, AFFiNE, and NotebookLM workflows.

It is the successor to Moodle2Affine and extends the original converter with a local Web UI, structured week exports, AFFiNE ZIP and Snapshot output, PDF text extraction with OCR fallback, and NotebookLM-ready folder bundles.

The current release also includes an end-to-end AI pipeline for weekly summaries and audio generation (Gemini TTS or ElevenLabs), including resume mode and job-level tracking.

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

## 🤖 AI Quickstart (5 minutes)

Use this section if you only want AI summaries + audio quickly.

1. Activate your virtual environment and install dependencies.
2. Set provider API keys in your shell.
3. Run one of the tested commands below.

### Option A: Gemini summary + Gemini TTS audio

```bash
export GEMINI_API_KEY="your_key_here"

python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --week-pages --ai-week-summary \
  --ai-summary-provider gemini --ai-summary-model gemini-2.5-flash \
  --gemini-tts --gemini-tts-model gemini-2.5-flash-preview-tts \
  --gemini-tts-voice Kore --gemini-tts-min-interval-seconds 5.0
```

### Option B: OpenAI-compatible summary + ElevenLabs audio

```bash
export OPENAI_API_KEY="your_key_here"
export ELEVENLABS_API_KEY="your_key_here"
export ELEVENLABS_VOICE_ID="your_voice_id"

python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --week-pages --ai-week-summary \
  --ai-summary-provider openai --ai-summary-model gpt-4o-mini \
  --elevenlabs-tts --elevenlabs-model-id eleven_multilingual_v2
```

### Resume only missing audio files

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --audio-only-missing --ai-summary-provider gemini --gemini-tts
```

This resume mode reuses existing output and only processes missing audio jobs where possible.

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

### Optional PDF text extraction (with optional PDF text audio)

Use `--pdf-text-blocks` if local PDF resources should be parsed and embedded as readable text directly inside week pages.

The original PDF file link is preserved, and extracted text is added inline when parsing succeeds.

Available parser options:

- `--pdf-text-engine auto` (default, tries `pymupdf`, then optional `tika`)
- `--pdf-text-engine pymupdf`
- `--pdf-text-engine tika` (requires `tika` package and Java runtime)

Extraction limits:

- `--pdf-text-max-pages 8`
- `--pdf-text-max-chars 20000`

Optional OCR fallback for scanned/image-based PDFs:

- `--pdf-text-ocr-fallback` (enabled by default when `--pdf-text-blocks` is used)
- `--no-pdf-text-ocr-fallback`
- `--pdf-text-ocr-lang eng` (examples: `deu`, `eng+deu`)

OCR requires the system binary `tesseract` to be installed and available in `PATH`.

Optional PDF text audio:

- `--pdf-text-audio` / `--no-pdf-text-audio`
- `--pdf-text-audio-min-chars 300` (minimum extracted text length before creating audio)

Example:

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --week-pages --pdf-text-blocks --pdf-text-engine auto \
  --pdf-text-max-pages 10 --pdf-text-max-chars 30000 \
  --pdf-text-ocr-fallback --pdf-text-ocr-lang eng+deu \
  --pdf-text-audio --pdf-text-audio-min-chars 300
```

### AI summaries and audio production

CourseBeaver supports AI-generated weekly summaries and audio output with a two-phase pipeline:

1. Phase 1: Generate all weekly summaries.
2. Phase 2: Generate audio from the generated summaries.

This design prevents partial runs where audio failures stop summary generation too early.

#### Providers

- Summary providers:
  - OpenAI-compatible (`--ai-summary-provider openai`)
  - Gemini (`--ai-summary-provider gemini`)
- Audio providers:
  - Gemini TTS (`--gemini-tts`)
  - ElevenLabs (`--elevenlabs-tts`)

Gemini TTS requires Gemini as summary provider.

#### Required environment variables

- For OpenAI-compatible summaries:
  - `OPENAI_API_KEY`
- For Gemini summaries/TTS:
  - `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- For ElevenLabs audio:
  - `ELEVENLABS_API_KEY`
  - `ELEVENLABS_VOICE_ID` (or pass `--elevenlabs-voice-id`)

#### Main AI/Audio CLI flags

- Summary:
  - `--ai-week-summary`
  - `--ai-summary-provider openai|gemini`
  - `--ai-summary-model ...`
  - `--ai-summary-language de|en|...`
  - `--ai-summary-max-chars 12000`
  - `--ai-summary-base-url ...`
- Gemini audio:
  - `--gemini-tts`
  - `--gemini-tts-model gemini-2.5-flash-preview-tts`
  - `--gemini-tts-voice Kore`
  - `--gemini-tts-base-url https://generativelanguage.googleapis.com/v1beta`
  - `--gemini-tts-min-interval-seconds 5.0`
- ElevenLabs audio:
  - `--elevenlabs-tts`
  - `--elevenlabs-voice-id ...`
  - `--elevenlabs-model-id eleven_multilingual_v2`
- Resume mode:
  - `--audio-only-missing`

#### Job artifacts and resume

AI processing writes job-level artifacts to `files/ai_jobs/`:

- `files/ai_jobs/input/` contains markdown inputs for summary/audio jobs.
- `files/ai_jobs/output/` contains generated summary/audio metadata markdown files.
- `files/ai_jobs/manifest.jsonl` tracks job states (`queued`, `done`, `reused`, `skipped`, `error`).

With `--audio-only-missing`, CourseBeaver resumes from existing output and uses manifest state to skip already completed jobs when possible.

#### End-to-end examples

Gemini-only summary + audio:

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --week-pages --ai-week-summary \
  --ai-summary-provider gemini --ai-summary-model gemini-2.5-flash \
  --gemini-tts --gemini-tts-model gemini-2.5-flash-preview-tts \
  --gemini-tts-voice Kore --gemini-tts-min-interval-seconds 5.0
```

OpenAI summary + ElevenLabs audio:

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --week-pages --ai-week-summary \
  --ai-summary-provider openai --ai-summary-model gpt-4o-mini \
  --elevenlabs-tts --elevenlabs-model-id eleven_multilingual_v2
```

Resume missing audio only:

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output \
  --audio-only-missing --ai-summary-provider gemini --gemini-tts
```

#### Troubleshooting (AI/Audio)

- Many 429/rate-limit events:
  - Increase `--gemini-tts-min-interval-seconds` (for example to `6.0` or `8.0`).
  - Re-run with `--audio-only-missing`.
- OCR fallback not working:
  - Install system `tesseract` and ensure it is in `PATH`.
- Gemini audio cannot be decoded by players:
  - Current pipeline wraps PCM responses into WAV automatically.
- Missing audio for short PDF extracts:
  - Lower `--pdf-text-audio-min-chars`.

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
files/
files/ai_jobs/
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

CourseBeaver is the successor to Moodle2Affine and remains a modernization and extension of the original project:

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
