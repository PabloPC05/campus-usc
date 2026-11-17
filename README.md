# campus-usc

El Campus Virtual de la USC en tu terminal, con el comando `campus`. Tiene la misma barra azul
marino, el Taboleiro, el Cronograma y «Os meus cursos», con los colores del tema de cv.usc.es.
Cada asignatura sale en el color que Moodle da a su tarjeta y las etiquetas están en gallego,
como en la web. Cada pantalla tarda unos 30 ms.

```sh
campus                    # Taboleiro: hoxe, calendario, cronograma, próximos exames e cursos
campus entregas           # tus próximas entregas, cada una con el comando para entregarla
campus pendientes         # Cronograma (-a atrasadas, -d 30 días, -c por cursos, «redes» solo esa)
campus horario            # tu semana en rejilla (+1 la siguiente, --grupos CLE_01 CLIL_02 --guardar-grupos)
campus hoy                # clases y entregas de hoy, con lo que tienes «agora»
campus examenes           # fechas oficiales, con cuenta atrás
campus calendario         # el mes, con entregas y exámenes marcados
campus cursos             # «Os meus cursos» en tarjetas, con su alias para los demás comandos
campus curso ia           # la página de la asignatura: secciones, actividades y lo pendiente
campus materiales ia      # sus archivos y carpetas
campus descargar ia       # baja sus materiales con barra de progreso (pregunta antes)
campus entregar redes 3 practica.pdf   # entrega un archivo en una tarea (pregunta antes)
campus notificaciones     # notificacións numeradas; «campus notificaciones 3» lee una entera
campus abrir redes        # abre la asignatura en el navegador
campus estado             # sesión y frescura de la caché · campus ayuda para todo lo demás
```

Las asignaturas se indican por alias, código, número o nombre (`ia`, `soi`, `asr`, `redes`,
`G4012224`). Todo acepta `--json`, `-f` para ignorar la caché y `--sin-color`.

## Instalación

Dos pasos, una sola vez. En Mac o Linux, abre la app Terminal y pega:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install "campus-usc @ https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"
```

En Windows, abre PowerShell y pega:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install "campus-usc @ https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"
```

Cierra la terminal, ábrela de nuevo y escribe `campus`. El primer paso instala
[uv](https://docs.astral.sh/uv/), que es quien instala y pone al día programas de Python. Para
actualizar `campus`, repite la segunda línea añadiendo `--reinstall --refresh`.

## Entrar en tu cuenta

No hay que hacer nada especial: la primera vez que escribes `campus`, se abre una ventana con la
página de la USC. Entras como en la web: tu correo, tu contraseña y el aviso del móvil. Cuando
pregunte «¿Mantener la sesión iniciada?», pulsa «Sí». La ventana se cierra sola y ya está.

Después, cuando la sesión del Campus caduca (pasa a las pocas horas sin usarla), `campus` la
renueva solo, sin ventana, en unos segundos: la ventana de entrar recuerda tu cuenta como
cualquier navegador. Solo vuelve a aparecer si Microsoft te pide algo nuevo, por ejemplo después
de cambiar la contraseña. `campus login` hace lo mismo cuando quieras. Se guarda la cookie de
sesión del Campus en el llavero del sistema, nunca tu contraseña.

¿Por qué una ventana y no un enlace, como en otras apps? En Moodle eso es el inicio de sesión de
la app móvil, y la USC lo tiene desactivado (`enablemobilewebservice = 0`). Además, la cookie del
Campus es `HttpOnly`: ninguna página puede pasársela a la terminal. Si prefieres tu propio
navegador, `campus login --pegar` te abre el Campus, te dice dónde copiar la cookie
`MoodleSession` y te la pide sin que se vea; la comprueba antes de guardarla.

## Velocidad

Medido el 17 de noviembre de 2026 con una cuenta real, en un Mac con Apple M5 y conexión de casa.

| Para ver… | `campus` | `campus` pidiendo al Campus | Asistente con MCP: la herramienta | Lo que tiene que leer el asistente | Web del Campus en el navegador |
|---|---:|---:|---:|---:|---:|
| Próximas entregas | **0,03 s** | 1,8 s | 1,7 s | 31 600 caracteres | 2,2 s |
| Os meus cursos | **0,03 s** | 2,1 s | 0,4 s | 6 800 caracteres | 1,1 s |
| Notificacións | **0,03 s** | 0,8 s | 0,1 s | 21 400 caracteres | 0,5 s |
| Horario da semana | **0,03 s** | 8,7 s | 6,3 s | 34 600 caracteres | (varias páginas de usc.gal) |
| Exames | **0,03 s** | 2,5 s | 1,3 s | 27 200 caracteres | (varias páginas de usc.gal) |

- **`campus`**: desde que escribes el comando hasta que termina de pintar, con la caché al día
  (mediana de 7 veces). Es lo normal: lo viejo se renueva en segundo plano.
- **`campus` pidiendo al Campus** (`-f`): sin caché, con un proceso nuevo que arranca el motor y
  abre la sesión.
- **Asistente con MCP**: lo que tarda la herramienta de [mcp-usc](https://github.com/PabloPC05/mcp-usc)
  con el servidor ya arrancado (arrancarlo, 0,3 s). A eso el asistente suma su propio tiempo: decidir
  qué herramienta usar, leer la respuesta (la columna de caracteres: entre 2 000 y 9 000 tokens) y
  escribirte el resumen. Ese tiempo depende del modelo y no está medido aquí.
- **Web del Campus**: Chromium cargando la página con la sesión ya abierta y la caché del navegador
  caliente, hasta que aparece el contenido (mediana de 3). No cuenta abrir el navegador, entrar ni
  buscar las cosas.

**Por qué el horario tarda más.** No viene del Campus: la USC lo publica en usc.gal, página a
página. Pedir una semana son 3 peticiones a cv.usc.es (0,6 s) y 61 a usc.gal, a casi un segundo
cada una (ficha de cada asignatura, sus grupos y la semana). El motor las lanza de 8 en 8 y guarda
en disco lo que no cambia, así que una semana nueva tarda de 6 a 9 s. `campus` la guarda 12 h,
precarga la siguiente y nunca deja que bloquee el Taboleiro.

Por qué `campus` es tan rápido:

- **Caché local.** Cada pantalla se pinta desde una caché privada (ficheros 0600, sin cookies ni
  claves) y no carga nada pesado hasta que de verdad hace falta la red.
- **Refresco en segundo plano.** Si un dato está algo viejo se muestra igualmente y un proceso
  aparte lo renueva para la próxima vez.
- **Una sola sesión.** Si falta algo, todas las consultas de la pantalla salen a la vez sobre una
  única sesión del Campus.

La caché vive en la carpeta de cachés de mcp-usc (`~/Library/Caches/mcp-usc/campus` en macOS;
`USC_CACHE_DIR` la cambia) y `campus limpiar` la vacía junto con las del motor. El motor,
[mcp-usc](https://github.com/PabloPC05/mcp-usc), se instala solo y comparte la sesión: si ya
entraste con `mcp-usc login`, `campus` no te pide nada. El comando también se llama `campus-usc`,
por si `campus` choca con otro.

## Entregar

```sh
campus entregar aed                          # las tareas de la asignatura, numeradas
campus entregar aed 3                        # cómo está: abierta, límites y lo que ya entregaste
campus entregar aed 3 practica.pdf           # la entrega (pregunta antes)
campus entregar aed 3 --retirar              # la retira, como «Eliminar entrega» en la web
campus entregar aed 3 --enviar               # «Enviar para cualificar», si la tarea lo pide
```

Antes de subir nada abre la página de entrega una vez, como «Engadir entrega» en la web. Así
sabe si la tarea sigue abierta, si admite archivos, cuántos y de qué tamaño, y qué tienes ya
entregado. Lo que vas a entregar sustituye a lo anterior, y te lo dice antes de preguntar. Sube
exactamente los bytes que confirmaste (sha256), solo desde la carpeta de los archivos que
nombraste, y al terminar vuelve a abrir la página para comprobar qué archivos tiene Moodle. Si la
tarea pide el paso final, te avisa de que queda como borrador hasta `--enviar`.

## Qué cambia en el Campus

`campus` solo lee, salvo en estos casos, y en todos pregunta antes o espera tu opción:

- `entregar`, `entregar --retirar` y `entregar --enviar` cambian tu entrega. Preguntan antes, o
  necesitan `--si` si no hay terminal.
- `notificaciones N --marcar-leida` marca esa notificación como leída. Leerla sin la opción no
  cambia nada.
- `descargar` abre cada material nuevo, así que queda registrado como visto. Pregunta antes, o
  `--si`, y no vuelve a abrir lo ya descargado.

Todas pasan por la confirmación de un solo uso de mcp-usc. El texto que llega del Campus se limpia
de caracteres de control antes de guardarlo, para que nadie pueda manejar tu terminal con una
notificación.

## Desarrollo

```sh
uv sync --extra dev
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```

El motor se instala desde el zip de `main` de mcp-usc. Cuando cambia, `uv` avisa de que el hash
no coincide: `uv lock --upgrade-package mcp-usc` lo pone al día (el `uv.lock` no se sube).

Para probar a la vez cambios del motor, con mcp-usc clonado al lado:
`uv pip install -e ../mcp-usc`, y luego `.venv/bin/python -m pytest`, porque `uv run` vuelve a
instalar el de GitHub. Las pruebas usan solo datos inventados y nunca tocan la red.
