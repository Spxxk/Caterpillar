"""PDF inspection report parser for Cat wheel loader reports.

Extracts structured header metadata, section-grouped checklist items with
statuses (PASS/NORMAL/MONITOR/FAIL → GREEN/YELLOW/RED), and comments.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

RAW_STATUS_MAP = {
    "PASS": "G",
    "NORMAL": "G",
    "MONITOR": "Y",
    "FAIL": "R",
}

SECTION_HEADINGS = [
    "FROM THE GROUND",
    "ENGINE COMPARTMENT",
    "ON THE MACHINE, OUTSIDE THE CAB",
    "INSIDE THE CAB",
    "General Info & Comments",
]

ITEM_RE = re.compile(
    r"^[l●•■□]\s*"
    r"(?:(\d+\.\d+)\s+)?"
    r"(.+?)\s+"
    r"(PASS|NORMAL|MONITOR|FAIL)\s*$",
    re.IGNORECASE,
)

HEADER_PATTERNS = {
    "model": re.compile(r"Model\s+(\S+)"),
    "serial": re.compile(r"Serial\s+Number\s+(\S+)"),
    "smu_hours": re.compile(r"SMU\s+(\d+)\s*Hours?", re.IGNORECASE),
    "completed_on": re.compile(r"Completed\s+On\s+(.+?)$", re.MULTILINE),
    "location": re.compile(r"Location\s+(.+?)$", re.MULTILINE),
    "inspector": re.compile(r"Inspector\s+(.+?)$", re.MULTILINE),
    "customer_name": re.compile(r"Customer\s+Name\s+(.+?)$", re.MULTILINE),
    "work_order": re.compile(r"Work\s+Order\s+(\S+)"),
    "asset_id": re.compile(r"Asset\s+ID\s+(\S+)"),
    "inspection_number": re.compile(r"Inspection\s+Number\s+(\S+)"),
}


@dataclass
class ReportMeta:
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


@dataclass
class ChecklistItem:
    section: str
    code: str  # e.g. "1.7" or "GEN"
    title: str
    raw_status: str  # PASS / NORMAL / MONITOR / FAIL
    status_rgb: str  # G / Y / R
    comments: str = ""


@dataclass
class ParseResult:
    meta: ReportMeta
    items: list[ChecklistItem]
    raw_text: str = ""
    parse_errors: list[str] = field(default_factory=list)


def _extract_text(pdf_path: Path) -> str:
    """Extract text from PDF using pdfplumber (preferred) or PyMuPDF fallback."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages)
    except ImportError:
        log.info("pdfplumber not installed, trying PyMuPDF")
    except Exception as e:
        log.warning("pdfplumber failed: %s, trying PyMuPDF", e)

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except ImportError:
        raise RuntimeError(
            "No PDF library available. Install pdfplumber: pip install pdfplumber"
        )


def _parse_meta(text: str) -> tuple[ReportMeta, list[str]]:
    meta = ReportMeta()
    errors: list[str] = []
    for field_name, pattern in HEADER_PATTERNS.items():
        m = pattern.search(text)
        if m:
            val = m.group(1).strip()
            if field_name == "smu_hours":
                try:
                    val = int(val)
                except ValueError:
                    errors.append(f"Could not parse SMU hours: {val!r}")
                    val = 0
            setattr(meta, field_name, val)
        else:
            errors.append(f"Header field '{field_name}' not found in PDF")
    return meta, errors


def _identify_section(line: str, current: str) -> str:
    upper = line.strip().upper()
    for heading in SECTION_HEADINGS:
        if heading.upper() in upper:
            return heading
    return current


def _parse_items(text: str) -> tuple[list[ChecklistItem], list[str]]:
    lines = text.split("\n")
    items: list[ChecklistItem] = []
    errors: list[str] = []
    current_section = "General"
    pending_item: Optional[ChecklistItem] = None
    seen_keys: set[str] = set()

    for i, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("--") or line.startswith("Serial Number:"):
            continue

        new_section = _identify_section(line, current_section)
        if new_section != current_section:
            current_section = new_section
            continue

        if line.lower().startswith("comments:"):
            comment_text = line[len("Comments:"):].strip()
            if pending_item is not None:
                pending_item.comments = comment_text
            continue

        m = ITEM_RE.match(line)
        if m:
            code = m.group(1) or "GEN"
            title = m.group(2).strip()
            raw_status = m.group(3).upper()
            status_rgb = RAW_STATUS_MAP.get(raw_status, "Y")

            dedup_key = f"{current_section}|{code}|{title}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            item = ChecklistItem(
                section=current_section,
                code=code,
                title=title,
                raw_status=raw_status,
                status_rgb=status_rgb,
            )
            items.append(item)
            pending_item = item
            continue

    if not items:
        errors.append("No checklist items found — PDF may have unexpected format")

    return items, errors


def parse_inspection_pdf(pdf_path: str | Path) -> ParseResult:
    """Parse a Cat inspection PDF into structured metadata + checklist items.

    Returns a ParseResult with .meta, .items, and .parse_errors for diagnostics.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    raw_text = _extract_text(pdf_path)
    if not raw_text.strip():
        return ParseResult(
            meta=ReportMeta(),
            items=[],
            raw_text="",
            parse_errors=["PDF text extraction returned empty — file may be image-only"],
        )

    meta, meta_errors = _parse_meta(raw_text)
    items, item_errors = _parse_items(raw_text)

    return ParseResult(
        meta=meta,
        items=items,
        raw_text=raw_text,
        parse_errors=meta_errors + item_errors,
    )
