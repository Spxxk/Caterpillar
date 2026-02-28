# WheelGuard-982 + HammerGuard

AI-assisted inspection triage for Caterpillar heavy equipment.

- **WheelGuard-982** — Upload a Cat 982 Wheel Loader inspection PDF, get structured findings with failure-mode triage cards, action plans, and parts.cat.com search links.
- **HammerGuard** — Photo/audio capture pipeline for Cat H95s hydraulic hammer inspections.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open **http://localhost:8000**, upload an inspection PDF, and tap **Generate Inspection Report**.

## Architecture

```
server.py                FastAPI backend (6 endpoints)
schemas.py               Pydantic models + 982 parts mapping
report.py                Offline HTML report generators (WheelGuard + HammerGuard)
static/index.html        Mobile-first frontend (PDF upload + evidence capture)
models/
  pdf_parse.py           PDF → structured sections + checklist items + statuses
  vision.py              GroundingDINO → YOLO → manual (HammerGuard path)
  audio.py               RNNoise → Whisper-tiny + BPM (HammerGuard path)
  llm.py                 Mistral 7B → OpenAI → rule-based (HammerGuard path)
data/
  parts_snapshot.json    Cat H95s parts catalog
  demo/                  Synthetic test media
evidence/{session}/      Runtime output per inspection
  report.pdf             Uploaded inspection PDF
  manifest.json          SHA-256 hashed evidence inventory
  findings.json          Structured findings array
  report.html            Self-contained offline report
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve frontend |
| `/upload` | POST | Upload image/audio → SHA-256 hash → manifest |
| `/upload_pdf` | POST | Upload inspection PDF → store as `report.pdf` + hash |
| `/infer_from_pdf` | POST | Parse PDF → findings + report.html |
| `/infer` | POST | Multimodal inference (HammerGuard path) |
| `/evidence/{session}/{file}` | GET | Serve evidence files |

## WheelGuard-982 Pipeline

1. **PDF Upload** — Stored as evidence, SHA-256 hashed, appended to manifest
2. **PDF Parsing** (`models/pdf_parse.py`) — Extracts:
   - Header metadata (model, serial, SMU, inspector, customer, location, etc.)
   - 4 inspection sections: From the Ground, Engine Compartment, Outside Cab, Inside Cab
   - Per-item status normalization: PASS/NORMAL → GREEN, MONITOR → YELLOW, FAIL → RED
3. **Finding Generation** — Deterministic triage logic:
   - Transmission FAIL → RED with 6-step noise triage (including audio capture prompt)
   - Radiator FAIL → RED with cooling performance checklist
   - MONITOR items → YELLOW with monitoring + parts suggestions
4. **Report Generation** — Self-contained offline HTML with:
   - Executive summary (RED first, then YELLOW)
   - Per-section checklist tables
   - Failure mode cards with triage workflows
   - Action plan with prioritized tasks
   - Parts.cat.com search links with `confidence: demo` badges
   - Evidence manifest with SHA-256 hashes

## Finding Schema

```json
{
  "id": "a1b2c3d4e5f6",
  "severity": "R",
  "title": "1.7 Transmission and Transfer Gears",
  "description": "CRITICAL: Abnormal noise detected...",
  "evidence_files": ["9508d489320b..."],
  "recommended_actions": [
    "Do NOT operate until inspected",
    "Check transmission fluid level and condition",
    "Record 5-10 second audio clip of noise"
  ],
  "parts_search_terms": ["982 transmission filter", "982 transmission oil TO-4"],
  "section": "FROM THE GROUND",
  "checklist_code": "1.7"
}
```

## 982 Parts Mapping (Demo)

The system maps findings to parts.cat.com search URLs for:
duo-cone seal, radiator core, air filter, transmission filter/oil,
differential oil, engine coolant, cutting edge, bucket tips, fan belt,
cab air filter, engine oil filter, fuel filter.

All links include a `confidence: demo` badge — these are search queries, not verified part numbers.

## Offline-First

The entire pipeline works with **zero model downloads**. The PDF parsing and
finding generation are fully deterministic. Evidence bundles always include
SHA-256 hashes regardless of which AI models are available.
