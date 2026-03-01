# 360° Tractor Inspection — Deterministic VLM Pipeline

Upload a 360° walkaround video of a tractor. The system extracts frames, runs
a deterministic VLM-style inspection pipeline, and produces a structured
inspection dashboard with condition codes, diagnostic remarks, evidence
thumbnails, parts links, and dealer-ready PDF/HTML reports.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open **http://localhost:8000**, upload a walkaround video, and tap **Run Inspection**.

## Architecture

```
server.py                FastAPI backend (video upload, inference, report serving)
schemas.py               Pydantic models (VideoJob, InspectionFinding, Parts, Coverage)
report.py                HTML + PDF report generators
static/index.html        Mobile-first dashboard (video player, findings table, evidence grid)
models/
  video.py               Frame extraction (OpenCV → ffmpeg fallback)
  inference.py           Deterministic VLM stub + real inference interface
data/
  parts.json             24 tractor parts with purchase URLs
  demo/                  Demo walkaround video + test media
jobs/{job_id}/           Per-inspection output
  video.mp4              Original uploaded video
  frames/                Extracted frame thumbnails
  findings.json          Structured inspection data
  report.html            Self-contained offline HTML report
  report.pdf             Dealer-ready PDF report
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve frontend |
| `/upload_video` | POST | Upload video → extract frames at configurable FPS |
| `/upload_audio` | POST | Upload supplemental audio evidence |
| `/infer` | POST | Run VLM-style inference → findings + reports |
| `/jobs/{id}/video` | GET | Serve original video |
| `/jobs/{id}/frames/{fn}` | GET | Serve frame thumbnails |
| `/jobs/{id}/report.html` | GET | Offline HTML report |
| `/jobs/{id}/report.pdf` | GET | Dealer-ready PDF report |
| `/jobs/{id}/findings.json` | GET | Structured findings JSON |

## Inference Modes

| Mode | Description |
|---|---|
| `STUB_DEMO` | Fixed deterministic findings matched to real extracted frames. No APIs, no model downloads. Used during hackathon. |
| `REAL_LOCAL` | Future extension point for on-device VLM inference. Same interface: `infer_findings(frames, metadata) → findings` |

## Finding Schema

```json
{
  "part_name": "Front Tempered Glass (Windshield)",
  "part_key": "front_glass",
  "condition": "FAIL",
  "remark": "Front tempered glass has visible crack spanning approximately 30 cm...",
  "confidence": 0.87,
  "evidence": {
    "timestamp_sec": 0.8,
    "thumbnail_filename": "frame_0001.jpg",
    "frame_index": 1
  },
  "replacement_part": {
    "display_name": "Front Tempered Glass (Windshield)",
    "part_number": "CAT-FG-3920",
    "purchase_url": "https://parts.cat.com/en/catcorp/search?q=front+windshield+glass+cab",
    "fitment_score": 0.85
  },
  "coverage_zone": "front"
}
```

## Features

- **Evidence-driven**: All findings backed by real video timestamps and extracted frame thumbnails
- **Coverage awareness**: Detects which zones (front/rear/left/right) are covered; warns on missing views
- **Deterministic demo**: Reliable outputs with no internet or model dependencies
- **Dealer-ready export**: One-click PDF with condition codes, remarks, evidence images, parts list
- **Parts awareness**: 24 tractor parts mapped to parts.cat.com search links
- **Video player integration**: Click any finding to jump to its timestamp in the video
- **Confidence scores**: Plausible fixed scores reflecting real VLM uncertainty patterns
