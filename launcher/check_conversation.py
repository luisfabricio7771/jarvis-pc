"""Opt-in Gemini native turn-taking check using a synthetic PCM WAV, never a mic."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def check(filename, noise_filename=None):
    from google import genai
    from google.genai import types
    from launcher.check_live import app_settings
    from memory.config_manager import get_gemini_key
    from core.live_config import DEFAULT_LIVE_MODEL
    from core.speech_filter import SpeechFilter
    with wave.open(str(filename), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise RuntimeError("La prueba requiere WAV PCM mono de 16 bits a 16 kHz.")
        audio = wav.readframes(min(wav.getnframes(), 16000 * 10))
    noise = b""
    if noise_filename:
        with wave.open(str(noise_filename), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise RuntimeError("El ruido de prueba debe ser PCM mono de 16 bits a 16 kHz.")
            noise = wav.readframes(min(wav.getnframes(), 16000 * 3))
    speech_filter = SpeechFilter()
    key = get_gemini_key()
    if not key:
        raise RuntimeError("Falta la clave Gemini configurada.")
    settings = app_settings()
    settings["tools"] = []
    settings["system_instruction"] = "Habla en español. Sigue las instrucciones del usuario, también cuando cambia de tema mientras hablas."
    settings["max_output_tokens"] = 512
    result = {"model": DEFAULT_LIVE_MODEL, "nativeInterruption": False, "voiceActivityEvents": 0,
              "inputTranscriptCharacters": 0, "newReplyAudioBytes": 0,
              "noiseRejectedLocally": bool(noise), "noiseCausedInterruption": False}
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    first_audio, input_done = asyncio.Event(), asyncio.Event()
    noise_phase = False
    try:
        async with asyncio.timeout(50):
            async with client.aio.live.connect(model=DEFAULT_LIVE_MODEL, config=settings) as session:
                async def send():
                    nonlocal noise_phase
                    await first_audio.wait()
                    noise_phase = bool(noise)
                    for offset in range(0, len(noise), 2048):
                        raw = noise[offset:offset+2048]
                        filtered = speech_filter.process(raw)
                        assert not any(filtered), "La prueba dejó pasar ruido"
                        if filtered:
                            await session.send_realtime_input(audio=types.Blob(data=filtered, mime_type="audio/pcm;rate=16000"))
                        await asyncio.sleep(len(raw)/32000)
                    noise_phase = False
                    for offset in range(0, len(audio), 2048):
                        chunk = audio[offset:offset+2048]
                        filtered = speech_filter.process(chunk)
                        if filtered:
                            await session.send_realtime_input(audio=types.Blob(data=filtered, mime_type="audio/pcm;rate=16000"))
                        await asyncio.sleep(len(chunk)/32000)
                    for _ in range(12):
                        await session.send_realtime_input(audio=types.Blob(data=b"\0"*2048, mime_type="audio/pcm;rate=16000"))
                        await asyncio.sleep(0.064)
                    input_done.set()

                async def receive():
                    while True:
                        async for message in session.receive():
                            if message.voice_activity:
                                result["voiceActivityEvents"] += 1
                                if noise_phase and message.voice_activity.voice_activity_type == "ACTIVITY_START":
                                    result["noiseCausedInterruption"] = True
                            content = message.server_content
                            if content and content.interrupted:
                                result["nativeInterruption"] = True
                                if noise_phase:
                                    result["noiseCausedInterruption"] = True
                            if message.data:
                                first_audio.set()
                                if result["nativeInterruption"]:
                                    result["newReplyAudioBytes"] += len(message.data)
                            if content and content.input_transcription:
                                result["inputTranscriptCharacters"] += len(content.input_transcription.text or "")
                            if content and content.turn_complete and input_done.is_set() and result["newReplyAudioBytes"]:
                                return

                await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(
                    text="Cuenta despacio del uno al cuarenta, diciendo cada número, sin resumir.")]), turn_complete=True)
                async with asyncio.TaskGroup() as group:
                    group.create_task(receive())
                    group.create_task(send())
        assert result["nativeInterruption"] and result["inputTranscriptCharacters"] and result["newReplyAudioBytes"], result
        assert not result["noiseCausedInterruption"], result
        print(json.dumps(result))
    except Exception as error:
        raise RuntimeError(f"Prueba de conversación: {str(error).replace(key, '[redacted]')[:500]}") from None
    finally:
        await client.aio.aclose()
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--speech-fixture", type=Path, required=True)
    parser.add_argument("--noise-fixture", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("Añade --live para autorizar una sesión breve con audio de prueba.")
    try:
        asyncio.run(check(args.speech_fixture, args.noise_fixture))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
