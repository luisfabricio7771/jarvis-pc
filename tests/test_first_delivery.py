"""Offline regression tests. All personal data is redirected to temporary files.

Run: python -B -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# Configure paths before importing application modules. No real settings are read.
_suite = tempfile.TemporaryDirectory(prefix="jarvis-regression-")
os.environ["JARVIS_DATA_DIR"] = _suite.name
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from core import storage, confirm
from memory import config_manager as config
from memory import memory_manager as memory
from memory import state_store as state


class IsolatedData(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="jarvis-case-")
        self.root = Path(self.folder.name)
        self.patches = [
            mock.patch.dict(os.environ, JARVIS_DATA_DIR=str(self.root)),
            mock.patch.object(config, "CONFIG_DIR", self.root / "config"),
            mock.patch.object(config, "CONFIG_FILE", self.root / "config" / "api_keys.json"),
            mock.patch.object(memory, "MEMORY_PATH", self.root / "memory" / "long_term.json"),
            mock.patch.object(state, "DB_PATH", self.root / "assistant.db"),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(self.folder.cleanup)
        for patch in self.patches:
            self.addCleanup(patch.stop)


class SettingsTests(IsolatedData):
    def test_reconfigure_preserves_other_settings(self):
        config.save_providers(mode="pipeline", pipeline={"llm": "openai_compat"},
                              creds={"openai_compat": {"model": "local-model"}})
        config.save_assistant_config("JARVIS", "Usuario")
        config.save_voice("Kore")
        config.patch_config(gemini_api_key="", os_system="windows")
        self.assertEqual(config.get_voice(), "Kore")
        self.assertEqual(config.get_provider_mode(), "pipeline")
        self.assertEqual(config.get_provider_config("openai_compat")["model"], "local-model")
        self.assertEqual(config.get_user_name(), "Usuario")

    @unittest.skipUnless(sys.platform == "win32", "Native Windows credential protection")
    def test_credentials_round_trip_without_plaintext_on_disk(self):
        config.save_api_keys("test-gemini-secret-not-a-real-key")
        config.save_provider_config("openai_compat", {"api_key": "test-provider-secret"})
        raw = config.CONFIG_FILE.read_text(encoding="utf-8")
        self.assertNotIn("test-gemini-secret-not-a-real-key", raw)
        self.assertNotIn("test-provider-secret", raw)
        self.assertEqual(config.get_gemini_key(), "test-gemini-secret-not-a-real-key")
        self.assertEqual(config.get_provider_config("openai_compat")["api_key"], "test-provider-secret")

    @unittest.skipUnless(sys.platform == "win32", "Native Windows credential protection")
    def test_legacy_plaintext_migrates_on_next_save(self):
        storage.write_json(config.CONFIG_FILE, {"gemini_api_key": "legacy-test-secret", "voice_name": "Kore"})
        self.assertEqual(config.get_gemini_key(), "legacy-test-secret")
        config.save_brief_enabled(False)
        self.assertNotIn("legacy-test-secret", config.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(config.get_voice(), "Kore")

    def test_parallel_nested_setting_updates_are_not_lost(self):
        def update(index):
            config.save_provider_config("local", {f"field_{index}": index})
            config.save_plugin_config("example", {f"field_{index}": index})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(update, range(32)))
        self.assertEqual(len(config.get_provider_config("local")), 32)
        self.assertEqual(len(config.get_plugin_config("example")), 32)

    def test_corrupt_settings_are_preserved(self):
        config.CONFIG_FILE.parent.mkdir(parents=True)
        config.CONFIG_FILE.write_text("{broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            config.save_voice("Kore")
        self.assertEqual(config.CONFIG_FILE.read_text(encoding="utf-8"), "{broken")

    def test_failed_atomic_replace_preserves_previous_document(self):
        storage.write_json(config.CONFIG_FILE, {"voice_name": "Kore"})
        with mock.patch("core.storage.os.replace", side_effect=OSError("simulated interrupted save")):
            with self.assertRaises(OSError):
                config.save_voice("Puck")
        self.assertEqual(config.get_voice(), "Kore")
        self.assertFalse(list(config.CONFIG_FILE.parent.glob("*.tmp")))

    @unittest.skipUnless(sys.platform == "win32", "Windows file-sharing errors")
    def test_transient_windows_lock_retries_the_atomic_replace(self):
        storage.write_json(config.CONFIG_FILE, {"voice_name": "Kore"})
        original = os.replace
        locked = PermissionError("temporary scanner lock")
        locked.winerror = 32
        attempts = []
        def replace(source, destination):
            attempts.append(source)
            if len(attempts) == 1:
                raise locked
            return original(source, destination)
        with mock.patch("core.storage.os.replace", side_effect=replace), mock.patch("core.storage.time.sleep"):
            config.save_voice("Puck")
        self.assertEqual(config.get_voice(), "Puck")
        self.assertEqual(len(attempts), 2)

    def test_pipeline_does_not_require_gemini_key(self):
        config.save_providers(mode="pipeline", pipeline={"llm": "openai_compat"})
        self.assertTrue(config.is_configured())
        config.save_provider_mode("gemini")
        self.assertFalse(config.is_configured())


class MemoryTests(IsolatedData):
    def test_parallel_fact_updates_survive(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: memory.remember(f"fact_{n}", f"value_{n}"), range(40)))
        self.assertEqual(len(memory.load_memory()["notes"]), 40)

    def test_temporary_facts_expire_and_can_be_corrected(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        memory.remember("temporary", "old", expires_at=past)
        memory.remember("project", "version one", expires_at=future)
        self.assertNotIn("temporary", memory.load_memory()["notes"])
        memory.remember("project", "version two", expires_at=future)
        memory.update_memory({"notes": {"project": {"value": "version three"}}})
        self.assertEqual(memory.load_memory()["notes"]["project"]["expires_at"], future)
        memory.remember("project", "durable version")
        self.assertNotIn("expires_at", memory.load_memory()["notes"]["project"])
        memory.forget("project")
        self.assertNotIn("durable version", memory.search_memory("project"))

    def test_corrupt_memory_cannot_be_overwritten_by_defaults(self):
        memory.MEMORY_PATH.parent.mkdir(parents=True)
        memory.MEMORY_PATH.write_text("[invalid", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            memory.remember("new", "value")
        self.assertEqual(memory.MEMORY_PATH.read_text(encoding="utf-8"), "[invalid")

    def test_legacy_summaries_migrate_once_and_remain_after_briefing(self):
        storage.write_json(memory.MEMORY_PATH, {"notes": {"existing": {"value": "keep me"}},
            "sessions": [{"date": "2026-10-18", "summary": "Decisión: preparar el reporte de inventario.", "language": "Spanish"}]})
        self.assertIn("inventario", memory.pop_last_session()["summary"])
        self.assertIsNone(memory.pop_last_session())
        self.assertEqual(len(state.list_episodes()), 1)
        self.assertIn("inventario", memory.search_memory("inventario"))
        self.assertEqual(memory.load_memory()["notes"]["existing"]["value"], "keep me")
        state.delete_episode(state.list_episodes()[0]["id"])
        self.assertNotIn("history/", memory.search_memory("inventario"))

    def test_new_summaries_are_not_consumed_or_truncated_to_280_characters(self):
        summary = "Decisión importante sobre el proyecto. " * 20
        for index in range(5):
            memory.save_session_summary(f"{index}: {summary}", "Spanish")
        self.assertEqual(len(state.list_episodes()), 5)
        self.assertGreater(len(memory.pop_last_session()["summary"]), 280)
        self.assertEqual(len(state.list_episodes()), 5)
        self.assertIsNone(memory.pop_last_session())

    def test_recall_includes_facts_tasks_and_decisions_with_accents(self):
        memory.remember("reunion", "Preparar presupuesto de México")
        task = state.create_task("Revisar presupuesto", project="México")
        state.save_episode("Se aprobó el presupuesto de México", "Spanish")
        result = memory.search_memory("presupuesto")
        self.assertIn("notes/", result)
        self.assertIn("history/", result)
        self.assertIn(task["id"], result)
        self.assertIn("México", memory.search_memory("mexico"))


class TaskTests(IsolatedData):
    def test_tasks_survive_a_new_python_process(self):
        task = state.create_task("Entregar reporte", project="Ventas", priority="high", due="2026-10-25")
        state.update_task(task["id"], status="in_progress")
        code = "from memory.state_store import list_tasks; import json; print(json.dumps(list_tasks()))"
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                                encoding="utf-8", check=True, cwd=Path(__file__).resolve().parent.parent)
        restored = json.loads(result.stdout)
        self.assertEqual(restored[0]["id"], task["id"])
        self.assertEqual(restored[0]["status"], "in_progress")

    def test_priority_completion_and_exact_id_validation(self):
        state.create_task("Low", priority="low")
        urgent = state.create_task("Urgent", priority="urgent")
        self.assertEqual(state.list_tasks()[0]["id"], urgent["id"])
        state.update_task(urgent["id"], status="completed")
        self.assertNotIn(urgent["id"], [row["id"] for row in state.list_tasks()])
        self.assertEqual(state.get_task(urgent["id"])["status"], "completed")
        with self.assertRaises(ValueError):
            state.update_task("invented-id", status="completed")
        with self.assertRaises(ValueError):
            state.create_task("", priority="normal")
        with self.assertRaises(ValueError):
            state.create_task("No timezone", due="2026-10-25T10:00:00")

    def test_task_action_can_be_discovered_and_executed(self):
        from core.action_loader import _validate, ActionRegistry
        from actions import task_manager
        record = _validate(task_manager, "task_manager.py")
        self.assertTrue(record.valid, record.error)
        registry = ActionRegistry({record.name: record}, lambda message: None)
        result = registry.run("manage_tasks", {"action": "create", "title": "Revisar informe"})
        self.assertIn("status=done", result)
        identifier = state.list_tasks()[0]["id"]
        result = registry.run("manage_tasks", {"action": "complete", "id": identifier})
        self.assertIn("status=done", result)
        self.assertEqual(state.get_task(identifier)["status"], "completed")

    def test_confirmation_cannot_be_overwritten(self):
        with mock.patch.object(confirm, "_pending", None), mock.patch.object(confirm, "_show_cb", lambda *args: None):
            first = confirm.request("first", "First action", "", lambda: "first")
            second = confirm.request("second", "Second action", "", lambda: "second")
            self.assertIn("CONFIRMATION_PENDING", first)
            self.assertIn("existing", second)
            self.assertEqual(confirm.pending_title(), "First action")


class PathTests(IsolatedData):
    def test_generated_files_cannot_escape_the_project(self):
        from actions.dev_agent import _safe_project_path
        project = self.root / "project"
        project.mkdir()
        for proposed in ("../outside.py", "..\\outside.py", "C:\\outside.py", "/tmp/outside.py",
                         "\\\\server\\share\\outside.py", "file.py:stream", "CON.py", "bad. /file.py", ""):
            with self.subTest(path=proposed):
                with self.assertRaises(ValueError):
                    _safe_project_path(project, proposed)
        self.assertEqual(_safe_project_path(project, "utils/helpers.py"), project / "utils" / "helpers.py")


class DashboardTests(IsolatedData):
    def setUp(self):
        super().setUp()
        from dashboard import server
        self.server_module = server
        self.module_patch = mock.patch.object(server, "CONFIG_DIR", config.CONFIG_DIR)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        with mock.patch.object(server, "_local_ip", return_value="127.0.0.1"):
            self.server = server.DashboardServer()
        self.server._tokens.update(mine=time.time(), other=time.time())
        self.server._token_keys.update(mine="mine-code", other="other-code")

    def test_secure_startup_does_not_downgrade_or_change_firewall(self):
        with mock.patch.object(self.server_module, "_ensure_certs", return_value=False), \
             mock.patch.object(self.server_module, "_ensure_network_access") as firewall, \
             mock.patch.object(self.server_module.uvicorn.Server, "serve", new_callable=mock.AsyncMock) as serve:
            asyncio.run(self.server.serve())
            self.assertIn("TLS", self.server._bind_error)
            firewall.assert_not_called()
            serve.assert_not_awaited()

    def test_explicit_http_is_loopback_only(self):
        config.patch_config(dashboard_https=False)
        self.assertEqual(self.server.get_url(), "http://127.0.0.1:8000")
        self.assertEqual(self.server.get_manual_url(), "127.0.0.1:8000")

    def test_revocation_closes_open_command_and_audio_sockets(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        with TestClient(self.server.app) as client:
            with client.websocket_connect("/ws?token=other") as command:
                with client.websocket_connect("/ws/phone-audio?token=other") as audio:
                    response = client.post("/api/revoke-devices", headers={"Authorization": "Bearer mine"})
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(self.server.valid_token("other"))
                    self.assertTrue(self.server.valid_token("mine"))
                    with self.assertRaises(WebSocketDisconnect):
                        while True:
                            command.receive_json()
                    with self.assertRaises(WebSocketDisconnect):
                        audio.receive_bytes()

    def test_expired_socket_cannot_send_another_command(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        with TestClient(self.server.app) as client:
            with client.websocket_connect("/ws?token=other") as connection:
                self.server._tokens["other"] = time.time() - self.server_module._TOKEN_TTL_SECONDS - 1
                connection.send_json({"type": "command", "text": "must not execute"})
                with self.assertRaises(WebSocketDisconnect):
                    connection.receive_json()
        self.assertTrue(self.server._command_queue.empty())

    def test_queued_commands_retain_auth_and_queue_is_bounded(self):
        from fastapi.testclient import TestClient
        with TestClient(self.server.app) as client:
            headers = {"Authorization": "Bearer other"}
            self.assertEqual(client.post("/api/command", json={"text": "status"}, headers=headers).status_code, 200)
            envelope = self.server._command_queue.get_nowait()
            self.assertEqual(envelope, {"text": "status", "token": "other"})
            for index in range(200):
                self.server._command_queue.put_nowait(envelope)
            self.assertEqual(client.post("/api/command", json={"text": "extra"}, headers=headers).status_code, 429)


class PanelTests(IsolatedData):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from PyQt6.QtGui import QFont, QFontDatabase
        for name in ("segoeui.ttf", "cour.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        cls.app.setFont(QFont("Segoe UI", 9))

    def test_setup_method_preserves_configuration(self):
        import ui
        config.save_providers(mode="pipeline", pipeline={"llm": "local"})
        config.save_voice("Kore")
        dummy = type("Window", (), {})()
        dummy._overlay = None
        dummy._log = type("Log", (), {"append_log": lambda *args: None})()
        dummy._check_config = config.is_configured
        dummy._apply_state = lambda state: None
        # The real setup method is exercised with an API key on Windows.
        if sys.platform == "win32":
            ui.MainWindow._on_setup_done(dummy, "test-setup-key", "windows")
            self.assertEqual(config.get_voice(), "Kore")
            self.assertEqual(config.get_pipeline()["llm"], "local")

    def test_local_first_boot_button_needs_no_gemini_key(self):
        import ui
        from PyQt6.QtWidgets import QPushButton
        overlay = ui.SetupOverlay()
        seen = []
        overlay.done.connect(lambda key, system: seen.append((key, system)))
        button = next(b for b in overlay.findChildren(QPushButton) if "MOTOR LOCAL" in b.text())
        button.click()
        self.assertEqual(seen[0][0], "")
        overlay.deleteLater()
        self.app.processEvents()

    def test_changing_the_active_model_requests_reconnection(self):
        import ui
        config.save_providers(mode="pipeline", pipeline={"llm": "openai_compat", "stt": "", "tts": ""},
                              creds={"openai_compat": {"base_url": "http://127.0.0.1:11434/v1", "model": "old-local-model", "catalog": "ollama"}})
        overlay = ui.ProvidersOverlay()
        events = []
        overlay.changed.connect(lambda: events.append("changed"))
        overlay._edits["openai_compat"]["model"][0].setCurrentText("new-local-model")
        overlay._apply()
        self.assertEqual(config.get_provider_config("openai_compat")["model"], "new-local-model")
        self.assertEqual(events, ["changed"])
        overlay.deleteLater()
        self.app.processEvents()

    def test_memory_panel_all_three_views_render(self):
        import ui
        from PyQt6.QtWidgets import QLabel
        memory.remember("preferencia", "<b>Texto literal</b>")
        state.create_task("Preparar reporte", project="Personal")
        state.save_episode("Se acordó entregar el reporte el viernes.", "Spanish")
        overlay = ui.MemoryOverlay()
        overlay.show()
        for page, expected in (("facts", "Texto literal"), ("tasks", "Preparar reporte"), ("history", "Se acordó")):
            overlay._page = page
            overlay._rebuild()
            self.app.processEvents()
            self.assertTrue(any(expected in label.text() for label in overlay.findChildren(QLabel)))
            self.assertLessEqual(overlay.height(), 650)
            artifacts = Path(__file__).resolve().parent.parent / ".local-backups" / "validation"
            artifacts.mkdir(parents=True, exist_ok=True)
            self.assertTrue(overlay.grab().save(str(artifacts / f"memory-{page}.png")))
        overlay.close()
        overlay.deleteLater()
        self.app.processEvents()

    def test_responses_settings_render_and_save_without_changing_voice_mode(self):
        import ui
        from PyQt6.QtWidgets import QLabel
        config.save_providers(mode="gemini", sidecar="openai_responses", creds={"openai_responses": {
            "api_key": "fake-panel-key", "model": "test-model", "routing": "openai"}})
        overlay = ui.ProvidersOverlay()
        overlay.show()
        self.app.processEvents()
        self.assertIn("openai_responses", overlay._edits)
        self.assertFalse(overlay._first_combo.isEnabled())
        self.assertTrue(any("Hoy (UTC)" in label.text() for label in overlay.findChildren(QLabel)))
        overlay._edits["openai_responses"]["daily_requests"][0].setText("7")
        artifacts = Path(__file__).resolve().parent.parent / ".local-backups" / "validation"
        artifacts.mkdir(parents=True, exist_ok=True)
        overlay._scroll.verticalScrollBar().setValue(0)
        self.app.processEvents()
        self.assertTrue(overlay.grab().save(str(artifacts / "responses-settings.png")))
        overlay._scroll.verticalScrollBar().setValue(overlay._scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(overlay.grab().save(str(artifacts / "responses-limits.png")))
        overlay._apply()
        self.assertEqual(config.get_provider_mode(), "gemini")
        self.assertEqual(config.get_provider_config("openai_responses")["daily_requests"], "7")
        overlay.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
