import React, { useState } from 'react';
import { PipelineResult } from '../types';
import { ClaimsAndContradictions } from './ClaimsAndContradictions';

interface Props {
  result: PipelineResult;
  onSeek: (time: number) => void;
}

export const IntelligenceTabs: React.FC<Props> = ({ result, onSeek }) => {
  const [activeTab, setActiveTab] = useState<'summary' | 'claims' | 'emotions' | 'entities' | 'topics'>('summary');

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="card" style={{ height: '620px', display: 'flex', flexDirection: 'column' }}>
      <div className="tabs-nav">
        <button
          className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => setActiveTab('summary')}
        >
          Executive Summary
        </button>
        <button
          className={`tab-btn ${activeTab === 'claims' ? 'active' : ''}`}
          onClick={() => setActiveTab('claims')}
        >
          Claims & Contradictions ({result.claims.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'emotions' ? 'active' : ''}`}
          onClick={() => setActiveTab('emotions')}
        >
          Emotions & Intents
        </button>
        <button
          className={`tab-btn ${activeTab === 'entities' ? 'active' : ''}`}
          onClick={() => setActiveTab('entities')}
        >
          Entities ({result.entities.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'topics' ? 'active' : ''}`}
          onClick={() => setActiveTab('topics')}
        >
          Topics ({result.topics.length})
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', paddingRight: '0.5rem' }}>
        {/* SUMMARY TAB */}
        {activeTab === 'summary' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', borderLeft: '4px solid var(--primary)' }}>
              <h4 style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.35rem' }}>
                High-Level Overview
              </h4>
              <p style={{ fontSize: '0.95rem', color: '#0f172a', lineHeight: 1.6 }}>
                {result.summary?.high_level_summary || 'Analysis complete.'}
              </p>
            </div>

            {result.summary?.detailed_summary && (
              <div>
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.35rem' }}>Detailed Synthesis</h4>
                <p style={{ fontSize: '0.875rem', color: '#334155', lineHeight: 1.6 }}>
                  {result.summary.detailed_summary}
                </p>
              </div>
            )}

            {result.summary?.key_takeaways && result.summary.key_takeaways.length > 0 && (
              <div>
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Key Takeaways</h4>
                <ul style={{ paddingLeft: '1.2rem', fontSize: '0.85rem', color: '#334155', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                  {result.summary.key_takeaways.map((t, idx) => (
                    <li key={idx}>{t}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Timeline */}
            {result.timeline.length > 0 && (
              <div>
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Conversation Timeline</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {result.timeline.map((ev, idx) => (
                    <div
                      key={idx}
                      onClick={() => onSeek(ev.timestamp)}
                      style={{
                        display: 'flex',
                        gap: '0.75rem',
                        padding: '0.5rem',
                        background: '#ffffff',
                        border: '1px solid var(--border)',
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        cursor: 'pointer',
                      }}
                    >
                      <span style={{ color: 'var(--primary)', fontWeight: 600, minWidth: '45px' }}>
                        {formatTime(ev.timestamp)}
                      </span>
                      <span style={{ fontWeight: 600, color: '#475569', minWidth: '80px' }}>
                        {ev.speaker}
                      </span>
                      <span style={{ color: '#1e293b' }}>{ev.event_description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* CLAIMS & CONTRADICTIONS TAB */}
        {activeTab === 'claims' && (
          <ClaimsAndContradictions
            claims={result.claims}
            contradictions={result.contradictions}
            onSeek={onSeek}
          />
        )}

        {/* EMOTIONS & INTENTS TAB */}
        {activeTab === 'emotions' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
              Model-estimated emotional characteristics and intent indicators per turn.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {result.transcript.map((seg, idx) => {
                const em = result.emotions[idx];
                const intent = result.intents[idx];

                return (
                  <div
                    key={seg.id}
                    onClick={() => onSeek(seg.start)}
                    style={{
                      padding: '0.75rem',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                      background: 'white',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--primary)' }}>
                        {seg.speaker} ({formatTime(seg.start)})
                      </span>
                      <div style={{ display: 'flex', gap: '0.35rem' }}>
                        {intent && (
                          <span className="badge badge-primary">
                            Intent: {intent.intent}
                          </span>
                        )}
                        {em && (
                          <span className="badge badge-warning">
                            {em.emotion} ({Math.round((em.confidence || 0.7) * 100)}%)
                          </span>
                        )}
                      </div>
                    </div>
                    <p style={{ fontSize: '0.85rem', color: '#1e293b' }}>"{seg.text}"</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ENTITIES TAB */}
        {activeTab === 'entities' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '0.75rem' }}>
              {result.entities.map((ent, idx) => (
                <div
                  key={idx}
                  onClick={() => onSeek(ent.timestamp)}
                  style={{
                    padding: '0.6rem 0.75rem',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: 'white',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--primary)', fontWeight: 700 }}>
                    {ent.type}
                  </span>
                  <p style={{ fontWeight: 600, fontSize: '0.9rem', color: '#0f172a', margin: '2px 0' }}>
                    {ent.text}
                  </p>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {ent.speaker} • {formatTime(ent.timestamp)}
                  </span>
                </div>
              ))}
            </div>

            {result.entities.length === 0 && (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: '2rem 0' }}>
                No named entities detected.
              </p>
            )}
          </div>
        )}

        {/* TOPICS TAB */}
        {activeTab === 'topics' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {result.topics.map((t, idx) => (
              <div
                key={idx}
                style={{
                  padding: '0.85rem',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'white',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--primary)' }}>{t.topic_name}</h4>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Relevance: {Math.round(t.relevance_score * 100)}%
                  </span>
                </div>
                <p style={{ fontSize: '0.8rem', color: '#334155', marginBottom: '0.5rem' }}>{t.summary}</p>
                <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                  {t.timestamps.map((ts, tIdx) => (
                    <button
                      key={tIdx}
                      onClick={() => onSeek(ts)}
                      style={{
                        padding: '2px 6px',
                        background: '#f1f5f9',
                        border: '1px solid #cbd5e1',
                        borderRadius: '4px',
                        fontSize: '0.7rem',
                        cursor: 'pointer',
                      }}
                    >
                      {formatTime(ts)}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
