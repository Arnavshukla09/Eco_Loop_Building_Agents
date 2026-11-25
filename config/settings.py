"""
config/settings.py
──────────────────
Centralised configuration for the Honeywell Eco-Loop system.
All values can be overridden with environment variables or a .env file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    Application settings.  Override any value with an environment variable
    of the same name (case-insensitive) or by creating a .env file in the
    project root.
    """

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── EnergyPlus ────────────────────────────────────────────────────────────
    ENERGYPLUS_PATH: str = Field(
        default="C:/EnergyPlus-24-1-0",
        description="Root directory of your EnergyPlus installation.",
    )
    IDF_FILE: str = Field(
        default=str(ROOT_DIR / "energyplus" / "building.idf"),
        description="Path to the EnergyPlus IDF building model.",
    )
    WEATHER_FILE: str = Field(
        default="",
        description="Path to an EPW weather file (leave blank to use built-in weather model).",
    )

    # ── Simulation control ────────────────────────────────────────────────────
    SIMULATION_MODE: bool = Field(
        default=True,
        description=(
            "True  → use the built-in physics simulator (no EnergyPlus required).\n"
            "False → attempt to use the real EnergyPlus Python API and fall back "
            "to simulation if EnergyPlus is unavailable."
        ),
    )
    TIMESTEP_MINUTES: int = Field(
        default=15,
        gt=0,
        description="Simulation timestep in minutes.",
    )
    SPEEDUP_FACTOR: float = Field(
        default=60.0,
        ge=1.0, le=3600.0, allow_inf_nan=False,
        description=(
            "Simulation speedup factor (ratio of simulated seconds to wall-clock seconds). "
            "Default (60.0) means 1 wall-clock second represents 60 simulated seconds "
            "(1 simulated minute), so a 15-minute timestep takes 15.0 wall-clock seconds."
        ),
    )

    # ── Zones ─────────────────────────────────────────────────────────────────
    ZONES: List[str] = Field(
        default=["Core", "Perimeter_N", "Perimeter_S", "Perimeter_E", "Perimeter_W"],
        description="List of thermal zone names in the building model.",
    )
    COOLING_SETPOINT_DEFAULT: float = Field(default=24.0, ge=18.0, le=32.0)
    HEATING_SETPOINT_DEFAULT: float = Field(default=20.0, ge=10.0, le=25.0)
    COOLING_SETPOINT_MIN: float = Field(default=20.0)
    COOLING_SETPOINT_MAX: float = Field(default=30.0)
    HEATING_SETPOINT_MIN: float = Field(default=16.0)
    HEATING_SETPOINT_MAX: float = Field(default=22.0)

    # ── LLM / Ollama ──────────────────────────────────────────────────────────
    OLLAMA_HOST: str = Field(
        default="http://localhost:11434",
        description="URL of the local Ollama server.",
    )
    LLM_MODEL: str = Field(
        default="qwen2.5:1.5b",
        description="Ollama model tag to use for AI decisions.",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="LLM sampling temperature (lower = more deterministic).",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default=60,
        description="Maximum seconds to wait for an LLM response.",
    )

    # ── Control loop ──────────────────────────────────────────────────────────
    AGENT_INTERVAL_SECONDS: float = Field(
        default=30.0,
        gt=0.0, allow_inf_nan=False,
        description="How often (wall-clock seconds) the AI agent runs a control cycle.",
    )

    SIMULATION_SEED: int = Field(default=42, description="Shared active/reference simulation seed.")
    SIMULATION_START: str = "2024-01-01T08:00:00"
    CONTROL_PROVIDER: str = Field(default="hybrid", pattern="^(hybrid|rule_based|forecast|scheduled)$")
    TARIFF_OFFPEAK: float = Field(default=0.10, ge=0)
    TARIFF_PEAK: float = Field(default=0.25, ge=0)
    TARIFF_PEAK_START: int = Field(default=16, ge=0, le=23)
    TARIFF_PEAK_END: int = Field(default=21, ge=1, le=24)
    TARIFF_CURRENCY: str = "USD"
    MANUAL_OVERRIDE_MINUTES: int = Field(default=60, ge=1, le=1440)
    FAN_MODEL_ENABLED: bool = True

    # ── MCP Server ────────────────────────────────────────────────────────────
    MCP_HOST: str = Field(default="127.0.0.1")
    MCP_PORT: int = Field(default=8001)

    # ── FastAPI / WebSocket ───────────────────────────────────────────────────
    ENVIRONMENT: str = Field(
        default="development",
        pattern="^(development|dev|staging|production|prod)$",
        description="Deployment environment: 'development', 'staging', or 'production'. In production, mutating operations fail-closed if API_KEY is unset.",
    )
    REQUIRE_API_KEY: bool = Field(
        default=False,
        description="Enforce API key authentication even when ENVIRONMENT is development.",
    )
    API_HOST: str = Field(default="127.0.0.1")
    API_PORT: int = Field(default=8000)
    API_KEY: Optional[str] = Field(
        default=None,
        description="Optional API key for mutating control endpoints. If set, requires 'Authorization: Bearer <key>'",
    )
    CORS_ORIGINS: List[str] = Field(default=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ])
    WS_BROADCAST_INTERVAL: float = Field(
        default=2.0,
        description="Seconds between WebSocket state broadcasts to the dashboard.",
    )

    # ── Database / Persistence ────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default=f"sqlite+aiosqlite:///{str((ROOT_DIR / 'data' / 'ecoloop.db').as_posix())}",
        description="Database connection URL. Defaults to local SQLite via aiosqlite.",
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    HISTORY_MAX_LEN: int = Field(
        default=500,
        description="Maximum number of historical timestep records kept in memory.",
    )
    BASELINE_SETPOINT_COOLING: float = Field(
        default=22.0,
        description="Cooling setpoint used for baseline energy calculation (no AI).",
    )
    BASELINE_SETPOINT_HEATING: float = Field(
        default=21.0,
        description="Heating setpoint used for baseline energy calculation (no AI).",
    )

    # ── Building location (for weather model) ─────────────────────────────────
    LOCATION_NAME: str = Field(default="Chicago")
    LOCATION_LATITUDE: float = Field(default=41.85)
    LOCATION_LONGITUDE: float = Field(default=-87.65)


# Singleton instance – import this everywhere
settings = Settings()
