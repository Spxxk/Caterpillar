"""Offline HTML report generator for HammerGuard inspection sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from schemas import Finding, SessionManifest

STATUS_COLORS = {"R": "#dc2626", "Y": "#ca8a04", "G": "#16a34a"}
STATUS_LABELS = {"R": "RED — Replace / Critical", "Y": "YELLOW — Monitor", "G": "GREEN — OK"}


def generate_report(
    session_dir: Path,
    manifest: SessionManifest,
    findings: list[Finding],
) -> Path:
    """Write a self-contained offline HTML report and return its path."""
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
        label = STATUS_LABELS.get(f.status.value, f.status.value)
        parts_html = ", ".join(f'<code>{p}</code>' for p in f.suggested_parts) or "—"
        finding_cards += f"""
<div class="card" style="border-left:4px solid {color}">
  <div class="card-head">
    <span class="badge" style="background:{color}">{f.status.value}</span>
    <strong>{f.component}</strong> — {f.check}
    <span class="conf">conf {f.confidence:.0%}</span>
  </div>
  <p>{f.notes}</p>
  <p class="parts">Suggested parts: {parts_html}</p>
</div>"""

    checklist_rows = ""
    for key, val in manifest.checklist.items():
        icon = "&#9745;" if val is True else ("&#9746;" if val is False else "&#9744;")
        checklist_rows += f"<li>{icon} {key.replace('_', ' ').title()}</li>"

    worst = "G"
    for f in findings:
        if f.status.value == "R":
            worst = "R"
            break
        if f.status.value == "Y":
            worst = "Y"
    overall_color = STATUS_COLORS[worst]
    overall_label = STATUS_LABELS[worst]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HammerGuard Report — {manifest.session_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:#0f172a;color:#e2e8f0;padding:1rem;max-width:900px;margin:auto}}
h1{{font-size:1.5rem;color:#fbbf24;margin-bottom:.25rem}}
h2{{font-size:1.15rem;color:#94a3b8;margin:1.5rem 0 .5rem;border-bottom:1px solid #334155;padding-bottom:.25rem}}
.meta{{color:#64748b;font-size:.85rem;margin-bottom:1rem}}
.overall{{padding:.75rem 1rem;border-radius:8px;font-size:1.1rem;font-weight:700;
          color:#fff;margin-bottom:1rem}}
.card{{background:#1e293b;border-radius:8px;padding:.75rem 1rem;margin-bottom:.75rem}}
.card-head{{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}}
.badge{{color:#fff;padding:2px 8px;border-radius:4px;font-size:.8rem;font-weight:700}}
.conf{{color:#64748b;font-size:.8rem;margin-left:auto}}
.card p{{margin-top:.4rem;font-size:.9rem;color:#cbd5e1}}
.parts{{font-size:.8rem;color:#94a3b8}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{padding:.5rem;text-align:left;border-bottom:1px solid #334155}}
th{{color:#94a3b8}}
ul{{list-style:none;columns:2;gap:1rem;font-size:.9rem}}
li{{margin-bottom:.3rem}}
code{{background:#334155;padding:1px 4px;border-radius:3px;font-size:.8rem}}
footer{{margin-top:2rem;text-align:center;color:#475569;font-size:.75rem}}
</style>
</head>
<body>
<h1>&#128296; HammerGuard Inspection Report</h1>
<p class="meta">Session: <code>{manifest.session_id}</code> &middot; Model: {manifest.hammer_model}
   &middot; Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>

<div class="overall" style="background:{overall_color}">
  Overall Status: {overall_label}
</div>

<h2>Checklist</h2>
<ul>{checklist_rows}</ul>

<h2>Findings ({len(findings)})</h2>
{finding_cards if finding_cards else "<p>No automated findings — manual review recommended.</p>"}

<h2>Evidence ({len(manifest.entries)} files)</h2>
<table>
<tr><th>Preview</th><th>File</th><th>SHA-256</th><th>Uploaded</th></tr>
{evidence_rows if evidence_rows else "<tr><td colspan='4'>No evidence uploaded.</td></tr>"}
</table>

<footer>
HammerGuard Prototype &middot; Cat H95s &middot; Offline Report &middot;
Evidence hashes anchored to manifest.json
</footer>
</body>
</html>"""

    out_path = session_dir / "report.html"
    out_path.write_text(html)
    return out_path
