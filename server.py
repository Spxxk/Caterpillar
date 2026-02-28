"""WheelGuard-982 / HammerGuard — FastAPI backend.

Endpoints:
  GET  /                         → serves frontend
  POST /upload                   → upload image/audio evidence
  POST /upload_pdf               → upload + store inspection PDF
  POST /infer_from_pdf           → parse PDF → findings + report
  POST /infer                    → multimodal inference (HammerGuard path)
  GET  /evidence/{session}/{fn}  → serve evidence files
  GET  /data/parts_snapshot.json → parts catalog
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from schemas import (
    CheckItem,
    ChecklistItemSchema,
    Finding,
    InferRequest,
    InferResponse,
    ManifestEntry,
    PARTS_982,
    PdfInferRequest,
    PdfInferResponse,
    ReportMeta,
    SessionManifest,
    Status,
    UploadResponse,
    WheelLoaderFinding,
    parts_search_url,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("wheelguard")

BASE = Path(__file__).resolve().parent
EVIDENCE_DIR = BASE / "evidence"
EVIDENCE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="WheelGuard-982", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_dir(session_id: str) -> Path:
    d = EVIDENCE_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_manifest(session_id: str) -> SessionManifest:
    p = _session_dir(session_id) / "manifest.json"
    if p.exists():
        return SessionManifest.model_validate_json(p.read_text())
    return SessionManifest(session_id=session_id)


def _write_manifest(manifest: SessionManifest):
    p = _session_dir(manifest.session_id) / "manifest.json"
    p.write_text(manifest.model_dump_json(indent=2))


def _hash_and_store(content: bytes, ext: str, session_id: str, media_type: str) -> tuple[str, str]:
    """Hash content, store in session dir, return (safe_name, sha256)."""
    sha = hashlib.sha256(content).hexdigest()
    safe_name = f"{sha[:12]}{ext}"
    dest = _session_dir(session_id) / safe_name
    dest.write_bytes(content)
    return safe_name, sha


def _append_manifest_entry(session_id: str, filename: str, sha: str, media_type: str, size: int):
    manifest = _read_manifest(session_id)
    if not any(e.sha256 == sha for e in manifest.entries):
        manifest.entries.append(ManifestEntry(
            filename=filename,
            sha256=sha,
            media_type=media_type,
            size_bytes=size,
        ))
        _write_manifest(manifest)
    return manifest


# ---------------------------------------------------------------------------
# Failure-mode triage logic
# ---------------------------------------------------------------------------

TRANSMISSION_ACTIONS = [
    "Do NOT operate until inspected by qualified technician",
    "Check transmission fluid level and condition (color, smell, debris)",
    "Inspect transmission filter for restriction / metal particles",
    "Check for overheating — measure transmission oil temp",
    "Record 5–10 second audio clip of noise for remote diagnosis",
    "Review SMU hours against scheduled transmission service interval",
]

RADIATOR_ACTIONS = [
    "Do NOT continue operation until cleaned",
    "Blow out radiator cores with compressed air (low pressure, rear to front)",
    "Inspect fan and fan drive for proper operation",
    "Check coolant level and condition after cleaning",
    "Verify ambient temperature operating limits",
    "Schedule cooling system pressure test if recurrent",
]

COOLING_CHECKLIST = [
    "What is the ambient temperature?",
    "Is the cooling fan running and engaging properly?",
    "Is there visible clogging or debris on the radiator face?",
    "Any coolant leaks visible around hoses or radiator?",
    "Is the coolant level within spec after cleaning?",
]


def _match_parts(title: str, comments: str) -> list[str]:
    """Find matching parts search terms from the 982 catalog."""
    text = f"{title} {comments}".lower()
    matches = []
    keywords = {
        "transmission": ["transmission filter", "transmission oil"],
        "radiator": ["radiator core", "engine coolant"],
        "coolant": ["engine coolant"],
        "air cleaner": ["air filter"],
        "air filter": ["air filter"],
        "cutting edge": ["cutting edge", "bucket tips"],
        "tip": ["bucket tips"],
        "duo-cone": ["duo-cone seal"],
        "differential": ["differential oil"],
        "final drive": ["differential oil", "duo-cone seal"],
        "belt": ["fan belt"],
        "fuel filter": ["fuel filter"],
        "oil level": ["engine oil filter"],
        "cab air": ["cab air filter"],
    }
    for keyword, part_keys in keywords.items():
        if keyword in text:
            matches.extend(part_keys)
    return list(dict.fromkeys(matches))  # dedupe preserving order


def _build_findings_from_items(items: list, evidence_ids: list[str]) -> list[WheelLoaderFinding]:
    """Convert parsed checklist items into WheelLoaderFinding objects with triage logic."""
    findings: list[WheelLoaderFinding] = []

    for item in items:
        if item.status_rgb == "G":
            continue

        parts = _match_parts(item.title, item.comments)
        parts_terms = [PARTS_982[p]["search"] for p in parts if p in PARTS_982]

        actions: list[str] = []
        description = item.comments or f"{item.title}: requires attention"
        title_lower = item.title.lower()

        if item.status_rgb == "R" and "transmission" in title_lower:
            actions = TRANSMISSION_ACTIONS.copy()
            description = (
                f"CRITICAL: {item.comments or 'Abnormal condition detected'}. "
                "Transmission issues can lead to catastrophic failure and safety hazard. "
                "Unit must be taken out of service for inspection."
            )
        elif item.status_rgb == "R" and "radiator" in title_lower:
            actions = RADIATOR_ACTIONS.copy()
            description = (
                f"CRITICAL: {item.comments or 'Radiator requires immediate service'}. "
                "Debris accumulation causes overheating which damages engine and hydraulic components. "
                "Clean before any further operation."
            )
        elif item.status_rgb == "Y":
            actions = [
                f"Monitor: {item.comments}" if item.comments else f"Monitor {item.title} at next service",
                f"Log current condition for trend tracking (SMU-stamped)",
            ]
            if parts:
                actions.append(f"Verify parts availability: {', '.join(parts)}")

        findings.append(WheelLoaderFinding(
            severity=Status(item.status_rgb),
            title=f"{item.code} {item.title}",
            description=description,
            evidence_files=evidence_ids,
            recommended_actions=actions,
            parts_search_terms=parts_terms,
            section=item.section,
            checklist_code=item.code,
        ))

    findings.sort(key=lambda f: {"R": 0, "Y": 1, "G": 2}[f.severity.value])
    return findings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    return (BASE / "static" / "index.html").read_text()


@app.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    session_id: str = Form(""),
):
    if not session_id:
        session_id = uuid.uuid4().hex[:12]

    content = await file.read()
    ext = Path(file.filename or "file").suffix or ".bin"
    safe_name, sha = _hash_and_store(content, ext, session_id, "file")

    media_type = "pdf" if ext.lower() == ".pdf" else (
        "image" if ext.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else "audio"
    )
    _append_manifest_entry(session_id, safe_name, sha, media_type, len(content))

    log.info("Uploaded %s (%s, %d bytes, sha256=%s) session=%s",
             safe_name, media_type, len(content), sha[:12], session_id)
    return UploadResponse(filename=safe_name, sha256=sha, session_id=session_id)


@app.post("/upload_pdf", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    session_id: str = Form(""),
):
    if not session_id:
        session_id = uuid.uuid4().hex[:12]

    content = await file.read()
    sha = hashlib.sha256(content).hexdigest()

    sdir = _session_dir(session_id)
    dest = sdir / "report.pdf"
    dest.write_bytes(content)

    _append_manifest_entry(session_id, "report.pdf", sha, "pdf", len(content))

    log.info("PDF uploaded (%d bytes, sha256=%s) session=%s", len(content), sha[:12], session_id)
    return UploadResponse(filename="report.pdf", sha256=sha, session_id=session_id)


@app.post("/infer_from_pdf", response_model=PdfInferResponse)
async def infer_from_pdf(req: PdfInferRequest):
    session_id = req.session_id
    sdir = _session_dir(session_id)
    pdf_path = sdir / "report.pdf"

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="No report.pdf found in session. Upload a PDF first.")

    from models.pdf_parse import parse_inspection_pdf
    result = parse_inspection_pdf(pdf_path)

    manifest = _read_manifest(session_id)
    manifest.report_meta = ReportMeta(**{
        k: getattr(result.meta, k) for k in ReportMeta.model_fields
    })
    _write_manifest(manifest)

    evidence_ids = [e.sha256 for e in manifest.entries]

    checklist_schemas = [
        ChecklistItemSchema(
            section=it.section,
            code=it.code,
            title=it.title,
            raw_status=it.raw_status,
            status_rgb=it.status_rgb,
            comments=it.comments,
        )
        for it in result.items
    ]

    findings = _build_findings_from_items(result.items, evidence_ids)

    # Persist findings
    findings_path = sdir / "findings.json"
    findings_path.write_text(json.dumps([f.model_dump() for f in findings], indent=2))

    # Generate report
    try:
        from report import generate_wheelguard_report
        generate_wheelguard_report(sdir, manifest, result.meta, result.items, findings)
        report_url = f"/evidence/{session_id}/report.html"
    except Exception:
        log.warning("Report generation failed", exc_info=True)
        report_url = ""

    log.info("PDF inference complete for session %s: %d items, %d findings, %d parse errors",
             session_id, len(result.items), len(findings), len(result.parse_errors))

    return PdfInferResponse(
        session_id=session_id,
        meta=manifest.report_meta,
        checklist_items=checklist_schemas,
        findings=findings,
        report_url=report_url,
        parse_errors=result.parse_errors,
    )


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    """Original HammerGuard multimodal inference path."""
    session_id = req.session_id
    sdir = _session_dir(session_id)
    manifest = _read_manifest(session_id)

    manifest.checklist.update(req.checklist)
    _write_manifest(manifest)

    evidence_ids = [e.sha256 for e in manifest.entries]

    all_detections: list[dict] = []
    for entry in manifest.entries:
        if entry.media_type != "image":
            continue
        try:
            from models.vision import detect
            dets = detect(sdir / entry.filename)
            all_detections.extend([
                {"label": d.label, "category": d.category, "score": d.score, "bbox": d.bbox, "file": entry.filename}
                for d in dets
            ])
        except Exception:
            log.warning("Vision failed for %s", entry.filename, exc_info=True)

    audio_notes = ""
    for entry in manifest.entries:
        if entry.media_type != "audio":
            continue
        try:
            from models.audio import analyse
            result = analyse(sdir / entry.filename)
            audio_notes += result.raw_notes + " "
        except Exception:
            log.warning("Audio failed for %s", entry.filename, exc_info=True)
    audio_notes = audio_notes.strip() or "No audio evidence"

    try:
        from models.llm import generate_findings
        findings = generate_findings(all_detections, audio_notes, manifest.checklist, evidence_ids)
    except Exception:
        log.warning("LLM finding generation failed", exc_info=True)
        findings = []

    findings_path = sdir / "findings.json"
    findings_path.write_text(json.dumps([f.model_dump() for f in findings], indent=2))

    try:
        from report import generate_report
        generate_report(sdir, manifest, findings)
        report_url = f"/evidence/{session_id}/report.html"
    except Exception:
        log.warning("Report generation failed", exc_info=True)
        report_url = ""

    return InferResponse(session_id=session_id, findings=findings, report_url=report_url)


@app.get("/evidence/{session_id}/{filename}")
async def serve_evidence(session_id: str, filename: str):
    path = EVIDENCE_DIR / session_id / filename
    if not path.exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path)


@app.get("/data/parts_snapshot.json")
async def parts_snapshot_route():
    return json.loads((BASE / "data" / "parts_snapshot.json").read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
