"""HammerGuard — FastAPI backend for Cat H95s hydraulic hammer inspection."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from schemas import (
    CheckItem,
    Finding,
    InferRequest,
    InferResponse,
    ManifestEntry,
    SessionManifest,
    UploadResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("hammerguard")

BASE = Path(__file__).resolve().parent
EVIDENCE_DIR = BASE / "evidence"
EVIDENCE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="HammerGuard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


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
    sha = hashlib.sha256(content).hexdigest()
    ext = Path(file.filename or "file").suffix or ".bin"
    safe_name = f"{sha[:12]}{ext}"

    dest = _session_dir(session_id) / safe_name
    dest.write_bytes(content)

    media_type = "image" if ext.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else "audio"

    manifest = _read_manifest(session_id)
    if not any(e.sha256 == sha for e in manifest.entries):
        manifest.entries.append(ManifestEntry(
            filename=safe_name,
            sha256=sha,
            media_type=media_type,
            size_bytes=len(content),
        ))
        _write_manifest(manifest)

    log.info("Uploaded %s (%s, %d bytes, sha256=%s…) to session %s",
             safe_name, media_type, len(content), sha[:12], session_id)
    return UploadResponse(filename=safe_name, sha256=sha, session_id=session_id)


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    session_id = req.session_id
    sdir = _session_dir(session_id)
    manifest = _read_manifest(session_id)

    manifest.checklist.update(req.checklist)
    _write_manifest(manifest)

    evidence_ids = [e.sha256 for e in manifest.entries]

    # --- Vision ---
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

    # --- Audio ---
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

    # --- LLM findings ---
    try:
        from models.llm import generate_findings
        findings = generate_findings(all_detections, audio_notes, manifest.checklist, evidence_ids)
    except Exception:
        log.warning("LLM finding generation failed", exc_info=True)
        findings = []

    # --- Persist findings ---
    findings_path = sdir / "findings.json"
    findings_path.write_text(json.dumps([f.model_dump() for f in findings], indent=2))

    # --- Generate report ---
    try:
        from report import generate_report
        report_path = generate_report(sdir, manifest, findings)
        report_url = f"/evidence/{session_id}/report.html"
    except Exception:
        log.warning("Report generation failed", exc_info=True)
        report_url = ""

    log.info("Inference complete for session %s: %d findings", session_id, len(findings))
    return InferResponse(session_id=session_id, findings=findings, report_url=report_url)


@app.get("/evidence/{session_id}/{filename}")
async def serve_evidence(session_id: str, filename: str):
    path = EVIDENCE_DIR / session_id / filename
    if not path.exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path)


@app.get("/data/parts_snapshot.json")
async def parts_snapshot():
    return json.loads((BASE / "data" / "parts_snapshot.json").read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
