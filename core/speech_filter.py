"""Local Silero speech gate for 16 kHz PCM. No downloads, recordings or APIs.

The ONNX model ships with faster-whisper. Per-stream recurrent state and a short
pre-roll distinguish sustained voice from loud clicks without clipping onset.
"""
from collections import deque
import threading

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512  # 32 ms, the bundled Silero v6 model's native frame.


class SpeechProbability:
    def __init__(self):
        from faster_whisper.vad import get_vad_model
        self._session = get_vad_model().session
        self.reset()

    def reset(self):
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros_like(self._h)
        self._context = np.zeros(64, dtype=np.float32)

    def scores(self, audio):
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(audio) or len(audio) % FRAME:
            raise ValueError("Speech detector expects complete 512-sample frames")
        windows = audio.reshape(-1, FRAME)
        contexts = np.concatenate([self._context[None, :], windows[:-1, -64:]], axis=0)
        inputs = np.concatenate([contexts, windows], axis=1)
        output, self._h, self._c = self._session.run(None, {"input": inputs, "h": self._h, "c": self._c})
        self._context = windows[-1, -64:].copy()
        return np.asarray(output).reshape(-1)


def contains_speech(audio):
    """Independent speech check for wake windows before attempting recognition."""
    from faster_whisper.vad import get_vad_model
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(audio) < FRAME * 4:
        return False
    padded = np.pad(audio, (0, (-len(audio)) % FRAME))
    probabilities = np.asarray(get_vad_model()(padded)).reshape(-1)
    return int(np.count_nonzero(probabilities >= 0.60)) >= 4


class SpeechFilter:
    def __init__(self, classifier=None):
        self._classifier = classifier if classifier is not None else SpeechProbability()
        self._lock = threading.RLock()
        self._reset_requested = threading.Event()
        self.reset()

    def reset(self):
        with self._lock:
            self._classifier.reset()
            self._pending = np.empty(0, dtype=np.int16)
            self._prefix = deque(maxlen=9)  # 288 ms, includes the first syllable.
            self._votes = deque(maxlen=8)
            self._strong = deque(maxlen=5)
            self._open = False
            self._quiet = 0
            self._reset_requested.clear()

    def request_reset(self):
        """Nonblocking mute/standby request, safe on the microphone callback."""
        self._reset_requested.set()

    def process(self, data):
        if len(data) % 2:
            raise ValueError("Microphone PCM must be 16-bit mono")
        with self._lock:
            if self._reset_requested.is_set():
                self.reset()
            samples = np.concatenate([self._pending, np.frombuffer(data, dtype=np.int16)])
            count = len(samples) // FRAME
            self._pending = samples[count * FRAME:].copy()
            if not count:
                return b""
            frames = samples[:count * FRAME].reshape(-1, FRAME)
            scores = self._classifier.scores(frames.reshape(-1).astype(np.float32) / 32768)
            result = bytearray()
            silence = b"\0" * (FRAME * 2)
            for frame, probability in zip(frames, scores, strict=True):
                pcm = frame.tobytes()
                rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2)))
                voiced = probability >= 0.70 and rms >= 0.002
                if not self._open:
                    self._prefix.append(pcm)
                    self._votes.append(voiced)
                    self._strong.append(probability >= 0.90 and rms >= 0.002)
                    # Clear voice can start in 96 ms; uncertain voice needs
                    # 160 ms. A single high-scoring click never opens the gate.
                    if voiced and (sum(self._votes) >= 5 or sum(self._strong) >= 3):
                        self._open = True
                        self._quiet = 0
                        result.extend(b"".join(self._prefix))
                        self._prefix.clear()
                    else:
                        result.extend(silence)
                else:
                    self._quiet = 0 if probability >= 0.35 and rms >= 0.002 else self._quiet + 1
                    if self._quiet >= 12:  # 384 ms hangover preserves natural pauses.
                        self._open = False
                        self._votes.clear()
                        self._strong.clear()
                        self._prefix.clear()
                        result.extend(silence)
                    else:
                        result.extend(pcm)
            if self._reset_requested.is_set():
                self.reset()
                return b""
            return bytes(result)
