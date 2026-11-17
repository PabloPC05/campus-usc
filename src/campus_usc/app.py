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

VIEW_MODULES = (  # the order of `campus ayuda`: what a student uses most comes first
    "taboleiro",
    "entregas",
    "entregar",
    "cronograma",
    "notas",
    "foros",
    "mensajes",
    "cuestionarios",
    "notificaciones",
    "cursos",
    "curso",
    "calendario",
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
    from . import modulos

    found.extend(modulos.commands())  # installed modules (campus modulos)
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
    from datetime import date

    from . import sources
    from .style import GREEN, RED, paint
    from .ui import out

    started = time.perf_counter()
    today = date.today()
    from . import modulos

    keys = ["perfil", "cursos", "pendientes", "notificaciones"]
    keys += modulos.collect("actualizar_keys", today)  # installed modules add their data
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
        return fail(auth.NO_BROWSER)
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
            muted("     Chrome o Edge: F12 › Aplicación › Cookies · Firefox: F12 › Almacenamiento"),
            muted("     Safari: activa antes Ajustes › Avanzado › «Mostrar funciones para"),
            muted("     desarrolladores web»; luego Desarrollo › Mostrar inspector web ›"),
            muted("     Almacenamiento › Cookies"),
            "  3. Pégalo aquí (no se ve al escribir). Se comprueba con el Campus antes de",
            "     guardarlo.",
            "",
        ]
    )
    if sys.stdin.isatty():
        cookie = _secret("  MoodleSession: ").strip()
    else:  # piped in, like `docker login --password-stdin`: never echoed
        cookie = sys.stdin.readline().strip()
    if not cookie:
        return fail("No pegaste nada; no se cambió la sesión.")
    try:
        asyncio.run(import_session_cookie(_new_settings(), cookie))
    except SessionImportError as exc:
        return fail(str(exc))
    return 0


def _login(args: argparse.Namespace) -> int:
    import textwrap

    from . import auth, sources
    from .style import GREEN, bold, muted, paint, term_width
    from .ui import navbar, out
    from .views import fail

    out([navbar(["Acceder"]), ""])
    como = (args.como or "").strip().casefold()
    if como and como not in _PASTE_WORDS:
        return fail(
            f"No entiendo «{args.como}». Escribe campus entrar, o campus entrar pegar para "
            "entrar pegando la sesión de tu navegador."
        )
    try:
        if args.pegar or como:
            code = _login_paste(args)
        elif (reason := auth.window_unavailable()) is None:
            code = _login_window(args)
        elif auth.available() and auth.ensure(interactive=False):
            code = 0  # no screen, but the login browser remembered you: renewed silently
        else:  # no window possible here: straight to pasting, saying why
            out(
                [
                    *textwrap.wrap(
                        reason, term_width() - 4, initial_indent="  ", subsequent_indent="  "
                    ),
                    "",
                ]
            )
            code = _login_paste(args)
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


def _salir(args: argparse.Namespace) -> int:
    """Close the session: on the Campus itself, and everything remembered on this computer."""

    import asyncio
    import shutil
    from pathlib import Path

    from . import store
    from .style import AMBER, GREEN, bold, muted, paint
    from .ui import navbar, out
    from .views import fail

    def done(text: str) -> str:
        return "  " + paint("✓", GREEN, bold=True) + " " + text

    out([navbar(["Saír"]), ""])
    settings = _new_settings()
    lines: list[str] = []
    if args.solo_aqui:
        from mcp_usc.session_auth import forget_session_cookie

        try:
            forget_session_cookie()
        except Exception as exc:  # noqa: BLE001 - shown to the person
            return fail(f"No pude borrar la sesión de este ordenador: {exc}")
        lines.append(done("Sesión olvidada en este ordenador (en el Campus sigue abierta)."))
    else:
        from mcp_usc.session_auth import end_campus_session

        try:
            result = asyncio.run(end_campus_session(settings))
        except Exception as exc:  # noqa: BLE001
            return fail(f"No pude cerrar la sesión: {exc}")
        remote = result.get("remote_logout")
        if remote is True:
            lines.append(
                done("Sesión cerrada en el Campus: esa sesión ya no vale en ningún sitio.")
            )
        elif remote is False:
            lines.append(done("La sesión ya estaba cerrada o caducada en el Campus."))
        else:
            lines.append(
                "  "
                + paint("!", AMBER, bold=True)
                + " No pude avisar al Campus; la sesión caducará sola en unas horas."
            )
        lines.append(done("Sesión olvidada en este ordenador."))
        if result.get("environment_session_kept"):
            lines.append(
                "  "
                + paint("!", AMBER, bold=True)
                + " Sigue definida USC_MOODLE_SESSION en tu entorno: bórrala tú."
            )
    profile = Path(settings.browser_profile_dir)
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
        lines.append(done("La ventana de entrar ya no recuerda tu cuenta de Microsoft."))
    removed = store.clear()
    if removed:
        lines.append(done(f"Borrados {removed} datos guardados (notas, mensajes, tareas…)."))
    out(lines + ["", muted("  Para volver a entrar: ") + bold("campus entrar")])
    return 0


def _configure_salir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--solo-aqui",
        action="store_true",
        help="Olvida la sesión en este ordenador sin cerrarla en el Campus",
    )


_PASTE_WORDS = {"pegar", "pega", "pegando"}


def _configure_login(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "como",
        nargs="?",
        metavar="pegar",
        help="«pegar»: entra con tu navegador y pega aquí la sesión, sin ventana aparte",
    )
    # the old spelling, still accepted: campus login --pegar
    parser.add_argument("--pegar", action="store_true", help=argparse.SUPPRESS)
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
        session = paint(" ✗ ", WHITE, RED, bold=True) + f" {exc}  →  {bold('campus entrar')}"
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


def _modulos(args: argparse.Namespace) -> int:
    """What can be added to campus and the one line that adds (or removes) it."""

    from . import modulos
    from .style import GREEN, bold, muted, paint
    from .ui import block, navbar, out

    installed = {module.name for module, _ in modulos.loaded()}
    lines = [navbar(["Módulos"]), block("Módulos", "lo que no es o Campus", 0), ""]
    for module in modulos.KNOWN:
        on = module.name in installed
        mark = paint("● instalado", GREEN, bold=True) if on else muted("○ sin instalar")
        lines.append(f"  {bold(module.name)}  {mark}")
        lines.append(f"    {module.summary}")
        lines.append(muted(f"    Comandos: {module.commands}"))
        wanted = installed - {module.name} if on else installed | {module.name}
        verb = "Quitarlo" if on else "Añadirlo"
        lines.append(muted(f"    {verb}:") + f" {modulos.install_command(wanted)}")
        lines.append("")
    lines.append(muted("  O vuelve a ejecutar el instalador, que te explica cada parte:"))
    installer = "https://raw.githubusercontent.com/PabloPC05/campus-usc/main/instalar.sh"
    lines.append(f"    curl -LsSf {installer} | sh")
    out(lines)
    return 0


def _builtin() -> list[Command]:
    return [
        Command(
            "entrar",
            "Entra en el Campus con tu cuenta de la USC",
            _login,
            _configure_login,
            aliases=("login", "acceder"),
        ),
        Command(
            "salir",
            "Cierra la sesión y borra lo guardado en este ordenador",
            _salir,
            _configure_salir,
            aliases=("logout", "cerrar-sesion"),
        ),
        Command("actualizar", "Trae todo del Campus ahora y lo guarda", _sync, aliases=("sync",)),
        Command("estado", "Si has entrado, y de cuándo es lo guardado", _estado),
        Command(
            "modulos",
            "Partes que puedes añadir (horario y exámenes)",
            _modulos,
            aliases=("módulos",),
        ),
        Command("limpiar", "Borra lo guardado en este ordenador (no cierra sesión)", _limpiar),
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
    lines.append(
        muted("  Para empezar: ")
        + bold("campus entrar")
        + muted("  ·  ")
        + bold("campus entregas")
        + muted("  ·  ")
        + bold("campus entregar 3 practica.pdf")
    )
    lines.append("")
    from . import modulos

    from_modules = {command.name for command in modulos.commands()}
    commands = [command for command in commands if not command.hidden]

    def row(command: Command) -> str:
        # One name per command: the others (aliases, old names) still work, unlisted.
        name = f"  {paint(command.name.ljust(16), BLUE, bold=True)}"
        return name + truncate(command.help, max(10, cells - width(name)))

    lines += [row(command) for command in commands if command.name not in from_modules]
    for module, _ in modulos.loaded():
        lines += ["", muted(f"  Módulo {module.name} · {module.summary}")]
        names = {name.strip() for name in module.commands.split(",")}
        lines += [row(command) for command in commands if command.name in names]
    missing = [module.name for module in modulos.KNOWN if not modulos.installed(module.name)]
    if missing:
        lines += [
            "",
            muted(f"  Módulos que puedes añadir: {', '.join(missing)}  ·  campus modulos"),
        ]
    lines.append("")
    lines.append(muted("  Asignaturas por alias, código o nombre: ia, soi, asr, redes, G4012224…"))
    lines.append(
        muted("  Para programas y agentes: --json  ·  --fresco (sin lo guardado)  ·  --sin-color")
    )
    out(lines)


# --- entry point ----------------------------------------------------------------------


def _utf8_output() -> None:
    """Redirected output in UTF-8, always.

    Windows writes to files and pipes in its old code page (cp1252), which has neither the
    box drawing nor the icons: `campus entregas > tareas.txt`, or an agent reading `campus`,
    crashed with UnicodeEncodeError. A real console is unaffected (Python writes it as text).
    """

    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_output()
    if argv[:1] == ["--refrescar"]:
        from .sources import refresh_main  # it loads the installed modules itself

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
