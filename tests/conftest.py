"""Keep tests independent of local services, saved runs, and other tests."""
from unittest.mock import patch

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def isolated_ollama():
    with patch("ollama.Client.list", side_effect=ConnectionError("Ollama disabled in unit tests")):
        yield


@pytest_asyncio.fixture(autouse=True)
async def isolated_runtime(tmp_path, monkeypatch):
    from backend import controller as module
    from backend.database import close_db
    from backend.state import BuildingStateStore
    from backend import state
    from config.settings import settings

    await close_db()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setattr(settings, "API_KEY", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", False)
    monkeypatch.setattr(settings, "SIMULATION_MODE", True)
    # Preserve the singleton identity imported by other modules.
    monkeypatch.setattr(state.state_store, "__dict__", BuildingStateStore().__dict__)
    monkeypatch.setattr(module.controller, "__dict__", module.AutonomousController().__dict__)
    yield
    if module.controller._running:
        await module.controller.stop()
    if module.controller._persistence_tasks:
        import asyncio
        await asyncio.gather(*tuple(module.controller._persistence_tasks), return_exceptions=True)
    await close_db()
