"""Report generators — offline HTML + dealer-ready PDF."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from pathlib import Path

from schemas import (
    ConditionCode,
    CoverageReport,
    InspectionFinding,
    VideoJobMeta,
)

log = logging.getLogger(__name__)

CONDITION_COLORS = {"FAIL": "#dc2626", "MONITOR": "#ca8a04", "PASS": "#16a34a"}
CONDITION_LABELS = {"FAIL": "FAIL — Replace", "MONITOR": "MONITOR — Reinspect", "PASS": "PASS — OK"}


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

def generate_html_report(
    job_dir: Path,
    meta: VideoJobMeta,
    findings: list[InspectionFinding],
    coverage: CoverageReport,
    summary: dict,
) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    fail_count = summary.get("fail_count", 0)
    monitor_count = summary.get("monitor_count", 0)
    pass_count = summary.get("pass_count", 0)
    overall = summary.get("overall", "PASS")
    overall_color = CONDITION_COLORS.get(overall, "#16a34a")

    coverage_html = ""
    for z in ["front", "rear", "left", "right"]:
        detected = any(str(zz.value) == z for zz in coverage.zones_detected)
        icon = "&#9745;" if detected else "&#9746;"
        color = "#16a34a" if detected else "#dc2626"
        coverage_html += f'<span style="color:{color};margin-right:1rem">{icon} {z.upper()}</span>'

    # --- Findings cards ---
    findings_html = ""
    for f in findings:
        color = CONDITION_COLORS.get(f.condition.value, "#888")
        label = f.condition.value

        thumb_path = job_dir / "frames" / f.evidence.thumbnail_filename
        thumb_tag = ""
        if thumb_path.exists():
            thumb_tag = f'<img src="frames/{f.evidence.thumbnail_filename}" style="width:200px;border-radius:6px;margin-top:.4rem"/>'

        parts_html = ""
        if f.replacement_part:
            rp = f.replacement_part
            parts_html = f"""
<div style="margin-top:.4rem;padding:.4rem .6rem;background:#0f172a;border-radius:6px;font-size:.82rem">
  <strong>{rp.display_name}</strong> &mdash; <code>{rp.part_number}</code>
  <span style="color:#64748b;margin-left:.5rem">fitment: {rp.fitment_score:.0%}</span><br/>
  <a href="{rp.purchase_url}" target="_blank" style="color:#fbbf24;text-decoration:underline">Purchase on parts.cat.com</a>
</div>"""

        findings_html += f"""
<div style="background:#1e293b;border-radius:8px;padding:.85rem 1rem;margin-bottom:.75rem;border-left:4px solid {color}">
  <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
    <span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:700">{label}</span>
    <strong>{f.part_name}</strong>
    <span style="color:#64748b;font-size:.78rem;margin-left:auto">conf {f.confidence:.0%} &middot; {f.coverage_zone.value} &middot; {f.evidence.timestamp_sec:.1f}s</span>
  </div>
  <p style="font-size:.88rem;color:#cbd5e1;margin-top:.3rem">{f.remark}</p>
  {thumb_tag}
  {parts_html}
</div>"""

    # --- Full page ---
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Inspection Report — {meta.job_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#0f172a;color:#e2e8f0;padding:1rem;max-width:960px;margin:auto;line-height:1.5}}
h1{{font-size:1.5rem;color:#fbbf24;margin-bottom:.15rem}}
h2{{font-size:1.15rem;color:#94a3b8;margin:1.5rem 0 .5rem;border-bottom:1px solid #334155;padding-bottom:.25rem}}
.meta{{color:#64748b;font-size:.85rem;margin-bottom:1rem}}
.meta code{{background:#1e293b;padding:1px 5px;border-radius:3px}}
.overall{{padding:.75rem 1rem;border-radius:8px;font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse;font-size:.83rem;margin-bottom:.75rem}}
th,td{{padding:.45rem .5rem;text-align:left;border-bottom:1px solid #334155}}
th{{color:#94a3b8;font-weight:600;background:#1e293b}}
code{{background:#334155;padding:1px 4px;border-radius:3px;font-size:.8rem}}
footer{{margin-top:2rem;text-align:center;color:#475569;font-size:.75rem;border-top:1px solid #1e293b;padding-top:1rem}}
a{{color:#fbbf24}}
</style>
</head>
<body>
<h1>360&deg; Tractor Inspection Report</h1>
<p class="meta">
  Job: <code>{meta.job_id}</code> &middot;
  Video: {meta.filename} ({meta.duration_sec:.1f}s, {meta.total_frames} frames at {meta.fps_extracted} fps) &middot;
  Mode: {meta.inference_mode.value} &middot;
  Generated: {now}
</p>

<div class="overall" style="background:{overall_color}">
  Overall: {overall} &mdash; {fail_count} fail, {monitor_count} monitor, {pass_count} pass
</div>

<h2>Coverage ({coverage.coverage_pct:.0f}%)</h2>
<p style="font-size:.9rem;margin-bottom:.5rem">{coverage_html}</p>
{f'<p style="color:#dc2626;font-size:.85rem">Warning: missing coverage for {", ".join(z.value.upper() for z in coverage.zones_missing)}</p>' if coverage.zones_missing else ""}

<h2>Findings ({len(findings)})</h2>
{findings_html}

<h2>Findings Table</h2>
<table>
<tr><th>Part</th><th>Status</th><th>Confidence</th><th>Zone</th><th>Time</th><th>Part #</th></tr>
{"".join(f'''<tr>
<td>{f.part_name}</td>
<td><span style="color:{CONDITION_COLORS.get(f.condition.value,'#888')}">{f.condition.value}</span></td>
<td>{f.confidence:.0%}</td>
<td>{f.coverage_zone.value}</td>
<td>{f.evidence.timestamp_sec:.1f}s</td>
<td>{f.replacement_part.part_number if f.replacement_part else "—"}</td>
</tr>''' for f in findings)}
</table>

<footer>
360&deg; Tractor Inspection &middot; Deterministic VLM Pipeline (STUB_DEMO) &middot; Offline Report
</footer>
</body>
</html>"""

    out = job_dir / "report.html"
    out.write_text(html)
    log.info("HTML report generated: %s", out)
    return out


# ---------------------------------------------------------------------------
# PDF Report (uses fpdf2 if available, falls back to HTML-only)
# ---------------------------------------------------------------------------

def generate_pdf_report(
    job_dir: Path,
    meta: VideoJobMeta,
    findings: list[InspectionFinding],
    coverage: CoverageReport,
    summary: dict,
) -> Path:
    try:
        from fpdf import FPDF
    except ImportError:
        log.warning("fpdf2 not installed — skipping PDF generation (pip install fpdf2)")
        raise

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "360 Tractor Inspection Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"Job: {meta.job_id}  |  Video: {meta.filename}  |  "
                    f"{meta.duration_sec:.1f}s, {meta.total_frames} frames  |  "
                    f"Mode: {meta.inference_mode.value}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Overall
    overall = summary.get("overall", "PASS")
    fail_c = summary.get("fail_count", 0)
    mon_c = summary.get("monitor_count", 0)
    pass_c = summary.get("pass_count", 0)

    color_map = {"FAIL": (220, 38, 38), "MONITOR": (202, 138, 4), "PASS": (22, 163, 74)}
    r, g, b = color_map.get(overall, (22, 163, 74))
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, f"  Overall: {overall}  --  {fail_c} fail, {mon_c} monitor, {pass_c} pass",
             fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Coverage
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"Coverage: {coverage.coverage_pct:.0f}%", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    zones_str = ", ".join(z.value.upper() for z in coverage.zones_detected)
    pdf.cell(0, 5, f"Detected: {zones_str}", new_x="LMARGIN", new_y="NEXT")
    if coverage.zones_missing:
        pdf.set_text_color(220, 38, 38)
        missing = ", ".join(z.value.upper() for z in coverage.zones_missing)
        pdf.cell(0, 5, f"Missing: {missing}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Findings table
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"Findings ({len(findings)})", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    col_widths = [55, 20, 18, 18, 15, 30, 34]
    headers = ["Part", "Status", "Conf", "Zone", "Time", "Part #", "Action"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 6, h, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7.5)
    for f in findings:
        r, g, b = color_map.get(f.condition.value, (0, 0, 0))
        pdf.set_text_color(r, g, b)
        pdf.cell(col_widths[0], 5.5, f.part_name[:30], border=1)
        pdf.cell(col_widths[1], 5.5, f.condition.value, border=1)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_widths[2], 5.5, f"{f.confidence:.0%}", border=1)
        pdf.cell(col_widths[3], 5.5, f.coverage_zone.value, border=1)
        pdf.cell(col_widths[4], 5.5, f"{f.evidence.timestamp_sec:.1f}s", border=1)
        pn = f.replacement_part.part_number if f.replacement_part else "-"
        pdf.cell(col_widths[5], 5.5, pn, border=1)
        action = "Replace" if f.condition == ConditionCode.FAIL else (
            "Monitor" if f.condition == ConditionCode.MONITOR else "None")
        pdf.cell(col_widths[6], 5.5, action, border=1)
        pdf.ln()

    pdf.ln(4)

    # Detail cards for FAIL and MONITOR items
    non_pass = [f for f in findings if f.condition != ConditionCode.PASS]
    if non_pass:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Detailed Findings", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for f in non_pass:
            r, g, b = color_map.get(f.condition.value, (0, 0, 0))

            pdf.set_draw_color(r, g, b)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(r, g, b)
            pdf.cell(0, 6, f"[{f.condition.value}] {f.part_name}", new_x="LMARGIN", new_y="NEXT")

            pdf.set_text_color(60, 60, 60)
            pdf.set_font("Helvetica", "", 8)
            pdf.multi_cell(0, 4.5, f.remark, new_x="LMARGIN", new_y="NEXT")

            thumb_path = job_dir / "frames" / f.evidence.thumbnail_filename
            if thumb_path.exists():
                try:
                    pdf.image(str(thumb_path), w=60)
                except Exception:
                    pass

            if f.replacement_part:
                rp = f.replacement_part
                pdf.set_font("Helvetica", "I", 7.5)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 4.5, f"Part: {rp.display_name} ({rp.part_number}) | Fitment: {rp.fitment_score:.0%}",
                         new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(0, 5, "360 Tractor Inspection | Deterministic VLM Pipeline (STUB_DEMO) | Generated for dealer review",
             new_x="LMARGIN", new_y="NEXT")

    out = job_dir / "report.pdf"
    pdf.output(str(out))
    log.info("PDF report generated: %s", out)
    return out
