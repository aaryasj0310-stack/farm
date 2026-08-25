"""Optional Pyannote Audio Diarization Engine adapter."""
from pathlib import Path
from typing import List, Optional, Union
import numpy as np
import soundfile as sf
from app.config.settings import settings
from app.models.schemas import DiarizationSegment
from app.utils.logger import get_logger

logger = get_logger("diarization.pyannote")


class PyannoteDiarizationEngine:
    """Pyannote.audio speaker diarization engine when HF_TOKEN is configured."""

    def __init__(self, hf_token: Optional[str] = None):
        self.hf_token = hf_token or settings.HF_TOKEN
        self._pipeline = None
        self._is_available = self._check_availability()

    def _check_availability(self) -> bool:
        """Checks if pyannote.audio is importable and token is present."""
        if not self.hf_token:
            logger.info("HF_TOKEN not configured; pyannote engine unavailable.")
            return False
        try:
            from pyannote.audio import Pipeline
            return True
        except ImportError:
            logger.info("pyannote.audio not installed; using spectral diarization engine.")
            return False

    def is_ready(self) -> bool:
        return self._is_available

    def diarize(
        self,
        audio_path: Union[str, Path],
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ) -> List[DiarizationSegment]:
        """Runs Pyannote diarization pipeline."""
        if not self._is_available:
            raise RuntimeError("Pyannote engine is not available.")

        from pyannote.audio import Pipeline
        if self._pipeline is None:
            logger.info("Initializing pyannote/speaker-diarization-3.1 pipeline...")
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=self.hf_token
            )
            device = settings.get_effective_device()
            if device == "cuda":
                import torch
                self._pipeline.to(torch.device("cuda"))

        diarization = self._pipeline(
            str(audio_path),
            min_speakers=min_speakers,
            max_speakers=max_speakers
        )

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            start = round(turn.start, 3)
            end = round(turn.end, 3)
            segments.append(DiarizationSegment(
                speaker=speaker,
                start=start,
                end=end,
                duration=round(end - start, 3)
            ))
        return segments
