# Cambios

## [0.1.0] - Sin publicar

Primera versión, separada de mcp-usc en su propio repositorio.

- Aspecto del Campus: barra azul marino con la marca USC y tus iniciales, etiquetas en gallego
  como en cv.usc.es, iconos de actividad con los colores de Moodle 4 y cada asignatura en el color
  de su tarjeta de «Os meus cursos».
- Pantallas: Taboleiro (por defecto), Cronograma (`pendientes`), `horario` en rejilla semanal con
  grupos recordados, `hoy`/`mañana`, `examenes` con cuenta atrás y línea de tiempo, `calendario`
  mensual, `cursos` en tarjetas, `curso` (secciones y actividades), `materiales`, `descargar` con
  barra de progreso, `abrir`, `notificaciones` (solo lectura), `estado`, `actualizar`, `limpiar` y
  `login`.
- Instantánea: cada pantalla se pinta en ~30 ms desde una caché local privada (0600, sin
  credenciales), con refresco en segundo plano de lo que está viejo, una sola sesión para todas las
  consultas de una pantalla y los bloques lentos del Taboleiro diferidos para no bloquearlo.
