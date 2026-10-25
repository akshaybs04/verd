"""
tickets.py – Workshop Ticket Management & PDF Dispatch for VERD.

Handles workshop booking tickets and integrates with report.py for PDF exports.
All vehicle data is labelled SIMULATED.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from pydantic import BaseModel, Field

from app.report import generate_ticket_pdf


class TicketCreateRequest(BaseModel):
    session_id: str
    station_id: str
    station_name: str
    station_address: str
    station_phone: str
    selected_slot: str
    price_range: str = "₹850 - ₹1,400"
    fault_headline: str = "High battery temperature in dense traffic"
    fault_body: str = "Battery cooling circulation reduced while crawling in Bengaluru traffic."
    telemetry_snapshot: dict[str, Any] = Field(default_factory=dict)
    source: str = "replayed"


class Ticket(BaseModel):
    ticket_id: str
    session_id: str
    station_id: str
    station_name: str
    station_address: str
    station_phone: str
    selected_slot: str
    price_range: str
    fault_headline: str
    fault_body: str
    telemetry_snapshot: dict[str, Any]
    source: str
    status: str = "confirmed"
    simulated: bool = True
    created_at: float = Field(default_factory=time.time)


# In-memory ticket registry (persists across demo run)
_TICKETS: dict[str, Ticket] = {}


def create_ticket(req: TicketCreateRequest) -> Ticket:
    """Create and store a workshop ticket."""
    tid = f"TKT-BLR-{uuid.uuid4().hex[:6].upper()}"
    ticket = Ticket(
        ticket_id=tid,
        session_id=req.session_id,
        station_id=req.station_id,
        station_name=req.station_name,
        station_address=req.station_address,
        station_phone=req.station_phone,
        selected_slot=req.selected_slot,
        price_range=req.price_range,
        fault_headline=req.fault_headline,
        fault_body=req.fault_body,
        telemetry_snapshot=req.telemetry_snapshot or {
            "battery_temp_c": 62.0,
            "coolant_temp_c": 52.0,
            "soc_pct": 72.0,
            "speed_kmh": 14.0,
        },
        source=req.source,
    )
    _TICKETS[tid] = ticket
    return ticket


def get_ticket(ticket_id: str) -> Ticket | None:
    """Get ticket by ID."""
    return _TICKETS.get(ticket_id)


def list_tickets() -> list[Ticket]:
    """List all created tickets."""
    return list(_TICKETS.values())


def get_ticket_pdf_bytes(ticket_id: str) -> bytes | None:
    """Generate PDF bytes for a ticket."""
    ticket = get_ticket(ticket_id)
    if not ticket:
        return None
    return generate_ticket_pdf(
        ticket_id=ticket.ticket_id,
        station_name=ticket.station_name,
        station_address=ticket.station_address,
        station_phone=ticket.station_phone,
        selected_slot=ticket.selected_slot,
        price_range=ticket.price_range,
        fault_headline=ticket.fault_headline,
        fault_body=ticket.fault_body,
        telemetry_snapshot=ticket.telemetry_snapshot,
        source=ticket.source,
        session_id=ticket.session_id,
    )
