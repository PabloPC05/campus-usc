"""Getting into the Campus without having to think about it.

:func:`ensure` runs when the Campus says the session is over (or there never was one):

1. **silently**, with no window: the login browser remembers your Microsoft account, like
   any browser does, and gets a new Campus session in a few seconds;
2. if Microsoft needs you (the first time, a new password, MFA) and someone is at the
   terminal, a window opens on the Campus's Microsoft sign-in and closes by itself.

The background refresher only tries step 1. After a silent attempt fails it is not
retried for ten minutes, so an expired account never keeps a browser busy.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from typing import Any

from . import store

SILENT_RETRY = 600  # seconds after a failed silent renewal before trying it again
_MARK = "login"  # cache entry with the last failed silent renewal (no secrets)

INTRO = (
    "",
    "  Para ver tu Campus hay que entrar con tu cuenta de la USC.",
    "  Se abre una ventana: escribe tu correo y tu contraseña de la USC y acepta el aviso",
    "  del móvil, igual que en la web. Si pregunta «¿Mantener la sesión iniciada?», pulsa",
    "  «Sí»: así las próximas veces entrará solo. La ventana se cierra sola al acabar.",
    "",
)


NO_SCREEN = (
    "Este ordenador no tiene pantalla para la ventana de entrar (¿estás por SSH?). "
    "Entra desde el navegador de otro equipo y pega la sesión: campus login --pegar"
)


def has_screen() -> bool:
    """Whether a login window can open here (a Linux server over SSH has no display)."""

    import os

    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def available() -> bool:
    """Whether the login browser (Playwright) is installed with the engine."""

    return importlib.util.find_spec("playwright") is not None


def _settings() -> Any:
    from mcp_usc.settings import Settings

    return Settings.from_env()


def _say(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _recently_failed() -> bool:
    cached = store.read(_MARK)
    if not cached or not isinstance(cached[0], dict):
        return False
    return time.time() - float(cached[0].get("silent_failed_at") or 0) < SILENT_RETRY


def silent(settings: Any | None = None) -> bool:
    """A new Campus session with no window, when the login browser still remembers you."""

    import asyncio

    from mcp_usc.campus import CampusError, renew_session_silently

    try:
        renewed = asyncio.run(renew_session_silently(settings or _settings()))
    except (CampusError, TimeoutError, OSError):
        renewed = False
    store.write(_MARK, {} if renewed else {"silent_failed_at": time.time()})
    return renewed


def window(settings: Any | None = None, minutes: int = 15) -> None:
    """The visible sign-in window; downloads its browser the first time if there is none."""

    import asyncio

    from mcp_usc.campus import LoginBrowserUnavailable, install_login_browser, interactive_login

    settings = settings or _settings()
    try:
        asyncio.run(interactive_login(settings, minutes * 60))
    except LoginBrowserUnavailable:
        _say("  Preparando el navegador para entrar (solo la primera vez; tarda un minuto)…")
        install_login_browser()
        asyncio.run(interactive_login(settings, minutes * 60))
    store.write(_MARK, {})


def ensure(*, interactive: bool, minutes: int = 15) -> bool:
    """True once there is a working Campus session again."""

    if not available():
        return False
    from mcp_usc.campus import CampusError

    from .sources import Spinner

    settings = _settings()
    if not _recently_failed():
        spinner = Spinner("Renovando la sesión del Campus") if interactive else None
        if spinner:
            spinner.start()
        try:
            if silent(settings):
                return True
        finally:
            if spinner:
                spinner.stop()
    if not interactive:
        return False
    if not has_screen():
        _say("  " + NO_SCREEN)
        return False
    for line in INTRO:
        _say(line)
    try:
        window(settings, minutes)
    except (CampusError, TimeoutError) as exc:
        from .views import fail

        fail(str(exc))
        return False
    return True


class SessionExpired(Exception):
    """The Campus asked for a login before anything was changed: safe to run again."""


def run_with_session(attempt: Any, *, interactive: bool) -> int:
    """``attempt()``; if it raises :class:`SessionExpired`, get in and try once more."""

    from .views import fail

    for tries in range(2):
        try:
            return attempt()
        except SessionExpired:
            if tries or not ensure(interactive=interactive):
                break
    return fail("La sesión del Campus caducó y no se pudo renovar: prueba `campus login`.")


__all__ = ["SessionExpired", "available", "ensure", "run_with_session", "silent", "window"]
