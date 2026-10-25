"""
crash.py – Crash Response Flow & Safety Supervisor for VERD.

Crash Response Flow:
1. Detect crash (simulated).
2. 20-second "Are you OK?" countdown with one-tap cancel.
3. If no response -> dispatch request + notify emergency contacts + car owner + mark rented car unavailable.
4. Ambulance request MUST NOT use TinyFish or any web agent.
5. Use EmergencyDispatch interface with MockDispatch. NEVER contacts real numbers.
6. After dispatch, TinyFish agents look up nearby hospitals and tow services in parallel.
7. A slow or failed TinyFish job must NEVER block dispatch.
8. Label mock results SIMULATED; state that VERD supports and NEVER replaces calling 112.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator
from pydantic import BaseModel, Field

from app.emergency import (
    DispatchPayload,
    DispatchResult,
    get_emergency_dispatcher,
)


class HospitalTowInfo(BaseModel):
    hospitals: list[dict[str, Any]] = Field(default_factory=list)
    tow_services: list[dict[str, Any]] = Field(default_factory=list)
    simulated: bool = True


class CrashStatus(BaseModel):
    simulated: bool = True
    active: bool = False
    countdown_seconds: int = 0
    status: str = "normal"  # "normal" | "countdown" | "cancelled" | "dispatched"
    impact_g: float = 0.0
    dispatch_result: DispatchResult | None = None
    hospital_tow_info: HospitalTowInfo | None = None
    message: str = "Nominal monitoring active."


class CrashSupervisor:
    """Manages crash lifecycle, 20-second countdown, and parallel post-dispatch agents."""

    def __init__(self) -> None:
        self.active: bool = False
        self.countdown: int = 0
        self.status: str = "normal"
        self.impact_g: float = 0.0
        self.dispatch_result: DispatchResult | None = None
        self.hospital_tow_info: HospitalTowInfo | None = None
        self._countdown_task: asyncio.Task[None] | None = None

    def simulate_crash(self, impact_g: float = 5.2) -> CrashStatus:
        """Trigger simulated high-impact collision."""
        self.active = True
        self.status = "countdown"
        self.countdown = 20
        self.impact_g = impact_g
        self.dispatch_result = None
        self.hospital_tow_info = None

        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()

        self._countdown_task = asyncio.create_task(self._run_countdown())
        return self.get_status("Simulated crash detected. 20-second countdown started.")

    async def _run_countdown(self) -> None:
        """Tick down from 20 to 0 unless cancelled."""
        try:
            while self.countdown > 0:
                await asyncio.sleep(1.0)
                self.countdown -= 1

            if self.status == "countdown":
                # Countdown finished without driver cancel -> automatic emergency dispatch
                await self.dispatch_now()
        except asyncio.CancelledError:
            pass

    def cancel(self) -> CrashStatus:
        """One-tap cancel from driver (Are you OK? -> Yes, Cancel)."""
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
        self.status = "cancelled"
        self.active = False
        self.countdown = 0
        return self.get_status("Emergency countdown cancelled by driver. No outbound dispatch sent.")

    async def dispatch_now(self) -> CrashStatus:
        """
        Immediately dispatch emergency services.
        Ambulance request MUST NOT use TinyFish or web agent (uses MockDispatch).
        """
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()

        dispatcher = get_emergency_dispatcher()
        payload = DispatchPayload(
            session_id="emergency-dispatch-live",
            impact_g_force=self.impact_g or 4.9,
        )
        self.dispatch_result = await dispatcher.dispatch(payload)
        self.status = "dispatched"
        self.active = False
        self.countdown = 0

        # After dispatch: TinyFish agents look up hospitals and tow in parallel (never blocking dispatch)
        asyncio.create_task(self._fetch_post_dispatch_support())

        return self.get_status("Emergency dispatch completed (MOCKED). EMS unit en route.")

    async def _fetch_post_dispatch_support(self) -> None:
        """Look up nearest emergency trauma centers and heavy EV flatbed tow services in parallel."""
        # Simulated fast agent lookup
        await asyncio.sleep(0.5)
        self.hospital_tow_info = HospitalTowInfo(
            simulated=True,
            hospitals=[
                {
                    "name": "Manipal Hospital Emergency Trauma Unit - HAL Old Airport Rd",
                    "distance_km": 2.4,
                    "phone": "+91 80 2502 4444",
                    "status": "Level 1 Trauma Bay Notified",
                },
                {
                    "name": "Apollo Emergency Care - Indiranagar",
                    "distance_km": 3.1,
                    "phone": "+91 80 4668 8888",
                    "status": "24/7 ER Ready",
                },
            ],
            tow_services=[
                {
                    "name": "QuickRecovery EV Flatbed Crane Service",
                    "distance_km": 1.8,
                    "phone": "+91 80 9988 7766",
                    "vehicle": "Hydraulic Zero-Degree Flatbed (EV Safe)",
                    "eta_mins": 12,
                }
            ],
        )

    def get_status(self, message: str = "") -> CrashStatus:
        return CrashStatus(
            simulated=True,
            active=self.active,
            countdown_seconds=self.countdown,
            status=self.status,
            impact_g=self.impact_g,
            dispatch_result=self.dispatch_result,
            hospital_tow_info=self.hospital_tow_info,
            message=message or f"Current crash status: {self.status}",
        )


crash_supervisor = CrashSupervisor()
