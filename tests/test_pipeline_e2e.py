"""End-to-End Integration tests for AudioIntelligencePipeline."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from app.models.schemas import CanonicalTranscriptSegment, JobStatusEnum, WordTimestamp
from app.pipeline.orchestrator import AudioIntelligencePipeline
from app.storage.db import JobStorage
from tests.fixtures.generate_synthetic_fixture import create_synthetic_audio


def test_pipeline_e2e_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_wav = create_synthetic_audio(tmp_path / "test_audio.wav")
        db_path = tmp_path / "test_jobs.db"

        # Mock ASR transcribe so we don't need to load Whisper weights during fast unit test runs
        mock_asr_segments = [
            CanonicalTranscriptSegment(
                id="seg_001",
                speaker="SPEAKER_00",
                start=0.5,
                end=2.5,
                text="नमस्ते, क्या पुणे की मीटिंग 5 बजे है?",
                confidence=0.96,
                words=[
                    WordTimestamp(word="नमस्ते,", start=0.5, end=0.9),
                    WordTimestamp(word="क्या", start=0.9, end=1.2),
                    WordTimestamp(word="पुणे", start=1.2, end=1.6),
                    WordTimestamp(word="की", start=1.6, end=1.8),
                    WordTimestamp(word="मीटिंग", start=1.8, end=2.1),
                    WordTimestamp(word="5", start=2.1, end=2.3),
                    WordTimestamp(word="बजे", start=2.3, end=2.5),
                    WordTimestamp(word="है?", start=2.5, end=2.5)
                ]
            ),
            CanonicalTranscriptSegment(
                id="seg_002",
                speaker="SPEAKER_01",
                start=3.3,
                end=5.5,
                text="हाँ, मैंने ₹50,000 की पेमेंट भेज दी है।",
                confidence=0.93,
                words=[
                    WordTimestamp(word="हाँ,", start=3.3, end=3.6),
                    WordTimestamp(word="मैंने", start=3.6, end=4.0),
                    WordTimestamp(word="₹50,000", start=4.0, end=4.6),
                    WordTimestamp(word="की", start=4.6, end=4.8),
                    WordTimestamp(word="पेमेंट", start=4.8, end=5.2),
                    WordTimestamp(word="भेज", start=5.2, end=5.4),
                    WordTimestamp(word="दी", start=5.4, end=5.5),
                    WordTimestamp(word="है।", start=5.5, end=5.5)
                ]
            )
        ]

        pipeline = AudioIntelligencePipeline()
        pipeline.storage = JobStorage(db_path=db_path)

        # Create job
        job_id = "test_job_e2e"
        pipeline.storage.create_job(
            job_id=job_id,
            original_filename="test_audio.wav",
            audio_path=str(test_wav)
        )

        with patch("app.pipeline.orchestrator.get_asr_engine") as mock_get_asr:
            mock_asr = MagicMock()
            mock_asr.model_size = "small"
            mock_asr.transcribe.return_value = mock_asr_segments
            mock_get_asr.return_value = mock_asr

            # Execute pipeline
            result = pipeline.process_job(
                job_id=job_id,
                audio_path=test_wav,
                language="hi"
            )

        # Verify all pipeline stages succeeded
        assert result.status == JobStatusEnum.COMPLETED
        assert result.audio_metadata is not None
        assert result.audio_metadata.duration_seconds >= 5.5
        assert len(result.vad_segments) >= 1
        assert len(result.speakers) >= 1
        assert len(result.transcript) == 2
        assert len(result.emotions) == 2
        assert len(result.intents) == 2
        assert len(result.entities) >= 2
        assert len(result.claims) >= 1
        assert result.summary is not None
        assert result.metadata is not None
        assert result.metadata.real_time_factor > 0.0

        # Verify database record
        db_job = pipeline.storage.get_job(job_id)
        assert db_job is not None
        assert db_job.status == JobStatusEnum.COMPLETED
        assert db_job.result is not None
