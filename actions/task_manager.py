"""Persistent personal tasks exposed through the existing action loader."""
import json

from core import confirm, outcome
from core.undo import push_undo
from memory import state_store as store


def _render(task):
    return outcome.untrusted("tasks", json.dumps(task, ensure_ascii=False))


def task_manager(parameters=None, **_) -> str:
    params = parameters or {}
    action = params.get("action", "list")
    identifier = str(params.get("id") or "").strip()
    try:
        if action == "list":
            rows = store.list_tasks(status=params.get("status", "active"),
                                    project=params.get("project", ""), query=params.get("query", ""))
            return outcome.done("list_tasks", count=len(rows)) + "\n" + _render(rows)
        if action == "create":
            row = store.create_task(**{key: params[key] for key in ("title", "notes", "project", "priority", "due") if key in params})
            push_undo(f"created task {row['title']}", lambda: str(store.delete_task(row["id"])))
            return outcome.done("create_task", id=row["id"]) + "\n" + _render(row)
        previous = store.get_task(identifier)
        if previous is None:
            return outcome.failed("manage_tasks", "Task not found; list tasks to retrieve the exact id")
        if action == "get":
            return outcome.done("get_task", id=identifier) + "\n" + _render(previous)
        if action == "delete":
            return confirm.request("delete-task", "Eliminar pendiente", previous["title"],
                                   lambda: outcome.done("delete_task", deleted=store.delete_task(identifier)))
        if action in ("update", "complete", "reopen", "cancel"):
            changes = {key: params[key] for key in ("title", "notes", "project", "priority", "due", "status") if key in params}
            if action != "update":
                changes["status"] = {"complete": "completed", "reopen": "pending", "cancel": "cancelled"}[action]
            if not changes:
                raise ValueError("Specify a field to update")
            row = store.update_task(identifier, **changes)
            old = {key: previous[key] for key in ("title", "notes", "project", "priority", "due", "status")}
            push_undo(f"updated task {row['title']}", lambda: str(store.update_task(identifier, **old)))
            return outcome.done("update_task", id=identifier) + "\n" + _render(row)
        return outcome.failed("manage_tasks", "Unknown action")
    except (ValueError, TypeError) as exc:
        return outcome.failed("manage_tasks", str(exc))


TOOL = {
    "name": "manage_tasks", "tier": "core",
    "description": "Manage persistent personal tasks: create, list, get, update, complete, reopen, cancel or delete. Save an agreed next step immediately. Tasks survive app restarts. Use exact ids from list/get. Due dates are not alarms; use reminder separately for notifications. Deleting requires the user's HUD confirmation.",
    "brief": "Create, list and update persistent tasks and project progress; exact ids come from list. Due dates do not schedule alarms.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["create", "list", "get", "update", "complete", "reopen", "cancel", "delete"]},
        "id": {"type": "STRING", "description": "Exact task id from list/get"},
        "title": {"type": "STRING"}, "notes": {"type": "STRING"},
        "project": {"type": "STRING"}, "query": {"type": "STRING"},
        "status": {"type": "STRING", "enum": [*store.STATUSES, "active", "all"]},
        "priority": {"type": "STRING", "enum": list(store.PRIORITIES)},
        "due": {"type": "STRING", "description": "YYYY-MM-DD, ISO datetime WITH UTC offset, or empty to clear"},
    }, "required": ["action"]}, "handler": task_manager,
}
