"""Local, Spanish-capable activation on the word JARVIS. No hosted ASR.

Only speech windows are decoded, on a worker with two CPU threads. A bounded
queue keeps the audio callback cheap. Neither recordings nor transcripts are
saved. Whisper tiny is downloaded once, never while listening.
"""
from __future__ import annotations

from collections import deque
import atexit
import importlib.util
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata

import numpy as np

WAKE_PHRASE = "JARVIS"
WAKE_MODEL = "tiny"
SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.5  # Kept for compatibility with the detector constructor.
_BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
MODEL_DIR = _BASE / ".local-models" / "wake-whisper-tiny"


def matches_keyword(text: str) -> bool:
    text = unicodedata.normalize("NFKD", text).casefold()
    words = re.findall(r"[a-z]+", "".join(c for c in text if not unicodedata.combining(c)))
    return "jarvis" in words


def is_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def is_ready() -> bool:
    return is_installed() and all((MODEL_DIR / name).is_file() for name in
                                 ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"))


def install_and_download(logger=print, notify=None) -> tuple[bool, str]:
    tell = notify or (lambda text: None)
    try:
        if not is_installed():
            tell("Instalando reconocimiento local para JARVIS…")
            result = subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper>=1.2.1,<2"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=600)
            if result.returncode:
                return False, "No se pudo instalar el reconocimiento local. Revisa la conexión y vuelve a intentarlo."
        if not is_ready():
            tell("Descargando el modelo local de activación (aprox. 78 MB)…")
            from faster_whisper.utils import download_model
            download_model(WAKE_MODEL, output_dir=str(MODEL_DIR))
        if not is_ready():
            return False, "La descarga del detector de JARVIS no está completa."
        logger("Activación local JARVIS preparada.")
        return True, "Activación por JARVIS preparada."
    except Exception as error:
        logger(f"Wake setup failed: {type(error).__name__}")
        return False, "No se pudo preparar el modelo local. Revisa la conexión y vuelve a intentarlo."


class SpeechWindow:
    """Small energy gate; silence alone is never passed to Whisper."""
    def __init__(self):
        self.reset()

    def reset(self):
        self._prefix = deque(maxlen=4)
        self._parts = []
        self._size = self._silence = self._speech = 0

    def feed(self, frame):
        frame = np.asarray(frame, dtype=np.int16).reshape(-1)
        rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2))) if frame.size else 0
        voiced = rms >= 0.006
        if not self._parts:
            if not voiced:
                self._prefix.append(frame.copy())
                return None
            self._parts = list(self._prefix)
        self._parts.append(frame.copy())
        self._size += frame.size
        self._speech += frame.size if voiced else 0
        self._silence = 0 if voiced else self._silence + frame.size
        if self._silence < SAMPLE_RATE * 0.28 and self._size < SAMPLE_RATE * 2.5:
            return None
        enough = self._speech >= SAMPLE_RATE * 0.12
        audio = np.concatenate(self._parts).astype(np.float32) / 32768 if enough else None
        self.reset()
        return audio


class WakeWordDetector:
    def __init__(self, on_detect, threshold=DEFAULT_THRESHOLD, logger=print, notify=None):
        self._on_detect, self._logger = on_detect, logger
        self._notify = notify or (lambda text: None)
        self._queue = queue.Queue(maxsize=48)
        self._running = self._ready = False
        self._reset = threading.Event()
        self._model = None
        self._thread = None

    @property
    def ready(self):
        return self._ready

    def start(self):
        if self._running:
            return True
        try:
            if not is_ready():
                raise RuntimeError("Local wake model not installed")
            from faster_whisper import WhisperModel
            self._model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8",
                                       cpu_threads=2, local_files_only=True)
        except Exception as error:
            self._logger(f"Activación local no disponible ({type(error).__name__}).")
            self._notify("Detector de JARVIS no disponible. La escucha permanece en espera; revisa su descarga.")
            return False
        self._running = self._ready = True
        atexit.register(self.stop)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="JarvisWakeWord")
        self._thread.start()
        self._logger("Escucha local: di JARVIS para empezar.")
        return True

    def clear(self):
        self._reset.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._running = self._ready = False
        atexit.unregister(self.stop)
        self.clear()
        self._queue.put_nowait(None)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def feed(self, frame):
        if self._running:
            try:
                self._queue.put_nowait(np.asarray(frame, dtype=np.int16).reshape(-1).copy())
            except queue.Full:
                self.clear()  # Do not wake on an old, backlogged utterance.

    def recognizes(self, audio):
        from core.speech_filter import contains_speech
        if not contains_speech(audio):
            return False
        segments, _ = self._model.transcribe(audio, language="es", initial_prompt="Jarvis.",
                                             beam_size=3, temperature=0, condition_on_previous_text=False)
        return any(matches_keyword(segment.text) and segment.no_speech_prob < 0.7
                   and segment.avg_logprob > -1.5 for segment in segments)

    def _loop(self):
        window = SpeechWindow()
        last_detection = 0.0
        while self._running:
            frame = self._queue.get()
            if frame is None:
                break
            if self._reset.is_set():
                window.reset()
                self._reset.clear()
            audio = window.feed(frame)
            if audio is None or time.monotonic() - last_detection < 1.5:
                continue
            try:
                detected = self.recognizes(audio)
                # A mute/reset while inference was running invalidates its result.
                if detected and self._running and not self._reset.is_set():
                    last_detection = time.monotonic()
                    # Release only this speech window and the frames that came
                    # in during recognition, not earlier room conversations.
                    initial = [(audio * 32768).astype(np.int16)]
                    while True:
                        try:
                            pending = self._queue.get_nowait()
                            if pending is not None:
                                initial.append(pending)
                        except queue.Empty:
                            break
                    self.clear()
                    self._on_detect(np.concatenate(initial).tobytes())
            except Exception as error:
                self._logger(f"Wake inference: {type(error).__name__}")
