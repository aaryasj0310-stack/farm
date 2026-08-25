"""Unit tests for audio preprocessing, validation, and normalization."""
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
from app.audio.preprocess import AudioPreprocessor


def test_audio_preprocessing_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        raw_audio_path = tmp_path / "test_raw_stereo.wav"

        # Create a 2-second stereo 44.1kHz sine wave
        sr = 44100
        duration = 2.0
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        left = 0.5 * np.sin(2 * np.pi * 440 * t)
        right = 0.5 * np.sin(2 * np.pi * 880 * t)
        stereo_data = np.stack([left, right], axis=-1)

        sf.write(str(raw_audio_path), stereo_data, sr)

        preprocessor = AudioPreprocessor(target_sample_rate=16000)
        metadata, normalized_path = preprocessor.get_metadata_and_normalize(
            input_path=raw_audio_path,
            output_dir=tmp_path / "processed"
        )

        assert metadata.duration_seconds >= 1.95 and metadata.duration_seconds <= 2.05
        assert metadata.sample_rate == 16000
        assert metadata.channels == 1
        assert metadata.codec == "pcm_s16le"
        assert metadata.original_filename == "test_raw_stereo.wav"
        assert metadata.is_clipping is False
        assert normalized_path.exists()

        # Validate that the output WAV file is 16kHz mono float32/int16
        data, read_sr = sf.read(str(normalized_path))
        assert read_sr == 16000
        assert data.ndim == 1  # mono


def test_audio_too_short():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        tiny_audio_path = tmp_path / "tiny.wav"

        # 0.01 second audio
        sf.write(str(tiny_audio_path), np.zeros(160), 16000)

        preprocessor = AudioPreprocessor()
        with pytest.raises(ValueError, match="too short"):
            preprocessor.get_metadata_and_normalize(tiny_audio_path)
