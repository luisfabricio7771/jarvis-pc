# JARVIS — menos reacción al ruido

24 de octubre de 2026. Cierra y vuelve a abrir `Jarvis.exe` para cargar los cambios. Se conservan Gemini 3.8 Live, la voz predeterminada, la activación por JARVIS y la conversación sin botones.

## Ajustes

- Detector neuronal **Silero VAD v6**, local y por CPU, incluido en `faster-whisper` 1.2.1 que ya estaba instalado. No se añadió una API, descarga de modelos ni acceso al micrófono para realizar las pruebas.
- Se analiza si hay voz antes de transmitir el audio. Los fragmentos rechazados se sustituyen por silencio, manteniendo el ritmo del flujo para que Gemini pueda terminar los turnos correctamente.
- Voz muy clara requiere al menos tres cuadros positivos (96 ms); voz probable, cinco (160 ms) dentro de una ventana acotada. Un pico aislado de volumen no abre el paso.
- Se conserva un inicio de hasta 288 ms y una continuidad de unos 384 ms para no perder sílabas ni cortar pausas breves. El filtro no se basa solo en subir el volumen mínimo.
- Gemini usa sensibilidad de inicio y final **LOW** y un prefijo de al menos 240 ms. La detección automática y la posibilidad de intervenir siguen activadas.
- El indicador del micrófono utiliza el audio filtrado, sin sobrescribir la animación de la respuesta de JARVIS cuando está hablando.
- El mismo detector comprueba que haya voz antes de intentar reconocer la palabra JARVIS, reduciendo intentos de transcripción de ruido mientras espera.
- Silenciar o volver a espera descarta cualquier prefijo y resultado de voz pendiente. El modelo corre fuera del callback del micrófono y tiene un estado independiente por sesión.

En esta PC no hizo falta instalar más paquetes. `faster-whisper>=1.2.1,<2` queda declarado en las dependencias para otras instalaciones.

## Verificación

- **82 pruebas de regresión aprobadas**: activación, privacidad, voz predeterminada, proveedores, turnos, clics aislados, ruido continuo, conservación del inicio, pausas y descarte al silenciar. Registro: `.local-backups/validation/speech-filter-tests.log`.
- **56 de 56 casos sintéticos principales correctos**: 48 voces aceptadas y ocho sonidos rechazados: silencio, ventilador, ruido fuerte, zumbido, aviso tonal, clic, golpe y teclado. Datos: `speech-filter-results.json` en esa misma carpeta.
- Respuestas cortas: se aceptaron todas las ocho muestras a volumen normal y siete de ocho al 15 % del volumen. Un “No” sintético muy débil no alcanzó la probabilidad de voz necesaria. No se afirma reconocimiento perfecto de susurros o monosílabos apenas audibles.
- **Prueba real con Gemini 3.8 aprobada:** el teclado artificial fue rechazado localmente y no causó interrupción. Después se envió voz artificial: hubo cambio nativo de turno, dos eventos de actividad, 48 caracteres de transcripción y 50402 bytes de audio de la nueva respuesta. No se usaron grabaciones personales, micrófono ni altavoces.
- El WAV de prueba español en `tests/fixtures/jarvis-es.wav` es una voz sintetizada de Windows, no una grabación del propietario.

Prueba real reproducible, solo con autorización explícita mediante `--live`:

```powershell
python -B launcher/check_conversation.py --live --speech-fixture RUTA_VOZ.wav --noise-fixture RUTA_RUIDO.wav
```

Ambos WAV deben ser PCM mono de 16 bits a 16 kHz. Usa la clave ya configurada y la cuota/facturación de Google correspondiente.

## Alcance

El detector distingue voz de muchos ruidos; no identifica quién habla. Una televisión, otra persona o el retorno de la propia voz por los altavoces pueden parecer voz. La protección de eco existente sigue activa, pero no equivale a cancelación acústica completa. Falta probar el ajuste con el micrófono y la habitación reales del propietario.

Referencias: [Silero VAD](https://github.com/snakers4/silero-vad), [detección automática en Gemini Live](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

Fuentes anteriores: `.local-backups/filtro-voz-20261024/`. No se modificó NEXUS.
