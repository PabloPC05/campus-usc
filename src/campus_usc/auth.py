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
    "Escribe campus entrar: te dirá cómo entrar con el navegador de otro equipo."
)
# What `campus entrar` says before asking for the session by hand.
NO_SCREEN_PASTE = (
    "Este ordenador no tiene pantalla para abrir la ventana de entrar (¿estás por SSH?): "
    "entra con el navegador de otro equipo y pega aquí la sesión."
)
NO_BROWSER_PASTE = (
    "No encuentro Chrome, Edge, Brave ni Chromium para abrir la ventana de entrar: entra con "
    "tu navegador y pega aquí la sesión. (Para no tener que hacerlo, instala Chrome o Edge, o "
    "añade el navegador incluido con el instalador: campus modulos te dice cómo.)"
)


def has_screen() -> bool:
    """Whether a login window can open here (a Linux server over SSH has no display)."""

    import os

    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def session_saved() -> bool:
    """Whether a Campus session is stored here (expired or not) or you never logged in."""

    try:
        from mcp_usc.credentials import CredentialStore
        from mcp_usc.session_auth import SESSION_CREDENTIAL_NAME

        return bool(CredentialStore().get(SESSION_CREDENTIAL_NAME))
    except Exception:  # noqa: BLE001 - only picks the wording of a message
        return False


ENGINE_ZIP = "https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"
NO_BROWSER = (
    "No encuentro Chrome, Edge, Brave ni Chromium para la ventana de entrar. Puedes instalar "
    "uno de ellos, entrar con tu navegador pegando la sesión (campus entrar pegar) o añadir "
    "el navegador incluido (unos 160 MB): "
    f'uv tool install --reinstall "campus-usc[navegador] @ {ENGINE_ZIP}"'
)


def bundled_browser() -> bool:
    """Whether the bundled login browser (Playwright, the `navegador` extra) is installed."""

    return importlib.util.find_spec("playwright") is not None


def window_unavailable() -> str | None:
    """Why the sign-in window cannot open here (no screen, no browser), or None if it can."""

    if not has_screen():
        return NO_SCREEN_PASTE
    if not available():
        return NO_BROWSER_PASTE
    return None


def available() -> bool:
    """Whether a login window can be opened: your Chrome/Edge/Brave, or the bundled one."""

    from mcp_usc.system_browser import find_browser

    return find_browser() is not None or bundled_browser()


def _settings() -> Any:
    from mcp_usc.settings import Settings

    return Settings.from_env()


def _say(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def remembers_someone(settings: Any | None = None) -> bool:
    """Whether the login window was ever used here: only then can it renew with no window.

    The first time (or after `campus salir`) there is no profile, so trying the silent way
    would only make the person wait some 20 s before the window opens.
    """

    from pathlib import Path

    try:
        folder = Path((settings or _settings()).browser_profile_dir)
        return folder.is_dir() and any(folder.iterdir())
    except (OSError, AttributeError, TypeError):
        return False


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
        if not bundled_browser():
            raise
        # Only with the `navegador` extra: its browser engine is fetched the first time.
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
    if not _recently_failed() and remembers_someone(settings):
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
    return fail("La sesión del Campus caducó y no se pudo renovar: prueba `campus entrar`.")


__all__ = [
    "SessionExpired",
    "available",
    "ensure",
    "run_with_session",
    "silent",
    "window",
    "window_unavailable",
]
