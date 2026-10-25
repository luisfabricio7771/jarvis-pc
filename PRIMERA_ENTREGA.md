# JARVIS local — primera entrega

Esta entrega conserva el motor de conversación, la voz, el avatar y las herramientas
existentes. Añade pendientes e historial seleccionado y corrige problemas de
estabilidad. La integración avanzada de OpenAI y los conectores Google/WhatsApp
corresponden a etapas posteriores.

## Uso

En esta computadora puedes abrir `Jarvis.exe` para iniciar el asistente completo,
o `Ver memoria.exe` para ver el panel nuevo sin iniciar voz, cámara ni una sesión
de IA. También puedes ejecutar `python -B preview.py`.

Estos ejecutables son **lanzadores locales**: usan el Python instalado y deben
permanecer junto al código. No incluyen Python ni sus dependencias. Se pueden
recrear con `powershell -ExecutionPolicy Bypass -File launcher/build.ps1`.

Abre **⚙ → 🧠 MEMORY**. El panel tiene tres vistas:

- **RECUERDOS:** consultar, añadir, corregir y eliminar datos guardados.
- **PENDIENTES:** crear y editar tareas con notas, proyecto, prioridad, estado y
  vencimiento; marcar como completadas y consultar las terminadas.
- **HISTORIAL:** consultar y eliminar resúmenes seleccionados de conversaciones.

También están disponibles las herramientas `manage_tasks` y `manage_memory`.
Ejemplos de instrucciones para el modelo configurado:

- «Anota el pendiente de preparar el reporte de ventas para el viernes».
- «¿Qué pendientes tengo del proyecto de inventario?».
- «Marca como completado el reporte de ventas».
- «Recuerda que prefiero los reportes en español».
- «¿Qué acordamos sobre el inventario?».
- «Corrige ese recuerdo» o «Olvida ese dato».

Las tareas se guardan inmediatamente. Una fecha de vencimiento **no programa una
alarma**: para una notificación sigue disponible la herramienta de recordatorios.
Los estados disponibles son pendiente, en progreso, bloqueada, completada y
cancelada. El modelo utiliza identificadores exactos para modificar tareas.

El historial guarda decisiones y resúmenes relevantes, no una grabación completa.
Los resúmenes guardados explícitamente con `manage_memory` son persistentes desde
ese momento. El resumen automático al terminar una sesión sigue dependiendo del
proveedor configurado y de que la sesión termine ordenadamente; cerrar el proceso
a la fuerza no garantiza ese último resumen. Un fallo al resumir ya no descarta
el contexto pendiente en memoria.

## Compatibilidad y almacenamiento

- Los hechos anteriores continúan en `memory/long_term.json`; se conserva su formato.
- Los resúmenes antiguos se importan una sola vez al consultarlos. La bienvenida
  marca un resumen como anunciado, sin eliminarlo del historial.
- Tareas y resúmenes nuevos usan SQLite. En Windows se guarda en
  `%LOCALAPPDATA%\JARVIS\assistant.db`; en Linux/macOS se utiliza
  `$XDG_DATA_HOME/jarvis/assistant.db` o `~/.local/share/jarvis/assistant.db`.
- La variable opcional `JARVIS_DATA_DIR` permite redirigir todos los nuevos datos y
  los archivos de configuración/memoria a una carpeta explícita. Las pruebas la
  usan con carpetas temporales.
- Los recuerdos temporales aceptan caducidad ISO con zona horaria y dejan de
  aparecer en consultas al caducar. Su corrección y eliminación actualizan el
  origen consultado por la búsqueda.
- La recuperación de esta entrega combina palabras, acentos, tareas y resúmenes.
  **Todavía no incorpora embeddings ni búsqueda semántica por significado.**
- SQLite y los recuerdos son archivos locales sin cifrado de contenido. No deben
  usarse para guardar contraseñas o claves. El panel permite eliminar elementos.

## Ajustes y credenciales

El guardado de configuración y recuerdos utiliza reemplazo atómico y serializa
las operaciones del proceso. Un archivo corrupto se conserva para recuperación;
un cambio de ajuste no lo sustituye silenciosamente por un documento vacío.
La sincronización no coordina varias instancias independientes de JARVIS: utiliza
una sola instancia para evitar cambios simultáneos entre procesos.

Reconfigurar la API conserva voz, nombre y proveedores. Es posible iniciar la
configuración de un proveedor local desde el primer arranque sin una clave Gemini.
Si un motor elegido no puede arrancar, no se activa Gemini de forma silenciosa;
el fallback requiere `allow_cloud_fallback: true` y una clave configurada.
Las llamadas auxiliares y búsquedas mantienen sus propios ajustes de proveedor.

Las claves de configuración nuevas o actualizadas se protegen con DPAPI del
usuario de Windows, usando la dependencia `pywin32` ya existente. En otros
sistemas se usa el almacén de credenciales mediante `keyring`; si no hay un
backend disponible, el guardado de claves informa del error. Las claves antiguas
en texto claro siguen siendo legibles y se protegen al siguiente guardado de
ajustes. No se publican ni se trasladan a un servidor de JARVIS.

DPAPI no impide que programas que ejecutas como tu usuario accedan a tus claves.
Un archivo protegido en un equipo/usuario distinto puede requerir reintroducir
sus claves. Conserva las claves originales en tu gestor de contraseñas.

## Estabilidad del panel remoto y los archivos

- HTTPS es obligatorio para acceso desde otros dispositivos. Si no se puede crear
  el certificado, el panel remoto queda deshabilitado.
- Con `dashboard_https: false`, HTTP se limita a `127.0.0.1`.
- El arranque no modifica el firewall ni convierte redes públicas en privadas.
  La configuración automática de red permanece como opción explícita
  `dashboard_auto_configure_network`, desactivada por defecto.
- Revocar dispositivos cierra las conexiones WebSocket de órdenes y audio. Las
  colas conservan el token y se valida de nuevo antes de utilizarlo.
- Tanto el emparejamiento manual como el QR tienen límite de intentos.
- El agente programador rechaza rutas absolutas, recorridos `..`, nombres
  reservados y destinos que resuelvan fuera de la carpeta del proyecto. Esto no
  convierte la ejecución de código generado en un entorno aislado; un sandbox
  completo corresponde a una etapa posterior.
- Una solicitud de confirmación nueva no sustituye a otra todavía pendiente.

## Validación y reversión

Ejecutar desde la carpeta del proyecto:

```powershell
python -B -m unittest discover -s tests -v
```

Las pruebas usan datos ficticios, ventanas Qt sin pantalla y servicios simulados.
Incluyen las verificaciones originales de proveedores, que ahora usan su propia
configuración temporal. No necesitan claves reales ni abren una sesión de voz.

La copia previa de los archivos originales y su manifiesto SHA-256 están en
`.local-backups/20261019-181446/`. Este respaldo corresponde al código y recursos;
no incluye claves de API. Para revertir, cierra JARVIS y restaura los archivos del
ZIP. El archivo de licencia original permanece sin cambios. Los datos nuevos de
SQLite permanecen separados y no necesitan borrarse al restaurar el código.

La verificación de voz real, permisos de micrófono, conexión con tu modelo y
emparejamiento desde un teléfono se realiza después con tu configuración habitual.
