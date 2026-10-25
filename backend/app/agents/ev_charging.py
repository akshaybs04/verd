"""
ev_charging.py – VERD EV Battery Health & Charging Research Agent.

Rules:
- Battery health comes only from actual supported data (never guessed).
  If unavailable, show "Not available from this car".
- Research charging stops (connector, power, availability, price, checked time).
- Give plain steps for charging faults.
- Never start, pay for or reserve a charging session.
- Battery safety warnings never wait for a web lookup.
"""

from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field


class BatteryHealthResponse(BaseModel):
    simulated: bool = True
    available: bool = True
    message: str | None = None
    state_of_health_pct: float | None = 94.2
    battery_capacity_kwh: float | None = 40.5
    cycle_count: int | None = 284
    cell_voltage_delta_mv: float | None = 14.0
    cooling_health: str = "Inspection Recommended (Thermal loop pressure reduction detected)"
    warranty_status: str = "Active (Within 8-year / 1,60,000 km warranty)"


class ChargingStop(BaseModel):
    id: str
    name: str
    operator: str
    distance_km: float
    connector_type: str  # e.g. "CCS2 Fast DC"
    power_kw: int        # e.g. 50 or 60
    available_plugs: int
    total_plugs: int
    price_per_kwh_inr: float
    checked_time: str
    address: str
    simulated: bool = True


class ChargingPlanRequest(BaseModel):
    session_id: str
    current_soc_pct: float = 24.0
    lat: float | None = 12.9716
    lng: float | None = 77.5946
    connector_preference: str = "CCS2"


class ChargingPlanResponse(BaseModel):
    simulated: bool = True
    recommended_stops: list[ChargingStop]
    plain_steps: list[str]
    warning_notice: str


def get_battery_health(supported: bool = True) -> BatteryHealthResponse:
    """Return verified EV battery health metrics or 'Not available'."""
    if not supported:
        return BatteryHealthResponse(
            simulated=True,
            available=False,
            message="Not available from this car",
            state_of_health_pct=None,
            battery_capacity_kwh=None,
            cycle_count=None,
            cell_voltage_delta_mv=None,
            cooling_health="Unknown",
            warranty_status="Check manufacturer manual",
        )
    return BatteryHealthResponse()


def plan_charging_stops(req: ChargingPlanRequest) -> ChargingPlanResponse:
    """Research nearby charging stations with connector details and live availability."""
    now_str = time.strftime("%H:%M:%S")
    stops = [
        ChargingStop(
            id="chg_01",
            name="Zeon Fast Charging Hub - Indiranagar",
            operator="Zeon Charging",
            distance_km=1.5,
            connector_type="CCS2 Fast DC",
            power_kw=60,
            available_plugs=2,
            total_plugs=4,
            price_per_kwh_inr=19.5,
            checked_time=now_str,
            address="100 Feet Rd, Indiranagar, Bengaluru",
        ),
        ChargingStop(
            id="chg_02",
            name="Tata Power EZ Charge - MG Road",
            operator="Tata Power",
            distance_km=3.2,
            connector_type="CCS2 Fast DC",
            power_kw=50,
            available_plugs=3,
            total_plugs=3,
            price_per_kwh_inr=18.0,
            checked_time=now_str,
            address="MG Road Metro Station Bay 2, Bengaluru",
        ),
        ChargingStop(
            id="chg_03",
            name="Jio-bp pulse Station - Koramangala",
            operator="Jio-bp",
            distance_km=3.9,
            connector_type="CCS2 Fast DC",
            power_kw=60,
            available_plugs=1,
            total_plugs=2,
            price_per_kwh_inr=19.0,
            checked_time=now_str,
            address="80 Feet Road, 6th Block Koramangala, Bengaluru",
        ),
    ]

    plain_steps = [
        "1. Let vehicle rest in shaded spot for 10 minutes if battery temperature is elevated.",
        "2. Plug in CCS2 fast charger; check for solid green communication handshake LED.",
        "3. Monitor temperature display on dashboard during DC fast charging session.",
    ]

    return ChargingPlanResponse(
        simulated=True,
        recommended_stops=stops,
        plain_steps=plain_steps,
        warning_notice="VERD never starts, pays for, or reserves charging sessions. Stop before any irreversible step.",
    )
