"""
simulator.py – VERD telemetry simulator.

Produces SIMULATED vehicle telemetry ticks every second.
All output is always labelled simulated=True; never presented as real sensor data.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import AsyncIterator

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TelemetryPacket(BaseModel):
    """One tick of vehicle telemetry. Always labelled simulated."""

    timestamp: float = Field(default_factory=time.time)
    simulated: bool = True  # Safety invariant: always True

    # Powertrain
    battery_temp_c: float  # °C
    battery_soc_pct: float  # 0–100
    motor_rpm: int
    motor_temp_c: float

    # Thermal / environment
    coolant_temp_c: float
    ambient_temp_c: float

    # Motion
    speed_kmh: float
    throttle_pct: float  # 0–100

    # Electrical
    voltage_v: float
    current_a: float

    # Health indicators
    fault_code: str | None = None  # e.g. "P0A1B" or None


# ---------------------------------------------------------------------------
# Baseline (normal Bengaluru commute, ~32 °C day)
# ---------------------------------------------------------------------------

NORMAL_STATE: dict[str, float | int | None] = {
    "battery_temp_c": 32.0,
    "battery_soc_pct": 78.0,
    "motor_rpm": 1400,
    "motor_temp_c": 55.0,
    "coolant_temp_c": 40.0,
    "ambient_temp_c": 32.0,
    "speed_kmh": 35.0,
    "throttle_pct": 30.0,
    "voltage_v": 396.0,
    "current_a": 85.0,
    "fault_code": None,
}

# Fault injection recipes
FAULT_RECIPES: dict[str, dict[str, float | int | str | None]] = {
    "battery_overheat": {
        "battery_temp_c": 62.0,   # well above 55 °C critical threshold
        "coolant_temp_c": 58.0,
        "motor_temp_c": 72.0,
        "speed_kmh": 8.0,          # stuck in traffic
        "fault_code": "P0A1B",
    },
    "low_soc": {
        "battery_soc_pct": 8.0,
        "fault_code": "P0AFA",
    },
    "motor_fault": {
        "motor_rpm": 0,
        "motor_temp_c": 90.0,
        "fault_code": "P0B3F",
    },
}


# ---------------------------------------------------------------------------
# Simulator state (module-level singleton, safe for single-worker demo)
# ---------------------------------------------------------------------------

_state: dict = dict(NORMAL_STATE)
_active_fault: str | None = None


def inject_fault(fault_name: str) -> None:
    """Merge a fault recipe into the running state."""
    global _active_fault
    recipe = FAULT_RECIPES.get(fault_name)
    if recipe is None:
        raise ValueError(f"Unknown fault: {fault_name!r}. Valid: {list(FAULT_RECIPES)}")
    _state.update(recipe)
    _active_fault = fault_name


def clear_fault() -> None:
    """Reset state to normal."""
    global _state, _active_fault
    _state = dict(NORMAL_STATE)
    _active_fault = None


def _add_jitter(value: float, pct: float = 0.02) -> float:
    """Add ±pct relative noise to a float value."""
    return value * (1.0 + random.uniform(-pct, pct))


def _current_tick() -> TelemetryPacket:
    """Build one telemetry packet from _state with natural jitter."""
    return TelemetryPacket(
        battery_temp_c=_add_jitter(_state["battery_temp_c"]),  # type: ignore[arg-type]
        battery_soc_pct=max(0.0, min(100.0, _add_jitter(_state["battery_soc_pct"]))),  # type: ignore[arg-type]
        motor_rpm=int(_add_jitter(float(_state["motor_rpm"]), 0.05)),  # type: ignore[arg-type]
        motor_temp_c=_add_jitter(_state["motor_temp_c"]),  # type: ignore[arg-type]
        coolant_temp_c=_add_jitter(_state["coolant_temp_c"]),  # type: ignore[arg-type]
        ambient_temp_c=_state["ambient_temp_c"],  # type: ignore[assignment]
        speed_kmh=max(0.0, _add_jitter(_state["speed_kmh"])),  # type: ignore[arg-type]
        throttle_pct=max(0.0, min(100.0, _add_jitter(_state["throttle_pct"]))),  # type: ignore[arg-type]
        voltage_v=_add_jitter(_state["voltage_v"]),  # type: ignore[arg-type]
        current_a=_add_jitter(_state["current_a"]),  # type: ignore[arg-type]
        fault_code=_state["fault_code"],  # type: ignore[arg-type]
    )


async def telemetry_stream(interval_s: float = 1.0) -> AsyncIterator[TelemetryPacket]:
    """Async generator: yields one TelemetryPacket every interval_s seconds."""
    while True:
        yield _current_tick()
        await asyncio.sleep(interval_s)
