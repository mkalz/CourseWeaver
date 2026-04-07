# Moodle2AffineMD

Convert an unpacked Moodle course backup into **clean Markdown for GitHub** and **AFFiNE-ready imports**.

> The CLI entry point remains `moodle2md.py` for backward compatibility.

## ✨ Features

- Converts Moodle course content into readable Markdown
- Cleans HTML-heavy Moodle exports for better publishing quality
- Copies media into local `img/` and `files/` folders
- Creates `README.md` plus optional `doc/*.md` pages
- Creates an optional single-page export: `ALL_IN_ONE.md`
- Creates an AFFiNE Markdown ZIP: `*_affine.zip`
- Creates a native AFFiNE Snapshot ZIP: `*_affine_native.zip`
- Creates an HTML fallback export: `AFFINE_IMPORT.html`
- Includes a local browser-based Web UI

## 🚀 Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output --single-page --zip --html
```

## 🔧 CLI usage

### Standard export

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output
```

### Full export for GitHub + AFFiNE

```bash
python moodle2md.py -d /path/to/unpacked-moodle-backup -o /path/to/output --single-page --zip --html
```

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
img/
<output_name>_affine.zip
<output_name>_affine_native.zip
```

## 📥 How to import into AFFiNE

| File | Import mode in AFFiNE | Purpose |
|---|---|---|
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

## � Upstream origin and attribution

This repository is a modernization and extension of the original project:

- **Original repository:** `josedom24/moodle2md`
- **URL:** `https://github.com/josedom24/moodle2md`
- **Original author:** José Domingo Muñoz Rodríguez

The current project adds Python 3 compatibility, GitHub-oriented documentation, a local Web UI, single-page export, AFFiNE ZIP export, AFFiNE native Snapshot export, and HTML fallback export.

## 📄 License and compliance note

At the time of review, the checked upstream repository contents showed the source files and `README.md`, but **no explicit `LICENSE` file** was visible in that repository listing.

Because of that:

- this repository now **explicitly references the original project and author**
- the included `LICENSE` applies to **new additions and modifications only, where licensable**
- the original upstream portions remain attributed to their original author and subject to the upstream licensing status
- for broad public redistribution, **upstream permission or explicit license clarification is recommended**

