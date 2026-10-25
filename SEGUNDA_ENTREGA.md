# Segunda entrega: OpenAI Responses y modo híbrido

## Ejecutar

Abre `Jarvis.exe` desde esta carpeta o ejecuta en PowerShell:

```powershell
cd "C:\Users\jabic\OneDrive\Escritorio\proyectos\Mark-LVI-main"
.\Jarvis.exe
```

También sirve `python -B main.py`. Cierra y vuelve a abrir JARVIS si estaba
ejecutándose durante la actualización.

`Configurar IA.exe` abre únicamente el panel de proveedores, sin sesión de voz,
micrófono ni cámara. Equivalentes: `Jarvis.exe --providers` o
`python -B preview.py --providers`. `Ver memoria.exe` sigue disponible.

Los EXE son lanzadores locales: necesitan el Python instalado con las dependencias
del proyecto y deben permanecer junto al código. No son paquetes portátiles.
Para reconstruirlos: `& .\launcher\build.ps1`.

## Configuración

1. Abre **Configurar IA.exe** o el panel **PROVIDERS** de JARVIS.
2. Para conservar la conversación y voz de Gemini Live, elige
   **OpenAI Responses / híbrido local** en **BACKGROUND REQUESTS**. Se aplica
   a las solicitudes auxiliares existentes, como análisis de documentos y código.
   La conversación principal sigue siendo Gemini; esta selección no envía cada
   frase de voz a OpenAI.
3. Para usar Responses en la conversación principal, elige **MY OWN SETUP** y
   este proveedor en **THINKING**. Conserva o configura **HEARING** y **SPEAKING**;
   sin esos proveedores se puede trabajar por texto. El audio de Gemini Live
   no se traslada automáticamente a este modo.
4. Introduce tu clave **dentro de la aplicación** y selecciona un modelo de texto
   compatible con Responses. **REFRESH** consulta los modelos de tu cuenta;
   aparecer listado no garantiza compatibilidad con cada nivel de razonamiento.
   No se fija un modelo ni se cambia tu selección actual automáticamente.
5. Elige `openai` para enviar las solicitudes de este proveedor a la API, o
   `hybrid` para combinarla con un servidor local. Para `hybrid`, completa
   dirección y nombre exacto del modelo instalado, por ejemplo en Ollama.
6. Revisa los límites y pulsa **SAVE & APPLY**. **TEST** comprueba la clave y la
   presencia del modelo mediante el listado; no genera una respuesta ni valida
   una conversación completa. El primer uso real sí puede tener coste.

No necesitas instalar otra biblioteca: se reutiliza `httpx`. La API requiere
acceso y saldo en la cuenta de OpenAI. No da acceso a tus conversaciones privadas
de ChatGPT.

## Cómo decide el modo híbrido

La selección usa reglas locales, sin una llamada adicional para clasificar:

- Peticiones sencillas: modelo local.
- Solicitudes que incluyen analizar, comparar, investigar, planificar, resolver,
  depurar, diseñar o razonar, o más de 1200 caracteres: OpenAI.
- Solicitudes auxiliares marcadas `SMART` por las herramientas actuales: OpenAI;
  las `FAST` siguen las mismas reglas de contenido.
- `local:` al principio fuerza el modelo local; `razona:` u `openai:` fuerza la
  API. En Gemini Live estos prefijos no cambian por sí solos el motor de voz.
- Las imágenes del contexto usan OpenAI si activaste visión con un modelo
  compatible. `local:` rechaza las imágenes en este adaptador.
- Las respuestas a herramientas continúan con el criterio del último mensaje
  de usuario. El contenido devuelto por una herramienta no decide el proveedor.

Son reglas prácticas, no un detector perfecto de dificultad. Puedes forzar la
elección con los prefijos. El servidor denominado local debe estar en loopback;
no se admite una dirección externa en ese campo.

Al seleccionar Responses para solicitudes auxiliares de texto, sus errores o
límites no activan una llamada a Gemini. La búsqueda con fuentes de Google y
las grabaciones conservan su ruta específica en Google, cuando está configurada.
Si conservas Gemini Live, su consumo de voz sigue siendo independiente.

## Límites y registro

- **50 intentos OpenAI por día UTC** de forma predeterminada. `0` los desactiva.
  Cada ronda con herramientas cuenta como otra solicitud. Intentos fallidos o
  cancelados también cuentan para evitar reintentos sin control.
- **2048 tokens de salida por respuesta**, incluidos los de razonamiento.
  Puedes aumentarlos si el modelo necesita más para terminar.
- **60000 caracteres de contexto y herramientas** por solicitud, configurable
  en **MORE**. Si se supera, se informa del límite sin enviar ni recortar a
  medias una llamada a herramientas. Las imágenes codificadas también cuentan.
- Hasta **4 rondas de herramientas** por turno del motor conversacional; después
  se pide la respuesta final sin herramientas. Las llamadas repetidas reutilizan
  su resultado. Si un modelo insiste, se detiene el turno.

El conteo de solicitudes se reserva en SQLite antes de enviar la petición y se
comparte entre modelos e instancias de JARVIS. Sobrevive al reinicio. El panel
muestra solicitudes y tokens de uso confirmado; vuelve a abrirlo para actualizar.
No almacena precios ni estima una factura: estos límites no equivalen a un tope
monetario de toda la cuenta. No abarcan otros programas, el proveedor compatible
antiguo, Gemini, STT o TTS. Los intentos sin uso confirmado pueden tener coste que
JARVIS no pudo registrar. El registro cuenta, incluso si borras o cambias la clave.

Los datos están en `assistant.db`, junto a tareas e historial, normalmente en
`%LOCALAPPDATA%\JARVIS`. La tabla `api_usage` contiene modelo, día, estado y tokens;
no guarda mensajes, claves ni argumentos de herramientas.

## Contexto, claves y herramientas

Se usa el endpoint oficial `https://api.openai.com/v1/responses`, con `store:false`.
JARVIS conserva en memoria el historial necesario, incluidos los elementos
opacos de razonamiento que Responses necesita para continuar tras una herramienta.
Esos elementos no se reproducen por voz ni se guardan como recuerdos.

Las solicitudes remotas incluyen el contexto conversacional y los resultados de
herramientas enviados al modelo. `store:false` no promete retención cero de todos
los datos en el servicio. Las claves siguen la protección local de la primera
entrega (DPAPI en Windows); nunca se incrustan en los ejecutables.

Se reutilizan las herramientas y confirmaciones actuales. Solo se despachan
llamadas completas con argumentos JSON válidos y nombre ofrecido al modelo.
Una transmisión cortada o respuesta incompleta no ejecuta sus llamadas parciales.
No se habilitan herramientas alojadas de OpenAI, conectores ni un agente nuevo.
El planificador persistente y las integraciones externas corresponden a las
siguientes entregas.

Referencias oficiales consultadas:
[Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses),
[funciones](https://developers.openai.com/api/docs/guides/function-calling),
[razonamiento](https://developers.openai.com/api/docs/guides/reasoning),
[transmisión](https://developers.openai.com/api/docs/guides/streaming-responses).
[Tratamiento de datos](https://developers.openai.com/api/docs/guides/your-data).

## Validación y respaldo

```powershell
python -B -m unittest discover -s tests -v
```

Las pruebas usan claves ficticias, datos temporales y respuestas HTTP simuladas.
Cubren contexto nativo, herramientas, transmisiones interrumpidas, límites entre
procesos, concurrencia, rutas locales, paneles y las regresiones anteriores.
No se ha probado una llamada con una clave real ni se ha consumido saldo.

### Si aparece un error de créditos o de transmisión

`credit_balance_exhausted` significa que no quedan créditos de API;
`insufficient_quota` puede indicar saldo o límites de la organización/proyecto.
Se revisan en la facturación de OpenAI. Reintentar no corrige estos problemas.
Un límite de frecuencia es una situación diferente y requiere esperar.
Consulta los [códigos oficiales de error](https://developers.openai.com/api/docs/guides/error-codes).

El adaptador muestra la causa reconocida también cuando llega como evento de
transmisión o respuesta fallida, sin copiar claves ni mensajes privados al log.
`TEST` valida clave y listado; no comprueba que haya saldo para generar.

Para reconocimiento local, selecciona **Whisper on this computer**, instala
`faster-whisper`, elige modelo `base`, procesador `cpu` e idioma `es`. Elegir
**OpenAI Whisper** envía el audio a la API y requiere saldo independientemente
de los límites de Responses. Cambiar solo HEARING a local no cambia THINKING:
el modelo de OpenAI seguirá necesitando acceso y saldo de API.

Respaldo del código anterior a esta fase:
`.local-backups/20261019-184947/before-second-delivery.zip`.
No incluye claves, ajustes privados ni la base de datos personal.
