# Tus repositorios de JARVIS

- PC: https://github.com/luisfabricio7771/jarvis-pc
- Android: https://github.com/luisfabricio7771/jarvis-android

Son privados: inicia sesión con tu cuenta para verlos. La app para PC ya existe. Android se prepara en su propio repositorio; todavía no tiene APK.

## Qué significa guardar en GitHub

GitHub conserva una copia del código y un historial de versiones. **No sincroniza automáticamente cada archivo que cambies en tu PC.** Hay que guardar los cambios en Git y enviarlos a GitHub. Puedes pedirme que actualice el respaldo después de cada entrega.

También puedes usar GitHub Desktop:

1. Inicia sesión con la cuenta que es propietaria de estos repositorios.
2. Añade la carpeta de JARVIS mediante **File → Add local repository**.
3. Verás la lista de archivos modificados. Revisa que sean cambios del proyecto.
4. Escribe una descripción corta, por ejemplo «Mejorar detección de voz», y guarda el **commit**.
5. Pulsa **Push origin**. Espera a que termine y comprueba en la página de GitHub que aparece tu descripción.

Un **commit** guarda una versión local. **Push** la envía a GitHub. **Clone** descarga el proyecto y su historial en otra computadora.

## Recuperar la versión de PC en otra computadora Windows

1. Inicia sesión en GitHub o GitHub Desktop y clona `jarvis-pc` en una carpeta nueva.
2. Instala Python 3.13 desde su sitio oficial y ejecuta `python -m pip install -r requirements.txt` desde la carpeta del proyecto.
3. Si vas a usar las funciones de navegación web, ejecuta `python -m playwright install chromium`.
4. Reconstruye los lanzadores locales con PowerShell: `& .\launcher\build.ps1`. Esto genera Jarvis.exe, Configurar IA.exe y Ver memoria.exe para el Python de esa computadora.
5. Abre Jarvis.exe e introduce nuevamente tu clave Gemini **en la aplicación**, no en GitHub.
6. Activa la descarga del modelo de JARVIS en el panel de controles si no está preparado. Los modelos locales se vuelven a descargar; no se incluyen en el repositorio.

Si solo quieres descargar los archivos desde el navegador, entra al repositorio y usa **Code → Download ZIP**. Para seguir guardando versiones resulta más cómodo clonarlo con GitHub Desktop.

## Datos que requieren otro respaldo

El repositorio conserva código, documentación, licencia y recursos necesarios para reconstruir la app. **No contiene tu clave Gemini, otras credenciales, memoria personal, base de datos, certificados, grabaciones o registros de actividad.** Los ejecutables locales y modelos descargados tampoco se versionan.

Las claves protegidas por Windows están ligadas a tu perfil: para otra PC vuelve a configurarlas desde la aplicación. No subas el archivo `config/api_keys.json`.

Si quieres conservar también tus recuerdos y tareas ante una avería, hace falta un respaldo independiente de esos datos, preferiblemente cifrado y guardado fuera de esta computadora. El respaldo de código de GitHub no sustituye ese respaldo personal.

Guía oficial: https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop
