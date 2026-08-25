import React from 'react';
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { JobStatusResponse } from '../types';

interface Props {
  status: JobStatusResponse;
}

const STAGES = [
  { id: 'PREPROCESSING', label: 'Audio Ingestion & Normalization' },
  { id: 'VAD', label: 'Voice Activity Detection' },
  { id: 'DIARIZATION', label: 'Speaker Diarization' },
  { id: 'TRANSCRIPTION', label: 'Hindi Speech Recognition (ASR)' },
  { id: 'ALIGNMENT', label: 'Speaker-Transcript Alignment' },
  { id: 'EMOTION_ANALYSIS', label: 'Emotion Analysis' },
  { id: 'INTENT_ANALYSIS', label: 'Intent & Entity Extraction' },
  { id: 'CLAIMS_AND_CONTRADICTIONS', label: 'Claims & Contradictions' },
  { id: 'LLM_REASONING', label: 'LLM Reasoning & Summary' },
];

export const ProgressTracker: React.FC<Props> = ({ status }) => {
  const currentIdx = STAGES.findIndex((s) => s.id === status.current_stage);

  return (
    <div className="card" style={{ maxWidth: '640px', margin: '3rem auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Loader2 className="spin" size={24} color="var(--primary)" />
          <h2 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Analyzing Audio...</h2>
        </div>
        <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--primary)' }}>
          {status.progress_percentage}%
        </span>
      </div>

      {/* Progress Bar */}
      <div style={{ width: '100%', height: '8px', background: '#e2e8f0', borderRadius: '4px', overflow: 'hidden', marginBottom: '1.5rem' }}>
        <div
          style={{
            width: `${status.progress_percentage}%`,
            height: '100%',
            background: 'var(--primary)',
            transition: 'width 0.4s ease',
          }}
        />
      </div>

      {/* Steps checklist */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {STAGES.map((stage, idx) => {
          const isDone = currentIdx > idx || status.status === 'COMPLETED';
          const isCurrent = currentIdx === idx && status.status === 'PROCESSING';

          return (
            <div
              key={stage.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                fontSize: '0.875rem',
                color: isDone ? '#0f172a' : isCurrent ? 'var(--primary)' : '#94a3b8',
                fontWeight: isCurrent ? 600 : 400,
              }}
            >
              {isDone ? (
                <CheckCircle2 size={18} color="var(--success)" />
              ) : isCurrent ? (
                <Loader2 className="spin" size={18} color="var(--primary)" />
              ) : (
                <div style={{ width: '18px', height: '18px', borderRadius: '50%', border: '2px solid #cbd5e1' }} />
              )}
              <span>{stage.label}</span>
            </div>
          );
        })}
      </div>

      {status.error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#fee2e2', color: '#991b1b', padding: '0.75rem', borderRadius: '8px', marginTop: '1.25rem', fontSize: '0.85rem' }}>
          <AlertCircle size={18} />
          <span>Error: {status.error}</span>
        </div>
      )}
    </div>
  );
};
