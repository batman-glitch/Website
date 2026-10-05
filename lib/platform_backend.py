"""FastAPI-facing project, service, and website management operations."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from lib.admin_backend import (
    VALID_SERVICES,
    ServiceError,
    _check_csrf,
    _ensure_schema,
    _json,
    _load_session,
    _read_json,
    database,
    iso,
    now_utc,
)

CONTENT_LIMIT = 18 * 1024
SERVICE_SEEDS = (
    ("Mixing", "Balance & character", "Depth, clarity, and movement without sanding off what makes the performance yours."),
    ("Mastering", "Ready for everywhere", "Careful final polish and delivery formats prepared for streaming, vinyl, and release."),
    ("Production", "From idea to record", "Arrangement, sound selection, and production support to help the strongest version emerge."),
    ("Recording", "A focused recording session", "Thoughtful recording and session direction with space for a strong performance."),
    ("Sound design", "Sound with intention", "Distinctive sonic textures and detail shaped around the story and the music."),
)
DEFAULT_SETTINGS = {
    "heroTitle": "Make your record",
    "heroAccent": "feel like itself.",
    "heroDescription": "Mixing, mastering, and production for artists who care about the details. Warm low end. Natural dynamics. A sound that still feels like you.",
    "availability": "Independent audio engineer · Remote worldwide",
    "contactEmail": "blessonkondeti@gmail.com",
    "aboutText": "I’m Blessson, an independent audio engineer partnering with artists to make records that feel honest, detailed, and unmistakably their own.",
}


def _ensure_content_schema(db) -> None:
    serial = "BIGSERIAL PRIMARY KEY" if db.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db.execute(f"""CREATE TABLE IF NOT EXISTS portfolio_projects (
        id {serial}, title TEXT NOT NULL, artist TEXT NOT NULL DEFAULT '', service TEXT NOT NULL,
        genre TEXT NOT NULL DEFAULT '', release_year INTEGER, description TEXT NOT NULL DEFAULT '',
        cover_url TEXT NOT NULL DEFAULT '', audio_url TEXT NOT NULL DEFAULT '', audio_label TEXT NOT NULL DEFAULT '',
        is_published BOOLEAN NOT NULL DEFAULT FALSE, is_featured BOOLEAN NOT NULL DEFAULT FALSE,
        display_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS portfolio_services (
        id {serial}, name TEXT NOT NULL UNIQUE, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE, display_order INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS portfolio_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS portfolio_projects_public_idx ON portfolio_projects(is_published, display_order, id)")
    db.execute("CREATE INDEX IF NOT EXISTS portfolio_services_public_idx ON portfolio_services(active, display_order, id)")
    for index, (name, title, description) in enumerate(SERVICE_SEEDS, start=1):
        db.execute(
            "INSERT INTO portfolio_services (name, title, description, active, display_order, updated_at) VALUES (?, ?, ?, TRUE, ?, ?) ON CONFLICT(name) DO NOTHING",
            (name, title, description, index * 10, iso()),
        )
    for key, value in DEFAULT_SETTINGS.items():
        db.execute("INSERT INTO portfolio_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?) ON CONFLICT(setting_key) DO NOTHING", (key, value, iso()))


def _project_dict(row):
    item = dict(row)
    item["is_published"] = bool(item["is_published"])
    item["is_featured"] = bool(item["is_featured"])
    return item


def _service_dict(row):
    item = dict(row)
    item["active"] = bool(item["active"])
    return item


def _safe_media_url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ServiceError(400, f"Choose a valid {field}.")
    value = value.strip()
    if not value:
        return ""
    if value.startswith("assets/") and ".." not in value:
        return value[:500]
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or not hostname.endswith(".public.blob.vercel-storage.com") or not parsed.path:
        raise ServiceError(400, f"The {field} must come from the studio media library.")
    return value[:1000]


def _project_payload(payload: dict) -> dict:
    def text(key: str, limit: int, required: bool = False) -> str:
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise ServiceError(400, f"Add a valid {key.replace('_', ' ')}.")
        value = value.strip()
        if len(value) > limit or (required and not value):
            raise ServiceError(400, f"Check the {key.replace('_', ' ')} field.")
        return value

    title = text("title", 120, True)
    artist = text("artist", 120)
    service = text("service", 60, True)
    if service not in VALID_SERVICES:
        raise ServiceError(400, "Choose a service from the list.")
    genre = text("genre", 100)
    description = text("description", 4000)
    audio_label = text("audio_label", 120)
    try:
        release_year = int(payload.get("release_year") or 0) or None
    except (TypeError, ValueError):
        raise ServiceError(400, "Enter a valid release year.")
    if release_year is not None and not 1900 <= release_year <= 2100:
        raise ServiceError(400, "Enter a year between 1900 and 2100.")
    try:
        display_order = max(-1000, min(10000, int(payload.get("display_order", 0))))
    except (TypeError, ValueError):
        display_order = 0
    return {
        "title": title,
        "artist": artist,
        "service": service,
        "genre": genre,
        "release_year": release_year,
        "description": description,
        "cover_url": _safe_media_url(payload.get("cover_url", ""), "cover image"),
        "audio_url": _safe_media_url(payload.get("audio_url", ""), "audio preview"),
        "audio_label": audio_label,
        "is_published": bool(payload.get("is_published", False)),
        "is_featured": bool(payload.get("is_featured", False)),
        "display_order": display_order,
    }


def _admin_session(db, headers, production):
    session, _ = _load_session(db, headers, production, iso())
    return session


def handle_platform_request(method: str, path: str, headers, body: bytes, production: bool):
    """Handle public portfolio data and authenticated admin content management."""
    try:
        parsed = urlsplit(path)
        clean_path = parsed.path.rstrip("/") or "/"
        if len(body) > CONTENT_LIMIT:
            return _json(413, {"error": "This update is too large."})
        is_public = clean_path in {"/api/portfolio", "/api/portfolio/projects", "/api/portfolio/services"} and method == "GET"
        with database(require_postgres=production) as db:
            _ensure_schema(db)
            _ensure_content_schema(db)
            if is_public:
                if clean_path.endswith("/projects"):
                    projects = db.execute("SELECT * FROM portfolio_projects WHERE is_published = TRUE ORDER BY is_featured DESC, display_order ASC, id DESC").fetchall()
                    return _json(200, {"projects": [_project_dict(row) for row in projects]})
                if clean_path.endswith("/services"):
                    services = db.execute("SELECT id, name, title, description, display_order FROM portfolio_services WHERE active = TRUE ORDER BY display_order ASC, id ASC").fetchall()
                    return _json(200, {"services": [dict(row) for row in services]})
                projects = db.execute("SELECT * FROM portfolio_projects WHERE is_published = TRUE ORDER BY is_featured DESC, display_order ASC, id DESC").fetchall()
                services = db.execute("SELECT id, name, title, description, display_order FROM portfolio_services WHERE active = TRUE ORDER BY display_order ASC, id ASC").fetchall()
                settings = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key, setting_value FROM portfolio_settings").fetchall()}
                return _json(200, {"projects": [_project_dict(row) for row in projects], "services": [dict(row) for row in services], "settings": settings})

            if not clean_path.startswith("/api/admin/"):
                return _json(404, {"error": "Endpoint not found."})
            session = _admin_session(db, headers, production)
            if not session:
                return _json(401, {"error": "Your session expired. Sign in again."})
            if session["must_change_password"]:
                return _json(403, {"error": "Set your new password before editing portfolio content."})
            write_method = method in {"POST", "PUT", "PATCH", "DELETE"}
            if write_method and not _check_csrf(db, session, headers):
                return _json(403, {"error": "Refresh the page and try again."})
            if clean_path == "/api/admin/projects":
                if method == "GET":
                    rows = db.execute("SELECT * FROM portfolio_projects ORDER BY is_featured DESC, display_order ASC, updated_at DESC").fetchall()
                    return _json(200, {"projects": [_project_dict(row) for row in rows]})
                if method == "POST":
                    raw_payload = _read_json(body)
                    payload = _project_payload(raw_payload)
                    values = tuple(payload[key] for key in ("title", "artist", "service", "genre", "release_year", "description", "cover_url", "audio_url", "audio_label", "is_published", "is_featured", "display_order"))
                    now_text = iso()
                    raw_id = raw_payload.get("id")
                    if raw_id:
                        try:
                            project_id = int(raw_id)
                        except (ValueError, TypeError):
                            return _json(400, {"error": "Choose a valid project."})
                        cursor = db.execute("""UPDATE portfolio_projects SET title=?, artist=?, service=?, genre=?, release_year=?, description=?, cover_url=?, audio_url=?, audio_label=?, is_published=?, is_featured=?, display_order=?, updated_at=? WHERE id=?""", (*values, now_text, project_id))
                        if cursor.rowcount == 0:
                            return _json(404, {"error": "Project not found."})
                        return _json(200, {"ok": True, "id": project_id, "published": payload["is_published"]})
                    cursor = db.execute("""INSERT INTO portfolio_projects (title, artist, service, genre, release_year, description, cover_url, audio_url, audio_label, is_published, is_featured, display_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""", (*values, now_text, now_text))
                    project_id = int(cursor.fetchone()["id"])
                    return _json(201, {"ok": True, "id": project_id, "published": payload["is_published"]})
            project_match = re.fullmatch(r"/api/admin/projects/(\d+)", clean_path)
            if project_match and method == "DELETE":
                project_id = int(project_match.group(1))
                cursor = db.execute("DELETE FROM portfolio_projects WHERE id = ?", (project_id,))
                if not cursor.rowcount:
                    return _json(404, {"error": "Project not found."})
                return _json(200, {"ok": True})
            if clean_path == "/api/admin/services":
                if method == "GET":
                    rows = db.execute("SELECT * FROM portfolio_services ORDER BY display_order ASC, id ASC").fetchall()
                    return _json(200, {"services": [_service_dict(row) for row in rows]})
                if method == "POST":
                    payload = _read_json(body)
                    try:
                        service_id = int(payload.get("id")) if payload.get("id") else None
                        order = int(payload.get("display_order", 0))
                    except (TypeError, ValueError):
                        return _json(400, {"error": "Choose a valid service."})
                    name = payload.get("name", "")
                    title = payload.get("title", "")
                    description = payload.get("description", "")
                    if name not in VALID_SERVICES or not isinstance(title, str) or not title.strip() or len(title) > 100 or not isinstance(description, str) or len(description.strip()) > 1000:
                        return _json(400, {"error": "Check the service name, title, and description."})
                    now_text = iso()
                    active = bool(payload.get("active", True))
                    if service_id:
                        cursor = db.execute("UPDATE portfolio_services SET title=?, description=?, active=?, display_order=?, updated_at=? WHERE id=? AND name=?", (title.strip(), description.strip(), active, order, now_text, service_id, name))
                        if not cursor.rowcount:
                            return _json(404, {"error": "Service not found."})
                        return _json(200, {"ok": True, "id": service_id})
                    try:
                        row = db.execute("INSERT INTO portfolio_services (name, title, description, active, display_order, updated_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id", (name, title.strip(), description.strip(), active, order, now_text)).fetchone()
                    except Exception:
                        return _json(409, {"error": "This service already exists."})
                    return _json(201, {"ok": True, "id": int(row["id"])})
            service_match = re.fullmatch(r"/api/admin/services/(\d+)", clean_path)
            if service_match and method == "DELETE":
                service_id = int(service_match.group(1))
                cursor = db.execute("UPDATE portfolio_services SET active=FALSE, updated_at=? WHERE id=?", (iso(), service_id))
                if not cursor.rowcount:
                    return _json(404, {"error": "Service not found."})
                return _json(200, {"ok": True})
            if clean_path == "/api/admin/settings":
                if method == "GET":
                    settings = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key, setting_value FROM portfolio_settings").fetchall()}
                    return _json(200, {"settings": {**DEFAULT_SETTINGS, **settings}})
                if method in {"PUT", "POST"}:
                    payload = _read_json(body)
                    allowed = {"heroTitle": 90, "heroAccent": 90, "heroDescription": 500, "availability": 120, "aboutText": 1200}
                    updates = {}
                    for key, limit in allowed.items():
                        value = payload.get(key)
                        if value is not None:
                            if not isinstance(value, str) or len(value.strip()) > limit or not value.strip():
                                return _json(400, {"error": f"Check the {key} field."})
                            updates[key] = value.strip()
                    contact = payload.get("contactEmail")
                    if contact is not None:
                        from lib.admin_backend import _valid_email
                        contact = _valid_email(contact)
                        if not contact:
                            return _json(400, {"error": "Enter a valid contact email."})
                        updates["contactEmail"] = contact
                    for key, value in updates.items():
                        db.execute("INSERT INTO portfolio_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at", (key, value, iso()))
                    return _json(200, {"ok": True})
            return _json(405, {"error": "That operation is not available."})
    except ServiceError as error:
        return _json(error.status, {"error": error.message}, error.headers)
    except Exception as error:
        print("Portfolio API request failed:", type(error).__name__)
        return _json(503, {"error": "The portfolio service is temporarily unavailable."})
