"""Exercise the original provider checks using their isolated mock services."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class ProviderRegressionTests(unittest.TestCase):
    def test_actual_main_dispatch_and_prompt_without_connecting(self):
        code = '''
import asyncio
from unittest import mock
from types import SimpleNamespace
import main
from memory import config_manager as config, memory_manager as memory, state_store as store

class UI:
    muted = False
    current_file = None
    def write_log(self, message): pass
    def set_state(self, state): pass

agent = main.JarvisLive(UI())
task = store.create_task("Preparar informe de prueba")
configuration = agent._build_config()
names = {d.name for tool in configuration.tools for d in tool.function_declarations}
assert {"manage_tasks", "manage_memory"}.issubset(names), names
assert task["title"] in configuration.system_instruction

async def exercise():
    call = main.types.FunctionCall(id="test-call", name="manage_tasks", args={"action":"complete", "id": task["id"]})
    response = await agent._execute_tool(call)
    assert "status=done" in response.response["result"]
    assert store.get_task(task["id"])["status"] == "completed"
    agent._session_log = ["User: Decidimos preparar el informe", "JARVIS: De acuerdo", "User: Continuamos mañana"]
    with mock.patch("core.gemini.text", return_value=""):
        await agent._save_session_summary()
    assert len(agent._session_log) == 3
    with mock.patch("core.gemini.text", return_value="Se acordó preparar el informe y continuar mañana."):
        await agent._save_session_summary()
    assert not agent._session_log
    assert store.list_episodes()
asyncio.run(exercise())
config.save_providers(mode="pipeline", pipeline={"llm":""})
try:
    agent._resolve_engine_caps()
except RuntimeError as exc:
    assert "cloud fallback is disabled" in str(exc)
else:
    raise AssertionError("An unavailable pipeline must not silently switch to Gemini")
print("main integration OK; no session was opened")
'''
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-main-test-") as folder:
            environment = dict(os.environ, JARVIS_DATA_DIR=folder, QT_QPA_PLATFORM="offscreen")
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root, env=environment,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_provider_suite(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([sys.executable, "-B", "-m", "providers._tests"], cwd=root,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        artifacts = root / ".local-backups" / "validation"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "providers.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-8000:])


if __name__ == "__main__":
    unittest.main()
