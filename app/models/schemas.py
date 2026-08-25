"""Canonical Pydantic data schemas for the Hindi Audio Intelligence Pipeline."""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class JobStatusEnum(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AudioMetadata(BaseModel):
    """Normalized audio technical properties."""
    duration_seconds: float
    sample_rate: int
    channels: int
    codec: str
    bitrate: Optional[int] = None
    file_size_bytes: int
    rms_volume_db: Optional[float] = None
    is_clipping: bool = False
    original_filename: str


class VADSegment(BaseModel):
    """Voice Activity Detection speech interval."""
    id: str
    start: float
    end: float
    duration: float
    confidence: Optional[float] = None


class DiarizationSegment(BaseModel):
    """Speaker turn interval."""
    speaker: str
    start: float
    end: float
    duration: float


class SpeakerMetrics(BaseModel):
    """Aggregated metrics per speaker."""
    speaker_id: str
    total_speech_time: float
    percentage_of_conversation: float
    segment_count: int


class WordTimestamp(BaseModel):
    """Word-level alignment timestamp."""
    word: str
    start: float
    end: float
    confidence: Optional[float] = None


class CanonicalTranscriptSegment(BaseModel):
    """Canonical speaker-attributed transcript segment in spoken Hindi/Hinglish."""
    id: str
    speaker: str
    start: float
    end: float
    text: str
    confidence: Optional[float] = None
    words: List[WordTimestamp] = Field(default_factory=list)
    uncertainty: str = "LOW"  # LOW, MEDIUM, HIGH


class EmotionResult(BaseModel):
    """Model-estimated emotional characteristics per utterance."""
    speaker: str
    start: float
    end: float
    segment_id: str
    emotion: str  # neutral, happy, sad, angry, fear, surprise, disgust, frustration, excitement, uncertainty
    confidence: Optional[float] = None
    acoustic_arousal: Optional[float] = None
    acoustic_valence: Optional[float] = None
    uncertainty_level: str = "MEDIUM"
    note: str = "Model-estimated emotional characteristics"


class IntentResult(BaseModel):
    """Utterance intent classification."""
    speaker: str
    start: float
    end: float
    segment_id: str
    intent: str
    confidence: Optional[float] = None
    utterance_snippet: str


class EntityResult(BaseModel):
    """Extracted named entity with temporal provenance."""
    text: str
    normalized_value: Optional[str] = None
    type: str  # PERSON, LOCATION, ORGANIZATION, DATE, TIME, MONEY, PHONE, EMAIL, VEHICLE, PRODUCT, ADDRESS
    speaker: str
    timestamp: float
    segment_id: str


class TopicResult(BaseModel):
    """Major conversation topic."""
    topic_name: str
    relevance_score: float
    timestamps: List[float] = Field(default_factory=list)
    summary: str


class ClaimResult(BaseModel):
    """Substantive speaker claim traceable to audio timestamps."""
    claim_id: str
    speaker: str
    claim_text: str
    source_segment_ids: List[str]
    source_start: float
    source_end: float
    confidence: Optional[float] = None
    evidence_quote: str


class ContradictionResult(BaseModel):
    """Potential statement contradiction across speaker turns."""
    contradiction_id: str
    speaker: str
    earlier_statement: str
    earlier_timestamp: float
    earlier_segment_id: str
    later_statement: str
    later_timestamp: float
    later_segment_id: str
    explanation: str
    confidence: Optional[float] = None
    uncertainty: str = "MEDIUM"
    disclaimer: str = "Potential inconsistency detected; does not imply deliberate deception."


class TimelineEvent(BaseModel):
    """Chronological event milestone."""
    timestamp: float
    speaker: str
    event_description: str
    category: str


class AnalysisSummary(BaseModel):
    """Comprehensive conversation summary."""
    high_level_summary: str
    detailed_summary: str
    key_takeaways: List[str] = Field(default_factory=list)
    speaker_summaries: Dict[str, str] = Field(default_factory=dict)
    important_questions: List[str] = Field(default_factory=list)
    unresolved_issues: List[str] = Field(default_factory=list)


class PipelineMetadata(BaseModel):
    """Pipeline execution metadata."""
    processing_duration_sec: float
    real_time_factor: float
    asr_model: str
    vad_model: str
    diarization_engine: str
    llm_provider: str
    device_used: str
    timestamp: str


class PipelineResult(BaseModel):
    """Canonical complete pipeline result schema."""
    job_id: str
    status: JobStatusEnum
    audio_metadata: Optional[AudioMetadata] = None
    vad_segments: List[VADSegment] = Field(default_factory=list)
    speakers: List[SpeakerMetrics] = Field(default_factory=list)
    transcript: List[CanonicalTranscriptSegment] = Field(default_factory=list)
    emotions: List[EmotionResult] = Field(default_factory=list)
    intents: List[IntentResult] = Field(default_factory=list)
    entities: List[EntityResult] = Field(default_factory=list)
    topics: List[TopicResult] = Field(default_factory=list)
    claims: List[ClaimResult] = Field(default_factory=list)
    contradictions: List[ContradictionResult] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    summary: Optional[AnalysisSummary] = None
    metadata: Optional[PipelineMetadata] = None
    error_message: Optional[str] = None


class JobRecord(BaseModel):
    """Job record in storage database."""
    job_id: str
    original_filename: str
    status: JobStatusEnum
    progress_percentage: int = 0
    current_stage: str = "QUEUED"
    audio_path: str
    normalized_audio_path: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[PipelineResult] = None
