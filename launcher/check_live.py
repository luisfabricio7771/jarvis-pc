"""Opt-in, bounded Gemini 3.8 Live smoke test with synthetic content only.

Run from the project root: python -B launcher/check_live.py --live
Uses the configured key; no personal memory, microphone, camera or OS tools.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def app_settings() -> dict:
    """Build the real application setup against an empty temporary profile."""
    import os
    import tempfile
    from unittest import mock
    from memory import config_manager

    class UI:
        muted = False
        current_file = None
        def write_log(self, text): pass
        def set_state(self, state): pass

    with tempfile.TemporaryDirectory(prefix="jarvis-live-setup-") as directory:
        with mock.patch.dict(os.environ, JARVIS_DATA_DIR=directory), \
             mock.patch.object(config_manager, "CONFIG_DIR", Path(directory) / "config"), \
             mock.patch.object(config_manager, "CONFIG_FILE", Path(directory) / "config" / "api_keys.json"):
            import main
            return main.JarvisLive(UI())._build_config().model_dump(exclude_none=True)


async def check(full_app: bool = False) -> None:
    from google import genai
    from google.genai import types
    from core.live_config import DEFAULT_LIVE_MODEL, prepare_config
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No hay una clave Gemini configurada en JARVIS.")
    settings = prepare_config({
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "session_resumption": {},
        "context_window_compression": {"sliding_window": {}},
        "system_instruction": "Responde brevemente en español. Es una prueba con datos ficticios. "
                              "Consulta test_status cuando el usuario pida verificar la prueba.",
        "tools": [{"function_declarations": [{
            "name": "test_status", "description": "Devuelve el estado ficticio de esta prueba, sin acceder al equipo.",
            "parameters": {"type": "OBJECT", "properties": {}}
        }]}],
    }, DEFAULT_LIVE_MODEL)
    if full_app:
        fixture = settings
        settings = app_settings()
        # Use the full tool schemas and tuning, with a synthetic prompt only.
        settings["system_instruction"] = fixture["system_instruction"]
        settings["tools"] += fixture["tools"]
    assert "speech_config" not in settings
    received = {"model": DEFAULT_LIVE_MODEL, "modelDefaultVoice": True,
                "audioBytes": 0, "transcriptCharacters": 0, "toolResponses": 0,
                "fullApplicationConfig": full_app}
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    try:
        async with asyncio.timeout(45):
            async with client.aio.live.connect(model=DEFAULT_LIVE_MODEL, config=settings) as session:
                await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(
                    text="Verifica la prueba usando test_status y di brevemente el resultado en español.")]), turn_complete=True)
                completed = False
                while not completed:
                    async for message in session.receive():
                        received["audioBytes"] += len(message.data or b"")
                        content = message.server_content
                        if content and content.output_transcription:
                            received["transcriptCharacters"] += len(content.output_transcription.text or "")
                        if message.tool_call:
                            responses = []
                            for call in message.tool_call.function_calls:
                                if call.name != "test_status" or received["toolResponses"] >= 2:
                                    raise RuntimeError("La prueba superó su límite de herramientas ficticias.")
                                responses.append(types.FunctionResponse(id=call.id, name=call.name,
                                                                         response={"status": "prueba completada"}))
                                received["toolResponses"] += 1
                            await session.send_tool_response(function_responses=responses)
                        if content and content.turn_complete and received["toolResponses"]:
                            completed = True
                if not received["audioBytes"] or not received["transcriptCharacters"]:
                    raise RuntimeError("La sesión no devolvió audio y transcripción completos.")
        print(json.dumps(received))
    except Exception as error:
        # Some WebSocket errors include the URI; never expose the configured key.
        detail = str(error).replace(key, "[redacted]")[:500]
        raise RuntimeError(f"Prueba Live fallida ({type(error).__name__}): {detail}") from None
    finally:
        await client.aio.aclose()
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Autoriza una sesión corta en la API Gemini configurada.")
    parser.add_argument("--app-config", action="store_true", help="Comprueba también los esquemas y ajustes reales con perfil vacío.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Añade --live para ejecutar la prueba real; sin ese indicador no se usa la API.")
    try:
        asyncio.run(check(args.app_config))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
