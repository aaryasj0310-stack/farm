import React, { useState } from 'react';
import { Search, Volume2 } from 'lucide-react';
import { CanonicalTranscriptSegment } from '../types';

interface Props {
  segments: CanonicalTranscriptSegment[];
  currentTime: number;
  onSeek: (timestamp: number) => void;
}

const SPEAKER_COLORS: Record<string, { bg: string; text: string }> = {
  SPEAKER_00: { bg: '#e0e7ff', text: '#3730a3' },
  SPEAKER_01: { bg: '#dcfce7', text: '#166534' },
  SPEAKER_02: { bg: '#fef3c7', text: '#92400e' },
  SPEAKER_03: { bg: '#fce7f3', text: '#9d174d' },
};

export const TranscriptView: React.FC<Props> = ({ segments, currentTime, onSeek }) => {
  const [search, setSearch] = useState('');

  const filtered = segments.filter((s) =>
    s.text.toLowerCase().includes(search.toLowerCase()) || s.speaker.toLowerCase().includes(search.toLowerCase())
  );

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="card" style={{ height: '620px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Speaker-Attributed Transcript</h3>
        <div style={{ position: 'relative', width: '220px' }}>
          <Search size={16} color="#94a3b8" style={{ position: 'absolute', left: '8px', top: '8px' }} />
          <input
            type="text"
            placeholder="Search Hindi or Speaker..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: '100%',
              padding: '0.35rem 0.5rem 0.35rem 2rem',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              fontSize: '0.8rem',
            }}
          />
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', paddingRight: '0.5rem' }}>
        {filtered.map((seg) => {
          const isActive = currentTime >= seg.start && currentTime <= seg.end;
          const speakerColor = SPEAKER_COLORS[seg.speaker] || { bg: '#f1f5f9', text: '#334155' };

          return (
            <div
              key={seg.id}
              className={`transcript-item ${isActive ? 'active' : ''}`}
              onClick={() => onSeek(seg.start)}
            >
              <div className="transcript-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span
                    style={{
                      background: speakerColor.bg,
                      color: speakerColor.text,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontWeight: 600,
                    }}
                  >
                    {seg.speaker}
                  </span>
                  <span>
                    {formatTime(seg.start)} – {formatTime(seg.end)}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {seg.confidence && (
                    <span style={{ fontSize: '0.7rem', color: '#64748b' }}>
                      {Math.round(seg.confidence * 100)}% conf
                    </span>
                  )}
                  <Volume2 size={14} color="#94a3b8" />
                </div>
              </div>

              <p className="transcript-text">{seg.text}</p>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '3rem 0', fontSize: '0.875rem' }}>
            No segments found matching your search.
          </div>
        )}
      </div>
    </div>
  );
};
