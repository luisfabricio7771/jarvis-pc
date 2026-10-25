"""Natural turn-taking and local activation; no real microphone or API calls."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from core.keyword_wake import SpeechWindow, WakeWordDetector, matches_keyword


class ActivationTests(unittest.TestCase):
    def test_keyword_is_a_complete_word(self):
        for text in ("Jarvis", "JARVIS, ¿qué hora es?", "¡Jarvis!", "Hey Jarvis"):
            self.assertTrue(matches_keyword(text))
        for text in ("Javier", "ya ves", "jarvista", "hola", "gracias", ""):
            self.assertFalse(matches_keyword(text))

    def test_silence_and_short_clicks_are_not_transcribed(self):
        window = SpeechWindow()
        for _ in range(100):
            self.assertIsNone(window.feed(np.zeros(1024, dtype=np.int16)))
        self.assertIsNone(window.feed(np.ones(1024, dtype=np.int16) * 9000))
        for _ in range(10):
            self.assertIsNone(window.feed(np.zeros(1024, dtype=np.int16)))

    def test_speech_is_bounded_and_includes_its_beginning(self):
        window = SpeechWindow()
        for _ in range(4):
            self.assertIsNone(window.feed(np.ones(1024, dtype=np.int16) * 3000))
        result = None
        for _ in range(5):
            result = window.feed(np.zeros(1024, dtype=np.int16))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(float(result[0]), 3000 / 32768)
        window = SpeechWindow()
        windows = [window.feed(np.ones(1024, dtype=np.int16) * 3000) for _ in range(41)]
        self.assertEqual(sum(item is not None for item in windows), 1)

    def test_reset_during_recognition_does_not_wake_later(self):
        found, processing, release = [], threading.Event(), threading.Event()
        detector = WakeWordDetector(found.append)
        def recognize(audio):
            processing.set()
            release.wait(3)
            return True
        detector.recognizes = recognize
        detector._running = detector._ready = True
        detector._thread = threading.Thread(target=detector._loop, daemon=True)
        detector._thread.start()
        try:
            for _ in range(5): detector.feed(np.ones(1024, dtype=np.int16) * 5000)
            for _ in range(5): detector.feed(np.zeros(1024, dtype=np.int16))
            self.assertTrue(processing.wait(3))
            detector.clear()
            release.set()
        finally:
            detector.stop()
        self.assertFalse(found)

    def test_actual_main_routes_awake_audio_while_speaking_and_respects_sleep_mute(self):
        code = '''
import asyncio
from types import SimpleNamespace
from unittest import mock
import numpy as np
import main

class UI:
    muted=False
    current_file=None
    def __init__(self): self.messages=[]
    def write_log(self,text): self.messages.append(text)
    def set_state(self,state): pass
    def set_audio_level(self,level): pass

async def exercise():
    ui=UI(); agent=main.JarvisLive(ui)
    loop=asyncio.get_running_loop();agent._loop=loop;agent.out_queue=asyncio.Queue()
    agent._wake_enabled=True;agent._awake=False
    detector=SimpleNamespace(feed=mock.Mock(),clear=mock.Mock(),ready=True)
    agent._wake_detector=detector
    frame=np.ones((1024,1),dtype=np.int16)*5000
    agent._route_mic_frame(frame,loop)
    await asyncio.sleep(0)
    assert agent.out_queue.empty() and detector.feed.call_count==1
    ui.muted=True;agent._route_mic_frame(frame,loop)
    assert detector.feed.call_count==1 and detector.clear.called
    ui.muted=False
    agent.wake('JARVIS',frame.tobytes());await asyncio.sleep(0)
    assert agent.out_queue.get_nowait()['data']==frame.tobytes()
    agent._is_speaking=True
    agent._echo=SimpleNamespace(is_user_speech=lambda *args:True,last_similarity=0.)
    agent._route_mic_frame(frame,loop);await asyncio.sleep(0)
    assert agent.out_queue.get_nowait()['data']==frame.tobytes(), 'Mic must reach Gemini while it speaks'
    agent.audio_in_queue=asyncio.Queue();agent.audio_in_queue.put_nowait(b'old audio')
    agent.sleep('test')
    assert not agent._awake and not agent._interrupted and agent.audio_in_queue.empty()

    agent.session=SimpleNamespace(send_realtime_input=mock.AsyncMock())
    # These transport/privacy assertions use symbolic payloads, not audio.
    # Neural filtering is verified separately with valid PCM fixtures.
    agent._engine_caps={}
    sender=asyncio.create_task(agent._send_realtime())
    agent.out_queue.put_nowait({'data':b'not authorized'})
    await asyncio.sleep(0);await asyncio.sleep(0)
    agent.session.send_realtime_input.assert_not_called()
    agent._awake=True
    agent.out_queue.put_nowait({'data':b'allowed'})
    await asyncio.sleep(0);await asyncio.sleep(0)
    assert agent.session.send_realtime_input.call_count==1
    ui.muted=True;agent.out_queue.put_nowait({'data':b'muted'})
    await asyncio.sleep(0);await asyncio.sleep(0)
    assert agent.session.send_realtime_input.call_count==1
    sender.cancel()
    try: await sender
    except asyncio.CancelledError: pass
    ui.muted=False
    agent._engine_caps=None

    class Session:
        received=False
        async def receive(self):
            if self.received: raise asyncio.CancelledError()
            self.received=True
            yield main.types.LiveServerMessage(voice_activity=main.types.VoiceActivity(voice_activity_type='ACTIVITY_START'))
            assert agent.audio_in_queue.empty() and not agent._interrupted
            yield main.types.LiveServerMessage(server_content=main.types.LiveServerContent(interrupted=True))
            yield main.types.LiveServerMessage(server_content=main.types.LiveServerContent(turn_complete=True))
            yield main.types.LiveServerMessage(server_content=main.types.LiveServerContent(model_turn=main.types.Content(role='model',parts=[main.types.Part(inline_data=main.types.Blob(data=b'new audio',mime_type='audio/pcm;rate=24000'))])))
    agent.session=Session();agent.audio_in_queue.put_nowait(b'stale audio')
    agent._turn_done_event=asyncio.Event()
    try: await agent._receive_audio()
    except asyncio.CancelledError: pass
    assert agent.audio_in_queue.get_nowait()==b'new audio'
    assert not any('Interrupted' in message for message in ui.messages)
    print('Main: local-only sleep, mute, pre-roll, full duplex and native turn events verified')
asyncio.run(exercise())
'''
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="jarvis-conversation-test-") as directory:
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
                                    env=dict(os.environ, JARVIS_DATA_DIR=directory, QT_QPA_PLATFORM="offscreen"),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
