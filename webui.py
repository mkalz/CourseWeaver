#!/usr/bin/env python3
import argparse
import io
import json
import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "webui"
DEFAULT_SOURCE = str(Path.home() / "Downloads" / "efmd26")
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "efmd26_markdown")
DEFAULT_INTERNAL_API_BASE_URL = "http://127.0.0.1:8766"

# Load .env from project root (does not overwrite already-set env vars)
_dotenv_path = ROOT / ".env"
if _dotenv_path.is_file():
    with _dotenv_path.open() as _dotenv_fh:
        for _line in _dotenv_fh:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            if "=" in _line and _line.split("=", 1)[0].replace("_", "").isalnum():
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip().strip('"').strip("'"))


class TeeStream:
    def __init__(self, *streams):
        self.streams = [stream for stream in streams if stream is not None]

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def parse_int(value, default, minimum):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, parsed)

def parse_float(value, default, minimum):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
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


def _api_request(base_url, method, path, payload=None, timeout=30):
    base = (base_url or DEFAULT_INTERNAL_API_BASE_URL).strip().rstrip("/")
    url = f"{base}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except Exception:
            detail = body or f"HTTP {exc.code}"
        raise RuntimeError(f"Internal API {method} {path} failed ({exc.code}): {detail}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Internal API unreachable at {base}: {exc.reason}") from exc


def _run_internal_api_job(base_url, source_dir, output_dir, options):
    submit_payload = {
        "source_dir": source_dir,
        "output_dir": output_dir or "",
        "options": options,
    }
    submit = _api_request(base_url, "POST", "/api/jobs", submit_payload, timeout=30)
    job_id = (submit.get("id") or "").strip()
    if not job_id:
        raise RuntimeError(f"Internal API did not return a job id: {submit}")

    deadline = time.time() + 60 * 60 * 2
    while time.time() < deadline:
        job = _api_request(base_url, "GET", f"/api/jobs/{job_id}", timeout=30)
        status = (job.get("status") or "").strip().lower()
        if status == "completed":
            return job
        if status in {"failed", "cancelled"}:
            raise RuntimeError(
                f"Internal API job {job_id} ended with status={status}: {job.get('error') or 'no details'}"
            )
        time.sleep(3)

    raise RuntimeError(f"Internal API job {job_id} timed out after 2 hours")


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
        parsed = urlsplit(self.path)

        if parsed.path.startswith("/internal-api/job/"):
            try:
                job_id = parsed.path.rsplit("/", 1)[-1].strip()
                if not job_id:
                    raise ValueError("Missing job id")
                query = parse_qs(parsed.query)
                base_url = (
                    (query.get("base_url", [DEFAULT_INTERNAL_API_BASE_URL])[0] or DEFAULT_INTERNAL_API_BASE_URL)
                    .strip()
                )
                job = _api_request(base_url, "GET", f"/api/jobs/{job_id}", timeout=30)
                result_data = job.get("result") or {}
                chapterized_mp3 = (result_data.get("chapterized_mp3") or "").strip()
                self._send_json(
                    {
                        "ok": True,
                        "job": job,
                        "api_base_url": base_url,
                        "audio_segments_endpoint": f"{base_url.rstrip('/')}/api/audio/{job_id}",
                        "chapters_mp3_endpoint": f"{base_url.rstrip('/')}/api/audio/{job_id}/chapters.mp3",
                        "chapters_mp3_path": chapterized_mp3,
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": normalize_error_message(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/health":
            self._send_json({"ok": True, "status": "running"})
            return

        if self.path == "/defaults":
            self._send_json({
                "ok": True,
                "source_dir": DEFAULT_SOURCE,
                "output_dir": DEFAULT_OUTPUT,
                "internal_api_base_url": DEFAULT_INTERNAL_API_BASE_URL,
                "use_internal_api": False,
                "pdf_text_ocr_lang": detect_default_ocr_lang(),
                "pdf_text_ocr_fallback": True,
                "has_openai_api_key": bool((os.environ.get("OPENAI_API_KEY") or "").strip()),
                "has_gemini_api_key": bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()),
                "has_elevenlabs_api_key": bool((os.environ.get("ELEVENLABS_API_KEY") or "").strip()),
                "has_elevenlabs_voice_id": bool((os.environ.get("ELEVENLABS_VOICE_ID") or "").strip()),
            })
            return

        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path not in {"/convert", "/internal-api/submit"}:
            self._send_json({"ok": False, "error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))

            if self.path == "/internal-api/submit":
                source_dir = (payload.get("source_dir") or "").strip()
                output_dir = (payload.get("output_dir") or "").strip()
                options = payload.get("options") or {}
                if not isinstance(options, dict):
                    raise ValueError("options must be an object")
                base_url = (
                    (payload.get("internal_api_base_url") or DEFAULT_INTERNAL_API_BASE_URL)
                    .strip()
                    or DEFAULT_INTERNAL_API_BASE_URL
                )
                if not source_dir:
                    raise ValueError("Please provide a Moodle backup directory.")
                submit = _api_request(
                    base_url,
                    "POST",
                    "/api/jobs",
                    {
                        "source_dir": source_dir,
                        "output_dir": output_dir,
                        "options": options,
                    },
                    timeout=30,
                )
                job_id = (submit.get("id") or "").strip()
                if not job_id:
                    raise RuntimeError(f"Internal API did not return a job id: {submit}")
                self._send_json(
                    {
                        "ok": True,
                        "job_id": job_id,
                        "api_base_url": base_url,
                        "status": submit.get("status", "pending"),
                        "message": "Internal API job submitted.",
                    }
                )
                return

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
            pdf_text_audio_raw = payload.get("pdf_text_audio")
            pdf_text_audio = (None if pdf_text_audio_raw is None else bool(pdf_text_audio_raw))
            pdf_text_audio_min_chars = parse_int(payload.get("pdf_text_audio_min_chars"), default=300, minimum=100)
            ocr_raw = payload.get("pdf_text_ocr_fallback")
            pdf_text_ocr_fallback = (pdf_text_blocks if ocr_raw is None else bool(ocr_raw))
            pdf_text_ocr_lang = (payload.get("pdf_text_ocr_lang") or "eng").strip() or "eng"
            ai_week_summary = bool(payload.get("ai_week_summary"))
            ai_summary_provider = (payload.get("ai_summary_provider") or "openai").strip().lower()
            if ai_summary_provider not in {"openai", "gemini"}:
                ai_summary_provider = "openai"
            ai_summary_model = (payload.get("ai_summary_model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
            ai_summary_language = (payload.get("ai_summary_language") or "de").strip() or "de"
            ai_summary_max_chars = parse_int(payload.get("ai_summary_max_chars"), default=12000, minimum=1000)
            ai_summary_base_url = (payload.get("ai_summary_base_url") or "https://api.openai.com/v1").strip() or "https://api.openai.com/v1"
            gemini_tts = bool(payload.get("gemini_tts"))
            gemini_tts_model = (payload.get("gemini_tts_model") or "gemini-2.5-flash-preview-tts").strip() or "gemini-2.5-flash-preview-tts"
            gemini_tts_voice = (payload.get("gemini_tts_voice") or "Kore").strip() or "Kore"
            gemini_tts_base_url = (payload.get("gemini_tts_base_url") or "https://generativelanguage.googleapis.com/v1beta").strip() or "https://generativelanguage.googleapis.com/v1beta"
            gemini_tts_min_interval_seconds = parse_float(payload.get("gemini_tts_min_interval_seconds"), default=5.0, minimum=0.0)
            gemini_summary_min_interval_seconds = parse_float(payload.get("gemini_summary_min_interval_seconds"), default=3.0, minimum=0.0)
            audio_only_missing = bool(payload.get("audio_only_missing"))
            elevenlabs_tts = bool(payload.get("elevenlabs_tts"))
            elevenlabs_voice_id = (payload.get("elevenlabs_voice_id") or "").strip()
            elevenlabs_model_id = (payload.get("elevenlabs_model_id") or "eleven_multilingual_v2").strip() or "eleven_multilingual_v2"
            notebooklm_export = bool(payload.get("notebooklm_export"))
            notebooklm_zip_raw = payload.get("notebooklm_zip")
            notebooklm_zip = (notebooklm_export if notebooklm_zip_raw is None else bool(notebooklm_zip_raw))
            use_internal_api = bool(payload.get("use_internal_api"))
            internal_api_base_url = (payload.get("internal_api_base_url") or DEFAULT_INTERNAL_API_BASE_URL).strip() or DEFAULT_INTERNAL_API_BASE_URL

            if not source_dir:
                raise ValueError("Please provide a Moodle backup directory.")

            runtime_error = runtime_error_if_unsupported()
            if runtime_error:
                raise RuntimeError(runtime_error)

            if use_internal_api:
                internal_options = {
                    "single_page": single_page,
                    "structured_weeks": structured_weeks,
                    "week_pages": week_pages,
                    "native_week_pages": native_week_pages,
                    "pdf_text_blocks": pdf_text_blocks,
                    "pdf_text_max_pages": pdf_text_max_pages,
                    "pdf_text_max_chars": pdf_text_max_chars,
                    "ai_summary_language": ai_summary_language,
                    "ai_summary_max_chars": ai_summary_max_chars,
                    "chapterized_mp3": True,
                    "accessibility_rewrite": True,
                }
                job = _run_internal_api_job(
                    internal_api_base_url,
                    source_dir,
                    output_dir,
                    internal_options,
                )
                result_data = job.get("result") or {}
                job_id = job.get("id")
                resolved_output_dir = (job.get("output_dir") or result_data.get("output_dir") or "").strip()
                chapterized_mp3 = (result_data.get("chapterized_mp3") or "").strip()

                result = {
                    "ok": True,
                    "api_mode": "internal",
                    "message": "Internal API job completed successfully.",
                    "source_dir": source_dir,
                    "output_dir": resolved_output_dir,
                    "job_id": job_id,
                    "job_status": job.get("status"),
                    "job_attempts": job.get("attempts", 0),
                    "job_error": job.get("error"),
                    "api_base_url": internal_api_base_url,
                    "audio_segments_endpoint": f"{internal_api_base_url.rstrip('/')}/api/audio/{job_id}",
                    "chapters_mp3_endpoint": f"{internal_api_base_url.rstrip('/')}/api/audio/{job_id}/chapters.mp3",
                    "chapters_mp3_path": chapterized_mp3,
                    "job_result": result_data,
                    "log": "Internal API mode used. See job_result for pipeline details.",
                }
                self._send_json(result)
                return

            from moodle2md import convert_course

            buffer = io.StringIO()
            tee_stdout = TeeStream(buffer, sys.__stdout__)
            tee_stderr = TeeStream(buffer, sys.__stderr__)
            with redirect_stdout(tee_stdout), redirect_stderr(tee_stderr):
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
                    pdf_text_audio=pdf_text_audio,
                    pdf_text_audio_min_chars=pdf_text_audio_min_chars,
                    pdf_text_ocr_fallback=pdf_text_ocr_fallback,
                    pdf_text_ocr_lang=pdf_text_ocr_lang,
                    ai_week_summary=ai_week_summary,
                    ai_summary_provider=ai_summary_provider,
                    ai_summary_model=ai_summary_model,
                    ai_summary_language=ai_summary_language,
                    ai_summary_max_chars=ai_summary_max_chars,
                    ai_summary_base_url=ai_summary_base_url,
                    gemini_tts=gemini_tts,
                    gemini_tts_model=gemini_tts_model,
                    gemini_tts_voice=gemini_tts_voice,
                    gemini_tts_base_url=gemini_tts_base_url,
                    gemini_tts_min_interval_seconds=gemini_tts_min_interval_seconds,
                    gemini_summary_min_interval_seconds=gemini_summary_min_interval_seconds,
                    audio_only_missing=audio_only_missing,
                    elevenlabs_tts=elevenlabs_tts,
                    elevenlabs_voice_id=elevenlabs_voice_id,
                    elevenlabs_model_id=elevenlabs_model_id,
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
                "pdf_text_audio": result_data.get("pdf_text_audio", False),
                "pdf_text_audio_min_chars": result_data.get("pdf_text_audio_min_chars", 300),
                "pdf_text_ocr_fallback": result_data["pdf_text_ocr_fallback"],
                "pdf_text_ocr_lang": result_data["pdf_text_ocr_lang"],
                "ai_week_summary": result_data.get("ai_week_summary", False),
                "ai_summary_provider": result_data.get("ai_summary_provider", "openai"),
                "ai_summary_model": result_data.get("ai_summary_model", "gpt-4o-mini"),
                "ai_summary_language": result_data.get("ai_summary_language", "de"),
                "ai_summary_max_chars": result_data.get("ai_summary_max_chars", 12000),
                "ai_summary_base_url": result_data.get("ai_summary_base_url", "https://api.openai.com/v1"),
                "gemini_tts": result_data.get("gemini_tts", False),
                "gemini_tts_model": result_data.get("gemini_tts_model", "gemini-2.5-flash-preview-tts"),
                "gemini_tts_voice": result_data.get("gemini_tts_voice", "Kore"),
                "gemini_tts_base_url": result_data.get("gemini_tts_base_url", "https://generativelanguage.googleapis.com/v1beta"),
                "gemini_tts_min_interval_seconds": result_data.get("gemini_tts_min_interval_seconds", 5.0),
                "gemini_summary_min_interval_seconds": result_data.get("gemini_summary_min_interval_seconds", 3.0),
                "audio_only_missing": result_data.get("audio_only_missing", False),
                "elevenlabs_tts": result_data.get("elevenlabs_tts", False),
                "elevenlabs_voice_id": result_data.get("elevenlabs_voice_id", ""),
                "elevenlabs_model_id": result_data.get("elevenlabs_model_id", "eleven_multilingual_v2"),
                "ai_audio_result": result_data.get("ai_audio_result") or {},
                "ai_jobs_manifest": result_data.get("ai_jobs_manifest"),
                "ai_jobs_input_dir": result_data.get("ai_jobs_input_dir"),
                "ai_jobs_output_dir": result_data.get("ai_jobs_output_dir"),
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
