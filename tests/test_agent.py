import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from backend.models import AgentDecision, BuildingObservation, ZoneSetpoint, ZoneState
from backend.llm_agent import BuildingAIAgent, _rule_based_decision
from config.settings import settings


@pytest.fixture
def sample_observation():
    zones = {
        z: ZoneState(
            zone_id=z,
            temperature=22.5,
            setpoint_cooling=24.0,
            setpoint_heating=20.0,
            pmv_score=0.1,
            ppd_score=5.5,
            humidity=50.0,
        )
        for z in settings.ZONES
    }
    return BuildingObservation(
        timestamp=datetime.now(timezone.utc),
        simulation_time=datetime(2024, 1, 15, 10, 0),
        zones=zones,
        outdoor_temp=12.0,
        outdoor_humidity=60.0,
        total_energy_kwh=150.0,
        hvac_power_kw=15.0,
        occupancy=0.8,
        timestep=40,
    )


def test_rule_based_decision_logic(sample_observation):
    """Verify rule-based decision produces valid setpoints with proper deadbands."""
    decision = _rule_based_decision(sample_observation)
    assert isinstance(decision, AgentDecision)
    assert decision.confidence > 0.5
    for zone, sp in decision.zone_setpoints.items():
        assert sp.cooling >= sp.heating + 1.5
        assert settings.COOLING_SETPOINT_MIN <= sp.cooling <= settings.COOLING_SETPOINT_MAX
        assert settings.HEATING_SETPOINT_MIN <= sp.heating <= settings.HEATING_SETPOINT_MAX


def test_validate_decision_clamps_bounds(sample_observation):
    """Verify _validate_decision forces setpoints within safety limits and maintains gap."""
    agent = BuildingAIAgent()
    malformed_decision = AgentDecision(
        zone_setpoints={
            "Core": ZoneSetpoint(cooling=31.5, heating=24.5),        # Exceeds settings max cooling (30) & heating (22)
            "Perimeter_N": ZoneSetpoint(cooling=19.0, heating=14.0), # Below settings min cooling (20) & heating (16)
        },
        fan_speed="high",
        energy_mode="comfort",
        reasoning="Test malformed setpoints",
        confidence=1.0,
        estimated_savings_pct=45.0,
    )
    validated = agent._validate_decision(malformed_decision, sample_observation)

    assert validated.confidence <= 1.0
    assert validated.estimated_savings_pct <= 50.0
    assert len(validated.zone_setpoints) == len(settings.ZONES)

    core_sp = validated.zone_setpoints["Core"]
    assert core_sp.cooling <= settings.COOLING_SETPOINT_MAX
    assert core_sp.heating <= settings.HEATING_SETPOINT_MAX
    assert core_sp.cooling >= core_sp.heating + 1.5


@pytest.mark.asyncio
async def test_agent_fallback_on_llm_error(sample_observation):
    """Verify agent falls back gracefully without exception when LLM fails or times out."""
    agent = BuildingAIAgent()
    agent._available = True

    with patch.object(agent, "_call_ollama_async", AsyncMock(return_value=None)):
        decision = await agent.analyze_and_decide(sample_observation)
        assert isinstance(decision, AgentDecision)
        assert "[Fallback]" in decision.reasoning or "[Rule-based]" in decision.reasoning


@pytest.mark.asyncio
async def test_agent_successful_mock_call(sample_observation):
    """Verify agent parses valid structured JSON and produces validated decision."""
    agent = BuildingAIAgent()
    agent._available = True

    mock_json = """
    {
      "zone_setpoints": {
        "Core": {"cooling": 25.0, "heating": 20.0},
        "Perimeter_N": {"cooling": 24.5, "heating": 19.5},
        "Perimeter_S": {"cooling": 25.0, "heating": 20.0},
        "Perimeter_E": {"cooling": 24.5, "heating": 19.5},
        "Perimeter_W": {"cooling": 24.5, "heating": 19.5}
      },
      "fan_speed": "medium",
      "energy_mode": "eco",
      "reasoning": "Occupancy moderate, deadband widened safely.",
      "confidence": 0.88,
      "estimated_savings_pct": 12.5
    }
    """
    with patch.object(agent, "_call_ollama_async", AsyncMock(return_value=mock_json)):
        decision = await agent.analyze_and_decide(sample_observation)
        assert decision.energy_mode == "eco"
        assert decision.confidence == pytest.approx(0.88)
        assert decision.zone_setpoints["Core"].cooling == 25.0
        assert decision.controller_source == "llm"


@pytest.mark.asyncio
async def test_llm_missing_model_detection(sample_observation):
    """Verify missing model in Ollama model list sets available=False and source=rule_based."""
    agent = BuildingAIAgent()
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama_async_client = MagicMock()
    mock_model_obj = MagicMock()
    mock_model_obj.model = "different-model:latest"
    mock_ollama_async_client.list = AsyncMock(return_value=MagicMock(models=[mock_model_obj]))

    with patch("ollama.AsyncClient", return_value=mock_ollama_async_client):
        is_avail = await agent.check_availability(force=True)
        assert is_avail is False
        assert agent.is_available is False

        decision = await agent.analyze_and_decide(sample_observation)
        assert decision.controller_source == "rule_based"
        assert "[Rule-based]" in decision.reasoning


@pytest.mark.asyncio
async def test_llm_recovery_when_model_installed(sample_observation):
    """Verify agent automatically recovers to available=True when model becomes present."""
    agent = BuildingAIAgent()
    agent._available = False
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama_async_client = MagicMock()
    mock_model_obj = MagicMock()
    mock_model_obj.model = settings.LLM_MODEL
    mock_ollama_async_client.list = AsyncMock(return_value=MagicMock(models=[mock_model_obj]))

    with patch("ollama.AsyncClient", return_value=mock_ollama_async_client):
        is_avail = await agent.check_availability(force=True)
        assert is_avail is True
        assert agent.is_available is True


@pytest.mark.asyncio
async def test_llm_timeout_triggers_rule_based_fallback(sample_observation):
    """Verify timeout during Ollama chat triggers fallback and attribution=rule_based."""
    agent = BuildingAIAgent()
    agent._available = True
    agent._timeout = 1

    from unittest.mock import MagicMock
    mock_async_client = MagicMock()

    async def timeout_chat(*args, **kwargs):
        raise asyncio.TimeoutError("Timeout in test")

    mock_async_client.chat = timeout_chat

    with patch("ollama.AsyncClient", return_value=mock_async_client):
        decision = await agent.analyze_and_decide(sample_observation)
        assert decision.controller_source == "rule_based"
        assert "[Fallback]" in decision.reasoning
        assert agent.is_available is False
