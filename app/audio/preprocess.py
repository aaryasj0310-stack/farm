"""Audio ingestion, validation, metadata extraction, and normalization."""
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import imageio_ffmpeg
import numpy as np
import soundfile as sf
from pydub import AudioSegment
from app.config.settings import settings
from app.models.schemas import AudioMetadata
from app.utils.logger import get_logger
from app.utils.security import sanitize_filename, validate_audio_file

logger = get_logger("audio.preprocess")

# Configure pydub to use imageio-ffmpeg binary
try:
    ffmpeg_binary = imageio_ffmpeg.get_ffmpeg_exe()
    AudioSegment.converter = ffmpeg_binary
except Exception as e:
    logger.warning(f"Could not auto-bind imageio-ffmpeg to pydub: {e}")


class AudioPreprocessor:
    """Handles audio inspection, security validation, and normalization."""

    def __init__(self, target_sample_rate: int = 16000):
        self.target_sample_rate = target_sample_rate
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    def get_metadata_and_normalize(
        self,
        input_path: Path | str,
        output_dir: Optional[Path | str] = None,
        job_id: Optional[str] = None
    ) -> Tuple[AudioMetadata, Path]:
        """Validates, extracts metadata, and normalizes input audio to 16kHz mono PCM WAV.
        
        Preserves original audio file and returns (AudioMetadata, normalized_wav_path).
        """
        input_path = Path(input_path).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {input_path}")

        file_size = input_path.stat().st_size
        valid, msg = validate_audio_file(
            input_path.name, file_size, max_size_mb=settings.MAX_AUDIO_FILE_SIZE_MB
        )
        if not valid:
            raise ValueError(f"Audio validation failed: {msg}")

        # Destination for normalized audio
        if output_dir is None:
            output_dir = input_path.parent
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        normalized_path = output_dir / f"{input_path.stem}_16k_mono.wav"

        # 1. Normalize to 16kHz Mono 16-bit PCM WAV using FFmpeg subprocess
        cmd = [
            self.ffmpeg_exe,
            "-y",  # overwrite output
            "-i", str(input_path),
            "-ar", str(self.target_sample_rate),
            "-ac", "1",  # mono
            "-c:a", "pcm_s16le",
            str(normalized_path)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"FFmpeg conversion failed: {err_msg}")
            raise RuntimeError(f"FFmpeg failed to decode audio: {err_msg[:200]}")

        if not normalized_path.exists() or normalized_path.stat().st_size == 0:
            raise RuntimeError("Normalized audio file is missing or 0 bytes.")

        # 2. Extract detailed technical properties from normalized WAV
        data, sr = sf.read(str(normalized_path), dtype="float32")
        duration_sec = len(data) / sr

        if duration_sec < 0.1:
            raise ValueError(f"Audio duration too short ({duration_sec:.2f}s). Minimum is 0.1s.")

        if duration_sec > settings.MAX_AUDIO_DURATION_SEC:
            raise ValueError(
                f"Audio duration ({duration_sec:.1f}s) exceeds maximum allowed ({settings.MAX_AUDIO_DURATION_SEC}s)."
            )

        # Calculate RMS volume and clipping
        rms = np.sqrt(np.mean(data**2))
        rms_db = 20 * math.log10(max(rms, 1e-9))
        is_clipping = bool(np.any(np.abs(data) >= 0.999))

        metadata = AudioMetadata(
            duration_seconds=round(duration_sec, 3),
            sample_rate=sr,
            channels=1,
            codec="pcm_s16le",
            bitrate=sr * 16,
            file_size_bytes=normalized_path.stat().st_size,
            rms_volume_db=round(rms_db, 2),
            is_clipping=is_clipping,
            original_filename=input_path.name
        )

        return metadata, normalized_path


def extract_audio_metadata(audio_path: Path | str) -> AudioMetadata:
    """Convenience function to inspect audio metadata."""
    preprocessor = AudioPreprocessor()
    meta, _ = preprocessor.get_metadata_and_normalize(audio_path)
    return meta


def normalize_audio(input_path: Path | str, output_dir: Optional[Path | str] = None) -> Tuple[AudioMetadata, Path]:
    """Convenience function to normalize audio and return metadata."""
    preprocessor = AudioPreprocessor()
    return preprocessor.get_metadata_and_normalize(input_path, output_dir=output_dir)
