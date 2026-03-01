"""Deterministic VLM-style inference layer for tractor 360° inspection.

Modes:
  STUB_DEMO  — fixed findings every run, matched to nearest extracted frames.
               No external APIs, no model downloads.
  REAL_LOCAL — future extension point for on-device VLM inference.

The interface is:  infer_findings(frames, metadata) → list[InspectionFinding]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from schemas import (
    ConditionCode,
    CoverageReport,
    CoverageZone,
    EvidenceFrame,
    InspectionFinding,
    PartInfo,
)

log = logging.getLogger(__name__)

PARTS_DB: dict[str, PartInfo] = {}
_parts_path = Path(__file__).resolve().parent.parent / "data" / "parts.json"
if _parts_path.exists():
    for p in json.loads(_parts_path.read_text()):
        PARTS_DB[p["part_key"]] = PartInfo(**p)


# ---------------------------------------------------------------------------
# Remark templates
# ---------------------------------------------------------------------------

REMARK_TEMPLATES = {
    ConditionCode.FAIL: "{part} appears damaged; replacement recommended.",
    ConditionCode.MONITOR: "Possible wear observed on {part}; reinspection advised.",
    ConditionCode.PASS: "No visible damage detected on {part}.",
}


def _remark(condition: ConditionCode, part_name: str) -> str:
    return REMARK_TEMPLATES[condition].format(part=part_name)


# ---------------------------------------------------------------------------
# Stub finding definitions
# ---------------------------------------------------------------------------
# Each entry: (part_key, condition, confidence, zone, timestamp_pct)
# timestamp_pct is 0.0–1.0 representing where in the video this appears.

STUB_FINDINGS = [
    # FAIL items
    ("front_glass",         ConditionCode.FAIL,    0.87, CoverageZone.FRONT, 0.08),
    ("right_step_belt",     ConditionCode.FAIL,    0.82, CoverageZone.RIGHT, 0.35),

    # MONITOR items
    ("left_fender",         ConditionCode.MONITOR, 0.65, CoverageZone.LEFT,  0.55),
    ("exhaust_stack",       ConditionCode.MONITOR, 0.58, CoverageZone.LEFT,  0.60),
    ("hydraulic_hose_right",ConditionCode.MONITOR, 0.63, CoverageZone.RIGHT, 0.30),
    ("rear_left_tire",      ConditionCode.MONITOR, 0.67, CoverageZone.REAR,  0.75),

    # PASS items
    ("hood_panel",          ConditionCode.PASS,    0.94, CoverageZone.FRONT, 0.05),
    ("left_headlight",      ConditionCode.PASS,    0.96, CoverageZone.FRONT, 0.10),
    ("right_headlight",     ConditionCode.PASS,    0.95, CoverageZone.FRONT, 0.12),
    ("left_mirror",         ConditionCode.PASS,    0.92, CoverageZone.LEFT,  0.50),
    ("right_mirror",        ConditionCode.PASS,    0.93, CoverageZone.RIGHT, 0.28),
    ("cab_door",            ConditionCode.PASS,    0.91, CoverageZone.LEFT,  0.52),
    ("front_left_tire",     ConditionCode.PASS,    0.90, CoverageZone.FRONT, 0.15),
    ("front_right_tire",    ConditionCode.PASS,    0.91, CoverageZone.RIGHT, 0.25),
    ("rear_right_tire",     ConditionCode.PASS,    0.90, CoverageZone.REAR,  0.78),
    ("three_point_hitch",   ConditionCode.PASS,    0.92, CoverageZone.REAR,  0.80),
    ("tail_light_left",     ConditionCode.PASS,    0.95, CoverageZone.REAR,  0.72),
    ("tail_light_right",    ConditionCode.PASS,    0.94, CoverageZone.REAR,  0.74),
    ("pto_shield",          ConditionCode.PASS,    0.91, CoverageZone.REAR,  0.82),
    ("radiator_grille",     ConditionCode.PASS,    0.93, CoverageZone.FRONT, 0.06),
]


# ---------------------------------------------------------------------------
# Custom remark overrides for FAIL / MONITOR items (more specific than templates)
# ---------------------------------------------------------------------------

CUSTOM_REMARKS: dict[str, str] = {
    "front_glass": "Front tempered glass has visible crack spanning approximately 30 cm from lower-left corner; compromises operator visibility and cab seal integrity. Immediate replacement recommended.",
    "right_step_belt": "Right rear step belt is torn and partially detached; creates slip hazard for operator ingress/egress. Replace before next shift.",
    "left_fender": "Left front fender shows denting and surface corrosion along trailing edge; structurally intact but monitor for progression.",
    "exhaust_stack": "Exhaust stack shows discoloration and minor surface pitting; may indicate elevated operating temperatures. Monitor at next service.",
    "hydraulic_hose_right": "Right hydraulic hose outer sheath shows abrasion wear at bend point near coupling; no active leak but approaching service limit.",
    "rear_left_tire": "Rear left tire tread depth measured at approximately 40% remaining; uneven wear pattern on inner shoulder suggests alignment check needed.",
}


def _nearest_frame(timestamp_pct: float, total_frames: int) -> int:
    """Map a 0-1 percentage to the nearest extracted frame index."""
    idx = int(timestamp_pct * (total_frames - 1))
    return max(0, min(idx, total_frames - 1))


# ---------------------------------------------------------------------------
# Public inference interface
# ---------------------------------------------------------------------------

def infer_findings(
    frame_files: list[str],
    duration_sec: float,
    fps: float,
    mode: str = "STUB_DEMO",
) -> list[InspectionFinding]:
    """Run VLM-style inference on extracted frames.

    In STUB_DEMO mode, returns fixed deterministic findings matched to nearest frames.
    In REAL_LOCAL mode (future), would run actual on-device VLM.
    """
    if mode == "REAL_LOCAL":
        log.warning("REAL_LOCAL inference not yet implemented; falling back to STUB_DEMO")

    total = len(frame_files)
    if total == 0:
        log.error("No frames available for inference")
        return []

    findings: list[InspectionFinding] = []

    for part_key, condition, confidence, zone, ts_pct in STUB_FINDINGS:
        part_info = PARTS_DB.get(part_key)
        part_name = part_info.display_name if part_info else part_key.replace("_", " ").title()

        frame_idx = _nearest_frame(ts_pct, total)
        timestamp_sec = round(ts_pct * duration_sec, 2)

        remark = CUSTOM_REMARKS.get(part_key, _remark(condition, part_name))

        findings.append(InspectionFinding(
            part_name=part_name,
            part_key=part_key,
            condition=condition,
            remark=remark,
            confidence=confidence,
            evidence=EvidenceFrame(
                timestamp_sec=timestamp_sec,
                thumbnail_filename=frame_files[frame_idx],
                frame_index=frame_idx,
            ),
            replacement_part=part_info,
            coverage_zone=zone,
        ))

    findings.sort(key=lambda f: {"FAIL": 0, "MONITOR": 1, "PASS": 2}[f.condition.value])
    return findings


def estimate_coverage(findings: list[InspectionFinding]) -> CoverageReport:
    """Estimate which zones of the 360° walkaround were captured."""
    all_zones = set(CoverageZone)
    detected = {f.coverage_zone for f in findings}
    missing = all_zones - detected

    return CoverageReport(
        zones_detected=sorted(detected, key=lambda z: z.value),
        zones_missing=sorted(missing, key=lambda z: z.value),
        coverage_pct=round(len(detected) / len(all_zones) * 100, 1) if all_zones else 0.0,
    )
