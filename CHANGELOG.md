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
- `login`: ventana de navegador para Microsoft + MFA que se cierra sola, o `--pegar` para entrar
  con tu propio navegador y pegar la cookie (se valida antes de guardarla). Saluda con tu nombre.
- Instalable sin git desde GitHub; el comando también se llama `campus-usc`.
- Instantánea: cada pantalla se pinta en ~30 ms desde una caché local privada (0600, sin
  credenciales), con refresco en segundo plano de lo que está viejo, una sola sesión para todas las
  consultas de una pantalla y los bloques lentos del Taboleiro diferidos para no bloquearlo.
