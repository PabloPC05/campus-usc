"""Where each screen's data comes from, how long it stays fresh, and how it is fetched.

``load(keys)`` is the whole policy, stale-while-revalidate:

* fresh in the local cache → returned at once, no network, no heavy imports;
* stale but recent enough → returned at once and refreshed by a detached background
  process, so the *next* command is fresh;
* missing, too old or ``force`` → fetched now, every key concurrently over a single
  Campus session (one login handshake for the whole screen).

Keys are ``name`` or ``name/param`` (``horario/2026-11-16``, ``contenidos/64462``).
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from . import store

MINUTE, HOUR, DAY = 60, 3600, 86400


@dataclass(frozen=True, slots=True)
class Source:
    label: str
    ttl: float  # fresh for this long
    max_stale: float  # shown (and refreshed behind) up to this age
    fetch: Callable[[Any, str], Awaitable[Any]]  # (service, param) -> JSON data
    slow: bool = False  # warn that the first fetch can take a while


@dataclass(slots=True)
class Result:
    key: str
    data: Any = None
    age: float | None = None  # seconds since it was fetched; 0 when just fetched
    refreshing: bool = False  # a background refresh was started
    error: str | None = None  # why fresh data could not be fetched
    login_needed: bool = False

    @property
    def ok(self) -> bool:
        return self.data is not None


# --- fetchers (heavy imports stay inside: only a cache miss pays for them) -----------


async def _pendientes(service: Any, _param: str) -> Any:
    return await service.list_events(days=60, include_overdue=True, course_ids=None, limit=200)


async def _cursos(service: Any, _param: str) -> Any:
    return await service.list_courses(include_archived=True)


async def _contenidos(service: Any, course_id: str) -> Any:
    """Every activity of the course: Moodle hands them out 100 at a time."""

    items: list[Any] = []
    offset, page = 0, {}
    for _ in range(50):  # 5000 activities is more than any course has
        page = await service.list_course_contents(int(course_id), None, offset, 100)
        batch = page.get("items") or []
        items.extend(batch)
        if not page.get("has_more") or not batch:
            break
        offset = int(page.get("next_offset") or offset + len(batch))
    return {**page, "items": items, "offset": 0, "returned": len(items), "has_more": False}


async def _notificaciones(service: Any, _param: str) -> Any:
    result = await service.list_notifications("all", 0, 30)
    payload = result.get("result") or {}
    keep = (
        "id",
        "subject",
        "smallmessage",
        "component",
        "eventtype",
        "timecreated",
        "read",
        "contexturl",
        "contexturlname",
    )
    from .text import html_to_text

    items = []
    for item in payload.get("notifications") or []:
        entry = {name: item.get(name) for name in keep}
        # The whole message, as text, so `campus notificaciones N` reads it offline.
        entry["text"] = html_to_text(item.get("fullmessagehtml") or item.get("fullmessage"))
        items.append(entry)
    return {"unread": payload.get("unreadcount", 0), "items": items}


async def _perfil(service: Any, _param: str) -> Any:
    result = await service.get_my_profile()
    users = result.get("result") or []
    user = users[0] if users else {}
    # Only what the header shows: no e-mail, preferences or ids on disk.
    return {
        "fullname": user.get("fullname"),
        "firstname": user.get("firstname"),
        "lastname": user.get("lastname"),
    }


async def _confirmed(method: Any, *args: Any) -> Any:
    """Pages that leave the same trace as opening them on the web: the engine asks for a
    one-time confirmation even to read them; running the command is that confirmation."""

    preview = await method(*args, None)
    return await method(*args, preview["confirmation_token"])


async def _notas(service: Any, course_id: str) -> Any:
    return await _confirmed(service.inspect_my_grades, int(course_id) if course_id else None)


async def _foro(service: Any, course_module_id: str) -> Any:
    return await _confirmed(service.inspect_forum_discussions, int(course_module_id), 0)


async def _debate(service: Any, discussion_id: str) -> Any:
    preview = await service.inspect_discussion_posts(int(discussion_id), 0, 100, None)
    return await service.inspect_discussion_posts(
        int(discussion_id), 0, 100, preview["confirmation_token"]
    )


async def _mensajes(service: Any, _param: str) -> Any:
    received = await service.list_messages("received", "conversations", "all", 0, 50, True)
    sent = await service.list_messages("sent", "conversations", "all", 0, 50, True)
    items = [{**item, "sent": False} for item in received.get("items") or []]
    items += [{**item, "sent": True} for item in sent.get("items") or []]
    people = {int(item["user_id_to" if item["sent"] else "user_id_from"] or 0) for item in items}
    names = await service.message_member_names(sorted(people - {0}))
    return {"items": items, "names": {str(key): value for key, value in names.items()}}


async def _conversa(service: Any, other_user_id: str) -> Any:
    return await service.conversation_with(int(other_user_id), 50)


async def _cuestionario(service: Any, course_module_id: str) -> Any:
    return await _confirmed(service.inspect_quiz_page, int(course_module_id))


SOURCES: dict[str, Source] = {
    "pendientes": Source("Cronograma", 10 * MINUTE, 12 * HOUR, _pendientes),
    "cursos": Source("Os meus cursos", 6 * HOUR, 30 * DAY, _cursos),
    "contenidos": Source("Contido do curso", 30 * MINUTE, 7 * DAY, _contenidos),
    "notificaciones": Source("Notificacións", 5 * MINUTE, 6 * HOUR, _notificaciones),
    "perfil": Source("Perfil", 7 * DAY, 90 * DAY, _perfil),
    "notas": Source("Cualificacións", HOUR, 7 * DAY, _notas),
    "foro": Source("Foro", 30 * MINUTE, 7 * DAY, _foro),
    "debate": Source("Debate", 15 * MINUTE, 7 * DAY, _debate),
    "mensajes": Source("Mensaxes", 5 * MINUTE, 6 * HOUR, _mensajes),
    "conversa": Source("Conversa", 5 * MINUTE, 6 * HOUR, _conversa),
    "cuestionario": Source("Cuestionario", 30 * MINUTE, 7 * DAY, _cuestionario),
}


def split(key: str) -> tuple[str, str]:
    name, _, param = key.partition("/")
    return name, param


def source(key: str) -> Source:
    return SOURCES[split(key)[0]]


# --- key helpers shared by the views ------------------------------------------------


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def horario_key(day: date | None = None) -> str:
    return f"horario/{monday_of(day or date.today()).isoformat()}"


def academic_year(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start}/{start + 1}"


def examenes_key(year: str | None = None) -> str:
    return f"examenes/{(year or academic_year()).replace('/', '-')}"


# --- loading ----------------------------------------------------------------------


def load(
    keys: list[str],
    *,
    force: bool = False,
    background: bool = True,
    quiet: bool = False,
    defer_slow: bool = False,
) -> dict[str, Result]:
    """Results for ``keys``, from the cache when possible (see module docstring).

    ``defer_slow``: a slow source with nothing usable cached is not awaited; it is
    fetched in the background and returned empty with ``refreshing`` set. Screens that
    combine several blocks (the Taboleiro) use it so one slow block never blocks them.
    """

    results: dict[str, Result] = {}
    to_fetch: list[str] = []
    to_refresh: list[str] = []
    for key in dict.fromkeys(keys):
        spec = source(key)
        cached = None if force else store.read(key)
        if cached is not None:
            data, age = cached
            if age < spec.ttl:
                results[key] = Result(key, data, age)
                continue
            if age < spec.max_stale:
                results[key] = Result(key, data, age)
                to_refresh.append(key)
                continue
        if defer_slow and spec.slow and not force:
            results[key] = Result(key)
            to_refresh.append(key)
            continue
        to_fetch.append(key)
    if to_fetch:
        fetched = fetch_now(to_fetch, quiet=quiet)
        for key in to_fetch:
            result = fetched[key]
            if not result.ok:
                # Offline or logged out: old data with a warning beats an empty screen.
                stale = store.read(key)
                if stale is not None:
                    result.data, result.age = stale
            results[key] = result
    if to_refresh and background and refresh_in_background(to_refresh):
        for key in to_refresh:
            results[key].refreshing = True
    return results


def fetch_now(keys: list[str], *, quiet: bool = False) -> dict[str, Result]:
    """Fetch ``keys`` concurrently with one Campus session and store what succeeds."""

    import asyncio

    def fetch(wanted: list[str]) -> dict[str, Result]:
        slow = any(source(key).slow and store.read(key) is None for key in wanted)
        labels = ", ".join(dict.fromkeys(source(key).label for key in wanted))
        spinner = None if quiet else Spinner(labels, slow=slow)
        if spinner:
            spinner.start()
        try:
            return asyncio.run(_fetch_all(wanted))
        finally:
            if spinner:
                spinner.stop()

    results = fetch(keys)
    expired = [key for key, result in results.items() if result.login_needed]
    if expired and not os.environ.get("CAMPUS_NO_LOGIN"):
        # No session, or it expired: get in (silently if the login browser remembers
        # you, else a window when someone is here) and ask again.
        from . import auth

        here = not quiet and sys.stdin.isatty() and sys.stderr.isatty()
        if auth.ensure(interactive=here):
            results.update(fetch(expired))
    return results


async def _fetch_all(keys: list[str]) -> dict[str, Result]:
    import asyncio

    from mcp_usc.academic_profile import AcademicProfileError
    from mcp_usc.campus import AuthenticationRequired, CampusError
    from mcp_usc.service import UscService

    from .text import scrub

    service = UscService()

    async def one(key: str) -> Result:
        name, param = split(key)
        try:
            data = await SOURCES[name].fetch(service, param)
        except AuthenticationRequired:
            return Result(key, error="La sesión del Campus Virtual caducó.", login_needed=True)
        except (CampusError, AcademicProfileError, ValueError) as exc:
            return Result(key, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - one broken block must not sink the screen
            return Result(key, error=f"{type(exc).__name__}: {exc}")
        data = scrub(data)  # text from the Campus can never drive the terminal
        with contextlib.suppress(OSError):
            store.write(key, data)
        return Result(key, data, 0.0)

    # Warm the session (sesskey, user id) once: it is cached per process, so the
    # concurrent calls below share it instead of each loading the preferences page.
    warmup = getattr(service._campus(), "_session_context", None)  # noqa: SLF001
    if warmup is not None:
        # Errors here are reported by each fetch below.
        with contextlib.suppress(Exception):
            await warmup()
    done = await asyncio.gather(*(one(key) for key in keys))
    return {result.key: result for result in done}


def refresh_in_background(keys: list[str]) -> bool:
    """Start a detached ``python -m campus_usc --refrescar`` for keys nobody refreshes."""

    if os.environ.get("MCP_USC_NO_BACKGROUND"):
        return False
    import subprocess

    claimed = [key for key in keys if store.claim_refresh(key)]
    if not claimed:
        return True  # someone else is already on it
    command = [sys.executable, "-m", "campus_usc", "--refrescar", *claimed]
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)  # noqa: S603 - our own module, fixed args
    except OSError:
        for key in claimed:
            store.release_refresh(key)
        return False
    return True


def refresh_main(keys: list[str]) -> int:
    """Body of the background refresher."""

    from . import modulos

    modulos.loaded()  # installed modules register their data sources
    try:
        fetch_now([key for key in keys if split(key)[0] in SOURCES], quiet=True)
    finally:
        for key in keys:
            store.release_refresh(key)
    return 0


# --- spinner ----------------------------------------------------------------------


class Spinner:
    """A small braille spinner on stderr while the Campus answers (TTY only)."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str, *, slow: bool = False) -> None:
        import threading

        self.label = label
        self.slow = slow
        self._stop = threading.Event()
        self._thread: Any = None
        self._started = 0.0

    def start(self) -> None:
        if not sys.stderr.isatty():
            return
        self._started = time.monotonic()
        import threading

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        from .style import BLUE, GRAY, paint

        index = 0
        while not self._stop.wait(0.08):
            elapsed = time.monotonic() - self._started
            hint = ""
            if self.slow and elapsed > 3:
                hint = "  la primera vez lee los planes de estudio de la USC; luego es instantáneo"
            frame = paint(self.FRAMES[index % len(self.FRAMES)], BLUE, bold=True)
            text = f"\r{frame} Consultando el Campus Virtual · {self.label} {elapsed:4.1f}s"
            sys.stderr.write(text + paint(hint, GRAY) + "\x1b[K")
            sys.stderr.flush()
            index += 1

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        sys.stderr.write("\r\x1b[K")
        sys.stderr.flush()


def describe_age(age: float | None) -> str:
    if age is None:
        return "sin datos"
    if age < 45:
        return "ahora mismo"
    minutes = age / 60
    if minutes < 60:
        return f"hace {round(minutes)} min"
    hours = minutes / 60
    if hours < 36:
        return f"hace {round(hours)} h"
    return f"hace {round(hours / 24)} días"


def today_iso() -> str:
    return datetime.now().date().isoformat()
