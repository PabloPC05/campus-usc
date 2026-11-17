# campus-usc

El Campus Virtual de la USC en tu terminal, con el comando `campus`. Tiene la misma barra azul marino, el Taboleiro, el
Cronograma y «Os meus cursos», con los colores del tema de cv.usc.es. Cada asignatura sale en el
color que Moodle da a su tarjeta y las etiquetas están en gallego, como en la web.

Cada pantalla se pinta en unos 30 ms.

```sh
campus                    # Taboleiro: hoxe, calendario, cronograma, próximos exames e cursos
campus pendientes         # Cronograma (-a atrasadas, -d 30 días, -c por cursos, «redes» solo esa)
campus horario            # tu semana en rejilla (+1 la siguiente, --grupos CLE_01 CLIL_02 --guardar-grupos)
campus hoy                # clases y entregas de hoy, con lo que tienes «agora»
campus examenes           # fechas oficiales, con cuenta atrás
campus calendario         # el mes, con entregas y exámenes marcados
campus cursos             # «Os meus cursos» en tarjetas, con su alias para los demás comandos
campus curso ia           # la página de la asignatura: secciones, actividades y lo pendiente
campus materiales ia      # sus archivos y carpetas
campus descargar ia       # baja sus materiales con barra de progreso (pregunta antes)
campus entregar aed       # sus tareas; «campus entregar aed 3 practica.pdf» la entrega
campus notificaciones     # notificacións numeradas; «campus notificaciones 3» lee una entera
campus abrir redes        # abre la asignatura en el navegador
campus estado             # sesión y frescura de la caché · campus ayuda para todo lo demás
```

Las asignaturas se indican por alias, código, número o nombre (`ia`, `soi`, `asr`, `redes`,
`G4012224`). Todo acepta `--json`, `-f` para ignorar la caché y `--sin-color`.

## Instalación

Necesitas [uv](https://docs.astral.sh/uv/). No hace falta git:

```sh
uv tool install "campus-usc[browser-auth] @ https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"
campus login              # una vez: tu cuenta de la USC (Microsoft + MFA)
campus actualizar         # lo deja todo en caché (unos 12 s)
```

Para actualizar, repite la instalación con `--reinstall --refresh`. El motor es
[mcp-usc](https://github.com/PabloPC05/mcp-usc): la sesión del Campus, el cliente de Moodle, los
horarios y las fechas de examen. Se instala solo y comparte la sesión, así que si ya entraste con
`mcp-usc login`, `campus` no te pide nada. El comando también se llama `campus-usc`, por si
`campus` choca con otro.

## Iniciar sesión

`campus login` abre una ventana de navegador en cv.usc.es. Entras con tu cuenta como en la web, y
cuando el Campus te deja pasar se cierra sola y guarda la cookie de sesión en el llavero del
sistema, nunca la contraseña. Usa tu Chrome o Edge y, si no tienes ninguno, ofrece descargar un
navegador solo para esto.

No puede funcionar como las apps que te dan un enlace y recogen la sesión al volver. En Moodle eso
es el inicio de sesión de la app móvil, y la USC lo tiene desactivado (`enablemobilewebservice = 0`).
Además, la cookie del Campus es `HttpOnly` y ninguna página puede pasársela a la terminal. Si
prefieres tu propio navegador, `campus login --pegar` te abre el enlace, te dice dónde copiar la
cookie `MoodleSession` y te la pide sin que se vea. La comprueba con el Campus antes de guardarla.

## Por qué es instantánea

- **Caché local.** Cada pantalla se pinta desde una caché privada (ficheros 0600, sin cookies ni
  claves) y no importa nada pesado hasta que de verdad hace falta la red.
- **Refresco en segundo plano.** Si un dato está algo viejo se muestra igualmente y un proceso
  aparte lo renueva para la próxima vez.
- **Una sola sesión.** Si falta algo, todas las consultas de la pantalla salen a la vez sobre una
  única sesión del Campus.
- **Lo lento no bloquea.** Localizar tus asignaturas en los planes de estudio (para horario y
  exámenes) nunca bloquea el Taboleiro, y al ver una semana se precarga la siguiente.

La caché vive en la carpeta de cachés de mcp-usc (`~/Library/Caches/mcp-usc/campus` en macOS;
`USC_CACHE_DIR` la cambia) y `campus limpiar` la vacía junto con las del motor.

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

Para probar a la vez cambios del motor, con mcp-usc clonado al lado:
`uv pip install -e ../mcp-usc`, y luego `.venv/bin/python -m pytest`, porque `uv run` vuelve a
instalar el de GitHub. Las pruebas usan solo datos inventados y nunca tocan la red.
