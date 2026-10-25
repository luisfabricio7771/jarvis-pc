# Conversación natural y activación por JARVIS

24 de octubre de 2026. Actualización sobre Gemini 3.8 Live, conservando la voz **Auto / predeterminada del modelo**.

Retoque posterior: se incorporó [un detector local de voz y filtrado de ruido](FILTRO_DE_VOZ.md), con menor sensibilidad a sonidos breves. La activación por JARVIS y los turnos naturales siguen disponibles.

## Uso

1. Cierra JARVIS y vuelve a abrir `Jarvis.exe` desde esta carpeta.
2. Arranca **en espera**. Di **JARVIS**, haz una pausa breve y continúa con tu pregunta. También conserva el inicio de una pregunta pronunciada junto al nombre mientras se procesa la activación.
3. Una vez activo puedes conversar normalmente e intervenir mientras responde, sin repetir el nombre en cada turno ni pulsar un botón.
4. Tras dos minutos sin voz del usuario vuelve a esperar su nombre. También puedes pulsar **Volver a espera**. El indicador muestra **Activación: JARVIS** y, cuando duerme, **Di JARVIS para empezar**.
5. **Silenciar micrófono** bloquea tanto el envío como la activación. Desactiva el silencio para usar el nombre otra vez.

En esta PC quedaron guardados `wake_word_enabled=true` y `push_to_talk_enabled=false`. La voz sigue en `default`. No se cambian las claves ni los proveedores auxiliares. El comportamiento natural descrito corresponde al motor Gemini Live; el motor alternativo STT/LLM/TTS conserva su modalidad anterior.

## Conversación

Se retiraron el botón **INTERRUPT** y el atajo global **Esc**. El micrófono ya no se bloquea durante las respuestas de Gemini. Se mantiene su detección automática de actividad y el modo nativo que permite al usuario tomar el turno.

Las señales de inicio de voz y de interrupción del servidor vacían el audio anterior y reinician la animación. Esto incluye el caso en que el servidor ya generó una respuesta pero aún queda audio por reproducir en la PC. Los nuevos fragmentos se aceptan en el siguiente turno. Los lotes de reproducción se redujeron a unos 50 ms; la latencia física depende del dispositivo.

Se atenúa el retorno de audio que se parece mucho a lo que reproduce JARVIS. Es una protección limitada, no una cancelación acústica completa: con altavoces fuertes, ruido o reverberación puede haber cortes o retorno. Los auriculares suelen mejorar la conversación. La prueba acústica con el micrófono y la habitación del propietario queda por realizar.

## Activación local

El detector anterior se había entrenado para **Hey Jarvis** y falló en las pruebas de JARVIS solo con pronunciación española. Se sustituyó por reconocimiento local de ventanas cortas con **Whisper tiny multilingüe**, CPU int8 y dos hilos. Solo se acepta la palabra completa `jarvis`; no se usan coincidencias parciales como `jarvista` o nombres como Javier.

El modelo se descarga una vez en `.local-models/wake-whisper-tiny` y pesa aproximadamente 78 MB. Ya está preparado en esta PC. Durante la escucha se carga solo desde disco; no consulta una API para reconocer el nombre. No se guardan grabaciones ni transcripciones de la habitación.

Mientras espera, el micrófono se procesa localmente. Después de reconocer el nombre se envía a Gemini la ventana de activación y el audio inmediatamente posterior, conservado en un búfer acotado para no perder el comienzo de la petición. No se entrega el historial anterior de la habitación. Mientras está activo, el audio sí se envía a Google para la conversación, como antes.

El detector es probabilístico: los resultados sintéticos no garantizan reconocimiento perfecto de cualquier voz, distancia o ruido. Puede tardar aproximadamente una pausa más el procesamiento local; decir JARVIS con claridad y dejar una pausa breve ayuda.

## Validación

- Pruebas de palabra completa, silencio y chasquidos, ventanas acotadas y cancelación de una detección pendiente al silenciar o reiniciar.
- Integración con el motor real de JARVIS sin conexión externa: audio local mientras espera, silencio, conservación del inicio de la petición, micrófono abierto mientras responde, rechazo de audio pendiente al dormir, recepción de nuevos turnos y señales nativas.
- **48 de 48 casos sintéticos correctos** en el mismo segmentador y modelo local de la app: 16 activaciones con JARVIS/Hey Jarvis y 32 frases negativas, incluidas Javier, gracias y conversaciones sin su nombre, con ocho voces de Windows. No son grabaciones de una persona ni una medición de falsos positivos por hora.
- **Prueba real de Gemini 3.8 Live aprobada:** se envió una intervención artificial mientras generaba voz. Se recibieron la interrupción nativa, dos eventos de actividad, 48 caracteres transcritos y 49922 bytes de audio de la nueva respuesta. No se usaron micrófono, altavoces ni memoria personal.
- **73 pruebas de regresión aprobadas**, registradas en `.local-backups/validation/conversation-tests.log`. Las pruebas de los 48 WAV están en `wake-fixtures/streaming-results.json` dentro de esa carpeta.

Para repetir voluntariamente una intervención artificial contra la API:

```powershell
python -B launcher/check_conversation.py --live --speech-fixture RUTA_AL_WAV_DE_PRUEBA
```

Requiere WAV PCM mono, 16 bits, 16 kHz. Solo con `--live` se abre una sesión real, limitada en tiempo. Usa la cuota/facturación de Google que corresponda a la cuenta.

Referencias: [turnos y señales de Gemini Live](https://ai.google.dev/api/live), [modelo Whisper local utilizado](https://huggingface.co/Systran/faster-whisper-tiny).

La copia de las fuentes anteriores y las preferencias no secretas se conserva en `.local-backups/conversacion-20261024/`. El EXE sigue siendo un lanzador local y debe permanecer junto al proyecto. NEXUS no se modifica.
