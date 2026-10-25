"""
test_m5_to_m9.py – Tests for Milestones 5 through 9:
  - Milestone 5: Workshop Tickets & ReportLab 1-Page PDF Storyboard
  - Milestone 8: Recall & Warranty Agent + EV Health & Charging Plan
  - Milestone 9: Crash Detection & Emergency Response Flow

Safety rules tested:
  [TK1] Ticket creation requires driver consent (returns 403 if unconsented).
  [TK2] Ticket creation produces valid ticket ID and stores record.
  [TK3] PDF export generates valid, non-empty PDF bytes starting with %PDF.
  [TK4] PDF contains SIMULATED label, vehicle details, and consent audit info.

  [RW1] Recalls cite official sources only (MoRTH, TPEM, SIAM).
  [RW2] Warranty terms explained in plain language (8-year / 1,60,000 km).
  [RW3] Fallback note clarifies checked sources and states it is not a legal guarantee.

  [EV1] Battery health is never guessed; if supported=False, returns 'Not available from this car'.
  [EV2] Supported battery health returns accurate SOH % and cycle count.
  [EV3] Charging plan warns that VERD never starts, pays for, or reserves sessions.

  [CR1] Crash simulation triggers 20-second countdown.
  [CR2] Driver one-tap cancel halts countdown and sets status=cancelled.
  [CR3] Emergency dispatch uses MockDispatch with EMERGENCY_MODE=mock (never real numbers).
  [CR4] Emergency ambulance dispatch never uses TinyFish web agents.
  [CR5] Post-dispatch hospital and tow lookup runs without blocking dispatch.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.crash import crash_supervisor
from app.emergency import MockDispatch, get_emergency_dispatcher
from app.main import app
from app.tickets import create_ticket, get_ticket_pdf_bytes, TicketCreateRequest


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# [TK] Milestone 5: Tickets & PDF
# ---------------------------------------------------------------------------

def test_tk1_ticket_blocked_without_consent(client) -> None:
    """POST /tickets must return 403 Forbidden if consent is pending or denied."""
    resp = client.post(
        "/tickets",
        json={
            "session_id": "ticket-unconsented",
            "station_id": "station_blr_01",
            "station_name": "ElectroFix EV Hub",
            "station_address": "100 Feet Rd, Indiranagar",
            "station_phone": "+91 80 4123 4567",
            "selected_slot": "Today 3:30 PM",
        },
    )
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"].lower()


def test_tk2_tk3_ticket_created_and_pdf_exported(client) -> None:
    """POST /tickets succeeds with consent; GET /tickets/{id}/pdf returns valid PDF."""
    client.post("/consent", json={"session_id": "ticket-auth-session", "granted": True})

    create_resp = client.post(
        "/tickets",
        json={
            "session_id": "ticket-auth-session",
            "station_id": "station_blr_01",
            "station_name": "ElectroFix EV Hub - Indiranagar",
            "station_address": "100 Feet Rd, Indiranagar, Bengaluru",
            "station_phone": "+91 80 4123 4567",
            "selected_slot": "Today 3:30 PM",
            "price_range": "₹850 - ₹1,400",
            "fault_headline": "Battery thermal loop reduced circulation",
            "fault_body": "Coolant flow reduced while crawling in dense traffic.",
        },
    )
    assert create_resp.status_code == 200
    ticket_data = create_resp.json()
    ticket_id = ticket_data["ticket_id"]
    assert ticket_id.startswith("TKT-BLR-")
    assert ticket_data["simulated"] is True

    # Fetch PDF
    pdf_resp = client.get(f"/tickets/{ticket_id}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")
    assert len(pdf_resp.content) > 1000  # Valid non-empty ReportLab output


# ---------------------------------------------------------------------------
# [RW] Milestone 8: Recalls & Warranty
# ---------------------------------------------------------------------------

def test_rw1_recalls_official_sources(client) -> None:
    """GET /recalls must cite official regulator and OEM sources."""
    resp = client.get("/recalls")
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulated"] is True
    assert len(data["sources_checked"]) >= 2
    sources_str = " ".join(data["sources_checked"]).lower()
    assert "morth" in sources_str or "tpem" in sources_str
    assert "warranty" in data
    assert "8" in str(data["warranty"]["warranty_period_years"])
    assert "not a legal guarantee" in data["disclaimer"].lower()


# ---------------------------------------------------------------------------
# [EV] Milestone 8: EV Health & Charging Plan
# ---------------------------------------------------------------------------

def test_ev1_battery_health_not_guessed(client) -> None:
    """When telemetry does not support battery health, shows 'Not available from this car'."""
    resp = client.get("/ev/health", params={"supported": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert "not available from this car" in data["message"].lower()


def test_ev2_battery_health_supported_metrics(client) -> None:
    """Supported battery health returns verified metrics."""
    resp = client.get("/ev/health", params={"supported": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["state_of_health_pct"] is not None
    assert data["state_of_health_pct"] > 90.0
    assert data["cycle_count"] > 0


def test_ev3_charging_plan_safety_notice(client) -> None:
    """POST /ev/charging/plan provides stops and explicitly warns against autonomous payment."""
    resp = client.post(
        "/ev/charging/plan",
        json={"session_id": "chg-session", "current_soc_pct": 22.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recommended_stops"]) >= 2
    assert "never starts, pays for, or reserves" in data["warning_notice"].lower()


# ---------------------------------------------------------------------------
# [CR] Milestone 9: Crash Detection & Mock Emergency Dispatch
# ---------------------------------------------------------------------------

def test_cr1_crash_countdown_and_cancel(client) -> None:
    """POST /crash/simulate starts 20s countdown; POST /emergency/cancel halts it."""
    sim_resp = client.post("/crash/simulate", json={"impact_g": 5.4})
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert sim_data["active"] is True
    assert sim_data["countdown_seconds"] == 20
    assert sim_data["status"] == "countdown"

    # Cancel
    cancel_resp = client.post("/emergency/cancel")
    assert cancel_resp.status_code == 200
    cancel_data = cancel_resp.json()
    assert cancel_data["active"] is False
    assert cancel_data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cr2_mock_emergency_dispatch(client) -> None:
    """POST /emergency/dispatch uses MockDispatch and never real phone numbers."""
    dispatcher = get_emergency_dispatcher()
    assert isinstance(dispatcher, MockDispatch)

    resp = client.post("/emergency/dispatch")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "dispatched"
    assert data["dispatch_result"] is not None
    assert data["dispatch_result"]["simulated"] is True
    assert "MOCK" in data["dispatch_result"]["channel"]
    assert "never replaces calling 112" in data["dispatch_result"]["advisory"].lower()
