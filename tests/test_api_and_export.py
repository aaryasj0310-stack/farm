"""Unit tests for FastAPI REST endpoints and Exporters."""
import io
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import AudioMetadata, JobStatusEnum, PipelineResult, CanonicalTranscriptSegment, ClaimResult, AnalysisSummary
from app.reporting.export import export_pipeline_result

client = TestClient(app)


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "device" in data


def test_api_models():
    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert data["asr"]["engine"] == "faster-whisper"
    assert data["vad"]["engine"] == "silero-vad"


def test_api_upload_and_lifecycle():
    # Create test WAV
    sr = 16000
    wav_bytes = io.BytesIO()
    data = (0.2 * np.sin(2 * np.pi * 440 * np.linspace(0, 1.0, sr))).astype(np.float32)
    sf.write(wav_bytes, data, sr, format="WAV")
    wav_bytes.seek(0)

    # 1. Upload
    response = client.post(
        "/api/audio/upload",
        files={"file": ("test_hindi_sample.wav", wav_bytes, "audio/wav")}
    )
    assert response.status_code == 201
    upload_data = response.json()
    job_id = upload_data["job_id"]
    assert job_id.startswith("job_")

    # 2. Status
    res_status = client.get(f"/api/audio/{job_id}/status")
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "QUEUED"

    # 3. Delete
    res_del = client.delete(f"/api/audio/{job_id}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True


def test_all_export_formats():
    result = PipelineResult(
        job_id="job_exp_001",
        status=JobStatusEnum.COMPLETED,
        audio_metadata=AudioMetadata(
            duration_seconds=15.0,
            sample_rate=16000,
            channels=1,
            codec="pcm_s16le",
            file_size_bytes=480000,
            original_filename="meeting.wav"
        ),
        transcript=[
            CanonicalTranscriptSegment(
                id="seg_01",
                speaker="SPEAKER_00",
                start=0.5,
                end=3.5,
                text="नमस्ते, कल पुणे की मीटिंग कितने बजे है?",
                confidence=0.95
            )
        ],
        claims=[
            ClaimResult(
                claim_id="clm_01",
                speaker="SPEAKER_00",
                claim_text="Speaker asks regarding Pune meeting time",
                source_segment_ids=["seg_01"],
                source_start=0.5,
                source_end=3.5,
                evidence_quote="नमस्ते, कल पुणे की मीटिंग कितने बजे है?"
            )
        ],
        summary=AnalysisSummary(
            high_level_summary="Meeting coordination conversation in Hindi.",
            detailed_summary="Speaker enquired regarding scheduled time for Pune meeting.",
            key_takeaways=["Meeting planned for Pune [00:00]"],
            speaker_summaries={"SPEAKER_00": "Initiated coordination enquiry."}
        )
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # JSON
        json_out = export_pipeline_result(result, export_format="json")
        assert "job_exp_001" in json_out

        # TXT
        txt_out = export_pipeline_result(result, export_format="txt")
        assert "HINDI AUDIO INTELLIGENCE REPORT" in txt_out

        # Markdown
        md_out = export_pipeline_result(result, export_format="md")
        assert "# Audio Intelligence Report" in md_out

        # HTML
        html_out = export_pipeline_result(result, export_format="html")
        assert "<html" in html_out and "Pune meeting" in html_out

        # PDF
        pdf_path = Path(tmpdir) / "test.pdf"
        pdf_bytes = export_pipeline_result(result, export_format="pdf", output_path=pdf_path)
        assert len(pdf_bytes) > 500
        assert pdf_path.exists()
