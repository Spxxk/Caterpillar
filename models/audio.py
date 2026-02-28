"""Audio module — denoise + ASR + BPM estimation.

RNNoise : optional C library denoiser (BSD-3; skipped if not built)
Whisper : openai/whisper-tiny via HF transformers
BPM     : simple energy-peak autocorrelation on the 5-second clip
"""

from __future__ import annotations

import logging
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

RNNOISE_BIN: Optional[Path] = None

for candidate in [
    Path(__file__).resolve().parent.parent / "rnnoise" / "examples" / "rnnoise_demo",
    Path("/usr/local/bin/rnnoise_demo"),
]:
    if candidate.exists():
        RNNOISE_BIN = candidate
        break


@dataclass
class AudioResult:
    transcript: str = ""
    estimated_bpm: Optional[float] = None
    denoised: bool = False
    raw_notes: str = ""


def _denoise(wav_path: Path) -> Path:
    """Run RNNoise on a WAV file, returning denoised path (or original on failure)."""
    if RNNOISE_BIN is None:
        log.info("RNNoise binary not found — skipping denoise")
        return wav_path
    try:
        import soundfile as sf
        import numpy as np

        data, sr = sf.read(wav_path, dtype="int16")
        if sr != 48000:
            log.info("RNNoise requires 48 kHz; resampling skipped — returning original")
            return wav_path

        if data.ndim > 1:
            data = data[:, 0]

        raw_in = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False)
        raw_out = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False)
        raw_in.write(data.tobytes())
        raw_in.close()
        raw_out.close()

        subprocess.run(
            [str(RNNOISE_BIN), raw_in.name, raw_out.name],
            check=True, timeout=10,
        )
        clean_data = np.frombuffer(Path(raw_out.name).read_bytes(), dtype=np.int16)
        out_path = wav_path.with_stem(wav_path.stem + "_clean")
        sf.write(str(out_path), clean_data, 48000)
        log.info("RNNoise denoise complete")
        return out_path
    except Exception:
        log.warning("RNNoise denoise failed — using original audio", exc_info=True)
        return wav_path


_whisper_pipe = None


def _load_whisper():
    global _whisper_pipe
    if _whisper_pipe is not None:
        return True
    try:
        from transformers import pipeline
        log.info("Loading Whisper-tiny …")
        _whisper_pipe = pipeline(
            "automatic-speech-recognition",
            model="openai/whisper-tiny",
            chunk_length_s=5,
        )
        log.info("Whisper-tiny ready")
        return True
    except Exception:
        log.warning("Whisper-tiny unavailable", exc_info=True)
        return False


def _estimate_bpm(wav_path: Path) -> Optional[float]:
    """Rough BPM from energy-peak autocorrelation."""
    try:
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]

        frame_len = int(sr * 0.01)  # 10 ms frames
        n_frames = len(data) // frame_len
        energy = np.array([
            np.sum(data[i * frame_len:(i + 1) * frame_len] ** 2)
            for i in range(n_frames)
        ])
        energy = energy - energy.mean()
        corr = np.correlate(energy, energy, mode="full")
        corr = corr[len(corr) // 2:]

        min_lag = int(0.04 / 0.01)   # ~1500 bpm upper bound
        max_lag = int(0.12 / 0.01)   # ~500 bpm lower bound
        if max_lag >= len(corr):
            return None

        search = corr[min_lag:max_lag]
        if len(search) == 0:
            return None
        peak_lag = np.argmax(search) + min_lag
        bpm = 60.0 / (peak_lag * 0.01)
        return round(bpm, 1)
    except Exception:
        log.warning("BPM estimation failed", exc_info=True)
        return None


def analyse(wav_path: str | Path) -> AudioResult:
    """Full audio pipeline: denoise -> transcribe -> estimate BPM."""
    wav_path = Path(wav_path)
    result = AudioResult()

    clean_path = _denoise(wav_path)
    result.denoised = clean_path != wav_path

    if _load_whisper():
        try:
            out = _whisper_pipe(str(clean_path))
            result.transcript = out.get("text", "").strip()
        except Exception:
            log.warning("Whisper inference failed", exc_info=True)

    result.estimated_bpm = _estimate_bpm(clean_path)

    notes: list[str] = []
    if result.transcript:
        notes.append(f"Transcript: {result.transcript}")
    if result.estimated_bpm is not None:
        notes.append(f"Estimated BPM: {result.estimated_bpm}")
        if result.estimated_bpm < 700 or result.estimated_bpm > 1260:
            notes.append("WARNING: BPM outside H95s normal range (700–1260)")
    if result.denoised:
        notes.append("Audio was denoised via RNNoise")
    result.raw_notes = "; ".join(notes) if notes else "No audio analysis available"

    return result
