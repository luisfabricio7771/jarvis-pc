"""Smoke-check the preview entry point without accessing real personal data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def test_preview_opens_without_a_provider_or_configuration(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-preview-test-") as folder:
            environment = dict(os.environ, JARVIS_DATA_DIR=folder, QT_QPA_PLATFORM="offscreen")
            result = subprocess.run([sys.executable, "-B", "preview.py", "--smoke-test"], cwd=root,
                                    env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((Path(folder) / "config" / "api_keys.json").exists())

    def test_local_launchers_are_windows_gui_executables(self):
        if sys.platform != "win32":
            self.skipTest("Local Windows launchers")
        root = Path(__file__).resolve().parent.parent
        for filename in ("Jarvis.exe", "Ver memoria.exe", "Configurar IA.exe"):
            path = root / filename
            if not path.exists():
                self.skipTest("Build the optional launchers with launcher/build.ps1")
            binary = path.read_bytes()
            self.assertEqual(binary[:2], b"MZ")
            pe_offset = int.from_bytes(binary[60:64], "little")
            self.assertEqual(binary[pe_offset:pe_offset+4], b"PE\x00\x00")
            # IMAGE_SUBSYSTEM_WINDOWS_GUI, so starting it does not open a console.
            self.assertEqual(int.from_bytes(binary[pe_offset+24+68:pe_offset+24+70], "little"), 2)

    def test_provider_settings_preview_opens_without_a_key(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-provider-preview-") as folder:
            environment = dict(os.environ, JARVIS_DATA_DIR=folder, QT_QPA_PLATFORM="offscreen")
            result = subprocess.run([sys.executable, "-B", "preview.py", "--providers", "--smoke-test"], cwd=root,
                                    env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((Path(folder) / "config" / "api_keys.json").exists())


if __name__ == "__main__":
    unittest.main()
