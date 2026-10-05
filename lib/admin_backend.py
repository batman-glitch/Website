"""Shared secure admin and inquiry backend for local SQLite and Vercel Postgres."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DB = ROOT / "Website" / "cr" / "outputs" / "data" / "portfolio.sqlite3"
VALID_SERVICES = {"Mixing", "Mastering", "Production", "Recording", "Sound design", "Not sure yet"}
VALID_STATUSES = {"new", "in_progress", "completed"}
PAGE_SIZES = {12, 24, 48}
MAX_BODY_BYTES = 18 * 1024
PBKDF2_ROUNDS = 600_000
SESSION_TTL = timedelta(hours=4)
LOGIN_WINDOW = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 5
INQUIRY_WINDOW = timedelta(minutes=15)
MAX_INQUIRIES_PER_WINDOW = 5
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()
DUMMY_PASSWORD_HASH = "pbkdf2_sha256$600000$Y2hhbmdlLXRoaXMtc2FsdA$E2sffJyQuXYX6V6t0W7x-AH5maBt2tBsA8sDtu1jAkI"


class ServiceError(Exception):
    def __init__(self, status: int, message: str, headers: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or []


class Database:
    def __init__(self, connection, postgres: bool):
        self.connection = connection
        self.postgres = postgres

    def execute(self, sql: str, parameters=()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)


@contextmanager
def database(require_postgres: bool = False):
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if require_postgres and not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        connection = psycopg.connect(database_url, connect_timeout=6, sslmode="require", row_factory=dict_row)
        db = Database(connection, True)
    else:
        db_path = Path(os.environ.get("LOCAL_DATABASE_PATH", str(DEFAULT_LOCAL_DB))).expanduser()
        db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(db_path.parent, 0o700)
        except OSError:
            pass
        connection = sqlite3.connect(db_path, timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=8000")
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
        db = Database(connection, False)
    try:
        yield db
        db.connection.commit()
    except Exception:
        db.connection.rollback()
        raise
    finally:
        db.connection.close()


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime | None = None) -> str:
    return (value or now_utc()).isoformat()


def _ensure_schema(db: Database) -> None:
    identity = os.environ.get("DATABASE_URL", "").strip() or str(Path(os.environ.get("LOCAL_DATABASE_PATH", str(DEFAULT_LOCAL_DB))).expanduser())
    ready_key = hashlib.sha256(("postgres:" if db.postgres else "sqlite:").encode() + identity.encode()).hexdigest()
    if ready_key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if ready_key in _SCHEMA_READY:
            return
        serial = "BIGSERIAL PRIMARY KEY" if db.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        user_id_type = "BIGINT" if db.postgres else "INTEGER"
        db.execute(f"""CREATE TABLE IF NOT EXISTS inquiries (
            id {serial}, created_at TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '', service TEXT NOT NULL, timeline TEXT NOT NULL DEFAULT '',
            genre TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new'
        )""")
        db.execute(f"""CREATE TABLE IF NOT EXISTS admin_users (
            id {serial}, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 0, mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            totp_secret_enc TEXT, mfa_setup_expires TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute(f"""CREATE TABLE IF NOT EXISTS admin_sessions (
            token_hash TEXT PRIMARY KEY, user_id {user_id_type} NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
            csrf_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
        )""")
        db.execute(f"""CREATE TABLE IF NOT EXISTS rate_limits (
            rate_key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_started_at TEXT NOT NULL,
            locked_until TEXT
        )""")
        # Add MFA columns to existing production databases without dropping account data.
        if db.postgres:
            db.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            db.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS totp_secret_enc TEXT")
            db.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS mfa_setup_expires TEXT")
        else:
            admin_columns = {row["name"] for row in db.execute("PRAGMA table_info(admin_users)").fetchall()}
            for name, definition in (("mfa_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"), ("totp_secret_enc", "TEXT"), ("mfa_setup_expires", "TEXT")):
                if name not in admin_columns:
                    db.execute(f"ALTER TABLE admin_users ADD COLUMN {name} {definition}")
        db.execute(f"""CREATE TABLE IF NOT EXISTS admin_recovery_codes (
            id {serial}, user_id {user_id_type} NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS admin_recovery_user_idx ON admin_recovery_codes(user_id, used_at)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_created_at_idx ON inquiries(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_status_created_at_idx ON inquiries(status, created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS inquiries_service_created_at_idx ON inquiries(service, created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS admin_sessions_expiry_idx ON admin_sessions(expires_at)")
        db.connection.commit()
        _SCHEMA_READY.add(ready_key)


def _password_hash(password: str) -> str:
    try:
        from argon2 import PasswordHasher, Type
        return PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID).hash(password)
    except ImportError:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS, dklen=32)
        return "pbkdf2_sha256${}${}${}".format(
            PBKDF2_ROUNDS,
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )


def _password_needs_upgrade(encoded: str) -> bool:
    if not encoded.startswith("$argon2id$"):
        return True
    try:
        from argon2 import PasswordHasher
        return PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2, hash_len=32, salt_len=16).check_needs_rehash(encoded)
    except ImportError:
        return False
    except Exception:
        return True


def _verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    if encoded.startswith("$argon2id$"):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError, VerificationError
            return PasswordHasher().verify(encoded, password)
        except ImportError:
            return False
        except (VerifyMismatchError, VerificationError, ValueError, TypeError):
            return False
    try:
        algorithm, rounds_text, salt_text, expected_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        if rounds < 300_000 or rounds > 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(expected_text + "=" * (-len(expected_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _mfa_fernet():
    key = os.environ.get("ADMIN_MFA_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("ADMIN_MFA_ENCRYPTION_KEY is not configured")
    from cryptography.fernet import Fernet
    return Fernet(key.encode("ascii"))


def _encrypt_totp_secret(secret: str) -> str:
    return _mfa_fernet().encrypt(secret.encode("ascii")).decode("ascii")


def _decrypt_totp_secret(ciphertext: str) -> str:
    return _mfa_fernet().decrypt(ciphertext.encode("ascii")).decode("ascii")


def _totp_at(secret: str, timestamp: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int(timestamp // 30).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{number:06d}"


def _normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def _verify_mfa_code(db: Database, user_id: int, encrypted_secret: str | None, supplied: object, now: datetime) -> bool:
    if not isinstance(supplied, str):
        return False
    code = supplied.strip()
    if encrypted_secret and re.fullmatch(r"\d{6}", code):
        try:
            secret = _decrypt_totp_secret(encrypted_secret)
            epoch = int(now.timestamp())
            return any(hmac.compare_digest(_totp_at(secret, epoch + offset * 30), code) for offset in (-1, 0, 1))
        except Exception:
            return False
    normalized = _normalize_recovery_code(code)
    if len(normalized) != 16:
        return False
    digest = hashlib.sha256(normalized.encode("ascii")).hexdigest()
    row = db.execute("SELECT id FROM admin_recovery_codes WHERE user_id = ? AND code_hash = ? AND used_at IS NULL", (user_id, digest)).fetchone()
    if not row:
        return False
    db.execute("UPDATE admin_recovery_codes SET used_at = ? WHERE id = ?", (iso(now), int(row["id"])))
    return True


def _new_recovery_codes() -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)) for _ in range(10)]


def _valid_email(value: object) -> str:
    email = value.strip().lower() if isinstance(value, str) else ""
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return ""
    return email


def _valid_password_hash(value: str) -> bool:
    if isinstance(value, str) and value.startswith("$argon2id$"):
        return len(value) < 512 and bool(re.fullmatch(r"\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+", value))
    try:
        algorithm, rounds_text, salt_text, digest_text = value.split("$", 3)
        rounds = int(rounds_text)
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        digest = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        return algorithm == "pbkdf2_sha256" and 300_000 <= rounds <= 2_000_000 and len(salt) >= 16 and len(digest) == 32
    except (ValueError, TypeError):
        return False


def _seed_admin(db: Database) -> None:
    email = _valid_email(os.environ.get("ADMIN_EMAIL", ""))
    password_hash = os.environ.get("ADMIN_INITIAL_PASSWORD_HASH", "")
    if not email or not _valid_password_hash(password_hash):
        return
    existing = db.execute("SELECT id FROM admin_users LIMIT 1").fetchone()
    if existing:
        return
    created = iso()
    db.execute(
        "INSERT INTO admin_users (email, password_hash, must_change_password, created_at, updated_at) VALUES (?, ?, 1, ?, ?) ON CONFLICT(email) DO NOTHING",
        (email, password_hash, created, created),
    )


def prepare_local_database(database_path: str | Path) -> None:
    os.environ["LOCAL_DATABASE_PATH"] = str(Path(database_path).expanduser())
    with database() as db:
        _ensure_schema(db)


def local_admin_exists() -> bool:
    with database() as db:
        _ensure_schema(db)
        return db.execute("SELECT id FROM admin_users LIMIT 1").fetchone() is not None


def create_local_admin(email: str, password: str) -> None:
    email = _valid_email(email)
    try:
        _validate_new_password(password)
    except ServiceError as error:
        raise ValueError(error.message) from error
    if not email:
        raise ValueError("Enter a valid email address.")
    with database() as db:
        _ensure_schema(db)
        if db.execute("SELECT id FROM admin_users LIMIT 1").fetchone():
            raise ValueError("A local admin account already exists.")
        timestamp = iso()
        db.execute(
            "INSERT INTO admin_users (email, password_hash, must_change_password, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
            (email, _password_hash(password), timestamp, timestamp),
        )


def _validate_new_password(password: object) -> str:
    if not isinstance(password, str) or len(password) < 14 or len(password) > 128:
        raise ServiceError(400, "Use a password or passphrase between 14 and 128 characters.")
    if not password.strip() or password != password.strip():
        raise ServiceError(400, "Remove spaces from the beginning and end of the password.")
    return password


def _session_secret(production: bool) -> bytes:
    configured = os.environ.get("ADMIN_SESSION_SECRET", "").strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("ADMIN_SESSION_SECRET must contain at least 32 characters")
        return configured.encode("utf-8")
    if production:
        raise RuntimeError("ADMIN_SESSION_SECRET is not configured")
    data_dir = Path(os.environ.get("LOCAL_DATABASE_PATH", str(DEFAULT_LOCAL_DB))).expanduser().parent
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_file = data_dir / ".admin-session-secret"
    if not secret_file.exists():
        try:
            fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(48))
    try:
        os.chmod(secret_file, 0o600)
    except OSError:
        pass
    return secret_file.read_bytes()


def _client_ip(headers) -> str:
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        # Vercel places the originating client first in this header.
        return forwarded.split(",", 1)[0].strip()[:80]
    return headers.get("x-real-ip", "local")[:80]


def _rate_key(secret: bytes, scope: str, identity: str) -> str:
    return hmac.new(secret, f"{scope}:{identity}".encode("utf-8"), hashlib.sha256).hexdigest()


def _rate_limited(db: Database, rate_key: str, now_text: str) -> bool:
    row = db.execute("SELECT locked_until FROM rate_limits WHERE rate_key = ?", (rate_key,)).fetchone()
    return bool(row and row["locked_until"] and row["locked_until"] > now_text)


def _record_rate_failure(db: Database, rate_key: str, now: datetime, limit: int, window: timedelta) -> tuple[int, bool]:
    now_text = iso(now)
    reset_before = iso(now - window)
    locked_until = iso(now + window)
    sql = """INSERT INTO rate_limits (rate_key, attempts, window_started_at, locked_until)
        VALUES (?, 1, ?, NULL)
        ON CONFLICT(rate_key) DO UPDATE SET
          attempts = CASE WHEN rate_limits.window_started_at <= ? THEN 1 ELSE rate_limits.attempts + 1 END,
          window_started_at = CASE WHEN rate_limits.window_started_at <= ? THEN ? ELSE rate_limits.window_started_at END,
          locked_until = CASE WHEN
            (CASE WHEN rate_limits.window_started_at <= ? THEN 1 ELSE rate_limits.attempts + 1 END) >= ?
            THEN ? ELSE NULL END
        RETURNING attempts, locked_until"""
    row = db.execute(sql, (rate_key, now_text, reset_before, reset_before, now_text, reset_before, limit, locked_until)).fetchone()
    return int(row["attempts"]), bool(row["locked_until"] and row["locked_until"] > now_text)


def _read_json(body: bytes) -> dict:
    if not body or len(body) > MAX_BODY_BYTES:
        raise ServiceError(413, "Request is empty or too large.")
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        raise ServiceError(400, "Could not read this request.")
    if not isinstance(result, dict):
        raise ServiceError(400, "Expected a JSON object.")
    return result


def _response(status: int, body: bytes = b"", content_type: str = "application/json; charset=utf-8", extra: list[tuple[str, str]] | None = None):
    headers = [("Content-Type", content_type), ("Cache-Control", "no-store, max-age=0"), ("Pragma", "no-cache"), ("X-Content-Type-Options", "nosniff")]
    if extra:
        headers.extend(extra)
    return status, headers, body


def _json(status: int, payload: dict, extra: list[tuple[str, str]] | None = None):
    return _response(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), extra=extra)


def _origin_ok(headers) -> bool:
    origin = headers.get("origin", "")
    host = headers.get("host", "")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
        return False
    return headers.get("sec-fetch-site", "same-origin") not in {"cross-site", "none"}


def _cookie_names(production: bool) -> tuple[str, str]:
    if production:
        return "__Host-blessson-session", "__Host-blessson-csrf"
    return "blessson_session", "blessson_csrf"


def _read_cookies(headers) -> dict[str, str]:
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("cookie", ""))
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in cookie.items()}


def _cookie_headers(session_token: str, csrf_token: str, production: bool, clear: bool = False) -> list[tuple[str, str]]:
    session_name, csrf_name = _cookie_names(production)
    secure = "; Secure" if production else ""
    if clear:
        expiry = "; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        return [
            ("Set-Cookie", f"{session_name}=; Path=/; HttpOnly; SameSite=Strict{secure}{expiry}"),
            ("Set-Cookie", f"{csrf_name}=; Path=/; SameSite=Strict{secure}{expiry}"),
        ]
    return [
        ("Set-Cookie", f"{session_name}={session_token}; Path=/; HttpOnly; SameSite=Strict{secure}; Max-Age={int(SESSION_TTL.total_seconds())}"),
        ("Set-Cookie", f"{csrf_name}={csrf_token}; Path=/; SameSite=Strict{secure}; Max-Age={int(SESSION_TTL.total_seconds())}"),
    ]


def _load_session(db: Database, headers, production: bool, now_text: str):
    cookies = _read_cookies(headers)
    session_name, csrf_name = _cookie_names(production)
    raw_token = cookies.get(session_name, "")
    if not raw_token or len(raw_token) > 160:
        return None, ""
    token_hash = hashlib.sha256(raw_token.encode("ascii", "ignore")).hexdigest()
    row = db.execute("""SELECT s.token_hash, s.csrf_hash, s.user_id, s.expires_at,
        u.email, u.must_change_password, u.mfa_enabled FROM admin_sessions s
        JOIN admin_users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?""", (token_hash, now_text)).fetchone()
    csrf_token = cookies.get(csrf_name, "")
    if not row or len(csrf_token) > 160:
        return None, ""
    csrf_hash = hashlib.sha256(csrf_token.encode("ascii", "ignore")).hexdigest()
    if not hmac.compare_digest(csrf_hash, row["csrf_hash"]):
        return None, ""
    return row, raw_token


def _new_session(db: Database, user_id: int, production: bool):
    session_token = secrets.token_urlsafe(40)
    csrf_token = secrets.token_urlsafe(32)
    created = now_utc()
    db.execute(
        "INSERT INTO admin_sessions (token_hash, user_id, csrf_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (hashlib.sha256(session_token.encode()).hexdigest(), user_id, hashlib.sha256(csrf_token.encode()).hexdigest(), iso(created), iso(created + SESSION_TTL)),
    )
    return session_token, csrf_token, _cookie_headers(session_token, csrf_token, production)


def _check_csrf(db: Database, session, headers) -> bool:
    supplied = headers.get("x-csrf-token", "")
    if not supplied or len(supplied) > 160 or not _origin_ok(headers):
        return False
    digest = hashlib.sha256(supplied.encode("ascii", "ignore")).hexdigest()
    return hmac.compare_digest(digest, session["csrf_hash"])


def _query_options(query_string: str) -> dict:
    parsed = parse_qs(query_string, keep_blank_values=True, max_num_fields=20)

    def value(name: str, default: str = "") -> str:
        return parsed.get(name, [default])[0][:200]

    clauses, params = [], []
    q = value("q").strip()
    if q:
        q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{q}%"
        columns = ("name", "email", "project", "service", "timeline", "genre", "message")
        clauses.append("(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + ")")
        params.extend([like] * len(columns))
    status = value("status", "all")
    if status in VALID_STATUSES:
        clauses.append("status = ?")
        params.append(status)
    service = value("service", "all")
    if service in VALID_SERVICES:
        clauses.append("service = ?")
        params.append(service)
    try:
        page = max(1, min(int(value("page", "1")), 100_000))
    except ValueError:
        page = 1
    try:
        requested_size = int(value("page_size", "12"))
    except ValueError:
        requested_size = 12
    page_size = requested_size if requested_size in PAGE_SIZES else 12
    order = "created_at ASC, id ASC" if value("sort", "newest") == "oldest" else "created_at DESC, id DESC"
    return {"where": " WHERE " + " AND ".join(clauses) if clauses else "", "params": params, "page": page, "page_size": page_size, "order": order}


def _list_inquiries(db: Database, query_string: str):
    options = _query_options(query_string)
    where = options["where"]
    total = int(db.execute(f"SELECT COUNT(*) AS count FROM inquiries{where}", options["params"]).fetchone()["count"])
    pages = max(1, (total + options["page_size"] - 1) // options["page_size"])
    page = min(options["page"], pages)
    offset = (page - 1) * options["page_size"]
    rows = db.execute(
        f"SELECT id, created_at, name, email, project, service, timeline, genre, message, status FROM inquiries{where} ORDER BY {options['order']} LIMIT ? OFFSET ?",
        [*options["params"], options["page_size"], offset],
    ).fetchall()
    counts = {status: 0 for status in VALID_STATUSES}
    for row in db.execute("SELECT status, COUNT(*) AS count FROM inquiries GROUP BY status").fetchall():
        counts[row["status"]] = int(row["count"])
    return {"inquiries": [dict(row) for row in rows], "stats": {"total": sum(counts.values()), **counts}, "pagination": {"page": page, "page_size": options["page_size"], "total": total, "pages": pages}}


def _safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if re.match(r"^[\s\ufeff\x00-\x1f]*[=+@-]", text):
        return "'" + text
    return text


def _export_csv(db: Database, query_string: str):
    options = _query_options(query_string)
    rows = db.execute(
        f"SELECT id, created_at, name, email, project, service, timeline, genre, message, status FROM inquiries{options['where']} ORDER BY {options['order']}",
        options["params"],
    ).fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ID", "Received", "Name", "Email", "Project", "Service", "Timeline", "Genre / style", "Project notes", "Status"])
    for row in rows:
        writer.writerow([_safe_csv_cell(row[key]) for key in ("id", "created_at", "name", "email", "project", "service", "timeline", "genre", "message", "status")])
    filename_date = now_utc().date().isoformat()
    return _response(200, ("\ufeff" + output.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", [("Content-Disposition", f'attachment; filename="blessson-enquiries-{filename_date}.csv"')])


def handle_admin_request(method: str, path: str, headers, body: bytes, production: bool):
    now = now_utc()
    now_text = iso(now)
    try:
        secret = _session_secret(production)
        with database(require_postgres=production) as db:
            _ensure_schema(db)
            if production:
                _seed_admin(db)
            parsed = urlsplit(path)
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
            action = query.get("action", [""])[0]
            if action == "health" and method == "GET":
                return _json(200, {"ok": True, "configured": db.execute("SELECT id FROM admin_users LIMIT 1").fetchone() is not None})
            if action == "session" and method == "GET":
                session, _ = _load_session(db, headers, production, now_text)
                if not session:
                    return _json(200, {"authenticated": False})
                return _json(200, {"authenticated": True, "email": session["email"], "mustChangePassword": bool(session["must_change_password"]), "mfaEnabled": bool(session["mfa_enabled"])})
            if action == "login" and method == "POST":
                if not _origin_ok(headers):
                    return _json(403, {"error": "This sign-in request could not be verified."})
                payload = _read_json(body)
                email = _valid_email(payload.get("email"))
                password = payload.get("password") if isinstance(payload.get("password"), str) else ""
                if not email or not password or len(password) > 128:
                    return _json(400, {"error": "Enter your account email and password."})
                identity = f"{email}|{_client_ip(headers)}"
                rate_key = _rate_key(secret, "login", identity)
                if _rate_limited(db, rate_key, now_text):
                    return _json(429, {"error": "Too many sign-in attempts. Try again in 15 minutes."}, [("Retry-After", "900")])
                configured = db.execute("SELECT id, email, password_hash, must_change_password, mfa_enabled, totp_secret_enc FROM admin_users WHERE email = ?", (email,)).fetchone()
                password_ok = _verify_password(password, configured["password_hash"] if configured else DUMMY_PASSWORD_HASH)
                mfa_code = payload.get("mfaCode", "")
                recovery_code = payload.get("recoveryCode", "")
                mfa_ok = not (configured and configured["mfa_enabled"]) or (password_ok and _verify_mfa_code(db, int(configured["id"]), configured["totp_secret_enc"], mfa_code or recovery_code, now))
                if not configured or not password_ok or not mfa_ok:
                    attempts, locked = _record_rate_failure(db, rate_key, now, MAX_LOGIN_FAILURES, LOGIN_WINDOW)
                    message = "Too many sign-in attempts. Try again in 15 minutes." if locked else "Check your email, password, and authenticator code."
                    return _json(429 if locked else 401, {"error": message}, [("Retry-After", "900")] if locked else None)
                if _password_needs_upgrade(configured["password_hash"]):
                    db.execute("UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE id = ?", (_password_hash(password), now_text, int(configured["id"])))
                db.execute("DELETE FROM rate_limits WHERE rate_key = ?", (rate_key,))
                db.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now_text,))
                session_token, csrf_token, cookies = _new_session(db, int(configured["id"]), production)
                return _json(200, {"authenticated": True, "email": configured["email"], "mustChangePassword": bool(configured["must_change_password"]), "mfaEnabled": bool(configured["mfa_enabled"])}, cookies)

            session, session_token = _load_session(db, headers, production, now_text)
            if not session:
                if action in {"logout", "password", "status", "inquiries", "export", "mfa-setup", "mfa-confirm", "mfa-disable", "revoke-sessions", "projects", "services", "settings"}:
                    return _json(401, {"error": "Your session expired. Sign in again."}, _cookie_headers("", "", production, clear=True))
                return _json(404, {"error": "Admin endpoint not found."})
            if method == "POST" and not _check_csrf(db, session, headers):
                return _json(403, {"error": "Refresh the page and try again."})
            if action == "mfa-setup" and method == "POST":
                if session["mfa_enabled"]:
                    return _json(409, {"error": "Authenticator sign-in is already enabled."})
                payload = _read_json(body)
                account = db.execute("SELECT email FROM admin_users WHERE id = ?", (int(session["user_id"]),)).fetchone()
                secret_text = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
                encrypted = _encrypt_totp_secret(secret_text)
                db.execute("UPDATE admin_users SET totp_secret_enc = ?, mfa_setup_expires = ?, updated_at = ? WHERE id = ?", (encrypted, iso(now + timedelta(minutes=10)), now_text, int(session["user_id"])))
                label = quote("Blessson Studio:" + str(account["email"]))
                issuer = quote("Blessson Studio")
                return _json(200, {"secret": secret_text, "otpAuthUrl": f"otpauth://totp/{label}?secret={secret_text}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"})
            if action == "mfa-confirm" and method == "POST":
                payload = _read_json(body)
                account = db.execute("SELECT totp_secret_enc, mfa_setup_expires, mfa_enabled FROM admin_users WHERE id = ?", (int(session["user_id"]),)).fetchone()
                if not account or account["mfa_enabled"] or not account["totp_secret_enc"] or not account["mfa_setup_expires"] or account["mfa_setup_expires"] <= now_text:
                    return _json(409, {"error": "The setup code expired. Start setup again."})
                if not _verify_mfa_code(db, int(session["user_id"]), account["totp_secret_enc"], payload.get("code"), now):
                    return _json(400, {"error": "That code did not match. Check your authenticator and try again."})
                recovery_codes = _new_recovery_codes()
                db.execute("UPDATE admin_users SET mfa_enabled = TRUE, mfa_setup_expires = NULL, updated_at = ? WHERE id = ?", (now_text, int(session["user_id"])))
                db.execute("DELETE FROM admin_recovery_codes WHERE user_id = ?", (int(session["user_id"]),))
                for recovery_code in recovery_codes:
                    digest = hashlib.sha256(_normalize_recovery_code(recovery_code).encode("ascii")).hexdigest()
                    db.execute("INSERT INTO admin_recovery_codes (user_id, code_hash, created_at) VALUES (?, ?, ?)", (int(session["user_id"]), digest, now_text))
                current_hash = hashlib.sha256(session_token.encode()).hexdigest()
                db.execute("DELETE FROM admin_sessions WHERE user_id = ? AND token_hash <> ?", (int(session["user_id"]), current_hash))
                return _json(200, {"ok": True, "recoveryCodes": recovery_codes})
            if action == "mfa-disable" and method == "POST":
                payload = _read_json(body)
                account = db.execute("SELECT password_hash, totp_secret_enc, mfa_enabled FROM admin_users WHERE id = ?", (int(session["user_id"]),)).fetchone()
                code = payload.get("code") or payload.get("recoveryCode")
                if not account or not account["mfa_enabled"] or not _verify_password(str(payload.get("currentPassword", "")), account["password_hash"]) or not _verify_mfa_code(db, int(session["user_id"]), account["totp_secret_enc"], code, now):
                    return _json(401, {"error": "Password or authenticator code was not accepted."})
                db.execute("UPDATE admin_users SET mfa_enabled = FALSE, totp_secret_enc = NULL, mfa_setup_expires = NULL, updated_at = ? WHERE id = ?", (now_text, int(session["user_id"])))
                db.execute("DELETE FROM admin_recovery_codes WHERE user_id = ?", (int(session["user_id"]),))
                return _json(200, {"ok": True})
            if action == "revoke-sessions" and method == "POST":
                db.execute("DELETE FROM admin_sessions WHERE user_id = ?", (int(session["user_id"]),))
                return _json(200, {"ok": True}, _cookie_headers("", "", production, clear=True))
            if session["must_change_password"] and action not in {"password", "logout", "session", "mfa-setup", "mfa-confirm"}:
                return _json(403, {"error": "Set a new password before opening the inbox."})
            if action == "logout" and method == "POST":
                token_hash = hashlib.sha256(session_token.encode()).hexdigest()
                db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
                return _json(200, {"ok": True}, _cookie_headers("", "", production, clear=True))
            if action == "password" and method == "POST":
                payload = _read_json(body)
                password = _validate_new_password(payload.get("newPassword"))
                if not session["must_change_password"]:
                    current = payload.get("currentPassword") if isinstance(payload.get("currentPassword"), str) else ""
                    account = db.execute("SELECT password_hash FROM admin_users WHERE id = ?", (int(session["user_id"]),)).fetchone()
                    if not current or not account or not _verify_password(current, account["password_hash"]):
                        return _json(401, {"error": "Current password was not accepted."})
                db.execute(
                    "UPDATE admin_users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
                    (_password_hash(password), now_text, int(session["user_id"])),
                )
                db.execute("DELETE FROM admin_sessions WHERE user_id = ?", (int(session["user_id"]),))
                _, csrf_token, cookies = _new_session(db, int(session["user_id"]), production)
                return _json(200, {"ok": True}, cookies)
            if action == "status" and method == "POST":
                payload = _read_json(body)
                try:
                    inquiry_id = int(payload.get("id"))
                except (TypeError, ValueError):
                    return _json(400, {"error": "Choose a valid enquiry."})
                status = payload.get("status")
                if status not in VALID_STATUSES:
                    return _json(400, {"error": "Choose a valid workflow status."})
                cursor = db.execute("UPDATE inquiries SET status = ? WHERE id = ?", (status, inquiry_id))
                if cursor.rowcount == 0:
                    return _json(404, {"error": "Enquiry not found."})
                return _json(200, {"ok": True})
            if action == "inquiries" and method == "GET":
                if session["must_change_password"]:
                    return _json(403, {"error": "Set a new password before opening the inbox."})
                return _json(200, _list_inquiries(db, parsed.query))
            if action == "export" and method == "GET":
                if session["must_change_password"]:
                    return _json(403, {"error": "Set a new password before exporting enquiries."})
                return _export_csv(db, parsed.query)
            return _json(404, {"error": "Admin endpoint not found."})
    except ServiceError as error:
        return _json(error.status, {"error": error.message}, error.headers)
    except Exception as error:
        print("Admin request failed:", type(error).__name__)
        return _json(503, {"error": "The secure inbox is temporarily unavailable. Try again shortly."})


def handle_inquiry_request(method: str, path: str, headers, body: bytes, production: bool):
    if method != "POST" or urlsplit(path).path != "/api/inquiries":
        return _json(404, {"error": "Endpoint not found."})
    if not _origin_ok(headers):
        return _json(403, {"error": "This enquiry could not be verified."})
    try:
        secret = _session_secret(production)
        with database(require_postgres=production) as db:
            _ensure_schema(db)
            now = now_utc()
            rate_key = _rate_key(secret, "inquiry", _client_ip(headers))
            if _rate_limited(db, rate_key, iso(now)):
                return _json(429, {"error": "Please wait before sending another enquiry."}, [("Retry-After", "900")])
            _record_rate_failure(db, rate_key, now, MAX_INQUIRIES_PER_WINDOW, INQUIRY_WINDOW)
            payload = _read_json(body)
            if isinstance(payload.get("website"), str) and payload["website"].strip():
                return _json(202, {"ok": True})
            name = payload.get("name", "").strip()[:120] if isinstance(payload.get("name"), str) else ""
            email = _valid_email(payload.get("email"))
            project = payload.get("project", "").strip()[:160] if isinstance(payload.get("project"), str) else ""
            service = payload.get("service", "")
            timeline = payload.get("timeline", "").strip()[:80] if isinstance(payload.get("timeline"), str) else ""
            genre = payload.get("genre", "").strip()[:100] if isinstance(payload.get("genre"), str) else ""
            message = payload.get("message", "").strip()[:4000] if isinstance(payload.get("message"), str) else ""
            if not name or not email or not message:
                return _json(400, {"error": "Add your name, a valid email, and a short project note."})
            if service not in VALID_SERVICES:
                return _json(400, {"error": "Choose a valid service."})
            cursor = db.execute(
                "INSERT INTO inquiries (created_at, name, email, project, service, timeline, genre, message, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new') RETURNING id",
                (iso(now), name, email, project, service, timeline, genre, message),
            )
            row = cursor.fetchone()
            return _json(201, {"ok": True, "id": int(row["id"])})
    except ServiceError as error:
        return _json(error.status, {"error": error.message}, error.headers)
    except Exception as error:
        print("Inquiry request failed:", type(error).__name__)
        return _json(503, {"error": "The enquiry form is temporarily unavailable."})
