"""Unit tests for Voice Activity Detection (VAD)."""
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
from app.vad.silero_engine import SileroVADEngine


def test_silero_vad_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir) / "speech_simulation.wav"
        sr = 16000

        # Construct 3 seconds: 0.5s silence, 1.0s speech tone, 0.5s silence, 1.0s speech tone
        silence_1 = np.zeros(int(sr * 0.5), dtype=np.float32)
        t1 = np.linspace(0, 1.0, int(sr * 1.0), endpoint=False)
        speech_1 = (0.3 * np.sin(2 * np.pi * 300 * t1) + 0.2 * np.sin(2 * np.pi * 600 * t1)).astype(np.float32)
        silence_2 = np.zeros(int(sr * 0.5), dtype=np.float32)
        t2 = np.linspace(0, 1.0, int(sr * 1.0), endpoint=False)
        speech_2 = (0.3 * np.sin(2 * np.pi * 350 * t2)).astype(np.float32)

        full_audio = np.concatenate([silence_1, speech_1, silence_2, speech_2])
        sf.write(str(audio_path), full_audio, sr)

        engine = SileroVADEngine(sample_rate=16000)
        segments = engine.detect_segments(audio_path)

        assert len(segments) >= 1
        for seg in segments:
            assert seg.start >= 0.0
            assert seg.end <= 3.1
            assert seg.duration > 0.0
            assert seg.id.startswith("vad_")
            assert seg.confidence is not None
