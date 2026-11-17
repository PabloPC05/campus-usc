from __future__ import annotations

import pytest
from campus_usc_core import academic_profile


@pytest.fixture(autouse=True)
def _isolate_caches(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """Every cache (this CLI's and the engine's) lives in a throwaway folder."""

    root = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("USC_CACHE_DIR", str(root))
    monkeypatch.setenv("MCP_USC_CACHE_DIR", str(root / "campus"))
    monkeypatch.setenv("MCP_USC_CLI_CONFIG", str(tmp_path_factory.mktemp("config") / "campus.json"))
    monkeypatch.setenv("MCP_USC_NO_BACKGROUND", "1")
    monkeypatch.setenv("CAMPUS_NO_LOGIN", "1")  # tests never open a login browser
    monkeypatch.delenv("USC_LOCATION_CACHE", raising=False)


@pytest.fixture(autouse=True)
def _no_personal_profile(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """Never let a developer's own `mcp-usc setup` profile leak into the tests."""

    missing = tmp_path_factory.mktemp("profile") / "perfil.json"
    monkeypatch.setattr(academic_profile, "default_profile_path", lambda: missing)


@pytest.fixture(autouse=True)
def _core_alone(monkeypatch):
    """The core's tests see no installed module (modulos/horarios has its own tests)."""

    from campus_usc import modulos

    monkeypatch.setattr(modulos, "KNOWN", ())
    modulos.reset()
    yield
    modulos.reset()
