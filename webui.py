#!/usr/bin/env python3
import argparse
import io
import json
import threading
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from moodle2md import convert_course

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "webui"
DEFAULT_SOURCE = str(Path.home() / "Downloads" / "efmd26")
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "efmd26_markdown")


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

            if not source_dir:
                raise ValueError("Please provide a Moodle backup directory.")

            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                result_data = convert_course(
                    source_dir,
                    output_dir or None,
                    single_page=single_page,
                    zip_output=zip_output,
                    html_output=html_output,
                )

            result = {
                "ok": True,
                "message": "Conversion completed successfully.",
                "source_dir": source_dir,
                "output_dir": result_data["output_dir"],
                "readme": result_data["readme"],
                "main_file": result_data["main_file"],
                "single_page": result_data["single_page"],
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
                    "error": str(exc),
                },
                HTTPStatus.BAD_REQUEST,
            )


def main():
    parser = argparse.ArgumentParser(description="Local HTML interface for Moodle2AffineMD")
    parser.add_argument("--host", default="127.0.0.1", help="host for the local server")
    parser.add_argument("--port", type=int, default=8765, help="port for the local server")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WebUIHandler)
    url = f"http://{args.host}:{args.port}"

    print(f"Moodle2AffineMD Web UI is running at {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
