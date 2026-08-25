"""FastAPI REST routes for Hindi Audio Intelligence Pipeline."""
import os
import shutil
import uuid
from pathlib import Path
from typing import List, Literal, Optional
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from app.config.settings import settings
from app.models.schemas import (
    JobRecord,
    JobStatusEnum,
    PipelineResult
)
from app.pipeline.orchestrator import AudioIntelligencePipeline
from app.reporting.export import export_pipeline_result
from app.storage.db import get_storage
from app.utils.logger import get_logger
from app.utils.security import sanitize_filename, validate_audio_file

logger = get_logger("api.routes")
router = APIRouter(prefix="/api", tags=["Audio Intelligence"])
pipeline_instance = AudioIntelligencePipeline()


@router.get("/health")
def get_health():
    """Returns application health and hardware execution profile."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "device": settings.get_effective_device(),
        "compute_type": settings.get_compute_type(),
        "asr_model_size": settings.ASR_MODEL_SIZE,
        "llm_provider": settings.LLM_PROVIDER
    }


@router.get("/models")
def get_models_info():
    """Returns information on available and active pipeline models."""
    return {
        "device": settings.get_effective_device(),
        "compute_type": settings.get_compute_type(),
        "asr": {
            "engine": "faster-whisper",
            "model_size": settings.ASR_MODEL_SIZE,
            "language": settings.ASR_LANGUAGE
        },
        "vad": {
            "engine": "silero-vad",
            "version": "6.2"
        },
        "diarization": {
            "engine": settings.DIARIZATION_ENGINE,
            "pyannote_ready": bool(settings.HF_TOKEN)
        },
        "llm": {
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL
        }
    }


@router.get("/jobs", response_model=List[JobRecord])
def list_all_jobs(limit: int = Query(default=20, ge=1, le=100)):
    """Lists recent audio analysis jobs."""
    storage = get_storage()
    return storage.list_jobs(limit=limit)


@router.post("/audio/upload", status_code=status.HTTP_201_CREATED)
async def upload_audio(file: UploadFile = File(...)):
    """Uploads an audio file and initializes a job record."""
    clean_name = sanitize_filename(file.filename or "audio.wav")
    job_id = f"job_{uuid.uuid4().hex[:10]}"

    job_dir = settings.STORAGE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    raw_audio_path = job_dir / clean_name

    # Save uploaded file
    try:
        with open(raw_audio_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        logger.error(f"Error saving uploaded audio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store audio file: {e}")

    file_size = raw_audio_path.stat().st_size
    valid, msg = validate_audio_file(clean_name, file_size, max_size_mb=settings.MAX_AUDIO_FILE_SIZE_MB)
    if not valid:
        try:
            raw_audio_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=msg)

    storage = get_storage()
    job = storage.create_job(
        job_id=job_id,
        original_filename=clean_name,
        audio_path=str(raw_audio_path)
    )

    logger.info(f"Job {job_id} initialized with file {clean_name} ({file_size / (1024*1024):.2f} MB).")
    return {
        "job_id": job.job_id,
        "original_filename": job.original_filename,
        "status": job.status,
        "created_at": job.created_at
    }


def _run_background_pipeline(job_id: str, audio_path: str, language: str = "hi"):
    """Background task worker to run pipeline without blocking HTTP request."""
    try:
        pipeline_instance.process_job(
            job_id=job_id,
            audio_path=audio_path,
            language=language
        )
    except Exception as e:
        logger.error(f"Background execution failed for job {job_id}: {e}")


@router.post("/audio/{job_id}/analyze")
def trigger_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    language: str = Query(default="hi")
):
    """Triggers asynchronous analysis for an uploaded audio job."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if job.status == JobStatusEnum.PROCESSING:
        return {"job_id": job_id, "status": "PROCESSING", "message": "Job is already being processed."}

    storage.update_job_progress(
        job_id=job_id,
        status=JobStatusEnum.PROCESSING,
        progress_percentage=0,
        current_stage="QUEUED"
    )

    background_tasks.add_task(
        _run_background_pipeline,
        job_id=job_id,
        audio_path=job.audio_path,
        language=language
    )

    return {
        "job_id": job_id,
        "status": JobStatusEnum.PROCESSING,
        "message": "Analysis started."
    }


@router.get("/audio/{job_id}/status")
def get_job_status(job_id: str):
    """Retrieves real-time processing status and progress."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "current_stage": job.current_stage,
        "error": job.error,
        "completed_at": job.completed_at
    }


@router.get("/audio/{job_id}/transcript")
def get_job_transcript(job_id: str):
    """Retrieves speaker-attributed transcript segments."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if not job.result:
        return {"job_id": job_id, "status": job.status, "transcript": []}

    return {
        "job_id": job_id,
        "language": "hi",
        "speakers": job.result.speakers,
        "segments": job.result.transcript
    }


@router.get("/audio/{job_id}/analysis")
def get_job_analysis(job_id: str):
    """Retrieves intelligence analysis components."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if not job.result:
        return {"job_id": job_id, "status": job.status, "analysis": None}

    return {
        "job_id": job_id,
        "emotions": job.result.emotions,
        "intents": job.result.intents,
        "entities": job.result.entities,
        "topics": job.result.topics,
        "claims": job.result.claims,
        "contradictions": job.result.contradictions,
        "timeline": job.result.timeline,
        "summary": job.result.summary
    }


@router.get("/audio/{job_id}/report", response_model=PipelineResult)
def get_full_report(job_id: str):
    """Returns complete canonical PipelineResult."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if not job.result:
        raise HTTPException(status_code=400, detail=f"Job is {job.status.value}, report not ready yet.")

    return job.result


@router.get("/audio/{job_id}/stream")
def stream_audio(job_id: str):
    """Serves the job audio file for HTML5 audio player playback."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    target_path = Path(job.normalized_audio_path or job.audio_path)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing on disk.")

    media_type = "audio/wav" if target_path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(
        str(target_path),
        media_type=media_type,
        filename=target_path.name
    )


@router.get("/audio/{job_id}/export")
def export_job_report(
    job_id: str,
    format: Literal["json", "txt", "md", "html", "pdf"] = Query(default="json")
):
    """Exports and downloads analysis in requested format."""
    storage = get_storage()
    job = storage.get_job(job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail=f"Completed report for job '{job_id}' not found.")

    if format == "pdf":
        pdf_path = settings.STORAGE_DIR / job_id / "report.pdf"
        pdf_bytes = export_pipeline_result(job.result, export_format="pdf", output_path=pdf_path)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{job_id}_report.pdf"'}
        )

    content = export_pipeline_result(job.result, export_format=format)
    media_types = {
        "json": "application/json",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "html": "text/html; charset=utf-8"
    }
    return Response(
        content=content,
        media_type=media_types[format],
        headers={"Content-Disposition": f'attachment; filename="{job_id}_report.{format}"'}
    )


@router.delete("/audio/{job_id}")
def delete_job(job_id: str):
    """Deletes job record and associated files."""
    storage = get_storage()
    deleted = storage.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, "deleted": True}
