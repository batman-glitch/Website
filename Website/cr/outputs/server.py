#!/usr/bin/env python3
"""Local portfolio site + inquiry API. Uses only Python's standard library."""

from __future__ import annotations

import csv
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SITE_DIR = Path(__file__).resolve().parent
DATA_DIR = SITE_DIR / "data"
DATABASE = DATA_DIR / "portfolio.sqlite3"
TOKEN_FILE = DATA_DIR / ".admin-token"
PORT = int(os.environ.get("PORT", "8787"))
MAX_BODY_BYTES = 18 * 1024
RATE_WINDOW_SECONDS = 15 * 60
RATE_MAX_REQUESTS = 5
RATE_EVENTS: dict[str, list[float]] = {}
VALID_SERVICES = {"Mixing", "Mastering", "Production", "Recording", "Sound design", "Not sure yet"}
VALID_STATUSES = {"new", "in_progress", "completed"}
ADMIN_PAGE_SIZES = {12, 24, 48}


def load_admin_token() -> str:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    configured = os.environ.get("ADMIN_TOKEN", "").strip()
    if configured:
        if len(configured) < 24:
            raise SystemExit("ADMIN_TOKEN must be at least 24 characters long.")
        return configured
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(36)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    print("\nAdmin access token (save it; this is shown only on first start):")
    print(token)
    return token


ADMIN_TOKEN = load_admin_token()


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def database():
    db = connect_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS inquiries (
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
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_created_at_idx ON inquiries(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_status_created_at_idx ON inquiries(status, created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_service_created_at_idx ON inquiries(service, created_at DESC)")


def clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]



def admin_query_options(query_string: str) -> dict[str, object]:
    """Validate inbox filters and return safe SQL fragments and parameters."""
    parsed = parse_qs(query_string, keep_blank_values=True, max_num_fields=20)

    def value(name: str, default: str = "") -> str:
        values = parsed.get(name, [default])
        return values[0][:200]

    clauses: list[str] = []
    parameters: list[str] = []
    query = value("q").strip()
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        searchable = ("name", "email", "project", "service", "timeline", "genre", "message")
        clauses.append("(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in searchable) + ")")
        parameters.extend([like] * len(searchable))

    status = value("status", "all")
    if status in VALID_STATUSES:
        clauses.append("status = ?")
        parameters.append(status)
    service = value("service", "all")
    if service in VALID_SERVICES:
        clauses.append("service = ?")
        parameters.append(service)

    sort = value("sort", "newest")
    order_by = "created_at ASC, id ASC" if sort == "oldest" else "created_at DESC, id DESC"
    try:
        requested_page = max(1, int(value("page", "1")))
    except ValueError:
        requested_page = 1
    try:
        requested_size = int(value("page_size", "12"))
    except ValueError:
        requested_size = 12
    page_size = requested_size if requested_size in ADMIN_PAGE_SIZES else 12

    return {
        "where": " WHERE " + " AND ".join(clauses) if clauses else "",
        "parameters": parameters,
        "order_by": order_by,
        "page": min(requested_page, 100_000),
        "page_size": page_size,
    }


def safe_csv_cell(value: object) -> str:
    """Prevent spreadsheet formula execution when opening exported enquiries."""
    text = "" if value is None else str(value)
    if re.match(r"^[\s\ufeff\x00-\x1f]*[=+@-]", text):
        return "'" + text
    return text


def inquiry_rows(db: sqlite3.Connection, options: dict[str, object], paginated: bool = True) -> tuple[list[sqlite3.Row], int]:
    where = str(options["where"])
    parameters = list(options["parameters"])
    total = int(db.execute(f"SELECT COUNT(*) FROM inquiries{where}", parameters).fetchone()[0])
    sql = f"SELECT * FROM inquiries{where} ORDER BY {options['order_by']}"
    if paginated:
        pages = max(1, (total + int(options["page_size"]) - 1) // int(options["page_size"]))
        page = min(int(options["page"]), pages)
        offset = (page - 1) * int(options["page_size"])
        sql += " LIMIT ? OFFSET ?"
        parameters.extend([int(options["page_size"]), offset])
    rows = db.execute(sql, parameters).fetchall()
    return rows, total


def allow_inquiry(ip: str) -> bool:
    now = time.monotonic()
    recent = [stamp for stamp in RATE_EVENTS.get(ip, []) if now - stamp < RATE_WINDOW_SECONDS]
    if len(recent) >= RATE_MAX_REQUESTS:
        RATE_EVENTS[ip] = recent
        return False
    recent.append(now)
    RATE_EVENTS[ip] = recent
    return True


class PortfolioHandler(SimpleHTTPRequestHandler):
    server_version = "PortfolioLocal/1.0"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self' mailto:; img-src 'self' data:; font-src 'self' https://fonts.gstatic.com data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; connect-src 'self'")
        path = urlsplit(self.path).path
        if path.startswith("/api/") or path.startswith("/admin") or path == "/admin.html":
            self.send_header("Cache-Control", "no-store")
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
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid request size."})
            return None
        if length < 1 or length > MAX_BODY_BYTES:
            self.send_json(413, {"error": "Request is empty or too large."})
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            self.send_json(415, {"error": "Send this request as JSON."})
            return None
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "Could not read the request."})
            return None
        if not isinstance(value, dict):
            self.send_json(400, {"error": "Expected a JSON object."})
            return None
        return value

    def require_admin(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, ADMIN_TOKEN):
            self.send_json(401, {"error": "Admin sign-in required."})
            return False
        return True

    def do_HEAD(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/data/") or path in {"/data", "/server.py", "/README.md"}:
            return self.send_error(404)
        if path in {"/admin", "/admin/"}:
            self.path = "/admin.html"
        return super().do_HEAD()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/admin", "/admin/"}:
            self.path = "/admin.html"
            return super().do_GET()
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        if path.startswith("/data/") or path in {"/server.py", "/README.md"}:
            return self.send_error(404)
        if path in {"/api/admin/inquiries", "/api/admin/export.csv"}:
            if not self.require_admin():
                return
            options = admin_query_options(urlsplit(self.path).query)
            with database() as db:
                if path == "/api/admin/export.csv":
                    rows, _ = inquiry_rows(db, options, paginated=False)
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(["ID", "Received", "Name", "Email", "Project", "Service", "Timeline", "Genre / style", "Project notes", "Status"])
                    for row in rows:
                        writer.writerow([safe_csv_cell(row[key]) for key in ("id", "created_at", "name", "email", "project", "service", "timeline", "genre", "message", "status")])
                    encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="blessson-enquiries-{datetime.now(timezone.utc).date().isoformat()}.csv"')
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return

                rows, total = inquiry_rows(db, options, paginated=True)
                all_statuses = {status: 0 for status in VALID_STATUSES}
                all_statuses.update({row["status"]: int(row["count"]) for row in db.execute("SELECT status, COUNT(*) AS count FROM inquiries GROUP BY status")})
            page_size = int(options["page_size"])
            pages = max(1, (total + page_size - 1) // page_size)
            page_number = min(int(options["page"]), pages)
            return self.send_json(200, {
                "inquiries": [dict(row) for row in rows],
                "stats": {
                    "total": sum(all_statuses.values()),
                    "new": all_statuses.get("new", 0),
                    "in_progress": all_statuses.get("in_progress", 0),
                    "completed": all_statuses.get("completed", 0),
                },
                "pagination": {"page": page_number, "page_size": page_size, "total": total, "pages": pages},
            })
        return super().do_GET()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/inquiries":
            return self.send_error(404)
        ip = self.client_address[0]
        if not allow_inquiry(ip):
            return self.send_json(429, {"error": "Please wait a little before sending another enquiry."})
        data = self.read_json()
        if data is None:
            return
        # Honeypot: bots get a success response, but their message is not stored.
        if clean_text(data.get("website"), 200):
            return self.send_json(202, {"ok": True})

        name = clean_text(data.get("name"), 120)
        email = clean_text(data.get("email"), 254)
        project = clean_text(data.get("project"), 160)
        service = clean_text(data.get("service"), 40)
        timeline = clean_text(data.get("timeline"), 80)
        genre = clean_text(data.get("genre"), 100)
        message = clean_text(data.get("message"), 4000)
        if not name or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not message:
            return self.send_json(400, {"error": "Add your name, a valid email, and a short project note."})
        if service not in VALID_SERVICES:
            return self.send_json(400, {"error": "Choose a valid service."})

        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with database() as db:
            cursor = db.execute(
                "INSERT INTO inquiries (created_at,name,email,project,service,timeline,genre,message) VALUES (?,?,?,?,?,?,?,?)",
                (created_at, name, email, project, service, timeline, genre, message),
            )
            inquiry_id = int(cursor.lastrowid)
        return self.send_json(201, {"ok": True, "id": inquiry_id})

    def do_PATCH(self) -> None:
        match = re.fullmatch(r"/api/admin/inquiries/(\d+)", urlsplit(self.path).path)
        if not match:
            return self.send_error(404)
        if not self.require_admin():
            return
        data = self.read_json()
        if data is None:
            return
        status = clean_text(data.get("status"), 20)
        if status not in VALID_STATUSES:
            return self.send_json(400, {"error": "Choose a valid status."})
        inquiry_id = int(match.group(1))
        with database() as db:
            cursor = db.execute("UPDATE inquiries SET status=? WHERE id=?", (status, inquiry_id))
        if cursor.rowcount == 0:
            return self.send_json(404, {"error": "Enquiry not found."})
        return self.send_json(200, {"ok": True})

    def log_message(self, format: str, *args: object) -> None:
        # Avoid logging enquiry content; only the request line and status are logged.
        super().log_message(format, *args)


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), lambda *args, **kwargs: PortfolioHandler(*args, directory=str(SITE_DIR), **kwargs))
    print(f"Portfolio: http://127.0.0.1:{PORT}/")
    print(f"Admin inbox: http://127.0.0.1:{PORT}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local portfolio server.")
    finally:
        server.server_close()
