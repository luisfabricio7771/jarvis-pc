"""Open memory or provider settings without microphone, camera or AI sessions."""
from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    from ui import MemoryOverlay, ProvidersOverlay

    application = QApplication.instance() or QApplication([sys.argv[0]])
    providers = "--providers" in sys.argv[1:]
    title = "JARVIS — Configurar IA" if providers else "JARVIS — Memoria y pendientes"
    application.setApplicationName(title)
    application.setStyle("Fusion")
    application.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "config" / "jarvis.ico")))
    panel = ProvidersOverlay() if providers else MemoryOverlay()
    panel.setWindowTitle(title)
    panel.show()
    if "--smoke-test" in sys.argv[1:]:
        QTimer.singleShot(300, application.quit)
    return application.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if "--smoke-test" in sys.argv[1:]:
            raise
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"No se pudo abrir el panel: {exc}", "JARVIS", 0x10)
        else:
            raise
