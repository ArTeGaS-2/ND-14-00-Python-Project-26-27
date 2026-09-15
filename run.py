"""Локальний сайт і API. Запуск: python run.py. Зберігання: data/schedule.sqlite3."""

import argparse
import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from server import APIError, ScheduleStore

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css", "/schedule.js": "schedule.js", "/favicon.svg": "favicon.svg"}


def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        def send_body(self, status, body, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def handle_request(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/"):
                    origin = self.headers.get("Origin")
                    if origin and urlparse(origin).netloc != self.headers.get("Host"):
                        raise APIError(403, "Запит має надходити з цього сайту.")
                    data = {}
                    if self.command in ("POST", "PUT", "DELETE"):
                        if not self.headers.get("Content-Type", "").startswith("application/json"):
                            raise APIError(415, "Потрібен JSON-запит.")
                        try:
                            size = int(self.headers.get("Content-Length", "0"))
                            if not 0 < size <= 32768:
                                raise APIError(413, "Запит завеликий або порожній.")
                            data = json.loads(self.rfile.read(size))
                            if not isinstance(data, dict):
                                raise ValueError()
                        except (ValueError, UnicodeDecodeError):
                            raise APIError(400, "Не вдалося прочитати запит.")
                    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                    result = store.dispatch(self.command, parsed.path, query, data, self.headers)
                    self.send_body(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
                elif self.command in ("GET", "HEAD") and parsed.path in PUBLIC_FILES:
                    file = ROOT / PUBLIC_FILES[parsed.path]
                    content_type = mimetypes.guess_type(file.name)[0] or "text/plain"
                    self.send_body(200, file.read_bytes(), content_type + "; charset=utf-8")
                else:
                    raise APIError(404, "Сторінку не знайдено.")
            except APIError as error:
                self.send_body(error.status, json.dumps({"error": error.message}, ensure_ascii=False).encode("utf-8"))
            except Exception:
                traceback.print_exc()
                self.send_body(503, json.dumps({"error": "Не вдалося зберегти або завантажити дані. Спробуй ще раз."}, ensure_ascii=False).encode("utf-8"))

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = handle_request
    return Handler


def main():
    # За потреби інший порт можна вказати так: python run.py --port 8001.
    parser = argparse.ArgumentParser(description="Локальний запуск шкільного розкладу")
    parser.add_argument("--port", type=int, default=8000, help="Порт сервера (типово 8000)")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "schedule.sqlite3", help="Шлях до SQLite-бази")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Порт має бути від 0 до 65535.")
    store = ScheduleStore(args.database)
    store.initialize()

    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(store)) as server:
            print(f"Відкрий у браузері: http://127.0.0.1:{server.server_port}/", flush=True)
            print("Щоб зупинити сервер, натисни Ctrl+C.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер зупинено.")
    except OSError as error:
        parser.exit(1, f"Не вдалося запустити сервер: {error}\nСпробуй інший порт: python run.py --port 8001\n")


if __name__ == "__main__":
    main()
