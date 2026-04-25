#!/usr/bin/env python3
import argparse
import io
import json
import os
import platform
import subprocess
import sys
import threading
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "webui"
DEFAULT_SOURCE = str(Path.home() / "Downloads" / "efmd26")
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "efmd26_markdown")


def parse_int(value, default, minimum):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, parsed)


def normalize_error_message(message):
    text = "" if message is None else str(message).strip()
    if not text:
        return "Unknown error"

    replacements = [
        ("Fichero no encontrado.", "File not found."),
        ("Fichero no encontrado", "File not found"),
        ("Archivo no encontrado", "File not found"),
        ("No se encontro", "Not found"),
        ("No se encontró", "Not found"),
        ("No encontrado", "Not found"),
        ("No existe", "Does not exist"),
        ("Directorio", "Directory"),
        ("directorio", "directory"),
        ("Ruta", "Path"),
        ("ruta", "path"),
        ("Error al", "Error while"),
    ]
    normalized = text
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized


def is_rosetta_translated_process():
    if sys.platform != "darwin":
        return False
    try:
        value = subprocess.check_output(["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"], text=True).strip()
        return value == "1"
    except Exception:
        return False


def runtime_error_if_unsupported():
    if sys.platform != "darwin":
        return None

    host_arch = ""
    try:
        host_arch = subprocess.check_output(["/usr/bin/uname", "-m"], text=True).strip().lower()
    except Exception:
        host_arch = platform.machine().lower()

    if host_arch in {"arm64", "aarch64"} and is_rosetta_translated_process():
        return (
            "Unsupported Python runtime: running under Rosetta (x86_64 translated) on Apple Silicon. "
            "Please use a native arm64 Python and recreate .venv."
        )
    return None


def detect_default_ocr_lang():
    locale_hint = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_CTYPE")
        or os.environ.get("LANG")
        or ""
    ).strip().lower()
    code = locale_hint.split(".")[0].split("_")[0].split("-")[0]

    tesseract_map = {
        "en": "eng",
        "de": "deu",
        "fr": "fra",
        "es": "spa",
        "it": "ita",
        "pt": "por",
        "nl": "nld",
        "sv": "swe",
        "da": "dan",
        "no": "nor",
        "fi": "fin",
        "pl": "pol",
        "cs": "ces",
        "tr": "tur",
        "ru": "rus",
        "uk": "ukr",
        "el": "ell",
        "ro": "ron",
        "hu": "hun",
    }

    primary = tesseract_map.get(code, "eng")
    if primary == "eng":
        return "eng"
    return f"{primary}+eng"


class WebUIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"ok": True, "status": "running"})
            return

        if self.path == "/defaults":
            self._send_json({
                "ok": True,
                "source_dir": DEFAULT_SOURCE,
                "output_dir": DEFAULT_OUTPUT,
                "pdf_text_ocr_lang": detect_default_ocr_lang(),
                "pdf_text_ocr_fallback": True,
            })
            return

        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path != "/convert":
            self._send_json({"ok": False, "error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
            source_dir = (payload.get("source_dir") or "").strip()
            output_dir = (payload.get("output_dir") or "").strip()
            single_page = bool(payload.get("single_page"))
            zip_output = bool(payload.get("zip_output"))
            html_output = bool(payload.get("html_output"))
            structured_weeks = bool(payload.get("structured_weeks"))
            week_pages = bool(payload.get("week_pages"))
            native_week_pages = bool(payload.get("native_week_pages"))
            pdf_text_blocks = bool(payload.get("pdf_text_blocks"))
            pdf_text_engine = (payload.get("pdf_text_engine") or "auto").strip().lower()
            if pdf_text_engine not in {"auto", "pymupdf", "tika"}:
                pdf_text_engine = "auto"
            pdf_text_max_pages = parse_int(payload.get("pdf_text_max_pages"), default=8, minimum=1)
            pdf_text_max_chars = parse_int(payload.get("pdf_text_max_chars"), default=20000, minimum=500)
            ocr_raw = payload.get("pdf_text_ocr_fallback")
            pdf_text_ocr_fallback = (pdf_text_blocks if ocr_raw is None else bool(ocr_raw))
            pdf_text_ocr_lang = (payload.get("pdf_text_ocr_lang") or "eng").strip() or "eng"
            notebooklm_export = bool(payload.get("notebooklm_export"))
            notebooklm_zip_raw = payload.get("notebooklm_zip")
            notebooklm_zip = (notebooklm_export if notebooklm_zip_raw is None else bool(notebooklm_zip_raw))

            if not source_dir:
                raise ValueError("Please provide a Moodle backup directory.")

            runtime_error = runtime_error_if_unsupported()
            if runtime_error:
                raise RuntimeError(runtime_error)

            from moodle2md import convert_course

            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                result_data = convert_course(
                    source_dir,
                    output_dir or None,
                    single_page=single_page,
                    zip_output=zip_output,
                    html_output=html_output,
                    structured_weeks=structured_weeks,
                    week_pages=week_pages,
                    native_week_pages=native_week_pages,
                    pdf_text_blocks=pdf_text_blocks,
                    pdf_text_engine=pdf_text_engine,
                    pdf_text_max_pages=pdf_text_max_pages,
                    pdf_text_max_chars=pdf_text_max_chars,
                    pdf_text_ocr_fallback=pdf_text_ocr_fallback,
                    pdf_text_ocr_lang=pdf_text_ocr_lang,
                    notebooklm_export=notebooklm_export,
                    notebooklm_zip=notebooklm_zip,
                )

            result = {
                "ok": True,
                "message": "Conversion completed successfully.",
                "source_dir": source_dir,
                "output_dir": result_data["output_dir"],
                "readme": result_data["readme"],
                "main_file": result_data["main_file"],
                "single_page": result_data["single_page"],
                "structured_weeks": result_data["structured_weeks"],
                "week_pages": result_data["week_pages"],
                "native_week_pages": result_data["native_week_pages"],
                "pdf_text_blocks": result_data["pdf_text_blocks"],
                "pdf_text_engine": result_data["pdf_text_engine"],
                "pdf_text_max_pages": result_data["pdf_text_max_pages"],
                "pdf_text_max_chars": result_data["pdf_text_max_chars"],
                "pdf_text_ocr_fallback": result_data["pdf_text_ocr_fallback"],
                "pdf_text_ocr_lang": result_data["pdf_text_ocr_lang"],
                "notebooklm_export": result_data["notebooklm_export"],
                "notebooklm_zip": result_data["notebooklm_zip"],
                "notebooklm_folder": result_data["notebooklm_folder"],
                "notebooklm_zip_file": result_data["notebooklm_zip_file"],
                "notebooklm_weeks": result_data.get("notebooklm_weeks", 0),
                "notebooklm_error": result_data.get("notebooklm_error"),
                "html_file": result_data["html_file"],
                "html_output": html_output,
                "zip_file": result_data["zip_file"],
                "native_snapshot_file": result_data.get("native_snapshot_file"),
                "native_zip_file": result_data.get("native_zip_file"),
                "zip_output": zip_output,
                "log": buffer.getvalue().strip(),
            }
            self._send_json(result)
        except Exception as exc:
            self._send_json(
                {
                    "ok": False,
                    "error": normalize_error_message(exc),
                },
                HTTPStatus.BAD_REQUEST,
            )


def main():
    parser = argparse.ArgumentParser(description="Local HTML interface for Moodle2AffineMD")
    parser.add_argument("--host", default="127.0.0.1", help="host for the local server")
    parser.add_argument("--port", type=int, default=8765, help="port for the local server")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    runtime_error = runtime_error_if_unsupported()
    if runtime_error:
        print(runtime_error)
        print("Hint: on Apple Silicon use /opt/homebrew/bin/python3 and recreate .venv.")
        raise SystemExit(1)

    port = args.port
    server = None
    for attempt in range(10):
        try:
            server = ThreadingHTTPServer((args.host, port), WebUIHandler)
            break
        except OSError:
            if attempt < 9:
                print(f"Port {port} is in use, trying {port + 1}…")
                port += 1
            else:
                raise
    url = f"http://{args.host}:{port}"

    print(f"Moodle2AffineMD Web UI is running at {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
