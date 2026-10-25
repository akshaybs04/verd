"""
emergency.py – Emergency Dispatch Interface and Mock Dispatcher for VERD.

Rules:
- Emergency ambulance dispatch MUST NOT use TinyFish or any web agent.
- EmergencyDispatch interface with MockDispatch for dev/demo (EMERGENCY_MODE=mock).
- NEVER contacts real numbers.
- Always labelled SIMULATED.
- State that VERD supports and NEVER replaces calling 112.
"""

from __future__ import annotations

import abc
import time
from typing import Any
from pydantic import BaseModel, Field


class DispatchPayload(BaseModel):
    session_id: str
    vehicle_model: str = "Tata Nexon EV Max"
    location: dict[str, float] = Field(default_factory=lambda: {"lat": 12.9716, "lng": 77.5946})
    impact_g_force: float = 4.8
    battery_status: str = "High Voltage Disconnect Triggered"
    emergency_contacts_notified: list[str] = Field(default_factory=lambda: ["Owner (+91 98765 43210)", "Fleet HQ"])
    timestamp: float = Field(default_factory=time.time)


class DispatchResult(BaseModel):
    simulated: bool = True
    dispatched: bool
    channel: str
    dispatch_id: str
    ambulance_status: str
    contacts_notified: bool
    owner_notified: bool
    rented_car_marked_unavailable: bool
    advisory: str


class EmergencyDispatch(abc.ABC):
    """Abstract interface for emergency dispatch."""

    @abc.abstractmethod
    async def dispatch(self, payload: DispatchPayload) -> DispatchResult:
        pass


class MockDispatch(EmergencyDispatch):
    """
    Mock dispatcher for dev and demo.
    NEVER contacts real emergency numbers.
    Always labelled SIMULATED.
    """

    async def dispatch(self, payload: DispatchPayload) -> DispatchResult:
        return DispatchResult(
            simulated=True,
            dispatched=True,
            channel="MOCK_EMERGENCY_SERVICES_112",
            dispatch_id=f"MOCK-AMB-{int(time.time())}",
            ambulance_status="MOCK DISPATCH: Nearest EMS Unit 14 Notified (ETA ~8 mins)",
            contacts_notified=True,
            owner_notified=True,
            rented_car_marked_unavailable=True,
            advisory="SIMULATED DISPATCH. VERD supports and NEVER replaces calling 112 in real emergencies.",
        )


def get_emergency_dispatcher() -> EmergencyDispatch:
    """Return configured emergency dispatcher (defaults to MockDispatch)."""
    return MockDispatch()
