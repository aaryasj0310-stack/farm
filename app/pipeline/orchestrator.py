"""Central Pipeline Orchestrator for Hindi Audio Intelligence."""
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from app.alignment.aligner import align_speakers_and_transcript
from app.analysis.claims import extract_claims_and_contradictions
from app.analysis.emotion import analyze_emotions
from app.analysis.entities import extract_entities
from app.analysis.intent import classify_intents
from app.analysis.topics import extract_topics
from app.asr.whisper_engine import get_asr_engine
from app.audio.preprocess import AudioPreprocessor
from app.config.settings import settings
from app.diarization.diarizer import DiarizationEngine
from app.llm.provider import synthesize_conversation_reasoning
from app.models.schemas import (
    JobStatusEnum,
    PipelineMetadata,
    PipelineResult
)
from app.storage.db import get_storage
from app.utils.logger import get_logger
from app.vad.silero_engine import SileroVADEngine

logger = get_logger("pipeline.orchestrator")


class AudioIntelligencePipeline:
    """End-to-end modular audio intelligence pipeline."""

    def __init__(self):
        self.preprocessor = AudioPreprocessor()
        self.vad_engine = SileroVADEngine()
        self.diarization_engine = DiarizationEngine()
        self.storage = get_storage()

    def process_job(
        self,
        job_id: str,
        audio_path: Path | str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        language: str = "hi"
    ) -> PipelineResult:
        """Executes full pipeline for a job and persists results."""
        start_time = time.time()
        audio_path = Path(audio_path).resolve()
        logger_context = get_logger("pipeline", job_id=job_id)

        def update_progress(pct: int, stage: str):
            logger_context.info(f"Progress {pct}% - Stage: {stage}")
            job_status = JobStatusEnum.COMPLETED if pct >= 100 else JobStatusEnum.PROCESSING
            self.storage.update_job_progress(
                job_id=job_id,
                status=job_status,
                progress_percentage=pct,
                current_stage=stage
            )
            if progress_callback:
                try:
                    progress_callback(pct, stage)
                except Exception:
                    pass

        try:
            # 1. Audio Ingestion & Normalization
            update_progress(10, "PREPROCESSING")
            audio_metadata, norm_path = self.preprocessor.get_metadata_and_normalize(
                input_path=audio_path,
                output_dir=settings.STORAGE_DIR / job_id
            )

            # 2. Voice Activity Detection (VAD)
            update_progress(25, "VAD")
            vad_segments = self.vad_engine.detect_segments(norm_path, job_id=job_id)

            # 3. Speaker Diarization
            update_progress(40, "DIARIZATION")
            try:
                diarization_segments = self.diarization_engine.diarize(
                    norm_path, vad_segments=vad_segments, job_id=job_id
                )
            except Exception as e:
                logger_context.warning(f"Diarization failed ({e}); falling back to single-speaker.")
                diarization_segments = []

            # 4. Hindi Speech Recognition (ASR)
            update_progress(60, "TRANSCRIPTION")
            asr_engine = get_asr_engine()
            raw_transcript = asr_engine.transcribe(
                norm_path,
                language=language,
                job_id=job_id
            )

            # 5. Speaker + Transcript Temporal Alignment
            update_progress(70, "ALIGNMENT")
            aligned_transcript, speaker_metrics = align_speakers_and_transcript(
                transcript_segments=raw_transcript,
                diarization_segments=diarization_segments,
                total_audio_duration=audio_metadata.duration_seconds
            )

            # 6. Emotion Analysis (Acoustic + Hindi Lexical)
            update_progress(78, "EMOTION_ANALYSIS")
            try:
                emotions = analyze_emotions(norm_path, aligned_transcript)
            except Exception as e:
                logger_context.warning(f"Emotion analysis failed ({e}).")
                emotions = []

            # 7. Intent Classification
            update_progress(82, "INTENT_ANALYSIS")
            try:
                intents = classify_intents(aligned_transcript)
            except Exception as e:
                logger_context.warning(f"Intent analysis failed ({e}).")
                intents = []

            # 8. Entity Extraction (Indic NER)
            update_progress(86, "ENTITY_EXTRACTION")
            try:
                entities = extract_entities(aligned_transcript)
            except Exception as e:
                logger_context.warning(f"Entity extraction failed ({e}).")
                entities = []

            # 9. Topic Extraction
            update_progress(90, "TOPIC_EXTRACTION")
            try:
                topics = extract_topics(aligned_transcript)
            except Exception as e:
                logger_context.warning(f"Topic extraction failed ({e}).")
                topics = []

            # 10. Claims & Contradictions Evidence Engine
            update_progress(93, "CLAIMS_AND_CONTRADICTIONS")
            try:
                claims, contradictions = extract_claims_and_contradictions(aligned_transcript)
            except Exception as e:
                logger_context.warning(f"Claims/contradiction extraction failed ({e}).")
                claims, contradictions = [], []

            # 11. LLM Reasoning Layer (Summary & Timeline)
            update_progress(96, "LLM_REASONING")
            try:
                summary, timeline = synthesize_conversation_reasoning(
                    transcript_segments=aligned_transcript,
                    speakers=speaker_metrics,
                    claims=claims,
                    topics=topics,
                    entities=entities,
                    emotions=emotions
                )
            except Exception as e:
                logger_context.warning(f"LLM reasoning failed ({e}).")
                summary = None
                timeline = []

            # Measure performance
            duration_sec = round(time.time() - start_time, 2)
            rtf = round(duration_sec / max(audio_metadata.duration_seconds, 0.01), 3)

            metadata = PipelineMetadata(
                processing_duration_sec=duration_sec,
                real_time_factor=rtf,
                asr_model=asr_engine.model_size,
                vad_model="silero_v6.2",
                diarization_engine=settings.DIARIZATION_ENGINE,
                llm_provider=settings.LLM_PROVIDER,
                device_used=settings.get_effective_device(),
                timestamp=datetime.now(timezone.utc).isoformat()
            )

            result = PipelineResult(
                job_id=job_id,
                status=JobStatusEnum.COMPLETED,
                audio_metadata=audio_metadata,
                vad_segments=vad_segments,
                speakers=speaker_metrics,
                transcript=aligned_transcript,
                emotions=emotions,
                intents=intents,
                entities=entities,
                topics=topics,
                claims=claims,
                contradictions=contradictions,
                timeline=timeline,
                summary=summary,
                metadata=metadata
            )

            # Persist result to database
            self.storage.save_job_result(
                job_id=job_id,
                result=result,
                normalized_audio_path=str(norm_path)
            )
            update_progress(100, "COMPLETED")
            logger_context.info(f"Pipeline completed in {duration_sec}s (RTF: {rtf}).")
            return result

        except Exception as e:
            err_msg = str(e)
            logger_context.error(f"Pipeline execution failed: {err_msg}", exc_info=True)
            self.storage.update_job_progress(
                job_id=job_id,
                status=JobStatusEnum.FAILED,
                error=err_msg
            )
            raise


def run_pipeline(job_id: str, audio_path: Path | str, language: str = "hi") -> PipelineResult:
    """Convenience function to execute pipeline."""
    pipeline = AudioIntelligencePipeline()
    return pipeline.process_job(job_id=job_id, audio_path=audio_path, language=language)
