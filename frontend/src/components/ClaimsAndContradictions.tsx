import React from 'react';
import { ShieldAlert, Clock } from 'lucide-react';
import { ClaimResult, ContradictionResult } from '../types';

interface Props {
  claims: ClaimResult[];
  contradictions: ContradictionResult[];
  onSeek: (time: number) => void;
}

export const ClaimsAndContradictions: React.FC<Props> = ({ claims, contradictions, onSeek }) => {
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Contradictions section */}
      {contradictions.length > 0 && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <ShieldAlert size={18} color="var(--danger)" />
            <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#991b1b' }}>
              Potential Contradictions Detected ({contradictions.length})
            </h4>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {contradictions.map((cntr) => (
              <div
                key={cntr.contradiction_id}
                style={{
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '8px',
                  padding: '0.85rem',
                  fontSize: '0.85rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                  <span style={{ fontWeight: 600, color: '#b91c1c' }}>{cntr.speaker}</span>
                  <span style={{ fontSize: '0.75rem', color: '#7f1d1d' }}>Inconsistency Flag</span>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <div
                    onClick={() => onSeek(cntr.earlier_timestamp)}
                    style={{ background: 'white', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid #fee2e2', cursor: 'pointer' }}
                  >
                    <span style={{ fontSize: '0.7rem', color: '#991b1b', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Clock size={12} /> Earlier ({formatTime(cntr.earlier_timestamp)})
                    </span>
                    <p style={{ marginTop: '2px', color: '#1e293b' }}>"{cntr.earlier_statement}"</p>
                  </div>

                  <div
                    onClick={() => onSeek(cntr.later_timestamp)}
                    style={{ background: 'white', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid #fee2e2', cursor: 'pointer' }}
                  >
                    <span style={{ fontSize: '0.7rem', color: '#991b1b', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Clock size={12} /> Later ({formatTime(cntr.later_timestamp)})
                    </span>
                    <p style={{ marginTop: '2px', color: '#1e293b' }}>"{cntr.later_statement}"</p>
                  </div>
                </div>

                <p style={{ color: '#450a0a', fontSize: '0.8rem', fontStyle: 'italic' }}>
                  {cntr.explanation}
                </p>
                <small style={{ color: '#991b1b', fontSize: '0.7rem', display: 'block', marginTop: '4px' }}>
                  {cntr.disclaimer}
                </small>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Substantive Claims */}
      <div>
        <h4 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.75rem' }}>
          Substantive Claims & Evidence ({claims.length})
        </h4>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {claims.map((c) => (
            <div
              key={c.claim_id}
              onClick={() => onSeek(c.source_start)}
              style={{
                padding: '0.75rem',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                background: 'white',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{c.speaker}</span>
                <span>{formatTime(c.source_start)} – {formatTime(c.source_end)}</span>
              </div>
              <p style={{ fontSize: '0.9rem', color: '#0f172a', marginBottom: '0.25rem' }}>
                {c.claim_text}
              </p>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                Evidence: "{c.evidence_quote}"
              </p>
            </div>
          ))}

          {claims.length === 0 && (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No substantive claims extracted.</p>
          )}
        </div>
      </div>
    </div>
  );
};
