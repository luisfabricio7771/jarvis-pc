"""Local, persistent tasks and session summaries. No network or model imports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, date
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid


def _default_path() -> Path:
    if os.environ.get("JARVIS_DATA_DIR"):
        return Path(os.environ["JARVIS_DATA_DIR"]) / "assistant.db"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "JARVIS" / "assistant.db"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jarvis" / "assistant.db"


DB_PATH = _default_path()
STATUSES = ("pending", "in_progress", "blocked", "completed", "cancelled")
PRIORITIES = ("low", "normal", "high", "urgent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def _terms(value: str) -> list[str]:
    ignored = {"de", "la", "el", "los", "las", "que", "del", "con", "para", "una", "the", "and", "about"}
    return [w for w in re.findall(r"\w+", _fold(value)) if len(w) > 1 and w not in ignored]


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA secure_delete=ON")
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'normal', due TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, summary TEXT NOT NULL, language TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, briefed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS episodes_date ON episodes(created_at);
        """)
        with connection:
            yield connection
    finally:
        connection.close()


def _text(value, limit: int, field: str, required=False) -> str:
    result = str(value or "").strip()
    if (required and not result) or len(result) > limit:
        raise ValueError(f"{field} must contain {'1' if required else '0'} to {limit} characters")
    return result


def _due(value) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        date.fromisoformat(value)
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("A due time must include a UTC offset, for example -06:00")
        value = parsed.astimezone(timezone.utc).isoformat()
    return value


def create_task(title: str, notes="", project="", priority="normal", due="") -> dict:
    fields = dict(title=_text(title, 300, "title", True), notes=_text(notes, 4000, "notes"),
                  project=_text(project, 200, "project"), priority=priority, due=_due(due))
    if priority not in PRIORITIES:
        raise ValueError("Unknown task priority")
    identifier, now = uuid.uuid4().hex[:12], _now()
    with _connect() as db:
        db.execute("INSERT INTO tasks (id,title,notes,project,priority,due,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                   (identifier, fields["title"], fields["notes"], fields["project"], priority, fields["due"], now, now))
        return dict(db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone())


def get_task(identifier: str) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row else None


def update_task(identifier: str, **changes) -> dict:
    clean = {}
    for key, value in changes.items():
        if key in ("title", "notes", "project"):
            clean[key] = _text(value, {"title": 300, "notes": 4000, "project": 200}[key], key, key == "title")
        elif key == "status":
            if value not in STATUSES:
                raise ValueError("Unknown task status")
            clean[key] = value
        elif key == "priority":
            if value not in PRIORITIES:
                raise ValueError("Unknown task priority")
            clean[key] = value
        elif key == "due":
            clean[key] = _due(value)
        else:
            raise ValueError(f"Unsupported task field: {key}")
    with _connect() as db:
        if not db.execute("SELECT id FROM tasks WHERE id=?", (identifier,)).fetchone():
            raise ValueError("Task not found; use list to retrieve its exact id")
        clean["updated_at"] = _now()
        clause = ",".join(f"{key}=?" for key in clean)
        db.execute(f"UPDATE tasks SET {clause} WHERE id=?", (*clean.values(), identifier))
        return dict(db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone())


def list_tasks(status="active", project="", query="", limit=50) -> list[dict]:
    if status not in (*STATUSES, "active", "all"):
        raise ValueError("Unknown task status filter")
    clauses, values = [], []
    if status == "active":
        clauses.append("status IN ('pending','in_progress','blocked')")
    elif status != "all":
        clauses.append("status=?")
        values.append(status)
    if project:
        clauses.append("project=?")
        values.append(project)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM tasks" + where + " ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, CASE WHEN due='' THEN 1 ELSE 0 END, due, created_at", values)]
    terms = _terms(query)
    if terms:
        rows = [row for row in rows if all(t in _fold(" ".join(str(row[k]) for k in ("title", "notes", "project"))) for t in terms)]
    return rows[:max(1, min(int(limit), 200))]


def delete_task(identifier: str) -> bool:
    with _connect() as db:
        return db.execute("DELETE FROM tasks WHERE id=?", (identifier,)).rowcount > 0


def save_episode(summary: str, language="", project="", *, identifier=None, created_at=None, briefed=False) -> str:
    summary = _text(summary, 4000, "summary", True)
    identifier = identifier or uuid.uuid4().hex
    with _connect() as db:
        db.execute("INSERT OR IGNORE INTO episodes (id,summary,language,project,created_at,briefed_at) VALUES (?,?,?,?,?,?)",
                   (identifier, summary, str(language)[:100], str(project)[:200], created_at or _now(), _now() if briefed else None))
    return identifier


def list_episodes(query="", project="", limit=20) -> list[dict]:
    with _connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM episodes" + (" WHERE project=?" if project else "") + " ORDER BY created_at DESC", (project,) if project else ())]
    terms = _terms(query)
    if terms:
        ranked = [(sum(t in _fold(row["summary"] + " " + row["project"]) for t in terms), row) for row in rows]
        rows = [row for score, row in sorted(ranked, key=lambda pair: pair[0], reverse=True) if score > 0]
    return rows[:max(1, min(int(limit), 200))]


def next_briefing() -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM episodes WHERE briefed_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        # Older unannounced summaries are historical context, not a backlog of greetings.
        db.execute("UPDATE episodes SET briefed_at=? WHERE briefed_at IS NULL", (_now(),))
        return {"id": row["id"], "date": row["created_at"][:10], "summary": row["summary"], "language": row["language"]}


def delete_episode(identifier: str) -> bool:
    with _connect() as db:
        return db.execute("DELETE FROM episodes WHERE id=?", (identifier,)).rowcount > 0


def task_context(limit=6) -> str:
    rows = list_tasks(limit=limit)
    if not rows:
        return ""
    return "[PENDING TASKS — use manage_tasks to inspect or update]\n" + "\n".join(
        f"{r['id']}: {r['title']} [{r['status']}, {r['priority']}" + (f", due {r['due']}" if r['due'] else "") + "]" for r in rows)
