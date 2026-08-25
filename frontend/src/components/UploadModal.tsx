import React, { useState } from 'react';
import { UploadCloud, FileAudio, AlertCircle } from 'lucide-react';
import { uploadAudio, startAnalysis } from '../api/client';

interface Props {
  onUploadComplete: (jobId: string) => void;
}

export const UploadModal: React.FC<Props> = ({ onUploadComplete }) => {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState<string>('hi');
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
      setError(null);
    }
  };

  const handleUploadAndAnalyze = async () => {
    if (!file) {
      setError('Please select an audio file to analyze.');
      return;
    }

    try {
      setIsUploading(true);
      setError(null);

      // 1. Upload audio
      const uploadRes = await uploadAudio(file);

      // 2. Start analysis pipeline
      await startAnalysis(uploadRes.job_id, language);

      onUploadComplete(uploadRes.job_id);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="card" style={{ maxWidth: '640px', margin: '3rem auto', textAlign: 'center' }}>
      <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>
        Analyze Hindi / Hinglish Audio
      </h2>
      <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
        Upload a recording (MP3, WAV, M4A, FLAC, OGG, AAC) to run diarization, Hindi ASR, emotions, claims, and timeline.
      </p>

      {error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#fee2e2', color: '#991b1b', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem', fontSize: '0.85rem', textAlign: 'left' }}>
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        style={{
          border: '2px dashed #cbd5e1',
          borderRadius: '12px',
          padding: '2.5rem 1.5rem',
          background: '#f8fafc',
          cursor: 'pointer',
          marginBottom: '1.25rem',
        }}
        onClick={() => document.getElementById('file-upload-input')?.click()}
      >
        <input
          id="file-upload-input"
          type="file"
          accept="audio/*,.mp3,.wav,.m4a,.flac,.aac,.ogg"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />

        {file ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
            <FileAudio size={40} color="var(--primary)" />
            <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{file.name}</span>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              {(file.size / (1024 * 1024)).toFixed(2)} MB
            </span>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.75rem' }}>
            <UploadCloud size={44} color="#94a3b8" />
            <div>
              <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Click to browse</span> or drag and drop audio
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
              Supports MP3, WAV, M4A, FLAC, AAC up to 100MB
            </span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem' }}>
          <label htmlFor="lang-select" style={{ fontWeight: 500, color: 'var(--text-muted)' }}>Language:</label>
          <select
            id="lang-select"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            style={{ padding: '0.35rem 0.6rem', borderRadius: '6px', border: '1px solid var(--border)', background: 'white' }}
          >
            <option value="hi">Hindi (देवनागरी)</option>
            <option value="auto">Auto-detect (Hinglish/Mixed)</option>
          </select>
        </div>

        <button
          className="btn btn-primary"
          onClick={handleUploadAndAnalyze}
          disabled={!file || isUploading}
          style={{ minWidth: '140px', justifyContent: 'center' }}
        >
          {isUploading ? 'Starting...' : 'Analyze Audio'}
        </button>
      </div>
    </div>
  );
};
