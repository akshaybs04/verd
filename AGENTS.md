# VERD – Vehicle Explanation, Reasoning & Dispatch
## Agent Instructions (AGENTS.md)
### Hackathon: "Swim with TinyFish" · Presidency University · Team: Starters

---

## What VERD Does
A car explains a fault in plain words, asks the driver for permission, then TinyFish web agents find nearby repair stations (slots, price range), check recalls and warranty, compare spare-part prices, and handle EV battery and charging help. The workshop gets a ticket and a one-page PDF report. If a crash is detected, VERD requests an ambulance through the emergency channel (mocked in the demo).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn, Pydantic, SQLite |
| Frontend | React + Vite, mobile-first PWA |
| Car data | Simulator only – always labelled **SIMULATED** |
| Web agents | TinyFish Search API + Agent API (`/run-sse`) via `tinyfish` Python SDK |
| Reports | ReportLab |

---

## Repo Layout

```
/backend/app/
    main.py
    simulator.py
    baseline.py
    anomaly.py
    causes.py
    explainer.py
    consent.py
    tinyfish_client.py
    stations.py
    report.py
    crash.py
    emergency.py
    agents/
        recall_warranty.py
        ev_charging.py
/backend/tests/
/app/                  # React PWA (driver, owner, fleet, privacy pages)
/data/replays/         # Cached TinyFish results for offline demo
.env.example
AGENTS.md              # This file
```

---

## API Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/telemetry/stream` | SSE stream of live telemetry |
| POST | `/faults/inject` | Inject a simulated fault |
| GET | `/alerts/current` | Current active alert |
| POST | `/consent` | Driver approves/denies outbound call |
| POST | `/stations/nearby` | Find nearby repair stations |
| GET | `/stations/stream` | SSE stream of per-station TinyFish results |
| POST | `/tickets` | Create workshop ticket |
| DELETE | `/me/data` | GDPR-style data deletion |
| GET | `/recalls` | Check recalls for vehicle |
| GET | `/ev/health` | EV battery health |
| POST | `/ev/charging/plan` | EV charging plan |
| POST | `/crash/simulate` | Simulate crash detection |
| POST | `/emergency/cancel` | Cancel emergency countdown |
| POST | `/emergency/dispatch` | Dispatch emergency |
| GET | `/emergency/stream` | SSE stream of emergency status |

---

## TinyFish Rules

1. **All TinyFish calls live only in `tinyfish_client.py`** – never in any other file, never in the frontend.
2. API key (`TINYFISH_API_KEY`) only in backend environment. **Never** in the app, git or logs.
3. Auth header is `X-API-Key`.
4. Every agent goal ends with: *"Do NOT confirm, submit or pay. Stop before any irreversible step."*
5. Request JSON output with fixed keys and validate with Pydantic.
6. **Fast first, detailed later**: return the station list immediately, then stream TinyFish results per station. Run the top 3 in parallel.
7. Hard timeout per run (~45 s). On failure show "call to confirm". **Never block the UI.**
8. Cache one good run per station in `/data/replays`. Label every result **live** or **replayed**.
9. Forward `streaming_url` to the UI so the audience can watch the agent.
10. Maximum 2 retries.

---

## Agent Specifications

### Recall & Warranty Agent
- Check **official** manufacturer and regulator sources only.
- Match make, model and year.
- Check VIN recalls only through legitimate supported sources; if none exist, say so and fall back to make/model/year.
- Explain warranty conditions in plain words and give next steps.
- If nothing is found, name the sources checked and say it is not a guarantee.

### EV Health & Charging Agent
- Battery health comes only from actual supported data (**never guessed**).
- If unavailable, show "Not available from this car".
- Research charging stops (connector, power, availability, price, checked time) and give plain steps for charging faults.
- **Never** start, pay for or reserve a charging session.
- Battery safety warnings **never** wait for a web lookup.

---

## Crash Response Flow

1. Detect crash (simulated).
2. 20-second "Are you OK?" countdown with one-tap cancel.
3. If no response → dispatch request + notify emergency contacts + car owner + mark rented car unavailable.
4. Ambulance request **must NOT** use TinyFish or any web agent.
5. Use `EmergencyDispatch` interface with `MockDispatch` for dev/demo (`EMERGENCY_MODE=mock` by default). **Never contacts real numbers.**
6. After dispatch, TinyFish agents look up nearby hospitals and tow services **in parallel**.
7. A slow or failed TinyFish job **must never block dispatch**.
8. Label mock results **SIMULATED**; state that VERD supports and **never replaces** calling 112.

---

## Safety and Privacy

- **No consent → no outbound call.** Location and fault data leave the device only after the driver taps Approve.
- Share vehicle data only, **no personal data**.
- Label simulated data and estimates (e.g. "about Rs. 1,500 per day lost" is an estimate).
- VERD advises only and **never controls** the car. Always show a **112 button** (first for Critical faults).
- If cause confidence is low, say **"I cannot tell"**.
- Every claim links to its evidence.
- Provide a working **"delete my data"** action.

---

## Roles

- One login holds several roles with a switch.
- Per-car permissions: driver, family (view-only), manager.
- Renter access ends with the booking window.
- Owner approves repairs.
- Phone lock on the owner role.

---

## Code Rules

- Type hints on every function.
- PEP 8 formatting.
- Pydantic validation for all request/response models.
- **No secrets in git** – keep `.env.example` current.
- Write tests for **every safety rule**.
- Plain-language UI copy.

---

## MUST NOT

- Call TinyFish from the frontend.
- Let an agent confirm or pay anywhere.
- Present simulated data as real.
- Estimate battery health.
- Query VIN data by unofficial means.
- Send real alerts to real emergency numbers in dev or demo mode.
- Add features outside the milestones without asking.

---

## Milestones

Do **one at a time**. Run `pytest -q` after each. Wait for "continue" before starting the next.

| # | Milestone |
|---|-----------|
| 1 | Simulator + baseline + anomaly (overheating battery in hot traffic) |
| 2 | Explainer + consent gate with tests |
| 3 | TinyFish client: station discovery, per-station Agent run, parallel top 3, SSE to UI, replay cache |
| 4 | Driver UI: alert card, Approve, nearby stations filling in, 112 button |
| 5 | Ticket + Storyboard PDF |
| 6 | Owner and fleet views with the role switch |
| 7 | Privacy page and demo control panel |
| 8 | Recall & Warranty and EV Health & Charging agents |
| 9 | Crash response with MockDispatch and tests |
| 10 | Polish: replay fallback, loading states, README |

---

## Demo Notes

- Demo is **3 minutes** long, end-to-end on **one phone**.
- All external calls are mocked/cached in `/data/replays` for offline demo reliability.
- The scenario is: overheating battery in hot Bengaluru traffic → driver consents → stations appear → ticket created → PDF generated.
