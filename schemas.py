"""Pydantic schemas for 360° Tractor Inspection pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConditionCode(str, Enum):
    PASS = "PASS"
    MONITOR = "MONITOR"
    FAIL = "FAIL"


class InferenceMode(str, Enum):
    STUB_DEMO = "STUB_DEMO"
    REAL_LOCAL = "REAL_LOCAL"


class CoverageZone(str, Enum):
    FRONT = "front"
    REAR = "rear"
    LEFT = "left"
    RIGHT = "right"


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

class PartInfo(BaseModel):
    part_key: str
    display_name: str
    part_number: str
    purchase_url: str
    category: str
    fitment_score: float = 0.0


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class EvidenceFrame(BaseModel):
    timestamp_sec: float
    thumbnail_filename: str
    frame_index: int


class InspectionFinding(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    part_name: str
    part_key: str
    condition: ConditionCode
    remark: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EvidenceFrame
    replacement_part: Optional[PartInfo] = None
    coverage_zone: CoverageZone
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Video Job
# ---------------------------------------------------------------------------

class VideoJobMeta(BaseModel):
    job_id: str
    filename: str
    duration_sec: float = 0.0
    fps_extracted: float = 2.0
    total_frames: int = 0
    inference_mode: InferenceMode = InferenceMode.STUB_DEMO
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CoverageReport(BaseModel):
    zones_detected: list[CoverageZone] = Field(default_factory=list)
    zones_missing: list[CoverageZone] = Field(default_factory=list)
    coverage_pct: float = 0.0


class InspectionResult(BaseModel):
    job: VideoJobMeta
    coverage: CoverageReport
    findings: list[InspectionFinding]
    summary: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    job_id: str
    filename: str
    duration_sec: float
    total_frames: int


class InferResponse(BaseModel):
    job_id: str
    inference_mode: str
    findings: list[InspectionFinding]
    coverage: CoverageReport
    summary: dict
    report_url: str


class AudioUploadResponse(BaseModel):
    job_id: str
    filename: str
    sha256: str
