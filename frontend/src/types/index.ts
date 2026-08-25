export interface AudioMetadata {
  duration_seconds: number;
  sample_rate: number;
  channels: number;
  codec: string;
  bitrate?: number;
  file_size_bytes: number;
  rms_volume_db?: number;
  is_clipping: boolean;
  original_filename: string;
}

export interface WordTimestamp {
  word: string;
  start: number;
  end: number;
  confidence?: number;
}

export interface CanonicalTranscriptSegment {
  id: string;
  speaker: string;
  start: number;
  end: number;
  text: string;
  confidence?: number;
  words?: WordTimestamp[];
  uncertainty?: string;
}

export interface SpeakerMetrics {
  speaker_id: string;
  total_speech_time: number;
  percentage_of_conversation: number;
  segment_count: number;
}

export interface EmotionResult {
  speaker: string;
  start: number;
  end: number;
  segment_id: string;
  emotion: string;
  confidence?: number;
  acoustic_arousal?: number;
  acoustic_valence?: number;
  uncertainty_level: string;
  note: string;
}

export interface IntentResult {
  speaker: string;
  start: number;
  end: number;
  segment_id: string;
  intent: string;
  confidence?: number;
  utterance_snippet: string;
}

export interface EntityResult {
  text: string;
  normalized_value?: string;
  type: string;
  speaker: string;
  timestamp: number;
  segment_id: string;
}

export interface TopicResult {
  topic_name: string;
  relevance_score: number;
  timestamps: number[];
  summary: string;
}

export interface ClaimResult {
  claim_id: string;
  speaker: string;
  claim_text: string;
  source_segment_ids: string[];
  source_start: number;
  source_end: number;
  confidence?: number;
  evidence_quote: string;
}

export interface ContradictionResult {
  contradiction_id: string;
  speaker: string;
  earlier_statement: string;
  earlier_timestamp: number;
  earlier_segment_id: string;
  later_statement: string;
  later_timestamp: number;
  later_segment_id: string;
  explanation: string;
  confidence?: number;
  uncertainty: string;
  disclaimer: string;
}

export interface TimelineEvent {
  timestamp: number;
  speaker: string;
  event_description: string;
  category: string;
}

export interface AnalysisSummary {
  high_level_summary: string;
  detailed_summary: string;
  key_takeaways: string[];
  speaker_summaries: Record<string, string>;
  important_questions: string[];
  unresolved_issues: string[];
}

export interface PipelineMetadata {
  processing_duration_sec: number;
  real_time_factor: number;
  asr_model: string;
  vad_model: string;
  diarization_engine: string;
  llm_provider: string;
  device_used: string;
  timestamp: string;
}

export interface PipelineResult {
  job_id: string;
  status: string;
  audio_metadata?: AudioMetadata;
  speakers: SpeakerMetrics[];
  transcript: CanonicalTranscriptSegment[];
  emotions: EmotionResult[];
  intents: IntentResult[];
  entities: EntityResult[];
  topics: TopicResult[];
  claims: ClaimResult[];
  contradictions: ContradictionResult[];
  timeline: TimelineEvent[];
  summary?: AnalysisSummary;
  metadata?: PipelineMetadata;
  error_message?: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  progress_percentage: number;
  current_stage: string;
  error?: string;
  completed_at?: string;
}
