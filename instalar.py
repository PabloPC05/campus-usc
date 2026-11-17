# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Instalador de campus-usc: explica qué se instala y por qué, y lo instala.

Lo arrancan instalar.sh (Mac y Linux) e instalar.ps1 (Windows) con `uv run`; también se
puede ejecutar a mano: `uv run instalar.py`. Solo usa la biblioteca estándar.

    --si                  no preguntes: lo recomendado para este ordenador
    --horarios / --sin-horarios
    --navegador / --sin-navegador
    --simular             enseña el plan y no instala nada
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

REPO_ZIP = "https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"
CORE_MB = 40
BROWSER_MB = 160

# --- what this computer has -----------------------------------------------------------------

_MAC = (
    ("Chrome", "/Applications/Google Chrome.app"),
    ("Edge", "/Applications/Microsoft Edge.app"),
    ("Brave", "/Applications/Brave Browser.app"),
    ("Chromium", "/Applications/Chromium.app"),
)
_WINDOWS = (
    ("Chrome", r"Google\Chrome\Application\chrome.exe"),
    ("Edge", r"Microsoft\Edge\Application\msedge.exe"),
    ("Brave", r"BraveSoftware\Brave-Browser\Application\brave.exe"),
)
_LINUX = (
    ("Chrome", "google-chrome"),
    ("Chrome", "google-chrome-stable"),
    ("Edge", "microsoft-edge"),
    ("Brave", "brave-browser"),
    ("Chromium", "chromium"),
    ("Chromium", "chromium-browser"),
)


@dataclass
class Machine:
    system: str  # "macOS" | "Windows" | "Linux"
    browser: str | None  # a Chromium browser the login window can use
    screen: bool  # False: a server or a session over SSH
    installed: bool  # campus-usc is already there
    others: list[str] = field(default_factory=list)  # other browsers seen (Safari, Firefox)


def find_browser(system: str) -> str | None:
    if system == "macOS":
        for name, path in _MAC:
            if Path(path).exists() or (Path.home() / path.lstrip("/")).exists():
                return name
        return None
    if system == "Windows":
        roots = [os.getenv(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for name, relative in _WINDOWS:
            if any(root and (Path(root) / relative).exists() for root in roots):
                return name
        return None
    for name, command in _LINUX:
        if shutil.which(command):
            return name
    return None


def look() -> Machine:
    system = {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), "Linux")
    screen = True
    if system == "Linux":
        screen = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    others = []
    if system == "macOS" and Path("/Applications/Safari.app").exists():
        others.append("Safari")
    if shutil.which("firefox") or Path("/Applications/Firefox.app").exists():
        others.append("Firefox")
    installed = False
    uv = shutil.which("uv")
    if uv:
        listing = subprocess.run([uv, "tool", "list"], capture_output=True, text=True, check=False)
        installed = any(line.startswith("campus-usc ") for line in listing.stdout.splitlines())
    return Machine(system, find_browser(system), screen, installed, others)


# --- what to recommend ----------------------------------------------------------------------


@dataclass
class Plan:
    horarios: bool
    navegador: bool

    def extras(self) -> list[str]:
        return [
            name for name, on in (("horarios", self.horarios), ("navegador", self.navegador)) if on
        ]

    def target(self) -> str:
        extras = self.extras()
        name = f"campus-usc[{','.join(extras)}]" if extras else "campus-usc"
        return f"{name} @ {REPO_ZIP}"

    def size_mb(self) -> int:
        return CORE_MB + (BROWSER_MB if self.navegador else 0)


def recommend_browser(machine: Machine) -> tuple[bool, str]:
    """(install the bundled browser?, why), for this computer."""

    if not machine.screen:
        return False, (
            "No hace falta: este ordenador no tiene pantalla (¿estás por SSH?). Entrarás con "
            "campus login --pegar, copiando la sesión desde el navegador de otro equipo."
        )
    if machine.browser:
        return False, (
            f"No hace falta: tienes {machine.browser}, y la ventana de entrar se abrirá en él "
            "(con un perfil aparte, sin tocar tus pestañas ni tus datos)."
        )
    seen = " y ".join(machine.others) or "ningún navegador compatible"
    return True, (
        f"Recomendado: no encuentro Chrome, Edge, Brave ni Chromium (veo {seen}), y la ventana "
        "de entrar necesita uno de ellos. Sin él también se puede entrar, pero copiando la "
        "sesión a mano (campus login --pegar)."
    )


# --- the menu ---------------------------------------------------------------------------------

_COLOR = bool(os.getenv("FORCE_COLOR")) or (sys.stdout.isatty() and not os.getenv("NO_COLOR"))


def _paint(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _COLOR else text


def bold(text: str) -> str:
    return _paint(text, "1")


def muted(text: str) -> str:
    return _paint(text, "2")


def header(text: str) -> str:
    return _paint(f" {text} ", "1;38;2;225;244;241;48;2;0;0;102")


def ask(question: str, default: bool) -> bool:
    hint = "[S/n]" if default else "[s/N]"
    try:
        answer = input(f"  {question} {hint} ").strip().casefold()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in {"s", "si", "sí", "y", "yes"}


def describe(machine: Machine) -> list[str]:
    if not machine.screen:
        login = "pegando la sesión (campus login --pegar), sin ventana"
    elif machine.browser:
        login = f"con una ventana de {machine.browser}"
    else:
        login = "con el navegador incluido (punto 3) o pegando la sesión"
    return [
        "",
        header("USC") + "  " + bold("Instalar campus-usc · el Campus Virtual en tu terminal"),
        "",
        "  Lo que he visto en este ordenador:",
        f"   · Sistema: {machine.system}",
        f"   · Navegador para la ventana de entrar: {machine.browser or 'ninguno compatible'}"
        + (muted(f"  (también tienes {', '.join(machine.others)})") if machine.others else ""),
        f"   · Pantalla: {'sí' if machine.screen else 'no (servidor o SSH)'}",
        f"   · Cómo entrarás en el Campus: {login}",
        *(
            ["   · campus-usc ya está instalado: esto lo actualiza y cambia sus partes"]
            if machine.installed
            else []
        ),
        "",
    ]


def heading(title: str, size: str) -> str:
    """A part's title with its size at the right; every size in the same column."""

    return bold(f"  {title}".ljust(66) + size.rjust(9))


def install_line(plan: Plan) -> str:
    return f'uv tool install --reinstall "{plan.target()}"'


def parts(machine: Machine) -> list[str]:
    _, why = recommend_browser(machine)
    return [
        heading("1. El Campus  (siempre)", f"~{CORE_MB} MB"),
        "     Tareas y entregas, notas, avisos y foros, mensajes, cuestionarios, materiales,",
        "     notificaciones y tus cursos. Cada pantalla tarda unos 30 ms.",
        "",
        heading("2. Horario y exámenes  (opcional)", "+0,3 MB"),
        "     Añade campus horario, hoy, mañana y examenes, y los muestra en el Taboleiro.",
        "     No son del Campus sino de usc.gal: la primera vez tardan 1 o 2 minutos en",
        "     localizar tus asignaturas en los planes de estudio; luego, al momento.",
        "",
        heading("3. Navegador incluido para entrar  (opcional)", f"+{BROWSER_MB} MB"),
        "     Solo sirve si no tienes Chrome, Edge, Brave ni Chromium. La primera vez que",
        "     entres descarga además su motor de navegador (un minuto más).",
        *("     " + line for line in textwrap.wrap(why, 80)),
        "",
    ]


def summary(plan: Plan) -> list[str]:
    chosen = ["el Campus"]
    if plan.horarios:
        chosen.append("horario y exámenes")
    if plan.navegador:
        chosen.append("el navegador incluido")
    seconds = "10–30 s" if plan.navegador else "unos 10 s"
    return [
        "",
        "  " + bold("Se instalará: ") + ", ".join(chosen),
        f"  Ocupará unos {plan.size_mb()} MB y tardará {seconds}.",
        "",
    ]


def choose(machine: Machine, options: argparse.Namespace) -> Plan:
    """The questions in the order of the list above: 2 (horario) and then 3 (navegador)."""

    horarios = bool(options.horarios)
    if options.horarios is None and not options.si:
        horarios = ask("¿Añado horario y exámenes (2)?", False)
    wants_browser, _ = recommend_browser(machine)
    if options.navegador is not None:
        wants_browser = options.navegador
    elif not options.si and machine.screen:
        wants_browser = ask("¿Añado el navegador incluido (3)?", wants_browser)
    return Plan(horarios=horarios, navegador=wants_browser)


# --- installing --------------------------------------------------------------------------------


def install(plan: Plan) -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("  No encuentro uv. Instálalo primero: https://docs.astral.sh/uv/")
        return 1
    seconds = "10–30 s" if plan.navegador else "unos 10 s"
    print(bold("  Instalando…") + muted(f"  ({seconds})"), flush=True)
    done = subprocess.run(
        [uv, "tool", "install", "--reinstall", "--quiet", plan.target()], check=False
    )
    if done.returncode != 0:
        print("  No se pudo instalar. Prueba de nuevo, o escribe esto a mano:")
        print(f"  {install_line(plan)}")
        return done.returncode
    subprocess.run([uv, "tool", "update-shell"], capture_output=True, check=False)
    return 0


def campus_path() -> str:
    uv = shutil.which("uv")
    if uv:
        found = subprocess.run([uv, "tool", "dir", "--bin"], capture_output=True, text=True)
        candidate = Path(found.stdout.strip()) / ("campus.exe" if os.name == "nt" else "campus")
        if candidate.exists():
            return str(candidate)
    return "campus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="instalar", description="Instala campus-usc.")
    parser.add_argument("--si", action="store_true", help="Lo recomendado, sin preguntar")
    parser.add_argument("--horarios", dest="horarios", action="store_true", default=None)
    parser.add_argument("--sin-horarios", dest="horarios", action="store_false")
    parser.add_argument("--navegador", dest="navegador", action="store_true", default=None)
    parser.add_argument("--sin-navegador", dest="navegador", action="store_false")
    parser.add_argument("--simular", action="store_true", help="Enseña el plan sin instalar")
    options = parser.parse_args(argv)

    machine = look()
    print("\n".join(describe(machine) + parts(machine)))
    plan = choose(machine, options)
    print("\n".join(summary(plan)))
    if options.simular:
        print(muted(f"  Por dentro: {install_line(plan)}"))
        print(muted("  (simulación: no se ha instalado nada)"))
        return 0
    if not options.si and not ask("¿Instalo?", True):
        print("  No se ha instalado nada.")
        return 0
    code = install(plan)
    if code:
        return code
    print("")
    print("  " + bold("Listo.") + " Abre una terminal nueva y escribe " + bold("campus") + ".")
    if plan.horarios:
        print(muted("  El horario tardará un poco la primera vez que lo pidas."))
    if options.si:
        return 0
    how = ["login"] if machine.screen else ["login", "--pegar"]
    if ask("¿Entras ya en el Campus?", True):
        return subprocess.run([campus_path(), *how], check=False).returncode
    print(f"  Cuando quieras: campus {' '.join(how)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
