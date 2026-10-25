"""
main.py – VERD FastAPI application entry point.

Milestone 1 routes:
  GET    /telemetry/stream   – SSE stream of SIMULATED telemetry
  POST   /faults/inject      – Inject a named fault into the simulator
  DELETE /faults/inject      – Clear active fault
  GET    /baseline/stats     – Baseline means/stds (debug)
  GET    /health             – Health check

Milestone 2 routes:
  GET    /alerts/current     – Latest anomaly events + plain-language explanation
  POST   /consent            – Driver grants or denies consent for outbound calls
  GET    /consent/{session_id} – Current consent state for a session
"""

from __future__ import annotations

import asyncio
import time
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.anomaly import AnomalyDetector, AnomalyEvent
from app.baseline import BaselineTracker
from app.consent import (
    ConsentGate,
    ConsentRequest,
    ConsentResponse,
    ConsentState,
    ConsentStatus,
    consent_gate,
)
from app.explainer import ExplainerResult, explain
from app.simulator import (
    TelemetryPacket,
    clear_fault,
    inject_fault,
    telemetry_stream,
)
from app.stations import (
    Station,
    get_nearby_stations,
    stream_top3_stations_agents,
)
from app.tickets import (
    Ticket,
    TicketCreateRequest,
    create_ticket,
    get_ticket,
    get_ticket_pdf_bytes,
    list_tickets,
)
from app.agents.recall_warranty import (
    RecallWarrantyResponse,
    get_vehicle_recalls,
)
from app.agents.ev_charging import (
    BatteryHealthResponse,
    ChargingPlanRequest,
    ChargingPlanResponse,
    get_battery_health,
    plan_charging_stops,
)
from app.crash import CrashStatus, crash_supervisor


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origins: str = "http://localhost:5173"
    emergency_mode: str = "mock"


settings = Settings()


# ---------------------------------------------------------------------------
# Shared state (single-worker dev/demo)
# ---------------------------------------------------------------------------

_baseline = BaselineTracker()
_detector = AnomalyDetector(_baseline)
_latest_events: list[AnomalyEvent] = []
_latest_packet: TelemetryPacket | None = None
_latest_explanation: ExplainerResult | None = None


async def _run_telemetry_loop() -> None:
    """Background task: pump simulator → baseline → detector → explainer."""
    global _latest_events, _latest_packet, _latest_explanation
    async for packet in telemetry_stream(interval_s=1.0):
        _latest_packet = packet
        _baseline.update(packet)
        events = _detector.check(packet)
        _latest_events = events
        _latest_explanation = explain(events)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_run_telemetry_loop())
    yield
    task.cancel()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VERD – Vehicle Explanation, Reasoning & Dispatch",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class FaultInjectRequest(BaseModel):
    fault: str


class FaultInjectResponse(BaseModel):
    ok: bool
    fault: str
    message: str


class ClearFaultResponse(BaseModel):
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# Routes – Milestone 1
# ---------------------------------------------------------------------------

@app.get("/telemetry/stream", summary="SSE stream of SIMULATED telemetry")
async def telemetry_stream_route(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of live (SIMULATED) telemetry packets."""

    async def _event_gen() -> AsyncIterator[str]:
        async for packet in telemetry_stream(interval_s=1.0):
            if await request.is_disconnected():
                break
            yield f"data: {packet.model_dump_json()}\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/faults/inject", response_model=FaultInjectResponse)
async def faults_inject(body: FaultInjectRequest) -> FaultInjectResponse:
    """Inject a named simulated fault into the vehicle simulator."""
    try:
        inject_fault(body.fault)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FaultInjectResponse(
        ok=True,
        fault=body.fault,
        message=f"Fault '{body.fault}' injected (SIMULATED). Data is not real.",
    )


@app.delete("/faults/inject", response_model=ClearFaultResponse)
async def faults_clear() -> ClearFaultResponse:
    """Clear any active fault and return to normal state."""
    clear_fault()
    return ClearFaultResponse(ok=True, message="Fault cleared. State reset to normal.")


@app.get("/baseline/stats", summary="Rolling baseline statistics (debug)")
async def baseline_stats() -> dict:
    return {"simulated": True, "stats": _baseline.snapshot()}


# ---------------------------------------------------------------------------
# Routes – Milestone 2: Alerts with explanation
# ---------------------------------------------------------------------------

@app.get("/alerts/current", summary="Current anomaly alerts with plain-language explanation")
async def alerts_current() -> dict:
    """
    Returns the most recent anomaly events AND a plain-language explanation.
    simulated=True is always present. consent_required=True reminds the UI
    to gate any outbound action behind driver approval.
    """
    explanation = _latest_explanation or explain([])
    return {
        "simulated": True,
        "count": len(_latest_events),
        "events": [e.model_dump() for e in _latest_events],
        "explanation": explanation.model_dump(),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Routes – Milestone 2: Consent gate
# ---------------------------------------------------------------------------

@app.post("/consent", response_model=ConsentResponse, summary="Driver consent for outbound calls")
async def post_consent(body: ConsentRequest) -> ConsentResponse:
    """
    Driver grants or denies consent for outbound calls (station search, ticket, etc.).

    Safety rule: No outbound call is made until this returns status=granted.
    Denying consent permanently blocks outbound calls for this session.
    """
    if body.granted:
        state = consent_gate.grant(body.session_id)
        message = (
            "Consent granted. VERD will now search for nearby service stations. "
            "Only vehicle data will be shared – no personal information."
        )
    else:
        state = consent_gate.deny(body.session_id)
        message = (
            "Consent denied. No data will be sent outside this device. "
            "You can still view local information."
        )

    return ConsentResponse(
        session_id=state.session_id,
        status=state.status,
        can_call_outbound=state.can_call_outbound,
        message=message,
    )


@app.get(
    "/consent/{session_id}",
    response_model=ConsentResponse,
    summary="Current consent state",
)
async def get_consent(session_id: str) -> ConsentResponse:
    """Return the current consent state for a session."""
    state = consent_gate.get(session_id)
    return ConsentResponse(
        session_id=state.session_id,
        status=state.status,
        can_call_outbound=state.can_call_outbound,
        message=f"Consent status: {state.status.value}",
    )


# ---------------------------------------------------------------------------
# Routes – Data deletion (privacy)
# ---------------------------------------------------------------------------

@app.delete("/me/data", summary="Delete session data (GDPR-style)")
async def delete_my_data(session_id: str) -> dict:
    """
    Delete all session data for the given session_id.
    Resets consent to PENDING. No personal data is held, but this clears
    any session-level records.
    """
    consent_gate.revoke(session_id)
    return {
        "ok": True,
        "message": (
            "Session data deleted. Consent has been reset. "
            "No personal data was held by VERD."
        ),
    }


# ---------------------------------------------------------------------------
# Routes – Milestone 3: Stations and TinyFish Agents
# ---------------------------------------------------------------------------

class StationsNearbyRequest(BaseModel):
    session_id: str
    lat: float | None = 12.9716
    lng: float | None = 77.5946
    fault_type: str | None = None


class StationsNearbyResponse(BaseModel):
    session_id: str
    simulated: bool = True
    stations: list[Station]
    count: int
    message: str


@app.post("/stations/nearby", response_model=StationsNearbyResponse, summary="Find nearby repair stations")
async def stations_nearby(body: StationsNearbyRequest) -> StationsNearbyResponse:
    """
    Find nearby service stations.
    Safety rule: Gated behind driver consent. If consent is not granted,
    location and vehicle data are never sent outbound.
    """
    if not consent_gate.can_call_outbound(body.session_id):
        raise HTTPException(
            status_code=403,
            detail="Driver consent required before locating service stations.",
        )

    stations = get_nearby_stations(lat=body.lat, lng=body.lng)
    return StationsNearbyResponse(
        session_id=body.session_id,
        simulated=True,
        stations=stations,
        count=len(stations),
        message=f"Discovered {len(stations)} nearby stations (fast lookup).",
    )


@app.get("/stations/stream", summary="SSE stream of per-station TinyFish results")
async def stations_stream(request: Request, session_id: str = Query(...)) -> StreamingResponse:
    """
    SSE stream of per-station TinyFish results.
    Safety rule: Driver consent required.
    Fast first: yields discovered stations list immediately,
    then runs TinyFish web agents on top 3 stations in parallel.
    """
    if not consent_gate.can_call_outbound(session_id):
        raise HTTPException(
            status_code=403,
            detail="Driver consent required before searching service stations.",
        )

    explanation = _latest_explanation or explain([])
    fault_desc = (
        explanation.headline
        if explanation and not explanation.all_clear
        else "High battery temperature in dense traffic"
    )

    async def _event_gen() -> AsyncIterator[str]:
        # 1. Fast first: yield discovered stations
        stations = get_nearby_stations()
        stations_data = [s.model_dump() for s in stations]
        yield f"event: stations_discovered\ndata: {json.dumps({'stations': stations_data})}\n\n"

        # 2. Detailed later: parallel top 3 agent runs
        async for item in stream_top3_stations_agents(stations=stations, fault_description=fault_desc):
            if await request.is_disconnected():
                break
            event_name = item.get("event", "station_agent_update")
            data_str = json.dumps(item.get("data", {}))
            yield f"event: {event_name}\ndata: {data_str}\n\n"

        yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Routes – Milestone 5: Workshop Tickets & PDF Reports
# ---------------------------------------------------------------------------

@app.post("/tickets", response_model=Ticket, summary="Create workshop booking ticket")
async def post_ticket(body: TicketCreateRequest) -> Ticket:
    """
    Create a workshop booking ticket.
    Safety rule: Consent required before dispatching ticket.
    """
    if not consent_gate.can_call_outbound(body.session_id):
        raise HTTPException(
            status_code=403,
            detail="Driver consent required before booking workshop ticket.",
        )
    return create_ticket(body)


@app.get("/tickets", response_model=list[Ticket], summary="List all workshop tickets")
async def get_tickets() -> list[Ticket]:
    return list_tickets()


@app.get("/tickets/{ticket_id}/pdf", summary="Download workshop storyboard PDF report")
async def get_ticket_pdf(ticket_id: str) -> Response:
    """Download or view the clean 1-page workshop diagnostic PDF."""
    pdf_bytes = get_ticket_pdf_bytes(ticket_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found.")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={ticket_id}.pdf"},
    )


# ---------------------------------------------------------------------------
# Routes – Milestone 8: Recalls & EV Charging Agents
# ---------------------------------------------------------------------------

@app.get("/recalls", response_model=RecallWarrantyResponse, summary="Check vehicle recalls and warranty")
async def recalls_route(
    make: str = "Tata",
    model: str = "Nexon EV Max",
    year: int = 2023,
    vin: str | None = None,
) -> RecallWarrantyResponse:
    """Check manufacturer recalls and warranty terms in plain English."""
    return get_vehicle_recalls(make=make, model=model, year=year, vin=vin)


@app.get("/ev/health", response_model=BatteryHealthResponse, summary="EV Battery Health metrics")
async def ev_health_route(supported: bool = True) -> BatteryHealthResponse:
    """Return verified battery health metrics. Never guessed."""
    return get_battery_health(supported=supported)


@app.post("/ev/charging/plan", response_model=ChargingPlanResponse, summary="Research EV charging stops")
async def ev_charging_plan_route(body: ChargingPlanRequest) -> ChargingPlanResponse:
    """Research nearby charging stations with connectors, pricing, and live availability."""
    return plan_charging_stops(body)


# ---------------------------------------------------------------------------
# Routes – Milestone 9: Crash Detection & Emergency Dispatch
# ---------------------------------------------------------------------------

class CrashSimulateRequest(BaseModel):
    impact_g: float = 5.2


@app.post("/crash/simulate", response_model=CrashStatus, summary="Simulate vehicle crash detection")
async def crash_simulate_route(body: CrashSimulateRequest) -> CrashStatus:
    """Trigger 20-second countdown for 'Are you OK?' prompt."""
    return crash_supervisor.simulate_crash(impact_g=body.impact_g)


@app.post("/emergency/cancel", response_model=CrashStatus, summary="Cancel emergency countdown")
async def emergency_cancel_route() -> CrashStatus:
    """Driver one-tap cancel during 20s countdown."""
    return crash_supervisor.cancel()


@app.post("/emergency/dispatch", response_model=CrashStatus, summary="Immediate emergency dispatch")
async def emergency_dispatch_route() -> CrashStatus:
    """Dispatch emergency services (MOCKED). Never contacts real emergency numbers."""
    return await crash_supervisor.dispatch_now()


@app.get("/emergency/stream", summary="SSE stream of crash countdown and emergency status")
async def emergency_stream_route(request: Request) -> StreamingResponse:
    """SSE stream of crash countdown and status."""
    async def _event_gen() -> AsyncIterator[str]:
        while True:
            if await request.is_disconnected():
                break
            st = crash_supervisor.get_status()
            yield f"data: {st.model_dump_json()}\n\n"
            if st.status in ("normal", "cancelled", "dispatched") and not st.active:
                await asyncio.sleep(2.0)
            else:
                await asyncio.sleep(1.0)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


# Mount static React PWA (serves index.html for root and assets for /assets/*)
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "app" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
