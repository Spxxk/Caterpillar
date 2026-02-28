"""Pydantic schemas for WheelGuard-982 + HammerGuard."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class Status(str, Enum):
    RED = "R"
    YELLOW = "Y"
    GREEN = "G"


# ---------------------------------------------------------------------------
# HammerGuard originals (kept for backward compat)
# ---------------------------------------------------------------------------

class CheckItem(str, Enum):
    GREASE_TOOL = "grease_tool"
    INSPECT_CRACKS_BURRS = "inspect_cracks_burrs"
    INSPECT_PINS = "inspect_pins"
    INSPECT_BUSHINGS = "inspect_bushings"
    CHECK_JUMPER_LINES = "check_jumper_lines"
    NOTE_BLANK_FIRING = "note_blank_firing"


class CreateFindingSchema(BaseModel):
    component: str = Field(..., description="Detected component label")
    check: str = Field(..., description="Which checklist item this addresses")
    status: Status = Field(..., description="R(ed) / Y(ellow) / G(reen) severity")
    evidence_ids: list[str] = Field(default_factory=list, description="SHA-256 hashes of evidence files")
    notes: str = Field("", description="Free-text observation or transcribed audio")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Model confidence 0-1")
    suggested_parts: list[str] = Field(default_factory=list, description="Part numbers from catalog")


class Finding(CreateFindingSchema):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# WheelGuard-982: PDF-parsed report structures
# ---------------------------------------------------------------------------

class ReportMeta(BaseModel):
    model: str = ""
    serial: str = ""
    smu_hours: int = 0
    completed_on: str = ""
    location: str = ""
    inspector: str = ""
    customer_name: str = ""
    work_order: str = ""
    asset_id: str = ""
    inspection_number: str = ""


class ChecklistItemSchema(BaseModel):
    section: str
    code: str
    title: str
    raw_status: str  # PASS / NORMAL / MONITOR / FAIL
    status_rgb: str  # G / Y / R
    comments: str = ""


class WheelLoaderFinding(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    severity: Status = Field(..., description="R / Y / G")
    title: str = Field(..., description="Short title for the finding")
    description: str = Field("", description="Full description with context")
    evidence_files: list[str] = Field(default_factory=list, description="SHA-256 hashes")
    recommended_actions: list[str] = Field(default_factory=list)
    parts_search_terms: list[str] = Field(default_factory=list, description="Search terms for parts.cat.com")
    section: str = ""
    checklist_code: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Evidence + manifest (shared)
# ---------------------------------------------------------------------------

class ManifestEntry(BaseModel):
    filename: str
    sha256: str
    media_type: str  # "image" | "audio" | "pdf"
    uploaded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    size_bytes: int = 0


class SessionManifest(BaseModel):
    session_id: str
    equipment_model: str = "Cat 982 Wheel Loader"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entries: list[ManifestEntry] = Field(default_factory=list)
    checklist: dict[str, Optional[bool]] = Field(default_factory=dict)
    report_meta: Optional[ReportMeta] = None


# ---------------------------------------------------------------------------
# API request/response
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    filename: str
    sha256: str
    session_id: str


class InferRequest(BaseModel):
    session_id: str
    checklist: dict[str, Optional[bool]] = Field(default_factory=dict)


class InferResponse(BaseModel):
    session_id: str
    findings: list[Finding]
    report_url: str


class PdfInferRequest(BaseModel):
    session_id: str


class PdfInferResponse(BaseModel):
    session_id: str
    meta: ReportMeta
    checklist_items: list[ChecklistItemSchema]
    findings: list[WheelLoaderFinding]
    report_url: str
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parts mapping for 982 Wheel Loader (demo — approximate search terms)
# ---------------------------------------------------------------------------

PARTS_982: dict[str, dict] = {
    "duo-cone seal": {
        "search": "982 duo-cone seal",
        "description": "Duo-cone seals for axle/final drive",
    },
    "radiator core": {
        "search": "982 radiator core",
        "description": "Radiator core assembly for cooling system",
    },
    "air filter": {
        "search": "982 air filter element",
        "description": "Primary/secondary engine air filter",
    },
    "transmission filter": {
        "search": "982 transmission filter",
        "description": "Transmission oil filter element",
    },
    "transmission oil": {
        "search": "982 transmission oil TO-4",
        "description": "Cat TO-4 transmission/drive train oil",
    },
    "differential oil": {
        "search": "982 differential final drive oil",
        "description": "Final drive / differential lubricant",
    },
    "engine coolant": {
        "search": "982 extended life coolant ELC",
        "description": "Cat ELC (Extended Life Coolant)",
    },
    "engine oil filter": {
        "search": "982 engine oil filter",
        "description": "Engine oil filter element",
    },
    "fuel filter": {
        "search": "982 fuel filter primary secondary",
        "description": "Primary and secondary fuel filters",
    },
    "cutting edge": {
        "search": "982 bucket cutting edge",
        "description": "Bolt-on cutting edge for bucket",
    },
    "bucket tips": {
        "search": "982 bucket tip adapter",
        "description": "Bucket tooth tips and adapters",
    },
    "fan belt": {
        "search": "982 serpentine belt fan",
        "description": "Engine fan / serpentine belt",
    },
    "cab air filter": {
        "search": "982 cab air filter HVAC",
        "description": "Cab fresh air / recirculation filter",
    },
}


def parts_search_url(query: str) -> str:
    """Build a parts.cat.com search URL for a given query string."""
    from urllib.parse import quote_plus
    return f"https://parts.cat.com/en/catcorp/search?q={quote_plus(query)}"
