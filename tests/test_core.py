"""The `campus` CLI core: cache, load policy, course lookup, text width and the timeline."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import pytest

from campus_usc import app, sources, store, style
from campus_usc.courses import CourseNotFound, find
from campus_usc.ui import countdown, course_alias, course_color


@pytest.fixture(autouse=True)
def _plain_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MCP_USC_CLI_CONFIG", str(tmp_path / "campus.json"))
    monkeypatch.setenv("MCP_USC_NO_BACKGROUND", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    # Offline by default: a test must never reach the real Campus through the keyring.
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    style.caps.reset()
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    return int(exit_info.value.code or 0), capsys.readouterr().out


def _age(key: str, seconds: float) -> None:
    path = store.cache_dir() / f"{key.replace('/', '_')}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["saved_at"] = time.time() - seconds
    path.write_text(json.dumps(entry), encoding="utf-8")


COURSES = [
    {"id": 101, "full_name": "Redes [G0000001] [2026/2027]"},
    {"id": 102, "full_name": "Administración de Sistemas e Redes [G0000002] [2026/2027]"},
    {"id": 103, "full_name": "Sistemas Operativos I [G0000003] [2026/2027]"},
    {"id": 104, "full_name": "Sistemas Operativos II [G0000004] [2026/2027]"},
    {"id": 105, "full_name": "Intelixencia Artificial [G0000005] [2026/2027]"},
    {"id": 99, "full_name": "Intelixencia Artificial [G0000005] [2025/2026]"},
]


def test_store_roundtrip_is_private_and_atomic():
    store.write("horario/2026-11-16", {"sessions": [1, 2]})
    data, age = store.read("horario/2026-11-16")
    assert data == {"sessions": [1, 2]}
    assert age < 5
    path = store.cache_dir() / "horario_2026-11-16.json"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(store.cache_dir().glob(".tmp-*"))


def test_store_ignores_corrupt_or_foreign_files():
    store.cache_dir().mkdir(parents=True)
    (store.cache_dir() / "cursos.json").write_text("{not json", encoding="utf-8")
    (store.cache_dir() / "perfil.json").write_text('{"v": 99, "data": 1}', encoding="utf-8")
    assert store.read("cursos") is None
    assert store.read("perfil") is None
    assert store.clear() == 2


def test_fresh_cache_never_touches_the_network(monkeypatch):
    store.write("cursos", COURSES)
    monkeypatch.setattr(sources, "fetch_now", lambda *a, **k: pytest.fail("network used"))
    result = sources.load(["cursos"])["cursos"]
    assert result.data == COURSES and not result.refreshing


def test_stale_cache_is_shown_and_refreshed_behind(monkeypatch):
    store.write("pendientes", [{"name": "old"}])
    _age("pendientes", sources.SOURCES["pendientes"].ttl + 5)
    started: list[list[str]] = []
    monkeypatch.setattr(sources, "fetch_now", lambda *a, **k: pytest.fail("blocked on network"))
    monkeypatch.setattr(sources, "refresh_in_background", lambda keys: started.append(keys) or True)
    result = sources.load(["pendientes"])["pendientes"]
    assert result.data == [{"name": "old"}]
    assert result.refreshing and started == [["pendientes"]]


def test_missing_or_forced_keys_are_fetched_together(monkeypatch):
    calls: list[list[str]] = []

    def fake_fetch(keys, quiet=False):
        calls.append(list(keys))
        return {key: sources.Result(key, {"k": key}, 0.0) for key in keys}

    monkeypatch.setattr(sources, "fetch_now", fake_fetch)
    store.write("cursos", COURSES)
    results = sources.load(["cursos", "pendientes", "notificaciones"], force=True)
    assert calls == [["cursos", "pendientes", "notificaciones"]]
    assert results["pendientes"].data == {"k": "pendientes"}


def test_failed_fetch_falls_back_to_old_data(monkeypatch):
    store.write("pendientes", [{"name": "old"}])
    _age("pendientes", sources.SOURCES["pendientes"].max_stale + 5)
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {
            key: sources.Result(key, error="caducó", login_needed=True) for key in keys
        },
    )
    result = sources.load(["pendientes"])["pendientes"]
    assert result.data == [{"name": "old"}] and result.login_needed


def test_slow_sources_can_be_deferred(monkeypatch):
    key = sources.horario_key()
    monkeypatch.setattr(sources, "fetch_now", lambda *a, **k: pytest.fail("waited for slow"))
    monkeypatch.setattr(sources, "refresh_in_background", lambda keys: True)
    result = sources.load([key], defer_slow=True)[key]
    assert result.data is None and result.refreshing


def test_course_lookup_by_alias_title_code_and_id():
    assert find(COURSES, "redes")["id"] == 101  # exact title beats «…e Redes»
    assert find(COURSES, "asr")["id"] == 102
    assert find(COURSES, "soi")["id"] == 103
    assert find(COURSES, "soii")["id"] == 104
    assert find(COURSES, "G0000003")["id"] == 103
    assert find(COURSES, "104")["id"] == 104
    assert find(COURSES, "inteligencia artif".replace("g", "x"))["id"] in {105, 99}
    with pytest.raises(CourseNotFound) as ambiguous:
        find(COURSES, "sistemas")
    assert {c["id"] for c in ambiguous.value.options} >= {102, 103, 104}
    with pytest.raises(CourseNotFound):
        find(COURSES, "química")


def test_aliases_and_moodle_course_colours():
    assert course_alias("Intelixencia Artificial [G0000005] [2026/2027]") == "ia"
    assert course_alias("Sistemas Operativos I") == "soi"
    assert course_alias("Redes") == "redes"
    assert course_color(64462) == "#a29bfe"  # Moodle basecolors[id % 10]


def test_text_width_handles_styles_and_wide_characters():
    style.caps.reset(color=True)
    styled = style.paint("Redes", style.RED, bold=True)
    assert style.width(styled) == 5
    assert style.width("漢字") == 4
    assert style.truncate("Computación Distribuída", 10) == "Computaci…"
    assert style.width(style.pad(styled, 9)) == 9


def test_countdown_colours_by_urgency():
    now = datetime(2026, 11, 17, 12, 0)
    assert countdown(now + timedelta(hours=5), now)[0] == "quedan 5 h"
    assert countdown(now + timedelta(days=2), now)[0] == "en 2 días"
    assert countdown(now - timedelta(days=3), now)[0] == "atrasada 3 días"


def _event(name: str, course: dict, when: datetime, module: str = "assign") -> dict:
    return {
        "name": f"{name} pendente de entrega",
        "module": module,
        "course_id": course["id"],
        "course_name": course["full_name"],
        "sort_at": when.astimezone().isoformat(),
        "url": "https://cv.usc.es/mod/assign/view.php?id=1",
        "action_name": "Engadir entrega",
        "action_url": "https://cv.usc.es/mod/assign/view.php?id=1&action=editsubmission",
        "actionable": True,
    }


def test_timeline_groups_by_day_and_hides_overdue_by_default(capsys):
    now = datetime.now()
    store.write(
        "pendientes",
        [
            _event("Práctica 3", COURSES[0], now + timedelta(days=2)),
            _event("Test tema 2", COURSES[4], now + timedelta(days=2, hours=1), "quiz"),
            _event("Boletín 1", COURSES[2], now - timedelta(days=4)),
            _event("Lonxe", COURSES[2], now + timedelta(days=20)),
        ],
    )
    store.write("perfil", {"fullname": "Ana Proba"})
    code, output = _run(capsys, "pendientes")
    assert code == 0
    assert "Campus Virtual" in output and "AP" in output
    assert "Cronograma" in output and "Próximos 7 días" in output
    assert "Práctica 3" in output and "pendente de entrega" not in output
    assert "Engadir entrega" in output
    assert "Lonxe" not in output
    assert " ".join(output.split()).count("1 atrasada sin entregar") == 1
    assert "\x1b[" not in output

    code, output = _run(capsys, "pendientes", "-a", "-d", "30")
    assert "Boletín 1" in output and "Lonxe" in output and "Atrasada" in output

    code, output = _run(capsys, "pendientes", "redes")
    assert "Práctica 3" in output and "Test tema 2" not in output


def test_timeline_json_is_the_filtered_list(capsys):
    now = datetime.now()
    store.write("pendientes", [_event("Práctica 3", COURSES[0], now + timedelta(days=1))])
    code, output = _run(capsys, "pendientes", "--json")
    assert code == 0
    assert [item["course_id"] for item in json.loads(output)] == [101]


def test_help_lists_commands(capsys):
    code, output = _run(capsys, "ayuda")
    assert code == 0
    assert "pendientes" in output and "actualizar" in output and "Campus Virtual" in output


def test_dashboard_opens_without_waiting_for_slow_blocks(capsys, monkeypatch):
    monkeypatch.setattr(sources, "fetch_now", lambda *a, **k: pytest.fail("blocked"))
    now = datetime.now()
    store.write("pendientes", [_event("Práctica 3", COURSES[0], now + timedelta(days=1))])
    store.write("cursos", COURSES)
    store.write("notificaciones", {"unread": 2, "items": []})
    store.write("perfil", {"fullname": "Ana Proba", "firstname": "Ana"})
    code, output = _run(capsys)
    assert code == 0
    assert "Taboleiro" in output and "Ana" in output
    assert "Práctica 3" in output
    assert "2 notificacións sen ler" in " ".join(output.split())


def test_clip_keeps_colours_and_links_whole(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    style.caps.reset()
    try:
        text = style.paint("agora", "#357a32") + " " + style.link("quedan 2 h 47 min", "https://x")
        cut = style.clip(text, 10)
        assert style.width(cut) == 10 and style.strip(cut).endswith("…")
        assert cut.count("\x1b]8;") % 2 == 0  # the link is closed
        assert cut.endswith("\x1b[0m")
        assert style.clip("curto", 10) == "curto"
    finally:
        style.caps.reset()
