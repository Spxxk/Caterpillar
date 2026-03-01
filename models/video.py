"""Video processing — frame extraction, thumbnails, duration detection.

Uses OpenCV for frame extraction. Falls back to ffmpeg CLI if cv2 unavailable.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_FPS = 2.0
THUMB_WIDTH = 640


@dataclass
class ExtractionResult:
    duration_sec: float
    fps_used: float
    total_frames: int
    frame_dir: Path
    frame_files: list[str]


def extract_frames(
    video_path: Path,
    output_dir: Path,
    fps: float = DEFAULT_FPS,
) -> ExtractionResult:
    """Extract frames from a video at the given FPS rate.

    Tries OpenCV first, falls back to ffmpeg subprocess.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        return _extract_opencv(video_path, output_dir, fps)
    except ImportError:
        log.info("OpenCV not available, trying ffmpeg CLI")
    except Exception as e:
        log.warning("OpenCV extraction failed: %s, trying ffmpeg", e)

    return _extract_ffmpeg(video_path, output_dir, fps)


def _extract_opencv(video_path: Path, output_dir: Path, fps: float) -> ExtractionResult:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_video_frames / video_fps if video_fps > 0 else 0.0

    frame_interval = max(1, int(video_fps / fps))

    frame_files: list[str] = []
    frame_idx = 0
    saved = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            h, w = frame.shape[:2]
            if w > THUMB_WIDTH:
                scale = THUMB_WIDTH / w
                frame = cv2.resize(frame, (THUMB_WIDTH, int(h * scale)))

            fname = f"frame_{saved:04d}.jpg"
            cv2.imwrite(str(output_dir / fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_files.append(fname)
            saved += 1
        frame_idx += 1

    cap.release()
    log.info("Extracted %d frames from %.1fs video (interval=%d)", saved, duration_sec, frame_interval)

    return ExtractionResult(
        duration_sec=round(duration_sec, 2),
        fps_used=fps,
        total_frames=saved,
        frame_dir=output_dir,
        frame_files=frame_files,
    )


def _extract_ffmpeg(video_path: Path, output_dir: Path, fps: float) -> ExtractionResult:
    pattern = str(output_dir / "frame_%04d.jpg")

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps={fps},scale={THUMB_WIDTH}:-1",
        "-q:v", "3",
        pattern,
        "-y", "-loglevel", "warning",
    ]
    subprocess.run(cmd, check=True, timeout=120)

    frame_files = sorted(f.name for f in output_dir.glob("frame_*.jpg"))

    duration_sec = 0.0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        duration_sec = float(probe.stdout.strip())
    except Exception:
        if frame_files:
            duration_sec = len(frame_files) / fps

    log.info("ffmpeg extracted %d frames from %.1fs video", len(frame_files), duration_sec)

    return ExtractionResult(
        duration_sec=round(duration_sec, 2),
        fps_used=fps,
        total_frames=len(frame_files),
        frame_dir=output_dir,
        frame_files=frame_files,
    )


def get_timestamp_for_frame(frame_index: int, fps: float) -> float:
    """Convert a frame index back to a timestamp in seconds."""
    return round(frame_index / fps, 2) if fps > 0 else 0.0
