"""`campus`: the USC Campus Virtual in your terminal.

Starts in milliseconds: only the standard library is imported until a screen actually
needs the network, and every screen renders from the local cache first.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import sys
import time
from typing import Any

from .views import Command

VIEW_MODULES = (
    "taboleiro",
    "cronograma",
    "horario",
    "examenes",
    "calendario",
    "cursos",
    "curso",
    "entregar",
    "entregas",
    "notificaciones",
)
_GLOBAL_FLAGS = {"--json": "json", "-f": "fresco", "--fresco": "fresco", "--sin-color": "no_color"}


def _commands() -> list[Command]:
    found: list[Command] = []
    for name in VIEW_MODULES:
        try:
            module = importlib.import_module(f"{__package__}.views.{name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"{__package__}.views.{name}":
                continue
            raise
        found.extend(getattr(module, "COMMANDS", []))
    found.extend(_builtin())
    return found


def _split_globals(argv: list[str]) -> tuple[dict[str, bool], list[str]]:
    flags = {"json": False, "fresco": False, "no_color": False}
    rest = []
    for value in argv:
        if value in _GLOBAL_FLAGS:
            flags[_GLOBAL_FLAGS[value]] = True
        else:
            rest.append(value)
    return flags, rest


# --- built-in commands ----------------------------------------------------------------


def _sync(args: argparse.Namespace) -> int:
    from datetime import date, timedelta

    from . import sources
    from .style import GREEN, RED, paint
    from .ui import out

    started = time.perf_counter()
    today = date.today()
    keys = [
        "perfil",
        "cursos",
        "pendientes",
        "notificaciones",
        sources.horario_key(today),
        sources.horario_key(today + timedelta(days=7)),
        sources.examenes_key(),
    ]
    from . import store
    from .courses import current
    from .ui import course_title

    def course_keys() -> list[str]:
        cached = store.read("cursos")
        courses = current(cached[0]) if cached and cached[0] else []
        return [f"contenidos/{course['id']}" for course in courses]

    # Each course page too, so `campus curso X` is instant from the start. Without a cached
    # course list, it is fetched first and the pages follow in a second round.
    contents = course_keys()
    results = sources.fetch_now(keys + contents)
    if not contents:
        contents = course_keys()
        results.update(sources.fetch_now(contents) if contents else {})
    keys += contents
    titles = {
        f"contenidos/{course['id']}": course_title(course.get("full_name"))
        for course in ((store.read("cursos") or ([], 0))[0] or [])
    }
    lines = []
    for key in keys:
        result = results[key]
        mark = paint("✓", GREEN, bold=True) if result.ok else paint("✗", RED, bold=True)
        label = sources.source(key).label
        detail = titles.get(key) or key.partition("/")[2]
        lines.append(
            f"  {mark} {label}{f' ({detail})' if detail else ''}"
            + (f"  {result.error}" if result.error else "")
        )
    lines.append(f"\n  Listo en {time.perf_counter() - started:.1f} s. Todo queda en caché.")
    out(lines)
    return 0 if all(r.ok for r in results.values()) else 1


def _limpiar(args: argparse.Namespace) -> int:
    from . import store
    from .ui import out

    removed = store.clear()
    # The engine's own disk caches (subject locations, timetable discovery) live beside it.
    from mcp_usc.disk_cache import disk_cache_root

    root = disk_cache_root()
    for folder in root.iterdir() if root.is_dir() else ():
        if folder.is_dir() and folder != store.cache_dir():
            for item in folder.glob("*.json"):
                with contextlib.suppress(OSError):
                    item.unlink()
                    removed += 1
    out(f"  Borrados {removed} ficheros de caché ({root}).")
    return 0


LOGIN_URL = "https://cv.usc.es/login/index.php"


def _new_settings() -> Any:
    from mcp_usc.settings import Settings

    return Settings.from_env()


def _secret(prompt: str) -> str:
    import getpass

    return getpass.getpass(prompt)


def _login_window(args: argparse.Namespace) -> int:
    """Silently if the login browser remembers you; otherwise the sign-in window."""

    from . import auth
    from .views import fail

    if not auth.available():
        return fail(
            "Falta el navegador del login: reinstala campus-usc "
            "o entra con tu navegador: campus login --pegar"
        )
    return 0 if auth.ensure(interactive=True, minutes=args.minutos) else 1


def _login_paste(args: argparse.Namespace) -> int:
    """Your own browser: log in there, then paste its MoodleSession cookie (hidden input)."""

    import asyncio
    import webbrowser

    from mcp_usc.session_auth import SessionImportError, import_session_cookie

    from .style import BLUE, bold, link, muted, paint
    from .ui import out
    from .views import fail

    opened = webbrowser.open(LOGIN_URL)
    out(
        [
            f"  1. {'Abrí' if opened else 'Abre'} "
            + link(paint(LOGIN_URL, BLUE, bold=True), LOGIN_URL)
            + " en tu navegador y entra como siempre.",
            "  2. Copia el valor de la cookie " + bold("MoodleSession") + " de cv.usc.es:",
            muted("     Safari: Desarrollo › Mostrar inspector web › Almacenamiento › Cookies"),
            muted("     Chrome/Edge: F12 › Aplicación › Cookies · Firefox: F12 › Almacenamiento"),
            "  3. Pégalo aquí (no se ve al escribir). Se comprueba con el Campus antes de",
            "     guardarlo.",
            "",
        ]
    )
    if not sys.stdin.isatty():
        return fail("Esto necesita una terminal para pegar la cookie sin que se vea.")
    cookie = _secret("  MoodleSession: ").strip()
    if not cookie:
        return fail("No pegaste nada; no se cambió la sesión.")
    try:
        asyncio.run(import_session_cookie(_new_settings(), cookie))
    except SessionImportError as exc:
        return fail(str(exc))
    return 0


def _login(args: argparse.Namespace) -> int:
    from . import sources
    from .style import GREEN, bold, muted, paint
    from .ui import navbar, out

    out([navbar(["Acceder"]), ""])
    try:
        code = _login_paste(args) if args.pegar else _login_window(args)
    except KeyboardInterrupt:
        return 130
    if code:
        return code
    # Who is in now (and the navbar's name, cached for every screen).
    perfil = sources.fetch_now(["perfil"], quiet=True)["perfil"]
    name = (perfil.data or {}).get("fullname") if perfil.ok else None
    out(
        "  "
        + paint("✓ Sesión iniciada", GREEN, bold=True)
        + (f" como {bold(name)}" if name else "")
        + muted("  ·  campus actualizar lo deja todo listo")
    )
    return 0


def _configure_login(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pegar",
        action="store_true",
        help="Entra con tu navegador y pega aquí su cookie MoodleSession (sin ventana aparte)",
    )
    parser.add_argument(
        "--minutos", type=int, default=15, help="Tiempo para completar el login (15)"
    )


def _estado(args: argparse.Namespace) -> int:
    """Session check (the one call that always uses the network) and cache freshness."""

    import asyncio

    from . import sources, store
    from .style import GREEN, RED, WHITE, bold, muted, paint
    from .ui import block, navbar, out

    started = time.perf_counter()
    try:
        from mcp_usc.service import UscService

        status = asyncio.run(UscService().auth_status())
        session = (
            paint(" ✓ ", WHITE, GREEN, bold=True)
            + f" Sesión activa como {bold(str(status.get('user_name') or '?'))}"
            + muted(f"  ({status.get('method')})")
        )
        code = 0
    except Exception as exc:  # noqa: BLE001 - shown to the person, never raised
        session = paint(" ✗ ", WHITE, RED, bold=True) + f" {exc}  →  {bold('campus login')}"
        code = 1
    lines = [navbar(["Estado"]), "", " " + session, block("Caché local", str(store.cache_dir()))]
    entries = sorted(store.cache_dir().glob("*.json")) if store.cache_dir().is_dir() else []
    for path in entries:
        key = path.stem
        name = key.split("_", 1)[0]
        cached = store.read(key)
        if name not in sources.SOURCES or cached is None:
            continue
        spec = sources.SOURCES[name]
        age = cached[1]
        state = (
            paint("fresco", GREEN)
            if age < spec.ttl
            else paint("se refresca al usarlo", "#f0ad4e")
            if age < spec.max_stale
            else paint("caducado", RED)
        )
        label = f"{spec.label}{' · ' + key.split('_', 1)[1] if '_' in key else ''}"
        lines.append(f"  {label:<32} {sources.describe_age(age):<16} {state}")
    if not entries:
        lines.append(muted("  Vacía: la primera consulta de cada pantalla la llenará."))
    lines.append(muted(f"\n  {time.perf_counter() - started:.2f} s"))
    out(lines)
    return code


def _builtin() -> list[Command]:
    return [
        Command(
            "actualizar", "Descarga todo de nuevo y lo deja en caché", _sync, aliases=("sync",)
        ),
        Command("estado", "Comprueba la sesión y lo fresca que está la caché", _estado),
        Command("limpiar", "Borra las cachés locales (CLI y motor)", _limpiar),
        Command(
            "login",
            "Inicia sesión en el Campus (Microsoft + MFA)",
            _login,
            _configure_login,
            aliases=("acceder",),
        ),
    ]


# --- help -----------------------------------------------------------------------------


def _help(commands: list[Command]) -> None:
    from .style import BLUE, bold, muted, paint, term_width, truncate, width
    from .ui import navbar, out

    cells = term_width()
    lines = [navbar(["Axuda"], cells=cells), ""]
    lines.append(
        "  " + bold("campus") + muted(" [orden] [opciones]   ·   sin orden abre el Taboleiro")
    )
    lines.append("")
    for command in commands:
        name = f"  {paint(command.name.ljust(16), BLUE, bold=True)}"
        aliases = muted(f"  ({', '.join(command.aliases)})") if command.aliases else ""
        line = name + command.help + aliases
        if width(line) > cells:  # narrow terminal: drop the aliases, then shorten the help
            line = name + truncate(command.help, cells - width(name))
        lines.append(line)
    lines.append("")
    lines.append(
        muted("  Opciones comunes: --json  ·  -f/--fresco (ignora la caché)  ·  --sin-color")
    )
    lines.append(muted("  Asignaturas por alias, código o nombre: ia, soi, asr, redes, G4012224…"))
    out(lines)


# --- entry point ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--refrescar"]:
        from .sources import refresh_main

        raise SystemExit(refresh_main(argv[1:]))
    flags, argv = _split_globals(argv)
    if flags["no_color"]:
        from .style import caps

        caps.reset(color=False)
    commands = _commands()
    if argv[:1] in (["-h"], ["--help"], ["ayuda"], ["help"]):
        _help(commands)
        raise SystemExit(0)
    if argv[:1] in (["-V"], ["--version"]):
        from mcp_usc import __version__ as engine

        from . import __version__

        print(f"campus-usc {__version__} (mcp-usc {engine})")
        raise SystemExit(0)
    parser = argparse.ArgumentParser(prog="campus", add_help=False)
    subparsers = parser.add_subparsers(dest="command")
    handlers = {}
    for command in commands:
        sub = subparsers.add_parser(command.name, aliases=list(command.aliases), help=command.help)
        if command.configure:
            command.configure(sub)
        for name in (command.name, *command.aliases):
            handlers[name] = command.run
    if not argv:
        argv = ["inicio"] if "inicio" in handlers else ["pendientes"]
    args = parser.parse_args(argv)
    args.json, args.fresco = flags["json"], flags["fresco"]
    try:
        code = handlers[args.command](args)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(code)
