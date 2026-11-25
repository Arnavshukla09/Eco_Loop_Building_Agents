"""Launcher and evaluation regressions for reproducible local operation."""
from collections import namedtuple
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import run
from config.settings import settings


def test_sim_only_check_runs_from_windows_legacy_output_encoding():
    result = subprocess.run(
        [sys.executable, "run.py", "--sim-only", "--check"],
        cwd=Path(run.__file__).parent,
        env={**run.os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "All checks passed." in result.stdout.decode("utf-8")


def test_launcher_requires_python_311(monkeypatch):
    version = namedtuple("Version", "major minor micro")
    monkeypatch.setattr(run.sys, "version_info", version(3, 10, 14))
    assert not run.check_python()
    monkeypatch.setattr(run.sys, "version_info", version(3, 11, 0))
    assert run.check_python()


def test_ollama_check_uses_configured_host_and_exact_model(monkeypatch):
    import ollama

    client = Mock()
    client.list.return_value = SimpleNamespace(models=[SimpleNamespace(model="qwen2.5:1.5b-extra")])
    factory = Mock(return_value=client)
    monkeypatch.setattr(ollama, "Client", factory)
    assert not run.check_ollama("qwen2.5:1.5b", "http://inference.test:11434")
    factory.assert_called_with(host="http://inference.test:11434", timeout=2.0)
    client.list.return_value = SimpleNamespace(models=[SimpleNamespace(model="qwen2.5:latest")])
    assert run.check_ollama("qwen2.5", "http://inference.test:11434")


def test_existing_dashboard_is_rebuilt_with_resolved_npm(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "dist").mkdir(parents=True)
    (frontend / "package.json").write_text("{}")
    (frontend / "dist" / "index.html").write_text("stale build")
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
    which = Mock(return_value="C:/Program Files/nodejs/npm.cmd")
    monkeypatch.setattr(run.shutil, "which", which)
    process = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(run.subprocess, "run", process)

    assert run.build_frontend()
    assert process.call_args.args[0] == ["C:/Program Files/nodejs/npm.cmd", "run", "build"]
    assert process.call_args.kwargs["cwd"] == str(frontend)
    which.assert_called_with("npm.cmd" if run.os.name == "nt" else "npm")


def test_dependency_install_tracks_lock_changes(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    lock = frontend / "package-lock.json"
    lock.write_text('{"version":1}')
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run.shutil, "which", lambda name: "/tools/npm")
    process = Mock()
    monkeypatch.setattr(run.subprocess, "run", process)

    assert run.install_frontend_deps()
    assert process.call_args.args[0] == ["/tools/npm", "ci"]
    process.reset_mock()
    assert run.install_frontend_deps()
    process.assert_not_called()
    lock.write_text('{"version":2}')
    assert run.install_frontend_deps()
    process.assert_called_once()


def test_sim_only_skips_ollama_and_selects_rule_controller(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--sim-only", "--check"])
    monkeypatch.setattr(run, "check_python", lambda: True)
    monkeypatch.setattr(run, "check_packages", lambda: True)
    monkeypatch.setattr(settings, "CONTROL_PROVIDER", "hybrid")
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setenv("SIMULATION_MODE", "false")
    monkeypatch.setenv("CONTROL_PROVIDER", "hybrid")
    probe = Mock()
    monkeypatch.setattr(run, "check_ollama", probe)

    with pytest.raises(SystemExit) as exit_info:
        run.main()
    assert exit_info.value.code == 0
    assert settings.CONTROL_PROVIDER == "rule_based"
    assert settings.SIMULATION_MODE is True
    assert run.os.environ["CONTROL_PROVIDER"] == "rule_based"
    probe.assert_not_called()


@pytest.mark.parametrize("speed", ["0", "-2", "inf", "nan", "3601"])
def test_invalid_speed_is_rejected(monkeypatch, speed):
    monkeypatch.setattr(sys, "argv", ["run.py", "--speed", speed])
    server = Mock()
    monkeypatch.setattr(run, "run_server", server)
    with pytest.raises(SystemExit) as exit_info:
        run.main()
    assert exit_info.value.code == 2
    server.assert_not_called()


def test_failed_frontend_setup_stops_launch(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.setattr(settings, "CONTROL_PROVIDER", "rule_based")
    monkeypatch.setattr(run, "check_python", lambda: True)
    monkeypatch.setattr(run, "check_packages", lambda: True)
    monkeypatch.setattr(run, "install_frontend_deps", lambda: False)
    server = Mock()
    monkeypatch.setattr(run, "run_server", server)
    with pytest.raises(SystemExit) as exit_info:
        run.main()
    assert exit_info.value.code == 1
    server.assert_not_called()


async def test_evaluation_uses_live_actuation_including_fans_without_database(monkeypatch):
    import evaluate
    from backend.controller import AutonomousController
    from backend.energyplus_runner import SimulatedBuildingEnvironment
    from backend.models import AgentDecision, ZoneSetpoint
    from backend.repository import repository
    from backend.state import state_store

    def decision(obs):
        return AgentDecision(
            zone_setpoints={z: ZoneSetpoint(cooling=30, heating=16) for z in obs.zones},
            fan_speed="low", reasoning="Regression: exercise full live actuation.",
        )

    monkeypatch.setattr(evaluate, "_rule_based_decision", decision)
    persist = AsyncMock(side_effect=AssertionError("Evaluation must not persist"))
    monkeypatch.setattr(repository, "record_decision", persist)
    actual = await evaluate.run_scenario("rule_based", steps=3, seed=42)

    env = SimulatedBuildingEnvironment(seed=42)
    ctrl = AutonomousController()
    ctrl.env = env
    state_store.reset()
    changes = 0
    for _ in range(3):
        obs = await env.step()
        state_store.update_observation(obs.model_copy(deep=True))
        requested = decision(obs)
        await ctrl._apply_decision(requested)
        changes += sum(
            abs(sp.cooling - obs.zones[z].setpoint_cooling) > 0.1
            or abs(sp.heating - obs.zones[z].setpoint_heating) > 0.1
            for z, sp in requested.applied_setpoints.items()
        )

    assert actual["total_energy_kwh"] == obs.total_energy_kwh
    assert actual["setpoint_changes_count"] == changes
    assert actual["final_fan_speed"] == "low"
    persist.assert_not_called()


@pytest.mark.parametrize("steps", [0, -1])
async def test_evaluation_rejects_empty_scenarios(steps):
    import evaluate

    with pytest.raises(ValueError, match="positive"):
        await evaluate.run_scenario("rule_based", steps=steps)


async def test_report_records_actual_duration_model_and_engine(monkeypatch, tmp_path):
    import evaluate

    monkeypatch.setattr(settings, "TIMESTEP_MINUTES", 30)
    monkeypatch.setattr(settings, "SIMULATION_START", "2024-04-01T10:00:00")
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model:latest")
    monkeypatch.setattr(evaluate, "_ollama_available", lambda: False)
    monkeypatch.setattr(evaluate, "real_llm_call", AsyncMock(side_effect=ConnectionError("Offline test")))
    target = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--steps", "2", "--seeds", "101", "--output", str(target)])

    await evaluate.main()

    report = target.read_text(encoding="utf-8")
    raw = json.loads((tmp_path / "evaluation_results.json").read_text())
    assert "1 simulated hours (2 timesteps × 30 min)" in report
    assert "Live LLM (test-model:latest)" in report
    assert "2024-04-01 10:00" in report
    assert "EnergyPlus is not run by this harness" in report
    assert "~1–5 ms" not in report
    assert raw["configuration"]["duration_hours"] == 1
    assert raw["configuration"]["timestep_minutes"] == 30
