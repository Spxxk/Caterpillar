"""LLM tool-call module — generates structured Finding JSON.

Primary : Mistral 7B Instruct v0.3 (local, Apache-2.0, function-calling)
Fallback: OpenAI gpt-4.1-mini structured outputs (network)
Manual  : rule-based fallback that still produces valid Finding objects
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from schemas import CreateFindingSchema, Finding, Status

log = logging.getLogger(__name__)

PARTS_SNAPSHOT: list[dict] = []
_parts_path = Path(__file__).resolve().parent.parent / "data" / "parts_snapshot.json"
if _parts_path.exists():
    PARTS_SNAPSHOT = json.loads(_parts_path.read_text())

COMPONENT_TO_PARTS: dict[str, list[str]] = {}
for p in PARTS_SNAPSHOT:
    COMPONENT_TO_PARTS.setdefault(p["category"], []).append(p["part_no"])

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_finding",
        "description": "Record an inspection finding for a Cat H95s hydraulic hammer component.",
        "parameters": CreateFindingSchema.model_json_schema(),
    },
}

_mistral_pipe = None


def _build_system_prompt(vision_notes: str, audio_notes: str, checklist: dict) -> str:
    checks_str = "\n".join(f"  - {k}: {'checked' if v else 'unchecked' if v is False else 'skipped'}"
                           for k, v in checklist.items())
    return f"""You are HammerGuard, an AI inspector for Cat H95s hydraulic hammers.
Operating specs: 700–1260 bpm, ~124 dB.

Checklist state:
{checks_str}

Vision detections:
{vision_notes}

Audio analysis:
{audio_notes}

Parts catalog (JSON):
{json.dumps(PARTS_SNAPSHOT, indent=1)}

For EACH relevant component detected or checklist item checked, call create_finding with:
- component: the component type (tool, bushing, hose, pin, grease)
- check: the checklist item it addresses
- status: R (red=replace/critical), Y (yellow=monitor), G (green=ok)
- evidence_ids: list of SHA-256 hashes from the evidence manifest
- notes: concise observation
- confidence: 0-1
- suggested_parts: part numbers from the catalog that may be needed"""


def _load_mistral():
    global _mistral_pipe
    if _mistral_pipe is not None:
        return True
    try:
        from transformers import pipeline
        log.info("Loading Mistral 7B Instruct v0.3 …")
        _mistral_pipe = pipeline(
            "text-generation",
            model="mistralai/Mistral-7B-Instruct-v0.3",
            device_map="auto",
            torch_dtype="auto",
            max_new_tokens=1024,
        )
        log.info("Mistral ready")
        return True
    except Exception:
        log.warning("Mistral unavailable", exc_info=True)
        return False


def _run_mistral(system: str, evidence_ids: list[str]) -> list[Finding]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Analyse the evidence and produce findings. Call create_finding for each component."},
    ]
    out = _mistral_pipe(
        messages,
        return_full_text=False,
        tools=[TOOL_SCHEMA],
    )
    findings: list[Finding] = []
    for choice in out:
        generated = choice.get("generated_text", "")
        if isinstance(generated, list):
            for msg in generated:
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls", []):
                        args = tc.get("function", {}).get("arguments", {})
                        if isinstance(args, str):
                            args = json.loads(args)
                        args.setdefault("evidence_ids", evidence_ids)
                        findings.append(Finding(**args))
        elif isinstance(generated, str) and "create_finding" in generated:
            try:
                start = generated.index("{")
                end = generated.rindex("}") + 1
                args = json.loads(generated[start:end])
                args.setdefault("evidence_ids", evidence_ids)
                findings.append(Finding(**args))
            except Exception:
                pass
    return findings


def _run_openai(system: str, evidence_ids: list[str]) -> list[Finding]:
    import openai
    client = openai.OpenAI()
    resp = client.responses.parse(
        model="gpt-4.1-mini",
        instructions=system,
        input="Analyse the evidence and produce findings as a JSON array.",
        text_format={"type": "json_schema", "strict": True,
                     "schema": {"name": "findings", "schema": {
                         "type": "object",
                         "properties": {"findings": {"type": "array", "items": CreateFindingSchema.model_json_schema()}},
                         "required": ["findings"], "additionalProperties": False
                     }}},
    )
    raw = json.loads(resp.output_text)
    findings: list[Finding] = []
    for f in raw.get("findings", []):
        f.setdefault("evidence_ids", evidence_ids)
        findings.append(Finding(**f))
    return findings


def _rule_based_fallback(
    vision_detections: list[dict],
    audio_notes: str,
    checklist: dict,
    evidence_ids: list[str],
) -> list[Finding]:
    """Deterministic fallback when no LLM is available."""
    findings: list[Finding] = []

    detected_categories = {d.get("category", "") for d in vision_detections}

    check_to_component = {
        "grease_tool": "grease",
        "inspect_cracks_burrs": "tool",
        "inspect_pins": "pin",
        "inspect_bushings": "bushing",
        "check_jumper_lines": "hose",
        "note_blank_firing": "tool",
    }

    for check_key, checked in checklist.items():
        comp = check_to_component.get(check_key, "tool")
        detected = comp in detected_categories

        if checked is True:
            status = Status.GREEN
            note = f"Checked: {check_key}."
            if detected:
                note += f" Vision confirmed {comp} detected."
        elif checked is False:
            status = Status.YELLOW
            note = f"Unchecked: {check_key} — needs attention."
        else:
            status = Status.YELLOW
            note = f"Skipped: {check_key}."

        if "blank_firing" in check_key and audio_notes:
            if "WARNING" in audio_notes:
                status = Status.RED
                note += f" {audio_notes}"
            elif "BPM" in audio_notes:
                note += f" {audio_notes}"

        parts = COMPONENT_TO_PARTS.get(comp, [])
        findings.append(Finding(
            component=comp,
            check=check_key,
            status=status,
            evidence_ids=evidence_ids,
            notes=note,
            confidence=0.6 if detected else 0.3,
            suggested_parts=parts[:2],
        ))

    return findings


def generate_findings(
    vision_detections: list[dict],
    audio_notes: str,
    checklist: dict,
    evidence_ids: list[str],
) -> list[Finding]:
    """Produce findings using best available LLM, falling back to rules."""
    vision_str = json.dumps(vision_detections, indent=1) if vision_detections else "No detections"
    system = _build_system_prompt(vision_str, audio_notes, checklist)

    if _load_mistral():
        try:
            findings = _run_mistral(system, evidence_ids)
            if findings:
                return findings
            log.warning("Mistral returned no findings — trying fallback")
        except Exception:
            log.warning("Mistral inference failed", exc_info=True)

    if os.environ.get("OPENAI_API_KEY"):
        try:
            findings = _run_openai(system, evidence_ids)
            if findings:
                return findings
            log.warning("OpenAI returned no findings — trying rule-based")
        except Exception:
            log.warning("OpenAI fallback failed", exc_info=True)

    log.info("Using rule-based fallback for findings")
    return _rule_based_fallback(vision_detections, audio_notes, checklist, evidence_ids)
