# Cambios

## [0.1.0] - Sin publicar

Primera versión, separada de mcp-usc en su propio repositorio.

- Aspecto del Campus: barra azul marino con la marca USC y tus iniciales, etiquetas en gallego
  como en cv.usc.es, iconos de actividad con los colores de Moodle 4 y cada asignatura en el color
  de su tarjeta de «Os meus cursos».
- Pantallas: Taboleiro (por defecto), Cronograma (`pendientes`), `horario` en rejilla semanal con
  grupos recordados, `hoy`/`mañana`, `examenes` con cuenta atrás y línea de tiempo, `calendario`
  mensual, `cursos` en tarjetas, `curso` (secciones y actividades), `materiales`, `descargar` con
  barra de progreso, `abrir`, `notificaciones`, `estado`, `actualizar`, `limpiar` y
  `login`.
- `entregar`: lista las tareas de una asignatura, enseña cómo está tu entrega (abierta, límites,
  archivos y «Estado da entrega»), entrega archivos preguntando antes, comprueba después qué tiene
  Moodle, avisa si queda como borrador y permite `--retirar` y `--enviar`. Se probó de verdad en
  una tarea del curso 2025/2026: se entregó y se retiró, y quedó como estaba.
- `notificaciones`: numeradas; `notificaciones N` lee una entera (texto completo y enlace) y
  `--marcar-leida` la marca como leída en el Campus.
- El texto que llega del Campus se limpia de caracteres de control antes de guardarlo (nada puede
  mover el cursor ni cambiar el título de la terminal); la caché pasa al formato 2.
- Entrar sin pensar en ello: si no hay sesión o caducó, `campus` la renueva solo y sin ventana
  cuando la ventana de entrar recuerda tu cuenta de Microsoft, y si hace falta abre la ventana
  ahí mismo y sigue con lo que pediste. `campus login` hace lo mismo; `--pegar` entra con tu
  propio navegador. El navegador del login viene incluido y se descarga solo si falta.
- `entregas`: las próximas tareas por entregar, por fecha, cada una con su `campus entregar`;
  las atrasadas que aún admiten entrega, aparte (`-a`).
- Instalable sin git desde GitHub en dos pasos; el comando también se llama `campus-usc`.
- README con medidas de velocidad frente a un asistente con MCP y la web del Campus.
- Revisado contra la web del Campus, asignatura por asignatura:
  - los cursos con más de 100 actividades salen enteros (a IA le faltaban 46), y el Cronograma
    se pide completo aunque pase de 50 eventos;
  - «atrasadas» son solo las que aún admiten entrega: las cerradas (sobre todo prácticas de
    otros grupos) ya no inflan los avisos y con `-a` salen en gris como «pechada»;
  - en la página de un curso, cada tarea pendiente lleva su aviso («Pendente · en 2 días»,
    «Atrasada», «pechada»);
  - las etiquetas muestran el texto del profesor, no el nombre recortado de Moodle;
  - si la sesión caduca justo al entregar, descargar o marcar una notificación, se renueva y
    el comando sigue;
  - `descargar` probado de verdad (un PDF de un curso pasado) y ninguna pantalla se pasa de
    80 columnas.
- El resto del Campus:
  - `notas`: «Cualificacións» con la nota de cada asignatura, y el informe de una con cada
    elemento, su intervalo y el comentario del profesor;
  - `avisos`: los anuncios de todas tus asignaturas, el más nuevo primero y los no leídos
    siempre a la vista; `foros` los de una asignatura y sus debates; `debate N` uno entero,
    con hilos, párrafos y anexos;
  - `mensajes`: conversaciones por persona sin marcarlas como leídas, cada una entera, y
    `escribir` para enviar uno (lo enseña y pregunta antes);
  - `cuestionarios`: los de cada asignatura, y el detalle de uno con fechas, tiempo límite,
    intentos permitidos, tus intentos y tu nota.
- Instantánea: cada pantalla se pinta en ~30 ms desde una caché local privada (0600, sin
  credenciales), con refresco en segundo plano de lo que está viejo, una sola sesión para todas las
  consultas de una pantalla y los bloques lentos del Taboleiro diferidos para no bloquearlo.
