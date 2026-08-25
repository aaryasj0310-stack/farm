"""SQLite-backed persistent storage layer for job tracking and results."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional
from app.config.settings import settings
from app.models.schemas import JobRecord, JobStatusEnum, PipelineResult
from app.utils.logger import get_logger

logger = get_logger("storage.db")


class JobStorage:
    """Thread-safe SQLite storage for jobs and analysis results."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yields an active SQLite connection and guarantees it is closed on exit."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes database schema."""
        with self._lock, self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_percentage INTEGER NOT NULL DEFAULT 0,
                    current_stage TEXT NOT NULL DEFAULT 'QUEUED',
                    audio_path TEXT NOT NULL,
                    normalized_audio_path TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    result_json TEXT
                )
            """)
            conn.commit()

    def create_job(self, job_id: str, original_filename: str, audio_path: str) -> JobRecord:
        """Creates a new job in QUEUED status."""
        now = datetime.now(timezone.utc).isoformat()
        record = JobRecord(
            job_id=job_id,
            original_filename=original_filename,
            status=JobStatusEnum.QUEUED,
            progress_percentage=0,
            current_stage="QUEUED",
            audio_path=str(audio_path),
            created_at=now
        )
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO jobs (job_id, original_filename, status, progress_percentage, current_stage, audio_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record.job_id,
                record.original_filename,
                record.status.value,
                record.progress_percentage,
                record.current_stage,
                record.audio_path,
                record.created_at
            ))
            conn.commit()
        return record

    def update_job_progress(
        self,
        job_id: str,
        status: Optional[JobStatusEnum] = None,
        progress_percentage: Optional[int] = None,
        current_stage: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Updates job status, progress percentage, or error state."""
        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if progress_percentage is not None:
            updates.append("progress_percentage = ?")
            params.append(progress_percentage)
        if current_stage is not None:
            updates.append("current_stage = ?")
            params.append(current_stage)
        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if not updates:
            return

        params.append(job_id)
        with self._lock, self._connection() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?", params)
            conn.commit()

    def save_job_result(
        self,
        job_id: str,
        result: PipelineResult,
        normalized_audio_path: Optional[str] = None
    ) -> None:
        """Saves completed pipeline result."""
        now = datetime.now(timezone.utc).isoformat()
        result_json = result.model_dump_json()
        with self._lock, self._connection() as conn:
            conn.execute("""
                UPDATE jobs SET
                    status = ?,
                    progress_percentage = 100,
                    current_stage = 'COMPLETED',
                    completed_at = ?,
                    normalized_audio_path = COALESCE(?, normalized_audio_path),
                    result_json = ?,
                    error = NULL
                WHERE job_id = ?
            """, (
                JobStatusEnum.COMPLETED.value,
                now,
                normalized_audio_path,
                result_json,
                job_id
            ))
            conn.commit()

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieves a job by ID."""
        with self._lock, self._connection() as conn:
            cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            result = None
            if row["result_json"]:
                result = PipelineResult.model_validate_json(row["result_json"])

            return JobRecord(
                job_id=row["job_id"],
                original_filename=row["original_filename"],
                status=JobStatusEnum(row["status"]),
                progress_percentage=row["progress_percentage"],
                current_stage=row["current_stage"],
                audio_path=row["audio_path"],
                normalized_audio_path=row["normalized_audio_path"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                error=row["error"],
                result=result
            )

    def list_jobs(self, limit: int = 50) -> List[JobRecord]:
        """Lists recent jobs ordered by creation time descending."""
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            jobs = []
            for row in cursor.fetchall():
                result = None
                if row["result_json"]:
                    try:
                        result = PipelineResult.model_validate_json(row["result_json"])
                    except Exception:
                        result = None
                jobs.append(JobRecord(
                    job_id=row["job_id"],
                    original_filename=row["original_filename"],
                    status=JobStatusEnum(row["status"]),
                    progress_percentage=row["progress_percentage"],
                    current_stage=row["current_stage"],
                    audio_path=row["audio_path"],
                    normalized_audio_path=row["normalized_audio_path"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    error=row["error"],
                    result=result
                ))
            return jobs

    def delete_job(self, job_id: str) -> bool:
        """Deletes a job and associated files."""
        job = self.get_job(job_id)
        if not job:
            return False
        
        # Cleanup audio files
        for p in [job.audio_path, job.normalized_audio_path]:
            if p:
                try:
                    path_obj = Path(p)
                    if path_obj.exists():
                        path_obj.unlink()
                except Exception as e:
                    logger.warning(f"Error removing audio file {p}: {e}")

        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
        return True


# Global singleton instance
_global_storage: Optional[JobStorage] = None


def get_storage() -> JobStorage:
    """Returns the singleton JobStorage instance."""
    global _global_storage
    if _global_storage is None:
        _global_storage = JobStorage()
    return _global_storage
