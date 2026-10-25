"""Model-specific Gemini Live wire configuration, shared by all Live callers.

3.8 Live always enables proactive audio and manages its own reasoning. JARVIS
executes tools sequentially, so opt into the supported blocking tool mode.
https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live
"""
from copy import deepcopy

DEFAULT_LIVE_MODEL = "models/gemini-3.8-live"
LEGACY_LIVE_MODEL = "models/gemini-3.1-flash-live-preview"


def is_live_38(model: str) -> bool:
    return model.removeprefix("models/") == "gemini-3.8-live"


def api_version(model: str, enhanced: bool = False) -> str:
    return "v1beta" if is_live_38(model) or not enhanced else "v1alpha"


def prepare_config(settings: dict, model: str) -> dict:
    """Return a separate config; never mutate registries or saved preferences."""
    result = deepcopy(settings)
    if not is_live_38(model):
        return result
    for field in ("thinking_config", "thinkingConfig", "enable_affective_dialog",
                  "enableAffectiveDialog", "proactivity"):
        result.pop(field, None)
    realtime = result.get("realtime_input_config") or {}
    if hasattr(realtime, "model_dump"):
        realtime = realtime.model_dump(exclude_none=True)
    realtime["activity_handling"] = "START_OF_ACTIVITY_INTERRUPTS"
    activity = realtime.get("automatic_activity_detection") or {}
    activity["disabled"] = False
    activity["start_of_speech_sensitivity"] = "START_SENSITIVITY_LOW"
    activity["end_of_speech_sensitivity"] = "END_SENSITIVITY_LOW"
    activity.setdefault("silence_duration_ms", 600)
    activity["prefix_padding_ms"] = max(240, activity.get("prefix_padding_ms") or 0)
    realtime["automatic_activity_detection"] = activity
    result["realtime_input_config"] = realtime
    for tool in result.get("tools", []):
        declarations = (tool.get("function_declarations", []) if isinstance(tool, dict)
                        else getattr(tool, "function_declarations", None)) or []
        for declaration in declarations:
            if isinstance(declaration, dict):
                declaration["behavior"] = "BLOCKING"
            else:
                declaration.behavior = "BLOCKING"
    return result
