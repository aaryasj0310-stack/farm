import { JobStatusResponse, PipelineResult } from '../types';

const API_BASE = '/api';

export async function uploadAudio(file: File): Promise<{ job_id: string; original_filename: string; status: string }> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/audio/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(errorData.detail || `Upload failed with status ${res.status}`);
  }

  return res.json();
}

export async function startAnalysis(jobId: string, language: string = 'hi'): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/audio/${jobId}/analyze?language=${encodeURIComponent(language)}`, {
    method: 'POST',
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Failed to start analysis' }));
    throw new Error(errorData.detail || `Analysis trigger failed with status ${res.status}`);
  }

  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE}/audio/${jobId}/status`);
  if (!res.ok) {
    throw new Error(`Failed to fetch status for job ${jobId}`);
  }
  return res.json();
}

export async function getFullReport(jobId: string): Promise<PipelineResult> {
  const res = await fetch(`${API_BASE}/audio/${jobId}/report`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Report not ready' }));
    throw new Error(errorData.detail || `Failed to fetch report`);
  }
  return res.json();
}

export function getAudioStreamUrl(jobId: string): string {
  return `${API_BASE}/audio/${jobId}/stream`;
}

export function getExportUrl(jobId: string, format: string): string {
  return `${API_BASE}/audio/${jobId}/export?format=${format}`;
}
