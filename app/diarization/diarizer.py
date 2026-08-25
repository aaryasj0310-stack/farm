"""Unified Diarization orchestrator interface."""
from pathlib import Path
from typing import List, Optional, Union
import numpy as np
from app.config.settings import settings
from app.diarization.pyannote_engine import PyannoteDiarizationEngine
from app.diarization.spectral_engine import SpectralDiarizationEngine
from app.models.schemas import DiarizationSegment, VADSegment
from app.utils.logger import get_logger

logger = get_logger("diarization.orchestrator")


class DiarizationEngine:
    """Orchestrates speaker diarization across Pyannote, Spectral clustering, or single speaker."""

    def __init__(self):
        self.spectral_engine = SpectralDiarizationEngine()
        self.pyannote_engine = PyannoteDiarizationEngine()

    def diarize(
        self,
        audio_input: Union[str, Path, np.ndarray],
        vad_segments: Optional[List[VADSegment]] = None,
        job_id: Optional[str] = None
    ) -> List[DiarizationSegment]:
        """Runs speaker diarization with automatic graceful fallback."""
        # 1. Check if Pyannote is explicitly requested & available
        if settings.DIARIZATION_ENGINE in ("auto", "pyannote") and self.pyannote_engine.is_ready():
            try:
                if isinstance(audio_input, (str, Path)):
                    logger.info("Executing Pyannote diarization...")
                    return self.pyannote_engine.diarize(audio_input)
            except Exception as e:
                logger.warning(f"Pyannote diarization failed ({e}). Falling back to spectral clustering.")

        # 2. Spectral / Acoustic clustering diarization (Local offline, zero token)
        try:
            logger.info("Executing local acoustic spectral clustering diarization...")
            segments = self.spectral_engine.diarize(audio_input, vad_segments=vad_segments)
            if segments:
                return segments
        except Exception as e:
            logger.error(f"Spectral diarization failed ({e}). Falling back to single-speaker.")

        # 3. Graceful Single-speaker Fallback
        logger.info("Using single-speaker fallback (SPEAKER_00).")
        if vad_segments and len(vad_segments) > 0:
            return [
                DiarizationSegment(
                    speaker="SPEAKER_00",
                    start=v.start,
                    end=v.end,
                    duration=v.duration
                )
                for v in vad_segments
            ]
        return [DiarizationSegment(speaker="SPEAKER_00", start=0.0, end=1.0, duration=1.0)]


def diarize_audio(
    audio_path: Union[str, Path],
    vad_segments: Optional[List[VADSegment]] = None
) -> List[DiarizationSegment]:
    """Convenience function to run diarization."""
    engine = DiarizationEngine()
    return engine.diarize(audio_path, vad_segments=vad_segments)
