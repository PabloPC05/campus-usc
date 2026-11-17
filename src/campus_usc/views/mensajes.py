"""«Mensaxes»: the Campus's private messages, by person, and writing one.

* ``campus mensajes``              who wrote to you (or you to them), newest first, numbered;
* ``campus mensajes 2``            the conversation with person 2, oldest first;
* ``campus escribir 2 "texto"``    a message to person 2 (or ``escribir "Ana Proba" …``);
                                   shows it and asks before sending (``--si`` skips that).

Reading marks nothing as read. Sending goes through mcp-usc's preview and one-time token.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime
from typing import Any

from .. import sources, store
from ..style import AMBER, BLUE, GREEN, WHITE, bold, muted, paint, term_width, truncate, width
from ..ui import block, empty, long_day, navbar, out, parse_moment
from . import Command, fail, show
from .notificaciones import relative_time

_YES = {"s", "si", "sí", "y", "yes"}


def people(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One entry per person, newest conversation first."""

    names = (data or {}).get("names") or {}
    found: dict[int, dict[str, Any]] = {}
    for item in (data or {}).get("items") or []:
        other = int(item.get("user_id_to" if item.get("sent") else "user_id_from") or 0)
        if not other:
            continue
        entry = found.setdefault(
            other,
            {"user_id": other, "name": names.get(str(other)) or f"#{other}", "unread": 0},
        )
        if not item.get("sent") and not item.get("is_read"):
            entry["unread"] += 1
        stamp = str(item.get("created_at") or "")
        if stamp >= str(entry.get("last_at") or ""):
            entry.update(last_at=stamp, last_text=item.get("text"), last_from_me=item.get("sent"))
    return sorted(found.values(), key=lambda entry: str(entry.get("last_at")), reverse=True)


def _stamp(value: Any) -> float | None:
    moment = parse_moment(value)
    return moment.timestamp() if moment else None


def _render_list(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    everyone = people(results["mensajes"].data)
    unread = sum(person["unread"] for person in everyone)
    lines = [block("Mensaxes", f"{unread} sen ler" if unread else "Todo ao día", cells), ""]
    if not everyone:
        return lines + [empty("Non tes mensaxes.")]
    for number, person in enumerate(everyone, start=1):
        dot = paint("●", BLUE, bold=True) if person["unread"] else muted("○")
        when = relative_time(_stamp(person.get("last_at")))
        first = f"  {muted(f'{number:>2}')} {dot} {bold(truncate(person['name'], cells - 30))}"
        first += " " * max(2, cells - width(first) - width(when)) + muted(when)
        text = " ".join(str(person.get("last_text") or "").split())
        prefix = "Ti: " if person.get("last_from_me") else ""
        lines += [first, "       " + muted(truncate(prefix + text, cells - 9))]
    lines += ["", muted("  campus mensajes <número> para ler a conversa")]
    return lines


def _render_conversation(key: str) -> Any:
    def render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        data = results[key].data or {}
        name = data.get("other_name") or "Conversa"
        lines = [block(truncate(str(name), cells // 2), "Conversa privada", cells), ""]
        messages = data.get("messages") or []
        if not messages:
            return lines + [empty("Aínda non hai mensaxes.")]
        wrap = max(20, cells - 8)
        for message in messages:
            mine = bool(message.get("from_me"))
            who = (
                paint("Ti", GREEN, bold=True) if mine else bold(str(message.get("author") or name))
            )
            stamp = message.get("created_at")
            moment = datetime.fromtimestamp(stamp) if stamp else None
            when = f"{long_day(moment.date())} · {moment:%H:%M}" if moment else ""
            lines.append(f"  {paint('▌', GREEN if mine else BLUE)} {who}  {muted(when)}")
            for paragraph in str(message.get("text") or "").split("\n"):
                rows = textwrap.wrap(paragraph, wrap) if paragraph.strip() else [""]
                lines += [f"    {row}".rstrip() for row in rows]
            lines.append("")
        lines.append(muted(f'  campus escribir {args.numero} "…" para responder'))
        return lines

    return render


def _person(number: int) -> dict[str, Any] | None:
    loaded = sources.load(["mensajes"]).get("mensajes")
    everyone = people(loaded.data if loaded and loaded.ok else None)
    return everyone[number - 1] if 1 <= number <= len(everyone) else None


def run(args: argparse.Namespace) -> int:
    if args.numero is None:
        return show(args, ["mensajes"], _render_list, ["Mensaxes"])
    person = _person(args.numero)
    if person is None:
        return fail(f"No hay conversación {args.numero}: mira la lista con campus mensajes.")
    key = f"conversa/{person['user_id']}"
    return show(args, [key], _render_conversation(key), ["Mensaxes", person["name"]])


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("numero", nargs="?", type=int, metavar="NÚMERO", help="Lee esa conversa")


# --- escribir -----------------------------------------------------------------------------------


def _new_service() -> Any:
    from campus_usc_core.service import UscService  # heavy: only when really sending

    return UscService()


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask(prompt: str) -> str:
    return input(prompt)


async def _recipient(service: Any, target: str) -> tuple[dict[str, Any] | None, list]:
    """Person N of `campus mensajes`, or whoever the Campus finds by that name."""

    if target.strip().isdigit():
        person = _person(int(target))
        if person:
            return {"user_id": person["user_id"], "name": person["name"]}, []
    found = await service.search_message_contacts(target.strip(), 10)
    options = [
        {"user_id": int(item["user_id"]), "name": str(item.get("full_name") or "")}
        for item in found
        if item.get("user_id")
    ]
    exact = [item for item in options if item["name"].casefold() == target.strip().casefold()]
    if len(exact) == 1 or len(options) == 1:
        return (exact or options)[0], []
    return None, options


async def _write(args: argparse.Namespace) -> int:
    from campus_usc_core.campus import AuthenticationRequired, CampusError

    text = " ".join(args.texto).strip()
    if not text:
        return fail('Escribe el mensaje entre comillas: campus escribir 2 "Ola, …"')
    service = _new_service()
    try:
        person, options = await _recipient(service, args.destino)
    except AuthenticationRequired:
        return fail("La sesión del Campus caducó: escribe `campus entrar`.")
    except (CampusError, ValueError) as exc:
        return fail(f"No pude buscar a quién escribir: {exc}")
    if person is None:
        fail(f"«{args.destino}» no identifica a una sola persona.")
        for option in options[:10]:
            sys.stderr.write(f"  · {option['name']}\n")
        return 1
    cells = term_width()
    user = ((store.read("perfil") or ({}, 0))[0] or {}).get("fullname")
    out([navbar(["Mensaxes", person["name"], "Escribir"], user, cells), ""])
    out(block("Nova mensaxe", "", cells))
    out(f"  {muted('Para:')} {bold(person['name'])}")
    out("")
    for paragraph in text.split("\n"):
        out([f"    {row}" for row in textwrap.wrap(paragraph, max(20, cells - 8)) or [""]])
    out("")
    if not args.si:
        if not _interactive():
            return fail("Confirma con --si para enviarlo sin preguntar.")
        out(paint(" ! ", WHITE, AMBER, bold=True) + " Se enviará de verdad, como desde la web.")
        if _ask("¿Enviar? [s/N] ").strip().casefold() not in _YES:
            out("No se ha enviado nada.")
            return 0
    try:
        preview = await service.send_message(person["user_id"], text, confirmation_token=None)
        token = preview.get("confirmation_token")
        if not token:
            return fail(str(preview.get("warning") or "Moodle no permite escribir a esta persona."))
        result = await service.send_message(person["user_id"], text, confirmation_token=token)
    except AuthenticationRequired:
        return fail("La sesión del Campus caducó: escribe `campus entrar`.")
    except (CampusError, ValueError) as exc:
        return fail(f"No se pudo enviar: {exc}")
    sources.refresh_in_background(["mensajes", f"conversa/{person['user_id']}"])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    out("  " + paint("✓ Enviada.", GREEN, bold=True) + muted("  campus mensajes para vela"))
    return 0


def run_escribir(args: argparse.Namespace) -> int:
    import asyncio

    try:
        return asyncio.run(_write(args))
    except KeyboardInterrupt:
        return 130


def configure_escribir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("destino", help="Número de campus mensajes o nombre de la persona")
    parser.add_argument("texto", nargs="+", help="El mensaje (entre comillas)")
    parser.add_argument("--si", action="store_true", help="No preguntes antes de enviar")


COMMANDS = [
    Command(
        "mensajes",
        "Tus mensajes privados; con un número, la conversación",
        run,
        configure,
        aliases=("mensaxes",),
    ),
    Command(
        "escribir",
        "Escribe un mensaje a alguien (pregunta antes de enviarlo)",
        run_escribir,
        configure_escribir,
    ),
]

__all__ = ["COMMANDS", "people"]
