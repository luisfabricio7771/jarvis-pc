"""Gemini 3.8 protocol regression tests; no network, microphone or personal data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from google.genai import types
from core.live_config import DEFAULT_LIVE_MODEL, LEGACY_LIVE_MODEL, api_version, prepare_config


class LiveConfigTests(unittest.TestCase):
    def test_primary_model_and_legacy_fallback(self):
        from core import gemini
        with mock.patch.dict(gemini._cooldown, {}, clear=True):
            self.assertEqual(gemini.live_model(), DEFAULT_LIVE_MODEL)
            gemini.note_live_failure(DEFAULT_LIVE_MODEL, "429 RESOURCE_EXHAUSTED")
            self.assertEqual(gemini.live_model(), LEGACY_LIVE_MODEL)
        self.assertEqual(DEFAULT_LIVE_MODEL, "models/gemini-3.8-live")

    def test_new_model_omits_incompatible_fields_and_blocks_tools(self):
        source = {"response_modalities": ["AUDIO"], "output_audio_transcription": {},
                  "thinking_config": {"thinking_budget": -1}, "enable_affective_dialog": True,
                  "proactivity": {"proactive_audio": False},
                  "tools": [{"function_declarations": [{"name": "test_tool", "description": "Test"}]}]}
        result = prepare_config(source, DEFAULT_LIVE_MODEL)
        self.assertNotIn("thinking_config", result)
        self.assertNotIn("enable_affective_dialog", result)
        self.assertNotIn("proactivity", result)
        self.assertEqual(result["tools"][0]["function_declarations"][0]["behavior"], "BLOCKING")
        self.assertNotIn("behavior", source["tools"][0]["function_declarations"][0])
        self.assertFalse(source["proactivity"]["proactive_audio"])
        parsed = types.LiveConnectConfig(**result)
        self.assertEqual(parsed.tools[0].function_declarations[0].behavior, types.Behavior.BLOCKING)
        self.assertEqual(parsed.realtime_input_config.activity_handling, types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS)
        self.assertFalse(parsed.realtime_input_config.automatic_activity_detection.disabled)
        self.assertEqual(parsed.realtime_input_config.automatic_activity_detection.start_of_speech_sensitivity,
                         types.StartSensitivity.START_SENSITIVITY_LOW)
        self.assertGreaterEqual(parsed.realtime_input_config.automatic_activity_detection.prefix_padding_ms, 240)

    def test_legacy_config_is_preserved_and_copied(self):
        source = {"thinking_config": {"thinking_budget": -1}, "proactivity": {"proactive_audio": True}}
        result = prepare_config(source, LEGACY_LIVE_MODEL)
        self.assertEqual(result, source)
        self.assertIsNot(result, source)
        self.assertEqual(api_version(LEGACY_LIVE_MODEL, True), "v1alpha")
        self.assertEqual(api_version(DEFAULT_LIVE_MODEL, True), "v1beta")

    def test_sdk_tools_are_supported_without_mutating_the_registry(self):
        tool = types.Tool(function_declarations=[types.FunctionDeclaration(name="sample")])
        result = prepare_config({"tools": [tool]}, "gemini-3.8-live")
        self.assertEqual(result["tools"][0].function_declarations[0].behavior, "BLOCKING")
        self.assertIsNone(tool.function_declarations[0].behavior)

    def test_auxiliary_live_calls_follow_the_running_entry_point(self):
        from core import gemini
        with mock.patch.dict(sys.modules, {"__main__": SimpleNamespace(LIVE_MODEL=LEGACY_LIVE_MODEL),
                                           "main": SimpleNamespace(LIVE_MODEL=DEFAULT_LIVE_MODEL)}):
            self.assertEqual(gemini._live_model(), LEGACY_LIVE_MODEL)
        with mock.patch.dict(sys.modules, {"__main__": SimpleNamespace(), "main": SimpleNamespace()}):
            self.assertEqual(gemini._live_model(), DEFAULT_LIVE_MODEL)

    def test_actual_main_default_voice_and_multipart_tool_turn(self):
        code = '''
import asyncio
from unittest import mock
import main
from memory import config_manager as config

class UI:
    muted = False
    current_file = None
    def __init__(self): self.messages=[]
    def write_log(self, text): self.messages.append(text)
    def set_state(self, state): pass

ui=UI(); agent=main.JarvisLive(ui)
config.save_voice("default")
assert config.get_voice()=="default"
with mock.patch.object(main,"get_thinking_enabled",return_value=True), mock.patch.object(main,"get_proactive_audio_enabled",return_value=False):
    cfg=agent._build_config()
assert cfg.speech_config is None, "Model default must omit the named voice"
assert cfg.thinking_config is None
assert cfg.proactivity is None
assert all(d.behavior==main.types.Behavior.BLOCKING for t in cfg.tools for d in t.function_declarations)
assert all("behavior" not in d for d in main.TOOL_DECLARATIONS)
config.save_voice("Kore")
assert agent._build_config().speech_config.voice_config.prebuilt_voice_config.voice_name=="Kore"
config.save_voice("default")

class Session:
    def __init__(self): self.sent=[]; self.received=False
    async def receive(self):
        if self.received: raise asyncio.CancelledError()
        self.received=True
        yield main.types.LiveServerMessage(
            server_content=main.types.LiveServerContent(
                model_turn=main.types.Content(role="model", parts=[
                    main.types.Part(inline_data=main.types.Blob(mime_type="audio/pcm;rate=24000",data=b"\\x01\\x00"*1300)),
                    main.types.Part(inline_data=main.types.Blob(mime_type="audio/pcm;rate=24000",data=b"\\x02\\x00"*200))]),
                output_transcription=main.types.Transcription(text="Prueba local completada."), turn_complete=True),
            tool_call=main.types.LiveServerToolCall(function_calls=[main.types.FunctionCall(id="fixture",name="fixture_tool",args={})]),
            session_resumption_update=main.types.LiveServerSessionResumptionUpdate(resumable=True,new_handle="fixture-handle"))
    async def send_tool_response(self, **kwargs): self.sent.append(kwargs)

async def exercise():
    agent.session=Session();agent.audio_in_queue=asyncio.Queue();agent._turn_done_event=asyncio.Event()
    agent._execute_tool=mock.AsyncMock(return_value=main.types.FunctionResponse(id="fixture",name="fixture_tool",response={"ok":True}))
    agent._flush_pending_vision=mock.AsyncMock()
    try: await agent._receive_audio()
    except asyncio.CancelledError: pass
    audio=b"".join(agent.audio_in_queue.get_nowait() for _ in range(agent.audio_in_queue.qsize()))
    assert audio==b"\\x01\\x00"*1300+b"\\x02\\x00"*200, "All audio parts must reach playback"
    assert any("Prueba local completada." in line for line in ui.messages)
    assert len(agent.session.sent)==1
    assert agent._resume_handle=="fixture-handle" and agent._resume_model==main.LIVE_MODEL
asyncio.run(exercise())
print("Actual main: default/named voice, compatible setup, multipart audio, transcript, tool response and resumption OK")
'''
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-live-38-test-") as folder:
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
                                    env=dict(os.environ, JARVIS_DATA_DIR=folder, QT_QPA_PLATFORM="offscreen"),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_voice_catalog_worker_can_finish_after_the_panel_is_deleted(self):
        code = '''
from unittest import mock
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6 import sip
from providers import tts_system, tts_piper
from ui import ProvidersOverlay
app=QApplication([]); callbacks=[]
with mock.patch.object(tts_system,"prefetch",side_effect=callbacks.append), mock.patch.object(tts_piper,"prefetch",side_effect=callbacks.append):
    panel=ProvidersOverlay()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert sip.isdeleted(panel)
    assert callbacks
    for callback in callbacks:
        assert isinstance(callback.__self__,threading.Event)
        worker=threading.Thread(target=callback);worker.start();worker.join()
print("Voice catalog callbacks do not touch a deleted Qt panel")
'''
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-catalog-test-") as folder:
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
                                    env=dict(os.environ, JARVIS_DATA_DIR=folder, QT_QPA_PLATFORM="offscreen"),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
