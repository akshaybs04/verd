# VERD – Vehicle Explanation, Reasoning & Dispatch
### Hackathon: "Swim with TinyFish" · Presidency University · Team: Starters

> **A car explains a fault in plain words, asks the driver for permission, then TinyFish web agents find nearby repair stations (slots, price range), check recalls and warranty, and handle EV battery and charging help. The workshop gets a ticket and a one-page PDF storyboard report. If a crash is detected, VERD requests an ambulance through an emergency channel.**

---

## ⚡ The 3-Minute Demo Script (End-to-End on One Phone)

1. **The Problem (0:00 - 0:45)**:
   - Driving in dense Bengaluru crawl (Indiranagar 100 Feet Rd, 38°C ambient).
   - Tap **"🔥 Overheat"** on the floating pitch bar.
   - Live telemetry updates immediately: Battery temp spikes to `62.0°C` (CRITICAL).
   - VERD explains the fault in **plain language**: *"Battery temperature is unusually high due to dense stop-and-go traffic and reduced cooling circulation."*
   - Driver can tap **"View Sensor Evidence"** to verify the CAN bus telemetry and z-score baseline.

2. **Consent Gate & TinyFish Parallel Web Agents (0:45 - 1:45)**:
   - Outbound search is strictly blocked by default (*No consent → no outbound call*).
   - Driver taps **"Approve Assistance"**.
   - **Fast first**: 3 nearby Bengaluru stations appear instantly.
   - TinyFish autonomous web agents inspect the top 3 stations in parallel via SSE:
     - ElectroFix EV Hub (Indiranagar): `Today 3:30 PM`, `₹850 - ₹1,400`.
     - VoltCare Express (Koramangala): `Today 3:15 PM`, `₹900 - ₹1,650`.
     - Apex Green Mobility (MG Road): `Today 4:00 PM`, `₹1,200 - ₹2,000`.
   - Driver can tap **"Watch"** to inspect the live TinyFish autonomous browser session!

3. **Workshop Dispatch & PDF Storyboard (1:45 - 2:15)**:
   - Driver taps **"Book Bay"** on ElectroFix.
   - Workshop booking ticket is generated (`TKT-BLR-...`).
   - Driver taps **"📄 View Workshop Storyboard PDF"**: opens a crisp, one-page ReportLab PDF diagnostic report with fault reasoning, telemetry vs baseline table, and driver consent audit.

4. **Multi-Role & Emergency Crash Response (2:15 - 3:00)**:
   - **Role Switcher**: Switch to **Owner** (remote lock, EV battery SOH at `94.2%`, recall bulletins) and **Fleet Manager** (3-vehicle fleet view with estimated downtime revenue loss).
   - **Crash Response**: Tap **"💥 Crash"**.
   - High-contrast **"ARE YOU OK?"** overlay with an animated 20-second countdown.
   - Driver can tap **"I'm OK (Cancel)"** or let it dispatch.
   - If dispatched: triggers simulated EMS ambulance dispatch + parallel lookup of nearest trauma hospital and EV hydraulic flatbed tow service without blocking emergency dispatch!

---

## 🛠️ Tech Stack & Architecture

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, ReportLab 5.1 |
| **Frontend** | React 18, Vite 6, Mobile-First PWA, Vanilla CSS Tokens & Glassmorphism |
| **Web Agents** | TinyFish Python SDK + Search API + Agent API (`/run-sse`) |
| **Safety** | Consent Gate, Mandatory Goal Safety Suffixes, Mock Emergency Dispatch |
| **Replay Cache** | `/data/replays/` for 100% offline demo reliability |

---

## 🔒 Safety & Privacy Principles

1. **No Consent → No Outbound Call**: Location and vehicle telemetry only leave the device after driver approval.
2. **Strict Data Minimization**: Zero driver personal identity, VIN ownership records, or financial information are transmitted.
3. **Mandatory Goal Suffix**: Every TinyFish agent goal strictly terminates with:  
   `"Do NOT confirm, submit or pay. Stop before any irreversible step."`
4. **Hard Timeouts**: 45-second execution ceiling with fallback to cached replays so the UI never blocks.
5. **Advisory First**: VERD advises only and never controls car actuators. Prominent **112 SOS** button is always accessible.
6. **GDPR "Delete My Data"**: Working `DELETE /me/data` wipes all session history and resets consent.

---

## 🚀 Quickstart Guide

### 1. Run the Backend & PWA
```bash
# In the repository root:
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser to:
👉 **`http://localhost:8000/`** (Serves the compiled React PWA directly!)

### 2. Run the Full Test Suite
```bash
cd backend
pytest -q
```
**Output**: `57 passed in ~6.0s` (100% test pass rate across all milestones).

---

## 📁 Repository Structure

```
├── AGENTS.md                   # Hackathon guidelines & milestones
├── README.md                   # System documentation & pitch guide
├── .env.example                # Environment template (TINYFISH_API_KEY)
├── app/                        # React + Vite Mobile-First PWA
│   ├── dist/                   # Production-compiled bundle served by FastAPI
│   ├── src/
│   │   ├── App.jsx             # Unified Cockpit: Driver, Owner, Fleet, Privacy & Crash
│   │   ├── index.css           # Modern dark mode design system & micro-animations
│   │   └── main.jsx
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI entry point & route definitions
│   │   ├── simulator.py        # CAN bus vehicle telemetry simulator
│   │   ├── baseline.py         # Rolling baseline statistics tracker
│   │   ├── anomaly.py          # Z-score & threshold anomaly detector
│   │   ├── causes.py           # Automotive fault cause mapping catalogue
│   │   ├── explainer.py        # Plain-language reasoning generator
│   │   ├── consent.py          # Strict Driver Consent Gate
│   │   ├── tinyfish_client.py  # Isolated TinyFish SDK client & safety enforcer
│   │   ├── stations.py         # Station catalogue & parallel agent orchestrator
│   │   ├── tickets.py          # Workshop ticket manager
│   │   ├── report.py           # ReportLab 1-page PDF storyboard generator
│   │   ├── crash.py            # Crash supervisor & 20s countdown manager
│   │   ├── emergency.py        # EmergencyDispatch & MockDispatch
│   │   └── agents/
│   │       ├── recall_warranty.py # MoRTH / TPEM manufacturer recall agent
│   │       └── ev_charging.py     # Battery health & charging research agent
│   └── tests/
│       ├── test_m1.py          # Simulator & anomaly tests
│       ├── test_m2.py          # Explainer & consent gate tests
│       ├── test_m3.py          # TinyFish client & station streaming tests
│       ├── test_m4.py          # Driver UI integration & static asset tests
│       └── test_m5_to_m9.py    # Tickets, PDF, Recalls, EV, and Crash tests
└── data/
    └── replays/                # Golden cached TinyFish agent runs for offline demo
```
