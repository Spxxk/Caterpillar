"""Offline HTML report generator for WheelGuard-982 and HammerGuard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from schemas import (
    Finding,
    ManifestEntry,
    PARTS_982,
    ReportMeta,
    SessionManifest,
    Status,
    WheelLoaderFinding,
    parts_search_url,
)

STATUS_COLORS = {"R": "#dc2626", "Y": "#ca8a04", "G": "#16a34a"}
STATUS_LABELS = {"R": "RED", "Y": "YELLOW", "G": "GREEN"}
STATUS_FULL = {"R": "RED — Critical / Do Not Operate", "Y": "YELLOW — Monitor", "G": "GREEN — OK"}

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#0f172a;color:#e2e8f0;padding:1rem;max-width:960px;margin:auto;line-height:1.5}
h1{font-size:1.5rem;color:#fbbf24;margin-bottom:.15rem}
h2{font-size:1.15rem;color:#94a3b8;margin:1.5rem 0 .5rem;border-bottom:1px solid #334155;padding-bottom:.25rem}
h3{font-size:1rem;color:#cbd5e1;margin:1rem 0 .4rem}
.meta{color:#64748b;font-size:.85rem;margin-bottom:1rem}
.meta code{background:#1e293b;padding:1px 5px;border-radius:3px}
.overall{padding:.75rem 1rem;border-radius:8px;font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:1rem}

.card{background:#1e293b;border-radius:8px;padding:.85rem 1rem;margin-bottom:.75rem}
.card-head{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.4rem}
.badge{color:#fff;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:700;text-transform:uppercase}
.card p{font-size:.88rem;color:#cbd5e1;margin-top:.25rem}
.card ul{margin:.4rem 0 .2rem 1.2rem;font-size:.85rem;color:#94a3b8}
.card li{margin-bottom:.2rem}
.parts-btn{display:inline-block;margin:.2rem .3rem .2rem 0;padding:3px 10px;border-radius:5px;
           font-size:.78rem;text-decoration:none;color:#fbbf24;border:1px solid #fbbf24;
           transition:all .15s}
.parts-btn:hover{background:#fbbf24;color:#0f172a}
.demo-badge{font-size:.65rem;padding:1px 5px;border-radius:3px;background:#334155;
            color:#94a3b8;margin-left:.3rem;vertical-align:middle}
.triage-box{background:#0f172a;border:1px solid #475569;border-radius:6px;padding:.6rem .8rem;margin:.5rem 0}
.triage-box h4{font-size:.85rem;color:#fbbf24;margin-bottom:.3rem}
.triage-box ol{margin-left:1.2rem;font-size:.82rem;color:#94a3b8}
.triage-box li{margin-bottom:.15rem}

table{width:100%;border-collapse:collapse;font-size:.83rem;margin-bottom:.75rem}
th,td{padding:.45rem .5rem;text-align:left;border-bottom:1px solid #334155}
th{color:#94a3b8;font-weight:600;background:#1e293b;position:sticky;top:0}
td code{background:#334155;padding:1px 4px;border-radius:3px;font-size:.78rem}

.section-title{background:#1e293b;padding:.4rem .6rem;border-radius:6px;margin:.75rem 0 .25rem;
               font-weight:600;font-size:.9rem;color:#fbbf24}

details{margin:.5rem 0}
details summary{cursor:pointer;color:#94a3b8;font-size:.85rem;padding:.3rem 0}
details summary:hover{color:#e2e8f0}

footer{margin-top:2rem;text-align:center;color:#475569;font-size:.75rem;border-top:1px solid #1e293b;padding-top:1rem}
"""


def _status_dot(status: str) -> str:
    c = STATUS_COLORS.get(status, "#888")
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{c};vertical-align:middle"></span>'


# ---------------------------------------------------------------------------
# WheelGuard-982 report
# ---------------------------------------------------------------------------

def generate_wheelguard_report(
    session_dir: Path,
    manifest: SessionManifest,
    meta,  # ReportMeta dataclass from pdf_parse
    checklist_items: list,  # ChecklistItem dataclasses from pdf_parse
    findings: list[WheelLoaderFinding],
) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    evidence_ids = [e.sha256 for e in manifest.entries]

    worst = "G"
    for f in findings:
        if f.severity.value == "R":
            worst = "R"
            break
        if f.severity.value == "Y":
            worst = "Y"

    # --- Executive summary ---
    red_items = [f for f in findings if f.severity.value == "R"]
    yellow_items = [f for f in findings if f.severity.value == "Y"]

    summary_html = ""
    if red_items:
        summary_html += '<h3 style="color:#dc2626">Immediate Action Required</h3>'
        for f in red_items:
            summary_html += f'<div class="card" style="border-left:4px solid #dc2626">'
            summary_html += f'<div class="card-head"><span class="badge" style="background:#dc2626">RED</span>'
            summary_html += f'<strong>{f.title}</strong></div>'
            summary_html += f'<p>{f.description}</p></div>'

    if yellow_items:
        summary_html += '<h3 style="color:#ca8a04">Monitor / Schedule Service</h3>'
        for f in yellow_items:
            summary_html += f'<div class="card" style="border-left:4px solid #ca8a04">'
            summary_html += f'<div class="card-head"><span class="badge" style="background:#ca8a04">YEL</span>'
            summary_html += f'<strong>{f.title}</strong></div>'
            summary_html += f'<p>{f.description}</p></div>'

    green_count = sum(1 for it in checklist_items if it.status_rgb == "G")
    total_count = len(checklist_items)
    summary_html += (
        f'<p style="margin-top:.75rem;font-size:.85rem;color:#94a3b8">'
        f'{green_count}/{total_count} checks passed &middot; '
        f'{len(red_items)} critical &middot; {len(yellow_items)} monitor</p>'
    )

    # --- Section tables ---
    sections_seen: list[str] = []
    for it in checklist_items:
        if it.section not in sections_seen:
            sections_seen.append(it.section)

    section_tables = ""
    for sec in sections_seen:
        sec_items = [it for it in checklist_items if it.section == sec]
        section_tables += f'<div class="section-title">{sec}</div>'
        section_tables += '<table><tr><th>Code</th><th>Check</th><th>Status</th><th>Comments</th></tr>'
        for it in sec_items:
            dot = _status_dot(it.status_rgb)
            lbl = STATUS_LABELS.get(it.status_rgb, "?")
            cmt = it.comments or "—"
            section_tables += f'<tr><td>{it.code}</td><td>{it.title}</td>'
            section_tables += f'<td>{dot} {lbl}</td><td>{cmt}</td></tr>'
        section_tables += '</table>'

    # --- Failure mode cards with triage ---
    failure_cards = ""
    for f in findings:
        color = STATUS_COLORS.get(f.severity.value, "#888")
        label = STATUS_FULL.get(f.severity.value, f.severity.value)

        actions_html = ""
        if f.recommended_actions:
            actions_html = "<ul>" + "".join(f"<li>{a}</li>" for a in f.recommended_actions) + "</ul>"

        parts_html = ""
        for term in f.parts_search_terms:
            url = parts_search_url(term)
            parts_html += f'<a class="parts-btn" href="{url}" target="_blank">{term}</a>'
            parts_html += '<span class="demo-badge">confidence: demo</span> '

        triage_html = ""
        title_lower = f.title.lower()
        if f.severity.value == "R" and "transmission" in title_lower:
            triage_html = """
<div class="triage-box">
<h4>Noise Triage — Transmission</h4>
<p style="font-size:.82rem;color:#94a3b8;margin-bottom:.3rem">
Record a 5–10 second audio clip of the noise for remote diagnosis:</p>
<ol>
<li>Position near transmission housing at idle</li>
<li>Record with phone (use "Record Audio" button in app)</li>
<li>Note: grinding = gears/bearings, whining = pump/converter, clunking = shaft/coupling</li>
<li>Attach to this session for service tech review</li>
</ol>
</div>"""
        elif f.severity.value == "R" and "radiator" in title_lower:
            triage_html = """
<div class="triage-box">
<h4>Cooling Performance Checklist</h4>
<ol>
<li>What is the ambient temperature today?</li>
<li>Is the cooling fan running and engaging properly?</li>
<li>Is there visible clogging or debris on the radiator face?</li>
<li>Any coolant leaks visible around hoses or radiator?</li>
<li>Is the coolant level within spec after cleaning?</li>
</ol>
</div>"""

        failure_cards += f"""
<div class="card" style="border-left:4px solid {color}">
  <div class="card-head">
    <span class="badge" style="background:{color}">{f.severity.value}</span>
    <strong>{f.title}</strong>
    <span style="color:#64748b;font-size:.78rem;margin-left:auto">{f.section}</span>
  </div>
  <p>{f.description}</p>
  {triage_html}
  {actions_html}
  {f'<p style="margin-top:.4rem">{parts_html}</p>' if parts_html else ""}
</div>"""

    # --- Action plan ---
    action_plan = ""
    action_idx = 0
    for f in findings:
        if not f.recommended_actions:
            continue
        action_idx += 1
        severity_tag = f'<span class="badge" style="background:{STATUS_COLORS[f.severity.value]}">{f.severity.value}</span>'
        action_plan += f'<p style="margin-top:.5rem"><strong>{action_idx}. {f.title}</strong> {severity_tag}</p><ul>'
        for a in f.recommended_actions:
            action_plan += f"<li>{a}</li>"
        action_plan += "</ul>"

    # --- Evidence manifest ---
    evidence_rows = ""
    for entry in manifest.entries:
        if entry.media_type == "image":
            preview = f'<img src="{entry.filename}" style="max-width:120px;border-radius:4px"/>'
        elif entry.media_type == "audio":
            preview = f'<audio controls src="{entry.filename}" style="width:140px"></audio>'
        else:
            preview = f'<code>{entry.filename}</code>'
        evidence_rows += f'<tr><td>{preview}</td><td><code>{entry.sha256[:20]}…</code></td>'
        evidence_rows += f'<td>{entry.media_type}</td><td>{entry.size_bytes:,} B</td><td>{entry.uploaded_at}</td></tr>'

    # --- Meta fields ---
    meta_model = getattr(meta, "model", "") or "982"
    meta_serial = getattr(meta, "serial", "") or "—"
    meta_smu = getattr(meta, "smu_hours", 0) or 0
    meta_completed = getattr(meta, "completed_on", "") or "—"
    meta_location = getattr(meta, "location", "") or "—"
    meta_inspector = getattr(meta, "inspector", "") or "—"
    meta_customer = getattr(meta, "customer_name", "") or "—"
    meta_wo = getattr(meta, "work_order", "") or "—"
    meta_asset = getattr(meta, "asset_id", "") or "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>WheelGuard Report — {manifest.session_id}</title>
<style>{_CSS}</style>
</head>
<body>

<h1>WheelGuard-982 Inspection Report</h1>
<p class="meta">
  Session: <code>{manifest.session_id}</code> &middot; Generated: {now}
</p>

<table style="margin-bottom:1rem">
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Model</td><td><strong>{meta_model}</strong></td></tr>
<tr><td>Serial Number</td><td><code>{meta_serial}</code></td></tr>
<tr><td>SMU Hours</td><td>{meta_smu:,}</td></tr>
<tr><td>Completed On</td><td>{meta_completed}</td></tr>
<tr><td>Location</td><td>{meta_location}</td></tr>
<tr><td>Inspector</td><td>{meta_inspector}</td></tr>
<tr><td>Customer</td><td>{meta_customer}</td></tr>
<tr><td>Work Order</td><td><code>{meta_wo}</code></td></tr>
<tr><td>Asset ID</td><td><code>{meta_asset}</code></td></tr>
</table>

<div class="overall" style="background:{STATUS_COLORS[worst]}">
  Overall: {STATUS_FULL[worst]} &mdash; {len(red_items)} critical, {len(yellow_items)} monitor, {green_count} passed
</div>

<h2>Executive Summary</h2>
{summary_html}

<h2>Inspection Checklist ({total_count} items)</h2>
{section_tables}

<h2>Findings &amp; Failure Mode Cards ({len(findings)})</h2>
{failure_cards if failure_cards else "<p style='color:#94a3b8'>No actionable findings — all checks passed.</p>"}

<h2>Action Plan</h2>
{action_plan if action_plan else "<p style='color:#94a3b8'>No actions required.</p>"}

<h2>Evidence Manifest ({len(manifest.entries)} files)</h2>
<details open>
<summary>Show evidence files</summary>
<table>
<tr><th>File</th><th>SHA-256</th><th>Type</th><th>Size</th><th>Uploaded</th></tr>
{evidence_rows if evidence_rows else "<tr><td colspan='5'>No evidence uploaded.</td></tr>"}
</table>
</details>

<footer>
WheelGuard-982 Prototype &middot; Cat 982 Wheel Loader &middot; Offline Report<br/>
Evidence hashes anchored to manifest.json &middot; Not an official Caterpillar document
</footer>
</body>
</html>"""

    out_path = session_dir / "report.html"
    out_path.write_text(html)
    return out_path


# ---------------------------------------------------------------------------
# Original HammerGuard report (kept for backward compat)
# ---------------------------------------------------------------------------

def generate_report(
    session_dir: Path,
    manifest: SessionManifest,
    findings: list[Finding],
) -> Path:
    evidence_rows = ""
    for entry in manifest.entries:
        if entry.media_type == "image":
            preview = f'<img src="{entry.filename}" style="max-width:180px;border-radius:6px" />'
        else:
            preview = f'<audio controls src="{entry.filename}" style="width:180px"></audio>'
        evidence_rows += f"""<tr>
  <td>{preview}</td>
  <td><code>{entry.filename}</code></td>
  <td><code style="font-size:0.7em">{entry.sha256[:16]}…</code></td>
  <td>{entry.uploaded_at}</td>
</tr>"""

    finding_cards = ""
    for f in findings:
        color = STATUS_COLORS.get(f.status.value, "#888")
        parts_html = ", ".join(f'<code>{p}</code>' for p in f.suggested_parts) or "—"
        finding_cards += f"""
<div class="card" style="border-left:4px solid {color}">
  <div class="card-head">
    <span class="badge" style="background:{color}">{f.status.value}</span>
    <strong>{f.component}</strong> — {f.check}
    <span style="color:#64748b;font-size:.8rem;margin-left:auto">conf {f.confidence:.0%}</span>
  </div>
  <p>{f.notes}</p>
  <p style="font-size:.8rem;color:#94a3b8">Suggested parts: {parts_html}</p>
</div>"""

    worst = "G"
    for f in findings:
        if f.status.value == "R":
            worst = "R"
            break
        if f.status.value == "Y":
            worst = "Y"

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HammerGuard Report — {manifest.session_id}</title>
<style>{_CSS}</style></head><body>
<h1>HammerGuard Inspection Report</h1>
<p class="meta">Session: <code>{manifest.session_id}</code> &middot;
Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
<div class="overall" style="background:{STATUS_COLORS[worst]}">{STATUS_FULL[worst]}</div>
<h2>Findings ({len(findings)})</h2>
{finding_cards or "<p>No automated findings.</p>"}
<h2>Evidence ({len(manifest.entries)} files)</h2>
<table><tr><th>Preview</th><th>File</th><th>SHA-256</th><th>Uploaded</th></tr>
{evidence_rows or "<tr><td colspan='4'>No evidence.</td></tr>"}</table>
<footer>HammerGuard Prototype &middot; Cat H95s</footer>
</body></html>"""

    out_path = session_dir / "report.html"
    out_path.write_text(html)
    return out_path
