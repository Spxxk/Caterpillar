# HammerGuard — Cat H95s Hydraulic Hammer Inspector

Minimal AI-assisted inspection prototype for Caterpillar H95s hydraulic hammers.
Captures photo/audio evidence, runs SOTA vision + audio + LLM analysis, and generates
an offline HTML report with hashed evidence bundles.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate

# Minimal (rule-based fallback, no large model downloads)
pip install -r requirements.txt

# Start the server
python server.py
# → http://localhost:8000
```

Open `http://localhost:8000` on a phone or browser. Walk through the checklist,
capture a photo and/or record 5 seconds of audio, then tap **Submit Inspection**.

## Architecture

```
static/index.html     Mobile-first SPA (checklist + capture + results)
server.py             FastAPI — POST /upload, POST /infer, static serving
models/
  vision.py           GroundingDINO → YOLOv8 → manual fallback
  audio.py            RNNoise denoise → Whisper-tiny ASR + BPM estimation
  llm.py              Mistral 7B tool-call → OpenAI → rule-based fallback
schemas.py            Pydantic: CreateFindingSchema, manifest, etc.
report.py             Self-contained offline HTML report generator
data/
  parts_snapshot.json Pre-built Cat H95s parts catalog (13 components)
  demo/               Sample images + audio for offline testing
evidence/{session}/   Runtime evidence storage
  manifest.json       SHA-256 hashed file manifest
  findings.json       Structured inspection findings
  report.html         Offline HTML report
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve frontend |
| `/upload` | POST | Upload image/audio → saves to evidence, returns SHA-256 |
| `/infer` | POST | Run vision + audio + LLM pipeline → findings + report |
| `/evidence/{session}/{file}` | GET | Serve evidence files |
| `/data/parts_snapshot.json` | GET | Parts catalog |

### POST /upload

```
Content-Type: multipart/form-data
Fields: file (binary), session_id (string, optional)
Response: { filename, sha256, session_id }
```

### POST /infer

```json
{
  "session_id": "abc123",
  "checklist": {
    "grease_tool": true,
    "inspect_cracks_burrs": true,
    "inspect_pins": false,
    "inspect_bushings": true,
    "check_jumper_lines": false,
    "note_blank_firing": true
  }
}
```

Response: `{ session_id, findings: [...], report_url }`

## Finding Schema

```json
{
  "component": "bushing",
  "check": "inspect_bushings",
  "status": "Y",
  "evidence_ids": ["sha256..."],
  "notes": "Scoring visible on upper bushing",
  "confidence": 0.72,
  "suggested_parts": ["340-5407"]
}
```

## Model Cascade

Each model tier falls through gracefully:

| Task | Primary | Fallback | Manual |
|---|---|---|---|
| Vision | GroundingDINO (Apache-2.0) | YOLOv8-nano (AGPL) | Empty detections → manual tag |
| Audio | RNNoise + Whisper-tiny | Whisper-tiny only | No transcript |
| LLM | Mistral 7B Instruct v0.3 | OpenAI gpt-4.1-mini | Rule-based mapping |

To use OpenAI fallback, set `OPENAI_API_KEY` environment variable.

## Offline Demo

Demo fixtures are pre-generated in `data/demo/`. The system works fully offline
with the rule-based fallback — no model downloads required for basic operation.
Evidence bundles always include SHA-256 hashes regardless of which models ran.

## H95s Specs

- Operating frequency: 700–1260 bpm
- Sound level: ~124 dB
- Product page: https://parts.cat.com/en/catcorp/product/561-2555
