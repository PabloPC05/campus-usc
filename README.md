# campus

El Campus Virtual de la USC en tu terminal. Tiene la misma barra azul marino, el Taboleiro, el
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
campus notificaciones     # notificacións, sin marcarlas como leídas
campus abrir redes        # abre la asignatura en el navegador
campus estado             # sesión y frescura de la caché · campus ayuda para todo lo demás
```

Las asignaturas se indican por alias, código, número o nombre (`ia`, `soi`, `asr`, `redes`,
`G4012224`). Todo acepta `--json`, `-f` para ignorar la caché y `--sin-color`.

## Instalación

`campus` usa [mcp-usc](https://github.com/PabloPC05/mcp-usc) como motor: la sesión del Campus, el
cliente de Moodle, los horarios y las fechas de examen. Mientras las mejoras de velocidad del motor
no estén publicadas, se instala junto a una copia local de mcp-usc en la carpeta de al lado:

```sh
git clone https://github.com/PabloPC05/mcp-usc ../mcp-usc
uv tool install --editable ".[browser-auth]"
campus login              # Microsoft + MFA en tu Chrome o Edge, una vez
campus actualizar         # lo deja todo en caché (unos 12 s)
```

Si ya entraste con `mcp-usc login`, `campus` usa esa misma sesión.

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

## Qué no hace

`campus` lee: no marca notificaciones como leídas, no entrega ni escribe nada en el Campus. La
única acción con efecto es `descargar`, que abre cada material y por eso queda registrado como
visto: pregunta antes (o `--si`) y no vuelve a abrir lo ya descargado.

## Desarrollo

```sh
uv sync --extra dev
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```

Las pruebas usan solo datos inventados y nunca tocan la red.
