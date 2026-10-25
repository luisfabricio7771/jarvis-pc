"""Persistent request limits; stores counts and tokens, never request contents."""
from datetime import datetime, timezone
import uuid

from memory.state_store import _connect


class BudgetExceeded(RuntimeError):
    pass


def _day():
    return datetime.now(timezone.utc).date().isoformat()


def _schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        id TEXT PRIMARY KEY, day TEXT NOT NULL, provider TEXT NOT NULL,
        model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0)""")
    db.execute("CREATE INDEX IF NOT EXISTS api_usage_day ON api_usage(day,provider)")


def reserve(model: str, daily_limit: int) -> str:
    """Count attempts before sending, atomically across processes and models.

    Failed/cancelled attempts still count: their billable outcome can be unknown.
    A zero limit disables paid requests. The day boundary is UTC.
    """
    identifier, day = uuid.uuid4().hex, _day()
    with _connect() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT COUNT(*) FROM api_usage WHERE day=? AND provider='openai'", (day,)).fetchone()[0]
        if daily_limit <= 0 or count >= daily_limit:
            raise BudgetExceeded(f"OpenAI: límite diario alcanzado ({count}/{daily_limit}, día UTC). Ajusta el límite en proveedores.")
        db.execute("INSERT INTO api_usage (id,day,provider,model,status) VALUES (?,?,'openai',?,'pending')", (identifier, day, model))
    return identifier


def finish(identifier: str, status: str, usage=None):
    usage = usage or {}
    with _connect() as db:
        _schema(db)
        db.execute("UPDATE api_usage SET status=?,input_tokens=?,output_tokens=? WHERE id=?",
                   (status, max(0, int(usage.get('input_tokens') or 0)),
                    max(0, int(usage.get('output_tokens') or 0)), identifier))


def today() -> dict:
    with _connect() as db:
        _schema(db)
        row = db.execute("""SELECT COUNT(*) AS requests,
            COALESCE(SUM(input_tokens),0) AS input_tokens,
            COALESCE(SUM(output_tokens),0) AS output_tokens,
            COALESCE(SUM(status!='completed'),0) AS uncertain_requests
            FROM api_usage WHERE day=? AND provider='openai'""", (_day(),)).fetchone()
        return dict(row)
