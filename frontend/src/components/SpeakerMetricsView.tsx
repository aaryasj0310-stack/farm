import React from 'react';
import { Users } from 'lucide-react';
import { SpeakerMetrics } from '../types';

interface Props {
  speakers: SpeakerMetrics[];
}

export const SpeakerMetricsView: React.FC<Props> = ({ speakers }) => {
  return (
    <div className="card" style={{ marginBottom: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <Users size={18} color="var(--primary)" />
        <h3 style={{ fontSize: '0.95rem', fontWeight: 600 }}>Speaker Participation</h3>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {speakers.map((spk) => (
          <div key={spk.speaker_id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <span style={{ fontWeight: 600 }}>{spk.speaker_id}</span>
              <span style={{ color: 'var(--text-muted)' }}>
                {spk.total_speech_time}s ({spk.percentage_of_conversation}%) • {spk.segment_count} turns
              </span>
            </div>

            <div style={{ width: '100%', height: '6px', background: '#f1f5f9', borderRadius: '3px', overflow: 'hidden' }}>
              <div
                style={{
                  width: `${spk.percentage_of_conversation}%`,
                  height: '100%',
                  background: 'var(--primary)',
                  borderRadius: '3px',
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
