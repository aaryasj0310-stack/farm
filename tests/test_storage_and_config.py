"""Unit tests for configuration, security utilities, and storage layer."""
import tempfile
from pathlib import Path
import pytest
from app.config.settings import Settings
from app.models.schemas import JobStatusEnum, PipelineResult, AudioMetadata
from app.storage.db import JobStorage
from app.utils.security import sanitize_filename, validate_audio_file


def test_sanitize_filename():
    assert sanitize_filename("../../../secret.wav") == "secret.wav"
    assert sanitize_filename("hindi recording (1).mp3") == "hindi_recording__1_.mp3"
    assert sanitize_filename("") == "unnamed_audio.wav"
    assert sanitize_filename(".hidden.wav") == "audio_hidden.wav"


def test_validate_audio_file():
    valid, msg = validate_audio_file("test.mp3", 1024 * 1024, max_size_mb=100)
    assert valid is True
    assert msg == ""

    invalid_ext, msg = validate_audio_file("test.exe", 1024)
    assert invalid_ext is False
    assert "Unsupported audio extension" in msg

    empty_file, msg = validate_audio_file("test.wav", 0)
    assert empty_file is False
    assert "empty" in msg

    oversized, msg = validate_audio_file("test.wav", 200 * 1024 * 1024, max_size_mb=100)
    assert oversized is False
    assert "exceeds limit" in msg


def test_storage_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_jobs.db"
        storage = JobStorage(db_path=db_path)

        # 1. Create Job
        job = storage.create_job(
            job_id="job_test_001",
            original_filename="sample_hindi.mp3",
            audio_path=str(Path(tmpdir) / "sample_hindi.mp3")
        )
        assert job.job_id == "job_test_001"
        assert job.status == JobStatusEnum.QUEUED

        # 2. Update Progress
        storage.update_job_progress(
            job_id="job_test_001",
            status=JobStatusEnum.PROCESSING,
            progress_percentage=45,
            current_stage="ASR"
        )
        fetched = storage.get_job("job_test_001")
        assert fetched is not None
        assert fetched.status == JobStatusEnum.PROCESSING
        assert fetched.progress_percentage == 45
        assert fetched.current_stage == "ASR"

        # 3. Save Result
        result = PipelineResult(
            job_id="job_test_001",
            status=JobStatusEnum.COMPLETED,
            audio_metadata=AudioMetadata(
                duration_seconds=12.5,
                sample_rate=16000,
                channels=1,
                codec="pcm_s16le",
                file_size_bytes=400000,
                original_filename="sample_hindi.mp3"
            )
        )
        storage.save_job_result("job_test_001", result, normalized_audio_path=str(Path(tmpdir) / "norm.wav"))
        completed = storage.get_job("job_test_001")
        assert completed.status == JobStatusEnum.COMPLETED
        assert completed.result is not None
        assert completed.result.audio_metadata.duration_seconds == 12.5

        # 4. List Jobs
        jobs = storage.list_jobs(limit=10)
        assert len(jobs) == 1
        assert jobs[0].job_id == "job_test_001"

        # 5. Delete Job
        deleted = storage.delete_job("job_test_001")
        assert deleted is True
        assert storage.get_job("job_test_001") is None
