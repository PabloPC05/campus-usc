"""Installable modules: what is not the Campus itself, added only by those who want it.

The core of `campus` is the Campus Virtual. A module adds commands and, if it wants, its
own data, pieces of the Taboleiro and of the calendar, and what `campus actualizar`
refreshes. Installed means on; not installed, it is simply not there (not even imported).

Only official modules are looked for, by their package name, which costs a fraction of a
millisecond (scanning every installed distribution for entry points would cost more on
each command). Every hook is optional:

    COMMANDS: list[Command]
    SOURCES: dict[str, Source]                         its data, cached like the rest
    actualizar_keys(today) -> list[str]
    taboleiro_keys(today) -> list[str]
    taboleiro_hoxe(results, pendientes, cells, now) -> list[str]   replaces «Hoxe»
    taboleiro_blocks(results, cells, now) -> list[str]             blocks after Cronograma
    calendar_keys(today) -> list[str]
    calendar_entries(results) -> list[calendario.Entry]            marks in the calendar
    calendar_json(results, year, month) -> dict                    for `campus cal --json`
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from types import ModuleType
from typing import Any

REPO_ZIP = "https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"


@dataclass(frozen=True, slots=True)
class Module:
    name: str  # the extra: campus-usc[name]
    package: str  # its import name
    summary: str
    commands: str


KNOWN = (
    Module(
        "horarios",
        "campus_usc_horarios",
        "Horario de clases e datas oficiais de exame (de usc.gal)",
        "horario, hoy, mañana, examenes",
    ),
)

_loaded: list[tuple[Module, ModuleType]] | None = None


def install_command(extras: set[str]) -> str:
    """The one line that leaves exactly these modules installed."""

    target = f"campus-usc[{','.join(sorted(extras))}]" if extras else "campus-usc"
    return f'uv tool install --reinstall "{target} @ {REPO_ZIP}"'


def loaded() -> list[tuple[Module, ModuleType]]:
    """The installed modules, imported once; their data sources registered."""

    global _loaded
    if _loaded is None:
        from . import sources

        found: list[tuple[Module, ModuleType]] = []
        for module in KNOWN:
            if importlib.util.find_spec(module.package) is None:
                continue
            try:
                imported = importlib.import_module(module.package)
            except Exception:  # noqa: BLE001 - a broken module must never break the Campus
                continue
            for name, source in getattr(imported, "SOURCES", {}).items():
                sources.SOURCES.setdefault(name, source)
            found.append((module, imported))
        _loaded = found
    return _loaded


def installed(name: str) -> bool:
    return any(module.name == name for module, _ in loaded())


def commands() -> list[Any]:
    return [command for _, module in loaded() for command in getattr(module, "COMMANDS", [])]


def collect(hook: str, *args: Any) -> list[Any]:
    """Every module's ``hook(*args)``, lists flattened (modules without it are skipped)."""

    found: list[Any] = []
    for _, module in loaded():
        function = getattr(module, hook, None)
        if function is None:
            continue
        value = function(*args)
        if isinstance(value, list):
            found.extend(value)
        elif value is not None:
            found.append(value)
    return found


def first(hook: str, *args: Any) -> Any:
    """The first module that implements ``hook`` answers; None when none does."""

    for _, module in loaded():
        function = getattr(module, hook, None)
        if function is not None:
            return function(*args)
    return None


def reset() -> None:
    """Forget what was found (tests install and remove fake modules)."""

    global _loaded
    _loaded = None


__all__ = ["KNOWN", "Module", "collect", "commands", "first", "install_command", "installed"]
