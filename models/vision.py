"""Vision module — open-set object detection for hammer components.

Primary : GroundingDINO  (IDEA-Research/grounding-dino-base, Apache-2.0)
Fallback: YOLOv8-nano   (ultralytics, AGPL — import only if primary fails)
Manual  : returns empty list so caller can tag manually.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)

LABELS = "tool bit . bushing . hydraulic hose . pin . grease cartridge ."

CATEGORY_MAP = {
    "tool bit": "tool",
    "bushing": "bushing",
    "hydraulic hose": "hose",
    "pin": "pin",
    "grease cartridge": "grease",
}


@dataclass
class Detection:
    label: str
    category: str
    score: float
    bbox: list[float] = field(default_factory=list)  # [x1,y1,x2,y2] normalised


_gdino_processor = None
_gdino_model = None
_yolo_model = None


def _load_gdino():
    global _gdino_processor, _gdino_model
    if _gdino_model is not None:
        return True
    try:
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        log.info("Loading GroundingDINO …")
        _gdino_processor = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-base")
        _gdino_model = AutoModelForZeroShotObjectDetection.from_pretrained(
            "IDEA-Research/grounding-dino-base"
        )
        _gdino_model.eval()
        log.info("GroundingDINO ready")
        return True
    except Exception:
        log.warning("GroundingDINO unavailable, will try YOLO fallback", exc_info=True)
        return False


def _load_yolo():
    global _yolo_model
    if _yolo_model is not None:
        return True
    try:
        from ultralytics import YOLO
        log.info("Loading YOLOv8-nano …")
        _yolo_model = YOLO("yolov8n.pt")
        log.info("YOLOv8-nano ready")
        return True
    except Exception:
        log.warning("YOLO fallback also unavailable", exc_info=True)
        return False


def _run_gdino(image: Image.Image, text: str = LABELS, threshold: float = 0.25) -> list[Detection]:
    import torch
    inputs = _gdino_processor(images=image, text=text, return_tensors="pt")
    with torch.no_grad():
        outputs = _gdino_model(**inputs)
    w, h = image.size
    results = _gdino_processor.post_process_grounded_object_detection(
        outputs,
        inputs["input_ids"],
        box_threshold=threshold,
        text_threshold=threshold,
        target_sizes=[(h, w)],
    )[0]

    detections: list[Detection] = []
    for score, lbl, box in zip(results["scores"], results["labels"], results["boxes"]):
        lbl_clean = lbl.strip().lower()
        cat = CATEGORY_MAP.get(lbl_clean, lbl_clean)
        detections.append(Detection(
            label=lbl_clean,
            category=cat,
            score=round(float(score), 3),
            bbox=[round(float(c), 1) for c in box.tolist()],
        ))
    return detections


def _run_yolo(image: Image.Image) -> list[Detection]:
    results = _yolo_model(image, verbose=False)[0]
    detections: list[Detection] = []
    for box in results.boxes:
        cls_id = int(box.cls[0])
        lbl = results.names[cls_id].lower()
        cat = CATEGORY_MAP.get(lbl, lbl)
        detections.append(Detection(
            label=lbl,
            category=cat,
            score=round(float(box.conf[0]), 3),
            bbox=[round(float(c), 1) for c in box.xyxy[0].tolist()],
        ))
    return detections


def detect(image_path: str | Path, threshold: float = 0.25) -> list[Detection]:
    """Run detection on an image, falling through backends gracefully."""
    image = Image.open(image_path).convert("RGB")

    if _load_gdino():
        try:
            return _run_gdino(image, threshold=threshold)
        except Exception:
            log.warning("GroundingDINO inference failed", exc_info=True)

    if _load_yolo():
        try:
            return _run_yolo(image)
        except Exception:
            log.warning("YOLO inference failed", exc_info=True)

    log.error("All vision backends failed — returning empty detections (manual tagging required)")
    return []
