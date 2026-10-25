# JARVIS — Gemini 3.8 Live

Actualización del 24 de octubre de 2026 sobre el proyecto existente.

## Abrir

Cierra JARVIS y vuelve a abrir `Jarvis.exe` en esta carpeta. También puedes usar:

```powershell
python -B main.py
```

El ejecutable es un lanzador local: conserva Python y los archivos del proyecto junto a él. No es un instalador ni una aplicación portátil independiente.

En **Configurar IA.exe → ENGINE & PROVIDERS**, el motor aparece como **GEMINI 3.8 LIVE**. Si ya está seleccionado Gemini, no necesitas cambiarlo. Si seleccionaste otro motor previamente, elige Gemini y aplica.

La voz queda en **Auto**, en **CUSTOMISE ASSISTANT**. Significa que JARVIS omite la selección de una voz predefinida y deja que Gemini use su voz predeterminada. No envía el nombre literal `default` a la API ni fuerza Charon, Kore u otra voz. Las voces anteriores siguen disponibles para quien las seleccione explícitamente.

Al conectar, el registro muestra el modelo realmente usado y **Voz: predeterminada del modelo**. Las claves y demás preferencias existentes se conservan.

## Cambios

- Modelo principal `models/gemini-3.8-live`, por la API `v1beta`.
- Gemini 3.8 gestiona su propio razonamiento: no se envía `thinking_config`. Tampoco se envía el campo eliminado de diálogo afectivo ni un interruptor de audio proactivo: en este modelo está activado permanentemente.
- Herramientas declaradas como `BLOCKING`, compatibles con la ejecución secuencial y las confirmaciones de JARVIS. No se introducen acciones asíncronas nuevas.
- Audio de salida, transcripciones y respuestas a herramientas se procesan aunque lleguen en el mismo evento. Se mantiene PCM de entrada a 16 kHz y salida a 24 kHz.
- Las solicitudes auxiliares Live siguen al modelo realmente activo tanto al ejecutar `main.py` como al importarlo. Los proveedores alternativos conservan su selección y sus límites.
- Se conserva 3.1 Flash Live Preview como alternativa ante falta de acceso o cuota, con su propia configuración. El registro avisa si se usa. Se elimina de esta lista el antiguo 2.5 nativo. La disponibilidad final depende de Google y de la clave configurada.
- Los identificadores de reanudación no se reutilizan entre modelos distintos.
- Se corrigió un fallo de Windows al cerrar el panel de proveedores antes de terminar de cargar el catálogo de voces: los trabajadores ya no emiten señales sobre un objeto Qt destruido.
- Dependencia mínima comprobada: `google-genai>=2.31.0,<3`. En esta PC ya estaba instalada 2.31.0; no se necesitó una instalación adicional.

## Validación

- **68 pruebas de regresión aprobadas** con `python -B -m unittest discover -s tests -v`, incluidas las comprobaciones internas de proveedores.
- Pruebas nuevas: modelo principal y alternativa, configuración compatible, conservación de declaraciones originales, herramientas del SDK, seguimiento del punto de entrada, voz Auto y voz seleccionada, varios fragmentos de audio, transcripción, respuesta a herramientas, reanudación y finalización del catálogo tras destruir el panel.
- **Conexión real a Gemini 3.8 Live aprobada** con una frase ficticia, voz predeterminada, audio, transcripción y una herramienta sin efectos sobre el equipo. La segunda comprobación usó los esquemas y ajustes reales de JARVIS con un perfil temporal vacío: 122402 bytes de audio, 39 caracteres transcritos y una respuesta a la herramienta de prueba.
- Las comprobaciones reales no activaron micrófono, cámara, herramientas del sistema ni cargaron memoria personal. No evalúan acústica, eco o latencia de los dispositivos físicos.
- Pantallas de configuración y voz Auto renderizadas y revisadas. Lanzadores de Windows reconstruidos.
- Fuentes y lanzadores previos conservados en `.local-backups/gemini-3.8-live-20261024/`. El registro de regresión y las capturas están en `.local-backups/validation/`.

Para repetir la prueba real voluntariamente, con una clave ya configurada:

```powershell
python -B launcher/check_live.py --live --app-config
```

Sin `--live` ese script no abre una sesión. La prueba dura como máximo 45 segundos de conexión y no reproduce el audio en los altavoces. Usa la API de Google y su cuota o facturación, según la cuenta; esta entrega no implica gratuidad garantizada.

Referencia de compatibilidad: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live

NEXUS no se modifica en esta actualización.
