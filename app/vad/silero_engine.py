"""Voice Activity Detection (VAD) engine using Silero VAD with robust fallbacks."""
from pathlib import Path
from typing import List, Optional, Union
import numpy as np
import soundfile as sf
import torch
from silero_vad import load_silero_vad, get_speech_timestamps
from app.config.settings import settings
from app.models.schemas import VADSegment
from app.utils.logger import get_logger

logger = get_logger("vad.silero")


class SileroVADEngine:
    """Voice Activity Detector with Silero VAD model and energy-based fallback."""

    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 200,
        sample_rate: int = 16000
    ):
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.sample_rate = sample_rate
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        """Loads Silero VAD model lazily and safely."""
        try:
            self._model = load_silero_vad()
            logger.info("Silero VAD model loaded successfully.")
        except Exception as e:
            logger.warning(f"Failed to load Silero VAD model ({e}). Will use fallback energy detector.")
            self._model = None

    def detect_segments(
        self,
        audio_input: Union[str, Path, np.ndarray],
        job_id: Optional[str] = None
    ) -> List[VADSegment]:
        """Detects speech intervals in 16kHz mono audio.
        
        Returns a list of structured VADSegment instances.
        """
        # Load audio data
        if isinstance(audio_input, (str, Path)):
            audio_path = Path(audio_input)
            data, sr = sf.read(str(audio_path), dtype="float32")
            if sr != self.sample_rate:
                logger.warning(f"Audio sample rate {sr} != expected {self.sample_rate}")
        else:
            data = audio_input.astype(np.float32)
            sr = self.sample_rate

        # Ensure single channel mono
        if data.ndim > 1:
            data = np.mean(data, axis=-1)

        total_duration = len(data) / sr

        # Try Silero VAD first
        if self._model is not None:
            try:
                wav_tensor = torch.from_numpy(data)
                speech_timestamps = get_speech_timestamps(
                    wav_tensor,
                    self._model,
                    sampling_rate=self.sample_rate,
                    threshold=self.threshold,
                    min_speech_duration_ms=self.min_speech_duration_ms,
                    min_silence_duration_ms=self.min_silence_duration_ms,
                    return_seconds=True
                )

                if speech_timestamps:
                    segments = []
                    for i, ts in enumerate(speech_timestamps):
                        start = round(ts["start"], 3)
                        end = round(ts["end"], 3)
                        duration = round(end - start, 3)
                        if duration > 0.05:
                            segments.append(VADSegment(
                                id=f"vad_{i+1:03d}",
                                start=start,
                                end=end,
                                duration=duration,
                                confidence=0.95
                            ))

                    if segments:
                        logger.info(f"Silero VAD detected {len(segments)} speech segments ({total_duration:.2f}s audio).")
                        return segments

            except Exception as e:
                logger.error(f"Error running Silero VAD: {e}. Falling back to energy VAD.")

        # Fallback: Energy-based VAD if Silero returns empty or fails on synthetic tones
        logger.info("Using energy-based VAD fallback.")
        return self._energy_vad_fallback(data, sr)

    def _energy_vad_fallback(self, data: np.ndarray, sr: int) -> List[VADSegment]:
        """Energy & zero-crossing rate VAD fallback."""
        frame_size = int(sr * 0.03)  # 30ms frames
        hop_size = int(sr * 0.01)    # 10ms hop
        
        num_frames = (len(data) - frame_size) // hop_size + 1
        if num_frames <= 0:
            return [VADSegment(id="vad_001", start=0.0, end=round(len(data)/sr, 3), duration=round(len(data)/sr, 3), confidence=0.5)]

        energies = np.array([
            np.sqrt(np.mean(data[i * hop_size : i * hop_size + frame_size] ** 2))
            for i in range(num_frames)
        ])

        energy_threshold = max(np.percentile(energies, 50) * 0.5, 0.002)
        is_speech = energies > energy_threshold

        segments = []
        in_speech = False
        start_frame = 0

        for i, speech in enumerate(is_speech):
            if speech and not in_speech:
                in_speech = True
                start_frame = i
            elif not speech and in_speech:
                in_speech = False
                start_sec = round((start_frame * hop_size) / sr, 3)
                end_sec = round(((i + 1) * hop_size) / sr, 3)
                if (end_sec - start_sec) >= (self.min_speech_duration_ms / 1000.0):
                    segments.append(VADSegment(
                        id=f"vad_{len(segments)+1:03d}",
                        start=start_sec,
                        end=end_sec,
                        duration=round(end_sec - start_sec, 3),
                        confidence=0.70
                    ))

        if in_speech:
            start_sec = round((start_frame * hop_size) / sr, 3)
            end_sec = round(len(data) / sr, 3)
            segments.append(VADSegment(
                id=f"vad_{len(segments)+1:03d}",
                start=start_sec,
                end=end_sec,
                duration=round(end_sec - start_sec, 3),
                confidence=0.70
            ))

        if not segments:
            # Whole file fallback
            segments.append(VADSegment(
                id="vad_001",
                start=0.0,
                end=round(len(data)/sr, 3),
                duration=round(len(data)/sr, 3),
                confidence=0.50
            ))

        return segments


def detect_voice_activity(audio_path: Union[str, Path]) -> List[VADSegment]:
    """Convenience function to run VAD."""
    engine = SileroVADEngine()
    return engine.detect_segments(audio_path)
