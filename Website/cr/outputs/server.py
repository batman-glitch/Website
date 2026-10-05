#!/usr/bin/env python3
"""Local portfolio server backed by the shared password-authenticated admin API."""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


SITE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.admin_backend import create_local_admin, handle_admin_request, handle_inquiry_request, local_admin_exists, prepare_local_database
from lib.platform_backend import handle_platform_request


DATA_DIR = SITE_DIR / "data"
DATABASE = DATA_DIR / "portfolio.sqlite3"
PORT = int(os.environ.get("PORT", "8787"))
MAX_BODY_BYTES = 18 * 1024


def initialize_database() -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    with sqlite3.connect(DATABASE, timeout=8) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            service TEXT NOT NULL,
            timeline TEXT NOT NULL DEFAULT '',
            genre TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_created_at_idx ON inquiries(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_status_created_at_idx ON inquiries(status, created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_service_created_at_idx ON inquiries(service, created_at DESC)")
    try:
        os.chmod(DATABASE, 0o600)
    except OSError:
        pass


def initialize_local_admin() -> None:
    if local_admin_exists():
        return
    print("\nCreate your private local admin account.")
    email = input("Admin email [blessonkondeti@gmail.com]: ").strip() or "blessonkondeti@gmail.com"
    while True:
        password = getpass.getpass("Choose a password/passphrase (14+ characters): ")
        confirmation = getpass.getpass("Confirm password/passphrase: ")
        if password != confirmation:
            print("Passwords do not match. Try again.")
            continue
        try:
            create_local_admin(email, password)
            break
        except ValueError as error:
            print(error)
    print("Local admin account created. Its password is stored as a salted PBKDF2 hash.")


class PortfolioHandler(SimpleHTTPRequestHandler):
    server_version = "PortfolioLocal/2.0"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self' mailto:; img-src 'self' data:; font-src 'self' https://fonts.gstatic.com data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; connect-src 'self'")
        path = urlsplit(self.path).path
        if path.startswith("/api/") or path.startswith("/admin") or path == "/admin.html":
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        candidate = Path(super().translate_path(path)).resolve()
        base = SITE_DIR.resolve()
        try:
            relative = candidate.relative_to(base)
        except ValueError:
            return str(base / "__not_found__")
        if (candidate == Path(__file__).resolve()
                or candidate == (SITE_DIR / "README.md").resolve()
                or candidate.is_relative_to(DATA_DIR.resolve())
                or any(part.startswith(".") for part in relative.parts)
                or candidate.suffix in {".py", ".sqlite", ".sqlite3", ".db"}):
            return str(base / "__not_found__")
        return str(candidate)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def dispatch_backend(self, backend) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json(400, {"error": "Invalid request size."})
        if length > MAX_BODY_BYTES:
            return self.send_json(413, {"error": "Request is too large."})
        body = self.rfile.read(length) if length else b""
        status, headers, payload = backend(self.command, self.path, self.headers, body, production=False)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/data/") or path in {"/data", "/server.py", "/README.md"}:
            return self.send_error(404)
        if path in {"/admin", "/admin/"}:
            self.path = "/admin.html"
        return super().do_HEAD()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/assets/admin-platform.bundle.js":
            source = SITE_DIR / "assets" / "admin-platform.js"
            try:
                encoded = source.read_bytes()
            except OSError:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            return self.wfile.write(encoded)
        if path in {"/admin", "/admin/"}:
            self.path = "/admin.html"
            return super().do_GET()
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        if path == "/api/admin":
            return self.dispatch_backend(handle_admin_request)
        if path.startswith("/api/"):
            return self.dispatch_backend(handle_platform_request)
        if path.startswith("/data/") or path in {"/data", "/server.py", "/README.md"}:
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/admin":
            return self.dispatch_backend(handle_admin_request)
        if path == "/api/inquiries":
            return self.dispatch_backend(handle_inquiry_request)
        if path.startswith("/api/admin/"):
            return self.dispatch_backend(handle_platform_request)
        return self.send_error(404)

    def do_PUT(self) -> None:
        return self.do_POST()

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/admin/"):
            return self.dispatch_backend(handle_platform_request)
        return self.send_error(404)

    def do_PATCH(self) -> None:
        return self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        # Avoid writing personal enquiry fields or search text to local logs.
        return


if __name__ == "__main__":
    os.umask(0o077)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    prepare_local_database(DATABASE)
    initialize_database()
    initialize_local_admin()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), lambda *args, **kwargs: PortfolioHandler(*args, directory=str(SITE_DIR), **kwargs))
    print(f"Portfolio: http://127.0.0.1:{PORT}/")
    print(f"Private admin: http://127.0.0.1:{PORT}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local portfolio server.")
    finally:
        server.server_close()
