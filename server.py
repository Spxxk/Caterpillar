"""360° Tractor Inspection — FastAPI backend.

Endpoints:
  GET  /                          → frontend
  POST /upload_video              → upload walkaround video, extract frames
  POST /upload_audio              → upload supplemental audio evidence
  POST /infer                     → run deterministic VLM-style inference
  GET  /jobs/{job_id}/video       → serve original video
  GET  /jobs/{job_id}/frames/{fn} → serve extracted frame thumbnails
  GET  /jobs/{job_id}/report.html → serve offline HTML report
  GET  /jobs/{job_id}/findings.json → serve findings JSON
  GET  /jobs/{job_id}/report.pdf  → serve dealer-ready PDF
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from schemas import (
    AudioUploadResponse,
    ConditionCode,
    InferResponse,
    InspectionFinding,
    UploadResponse,
    VideoJobMeta,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("tractor-inspect")

BASE = Path(__file__).resolve().parent
JOBS_DIR = BASE / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="360° Tractor Inspection", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _job_dir(job_id: str) -> Path:
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_job_meta(job_id: str) -> VideoJobMeta | None:
    p = _job_dir(job_id) / "job.json"
    if p.exists():
        return VideoJobMeta.model_validate_json(p.read_text())
    return None


def _write_job_meta(meta: VideoJobMeta):
    p = _job_dir(meta.job_id) / "job.json"
    p.write_text(meta.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    return (BASE / "static" / "index.html").read_text()


@app.post("/upload_video", response_model=UploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    fps: float = Form(2.0),
):
    job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(job_id)

    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_path = jdir / f"video{ext}"
    content = await file.read()
    video_path.write_bytes(content)

    frames_dir = jdir / "frames"
    from models.video import extract_frames
    result = extract_frames(video_path, frames_dir, fps=fps)

    meta = VideoJobMeta(
        job_id=job_id,
        filename=file.filename or f"video{ext}",
        duration_sec=result.duration_sec,
        fps_extracted=result.fps_used,
        total_frames=result.total_frames,
    )
    _write_job_meta(meta)

    log.info("Video uploaded: job=%s, %.1fs, %d frames at %.1f fps",
             job_id, result.duration_sec, result.total_frames, fps)

    return UploadResponse(
        job_id=job_id,
        filename=meta.filename,
        duration_sec=result.duration_sec,
        total_frames=result.total_frames,
    )


@app.post("/upload_audio", response_model=AudioUploadResponse)
async def upload_audio(
    file: UploadFile = File(...),
    job_id: str = Form(...),
):
    jdir = _job_dir(job_id)
    content = await file.read()
    sha = hashlib.sha256(content).hexdigest()
    ext = Path(file.filename or "audio.webm").suffix or ".webm"
    safe_name = f"audio_{sha[:8]}{ext}"
    (jdir / safe_name).write_bytes(content)

    log.info("Audio uploaded: job=%s, %s, %d bytes", job_id, safe_name, len(content))
    return AudioUploadResponse(job_id=job_id, filename=safe_name, sha256=sha)


@app.post("/infer", response_model=InferResponse)
async def infer(job_id: str = Form(...)):
    meta = _read_job_meta(job_id)
    if meta is None:
        raise HTTPException(404, "Job not found. Upload a video first.")

    jdir = _job_dir(job_id)
    frames_dir = jdir / "frames"
    frame_files = sorted(f.name for f in frames_dir.glob("frame_*.jpg"))

    if not frame_files:
        raise HTTPException(400, "No frames extracted. Video may be corrupted.")

    from models.inference import infer_findings, estimate_coverage
    findings = infer_findings(frame_files, meta.duration_sec, meta.fps_extracted)
    coverage = estimate_coverage(findings)

    fail_count = sum(1 for f in findings if f.condition == ConditionCode.FAIL)
    monitor_count = sum(1 for f in findings if f.condition == ConditionCode.MONITOR)
    pass_count = sum(1 for f in findings if f.condition == ConditionCode.PASS)

    summary = {
        "total_findings": len(findings),
        "fail_count": fail_count,
        "monitor_count": monitor_count,
        "pass_count": pass_count,
        "overall": "FAIL" if fail_count > 0 else ("MONITOR" if monitor_count > 0 else "PASS"),
    }

    findings_path = jdir / "findings.json"
    findings_path.write_text(json.dumps({
        "job": meta.model_dump(),
        "coverage": coverage.model_dump(),
        "summary": summary,
        "findings": [f.model_dump() for f in findings],
    }, indent=2))

    from report import generate_html_report, generate_pdf_report
    try:
        generate_html_report(jdir, meta, findings, coverage, summary)
    except Exception:
        log.warning("HTML report generation failed", exc_info=True)

    try:
        generate_pdf_report(jdir, meta, findings, coverage, summary)
    except Exception:
        log.warning("PDF report generation failed", exc_info=True)

    log.info("Inference complete: job=%s, %d findings (%d FAIL, %d MONITOR, %d PASS)",
             job_id, len(findings), fail_count, monitor_count, pass_count)

    return InferResponse(
        job_id=job_id,
        inference_mode=meta.inference_mode.value,
        findings=findings,
        coverage=coverage,
        summary=summary,
        report_url=f"/jobs/{job_id}/report.html",
    )


# ---------------------------------------------------------------------------
# Static asset serving
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}/video")
async def serve_video(job_id: str):
    jdir = _job_dir(job_id)
    for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv"]:
        p = jdir / f"video{ext}"
        if p.exists():
            return FileResponse(p, media_type="video/mp4")
    raise HTTPException(404, "Video not found")


@app.get("/jobs/{job_id}/frames/{filename}")
async def serve_frame(job_id: str, filename: str):
    p = _job_dir(job_id) / "frames" / filename
    if not p.exists():
        raise HTTPException(404, "Frame not found")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/jobs/{job_id}/report.html")
async def serve_html_report(job_id: str):
    p = _job_dir(job_id) / "report.html"
    if not p.exists():
        raise HTTPException(404, "Report not generated yet")
    return FileResponse(p, media_type="text/html")


@app.get("/jobs/{job_id}/report.pdf")
async def serve_pdf_report(job_id: str):
    p = _job_dir(job_id) / "report.pdf"
    if not p.exists():
        raise HTTPException(404, "PDF report not generated yet")
    return FileResponse(p, media_type="application/pdf")


@app.get("/jobs/{job_id}/findings.json")
async def serve_findings(job_id: str):
    p = _job_dir(job_id) / "findings.json"
    if not p.exists():
        raise HTTPException(404, "Findings not generated yet")
    return FileResponse(p, media_type="application/json")


@app.get("/data/parts.json")
async def parts_catalog():
    return json.loads((BASE / "data" / "parts.json").read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
