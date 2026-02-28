"""Pydantic schemas for HammerGuard."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    RED = "R"
    YELLOW = "Y"
    GREEN = "G"


class CheckItem(str, Enum):
    GREASE_TOOL = "grease_tool"
    INSPECT_CRACKS_BURRS = "inspect_cracks_burrs"
    INSPECT_PINS = "inspect_pins"
    INSPECT_BUSHINGS = "inspect_bushings"
    CHECK_JUMPER_LINES = "check_jumper_lines"
    NOTE_BLANK_FIRING = "note_blank_firing"


class CreateFindingSchema(BaseModel):
    component: str = Field(..., description="Detected component label, e.g. 'tool_bit', 'bushing', 'hose'")
    check: str = Field(..., description="Which checklist item this addresses")
    status: Status = Field(..., description="R(ed) / Y(ellow) / G(reen) severity")
    evidence_ids: list[str] = Field(default_factory=list, description="SHA-256 hashes of evidence files")
    notes: str = Field("", description="Free-text observation or transcribed audio")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Model confidence 0-1")
    suggested_parts: list[str] = Field(default_factory=list, description="Part numbers from catalog")


class Finding(CreateFindingSchema):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ManifestEntry(BaseModel):
    filename: str
    sha256: str
    media_type: str  # "image" | "audio"
    uploaded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    size_bytes: int = 0


class SessionManifest(BaseModel):
    session_id: str
    hammer_model: str = "Cat H95s"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entries: list[ManifestEntry] = Field(default_factory=list)
    checklist: dict[str, Optional[bool]] = Field(
        default_factory=lambda: {item.value: None for item in CheckItem}
    )


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
