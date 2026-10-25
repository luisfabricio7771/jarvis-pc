"""Speech-only input filtering; artificial signals, no microphone or network."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import wave

import numpy as np
from core.speech_filter import FRAME, SpeechFilter, contains_speech


class Classifier:
    def __init__(self, probabilities):
        self.probabilities = probabilities
    def reset(self):
        self.index = 0
    def scores(self, audio):
        count = len(audio) // FRAME
        result = self.probabilities[self.index:self.index + count]
        self.index += count
        return result


def pcm_frame(level=5000):
    return np.full(FRAME, level, dtype=np.int16).tobytes()


class SpeechFilterTests(unittest.TestCase):
    def test_single_loud_click_cannot_open_the_gate(self):
        gate = SpeechFilter(Classifier([0.99] + [0.01] * 20))
        output = gate.process(pcm_frame(30000) + pcm_frame(0) * 20)
        self.assertFalse(any(output))
        gate = SpeechFilter(Classifier([0.99, 0.99] + [0.01] * 20))
        self.assertFalse(any(gate.process(pcm_frame(30000) * 2 + pcm_frame(0) * 20)))

    def test_sustained_noise_is_not_speech_even_when_loud(self):
        gate = SpeechFilter(Classifier([0.05] * 20))
        self.assertFalse(any(gate.process(pcm_frame(10000) * 20)))

    def test_speech_keeps_its_onset_and_pauses(self):
        gate = SpeechFilter(Classifier([0.95] * 10 + [0.1] * 5 + [0.95] * 10))
        first = b"".join(pcm_frame(1000 + i * 300) for i in range(10))
        output = b""
        for frame in (first, pcm_frame(0) * 5, pcm_frame(7000) * 10):
            output += gate.process(frame)
        self.assertIn(first, output)  # Early phonemes survive the onset decision.
        self.assertIn(pcm_frame(7000) * 10, output)

    def test_gate_closes_after_speech_and_filters_later_clicks(self):
        gate = SpeechFilter(Classifier([0.95] * 6 + [0.01] * 30 + [0.99] + [0.01] * 10))
        gate.process(pcm_frame() * 6)
        gate.process(pcm_frame(0) * 30)
        self.assertFalse(any(gate.process(pcm_frame(30000) + pcm_frame(0) * 10)))

    def test_mute_reset_discards_an_unfinished_voice_prefix(self):
        gate = SpeechFilter(Classifier([0.80] * 30))
        self.assertFalse(any(gate.process(pcm_frame() * 4)))
        gate.request_reset()
        self.assertFalse(any(gate.process(pcm_frame(0) * 10)))

    def test_reset_during_inference_discards_the_result(self):
        ready, release = threading.Event(), threading.Event()
        class BlockingClassifier(Classifier):
            def scores(self, audio):
                ready.set()
                release.wait(3)
                return super().scores(audio)
        gate = SpeechFilter(BlockingClassifier([0.99] * 20))
        results = []
        worker = threading.Thread(target=lambda: results.append(gate.process(pcm_frame() * 10)))
        worker.start()
        try:
            self.assertTrue(ready.wait(3))
            gate.request_reset()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(any(b"".join(results)))

    def test_partial_frames_are_buffered_and_malformed_pcm_is_rejected(self):
        gate = SpeechFilter(Classifier([0.01] * 20))
        self.assertEqual(gate.process(b"\0" * 256), b"")
        self.assertEqual(len(gate.process(b"\0" * 768)), 1024)
        with self.assertRaises(ValueError):
            gate.process(b"x")

    def test_real_model_rejects_noise_and_preserves_synthetic_spanish_voice(self):
        rng = np.random.default_rng(42)
        noise = (rng.normal(0, 0.06, 32000) * 32767).astype(np.int16)
        self.assertFalse(contains_speech(noise.astype(np.float32) / 32768))
        gate = SpeechFilter()
        self.assertFalse(any(gate.process(noise.tobytes())))
        fixture = Path(__file__).parent / "fixtures" / "jarvis-es.wav"
        with wave.open(str(fixture), "rb") as stream:
            voice = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16)
        voice = np.concatenate([np.zeros(4096, dtype=np.int16), voice, np.zeros(8192, dtype=np.int16)])
        self.assertTrue(contains_speech(voice.astype(np.float32) / 32768))
        gate.reset()
        filtered = b"".join(gate.process(voice[i:i+1024].tobytes()) for i in range(0, len(voice), 1024))
        self.assertTrue(any(filtered))

    def test_real_sender_filters_noise_and_updates_the_indicator_only_from_voice(self):
        code = '''
import asyncio,wave
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import main

class UI:
    muted=False
    current_file=None
    def __init__(self): self.levels=[]
    def write_log(self,text): pass
    def set_state(self,state): pass
    def set_audio_level(self,level): self.levels.append(level)

async def exercise():
    ui=UI();agent=main.JarvisLive(ui)
    agent._wake_enabled=False;agent._awake=True;agent.out_queue=asyncio.Queue()
    observed=[];noise_done=asyncio.Event();voice_done=asyncio.Event()
    async def send(audio):
        observed.append(audio.data)
        (voice_done if any(audio.data) else noise_done).set()
    agent.session=SimpleNamespace(send_realtime_input=send)
    sender=asyncio.create_task(agent._send_realtime())
    try:
        click=np.zeros(32000,dtype=np.int16);click[8000:8064]=30000
        agent.out_queue.put_nowait({'data':click.tobytes()})
        await asyncio.wait_for(noise_done.wait(),3)
        assert observed and not any(b''.join(observed))
        assert not any(ui.levels), 'Noise must not animate the mic indicator'
        with wave.open('tests/fixtures/jarvis-es.wav','rb') as w: pcm=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16)
        agent.out_queue.put_nowait({'data':pcm.tobytes()+b'\\0'*16384})
        await asyncio.wait_for(voice_done.wait(),3)
        assert any(ui.levels)
    finally:
        sender.cancel()
        try: await sender
        except asyncio.CancelledError: pass
    print('Sender and indicator: noise blocked; Spanish voice preserved')
asyncio.run(exercise())
'''
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-noise-test-") as directory:
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
                                    env=dict(os.environ, JARVIS_DATA_DIR=directory, QT_QPA_PLATFORM="offscreen"),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
