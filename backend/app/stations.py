"""
stations.py – Station discovery, catalogue, and parallel agent orchestration.

Follows VERD rules:
- Fast first, detailed later: return station list immediately, then stream TinyFish results.
- Run top 3 in parallel.
- All external TinyFish calls happen exclusively through tinyfish_client.py.
- Always labelled SIMULATED for vehicle / station mock data.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from pydantic import BaseModel, Field

from app.tinyfish_client import (
    AgentStreamEvent,
    StationAgentResult,
    run_single_station_agent,
)


class Station(BaseModel):
    id: str
    name: str
    distance_km: float
    address: str
    phone: str
    specialties: list[str]
    rating: float = 4.8
    website_url: str
    simulated: bool = True


# Catalogue of Bengaluru service stations for the demo scenario
# Scenario: Overheating battery in Bengaluru traffic
BENGALURU_STATIONS: list[Station] = [
    Station(
        id="station_blr_01",
        name="ElectroFix EV Hub - Indiranagar",
        distance_km=1.2,
        address="100 Feet Rd, HAL 2nd Stage, Indiranagar, Bengaluru, Karnataka 560038",
        phone="+91 80 4123 4567",
        specialties=["EV Thermal Management", "Coolant Circulation", "Battery Diagnostics"],
        rating=4.9,
        website_url="https://demo.electrofix.in/indiranagar",
    ),
    Station(
        id="station_blr_02",
        name="VoltCare Express Workshop - Koramangala",
        distance_km=2.8,
        address="80 Feet Rd, 4th Block, Koramangala, Bengaluru, Karnataka 560034",
        phone="+91 80 2552 8899",
        specialties=["High-Voltage Diagnostics", "Emergency EV Bay", "Thermal Coolant Flush"],
        rating=4.7,
        website_url="https://demo.voltcare.in/koramangala",
    ),
    Station(
        id="station_blr_03",
        name="Apex Green Mobility Service - MG Road",
        distance_km=3.5,
        address="Mahatma Gandhi Rd, Shanthala Nagar, Ashok Nagar, Bengaluru, Karnataka 560001",
        phone="+91 80 4911 2233",
        specialties=["OEM Battery Servicing", "BMS Calibration", "Rapid Diagnostics"],
        rating=4.8,
        website_url="https://demo.apexmobility.in/mgroad",
    ),
    Station(
        id="station_blr_04",
        name="Blr AutoCraft EV Station - Domlur",
        distance_km=4.1,
        address="Intermediate Ring Rd, Domlur, Bengaluru, Karnataka 560071",
        phone="+91 80 6712 9000",
        specialties=["General EV Repair", "Radiator and Coolant Check"],
        rating=4.5,
        website_url="https://demo.blrautocraft.in/domlur",
    ),
]


def get_nearby_stations(
    lat: float | None = 12.9716,
    lng: float | None = 77.5946,
    limit: int = 10,
) -> list[Station]:
    """
    Fast first: Return nearby stations list immediately from local catalogue.
    Does NOT block for web agent lookups.
    """
    # Sorted by proximity
    stations = sorted(BENGALURU_STATIONS, key=lambda s: s.distance_km)
    return stations[:limit]


async def stream_top3_stations_agents(
    stations: list[Station] | None = None,
    fault_description: str = "High battery temperature in dense traffic, coolant circulation reduced",
) -> AsyncIterator[dict[str, Any]]:
    """
    Runs TinyFish agents for top 3 stations in parallel.
    Pushes real-time SSE event dicts to the consumer as each event occurs.
    """
    candidate_stations = (stations or get_nearby_stations())[:3]

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _worker(stn: Station) -> None:
        try:
            async for ev in run_single_station_agent(
                station_id=stn.id,
                station_name=stn.name,
                station_url=stn.website_url,
                fault_description=fault_description,
                address=stn.address,
                phone=stn.phone,
            ):
                await event_queue.put({
                    "event": f"station_agent_{ev.type}",
                    "station_id": stn.id,
                    "data": ev.model_dump(),
                })
        except Exception as exc:
            await event_queue.put({
                "event": "station_agent_error",
                "station_id": stn.id,
                "data": {"station_id": stn.id, "error": str(exc)},
            })

    async def _supervisor() -> None:
        # Launch top 3 in parallel
        tasks = [asyncio.create_task(_worker(stn)) for stn in candidate_stations]
        await asyncio.gather(*tasks)
        await event_queue.put(None)  # Sentinel to terminate queue consumer

    supervisor_task = asyncio.create_task(_supervisor())

    try:
        while True:
            item = await event_queue.get()
            if item is None:
                break
            yield item
    finally:
        if not supervisor_task.done():
            supervisor_task.cancel()
