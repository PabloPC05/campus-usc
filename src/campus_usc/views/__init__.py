"""Screens of the `campus` command. Each module exposes ``COMMANDS``.

A typical screen declares the cache keys it needs and a ``render(results, args)`` that
returns lines; :func:`show` does the rest (cache policy, --json, navbar, footer).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import sources
from ..ui import navbar, out, status_line


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    help: str
    run: Callable[[argparse.Namespace], int]
    configure: Callable[[argparse.ArgumentParser], None] | None = None
    aliases: tuple[str, ...] = ()  # other names that work too; `campus ayuda` shows only `name`
    hidden: bool = False  # works, but `campus ayuda` does not list it (old names, for agents)


Render = Callable[[dict[str, sources.Result], argparse.Namespace], list[str]]


def words_as_flags(args: argparse.Namespace, field: str, flags: dict[str, set[str]]) -> None:
    """Plain words instead of options: «campus entregas atrasadas» is «campus entregas -a».

    The words in ``args.<field>`` that spell a flag set it; the rest stay as ``<field>``
    (joined, or None), so «campus entregas ia atrasadas» is still the course «ia».
    """

    from ..ui import fold

    value = getattr(args, field, None)
    words = value if isinstance(value, list) else ([value] if value else [])
    rest = []
    for word in words:
        flag = next((flag for flag, spellings in flags.items() if fold(word) in spellings), None)
        if flag:
            setattr(args, flag, True)
        else:
            rest.append(word)
    setattr(args, field, " ".join(rest) or None)


def add_max(parser: argparse.ArgumentParser, default: int | None, what: str) -> None:
    """``-n/--max N``: how many to show. «--numero» is the old spelling, still accepted."""

    shown = f" ({default})" if default else ""
    parser.add_argument("-n", "--max", type=int, default=default, help=f"Cuántos {what}{shown}")
    parser.add_argument(
        "--numero", dest="max", type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )


def show(
    args: argparse.Namespace,
    keys: list[str],
    render: Render,
    crumbs: list[str],
    *,
    json_payload: Callable[[dict[str, sources.Result]], Any] | None = None,
    defer_slow: bool = False,
) -> int:
    """Load ``keys`` (plus the profile, for the navbar), print the screen, return status."""

    started = time.perf_counter()
    wanted = [*keys, "perfil"] if not args.json else list(keys)
    results = sources.load(wanted, force=args.fresco, defer_slow=defer_slow and not args.json)
    main = {key: results[key] for key in keys}
    if args.json:
        payload = (
            json_payload(main)
            if json_payload
            else (main[keys[0]].data if len(keys) == 1 else {k: r.data for k, r in main.items()})
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if all(r.ok for r in main.values()) else 1
    user = (results.get("perfil").data or {}).get("fullname") if results.get("perfil") else None
    lines = [navbar(crumbs, user)]
    lines.extend(render(main, args))
    footer = status_line(main, started)
    if footer:
        lines.append("")
        lines.append(footer)
    out(lines)
    if not any(r.ok or r.refreshing for r in main.values()):
        return 1
    return 0


def fail(message: str) -> int:
    from ..style import RED, WHITE, paint

    sys.stderr.write(paint(" ! ", WHITE, RED, bold=True) + " " + message + "\n")
    return 1
