"""Inspect, correct or forget facts and selected historical decisions."""
import json

from core import confirm, outcome
from memory import memory_manager as memory
from memory import state_store as store


def memory_control(parameters=None, **_) -> str:
    params = parameters or {}
    action = params.get("action", "search")
    category = params.get("category", "notes")
    try:
        if action == "search":
            text = memory.search_memory(str(params.get("query") or ""))
        elif action == "list":
            text = json.dumps(memory.all_entries_for_ui(), ensure_ascii=False)
        elif action == "remember":
            text = memory.remember(params.get("key", ""), params.get("value", ""), category,
                                   source="user", expires_at=params.get("expires_at", ""))
        elif action == "forget":
            key = str(params.get("key") or "").strip()
            if not key:
                raise ValueError("Specify the exact memory key")
            return confirm.request("forget-memory", "Olvidar recuerdo", f"{category}/{key}",
                                   lambda: memory.forget(key, category))
        elif action == "save_episode":
            identifier = store.save_episode(params.get("value", ""), params.get("language", ""), params.get("project", ""))
            return outcome.done("save_episode", id=identifier)
        elif action == "history":
            memory._migrate_sessions()
            text = json.dumps(store.list_episodes(params.get("query", ""), params.get("project", "")), ensure_ascii=False)
        elif action == "delete_episode":
            identifier = str(params.get("id") or "").strip()
            if not identifier:
                raise ValueError("Specify the exact episode id")
            return confirm.request("forget-episode", "Eliminar resumen", identifier,
                                   lambda: outcome.done("delete_episode", deleted=store.delete_episode(identifier)))
        else:
            raise ValueError("Unknown memory action")
        return outcome.done("manage_memory") + "\n" + outcome.untrusted("memory", text)
    except (ValueError, TypeError) as exc:
        return outcome.failed("manage_memory", str(exc))


TOOL = {
    "name": "manage_memory", "tier": "core",
    "description": "Inspect, search, correct and forget persistent memories or selected conversation summaries. remember updates an existing category/key. Save only useful user-approved facts or agreed decisions/next steps, never passwords, API keys or full transcripts. Temporary facts need expires_at. Saving an episode persists it immediately; it is not necessary to wait for app shutdown. Forget/delete requires HUD confirmation.",
    "brief": "Inspect/correct/forget memories and save selected decisions as history. Never store secrets or entire conversations.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["search", "list", "remember", "forget", "save_episode", "history", "delete_episode"]},
        "category": {"type": "STRING", "enum": ["identity", "preferences", "projects", "relationships", "wishes", "notes"]},
        "key": {"type": "STRING"}, "value": {"type": "STRING"}, "query": {"type": "STRING"},
        "id": {"type": "STRING"}, "project": {"type": "STRING"}, "language": {"type": "STRING"},
        "expires_at": {"type": "STRING", "description": "ISO datetime WITH UTC offset for temporary facts; empty means durable"},
    }, "required": ["action"]}, "handler": memory_control,
}
