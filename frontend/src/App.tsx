import React, { useState, useEffect } from 'react';
import { Mic, RefreshCw } from 'lucide-react';
import { getJobStatus, getFullReport } from './api/client';
import { JobStatusResponse, PipelineResult } from './types';
import { UploadModal } from './components/UploadModal';
import { ProgressTracker } from './components/ProgressTracker';
import { AudioPlayer } from './components/AudioPlayer';
import { TranscriptView } from './components/TranscriptView';
import { SpeakerMetricsView } from './components/SpeakerMetricsView';
import { IntelligenceTabs } from './components/IntelligenceTabs';
import { ExportMenu } from './components/ExportMenu';

export const App: React.FC = () => {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [seekTime, setSeekTime] = useState<number | null>(null);

  // Polling loop for active job
  useEffect(() => {
    if (!activeJobId) return;

    let isMounted = true;
    const poll = async () => {
      try {
        const status = await getJobStatus(activeJobId);
        if (!isMounted) return;
        setJobStatus(status);

        if (status.status === 'COMPLETED') {
          const report = await getFullReport(activeJobId);
          if (isMounted) {
            setPipelineResult(report);
          }
        }
      } catch (err) {
        console.error('Error polling status:', err);
      }
    };

    poll();
    const interval = setInterval(() => {
      if (jobStatus?.status !== 'COMPLETED' && jobStatus?.status !== 'FAILED') {
        poll();
      }
    }, 1500);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [activeJobId, jobStatus?.status]);

  const handleSeek = (time: number) => {
    setCurrentTime(time);
    setSeekTime(time);
  };

  const handleReset = () => {
    setActiveJobId(null);
    setJobStatus(null);
    setPipelineResult(null);
    setCurrentTime(0);
    setSeekTime(null);
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <header className="header">
        <div className="header-title">
          <Mic size={28} color="var(--primary)" />
          <div>
            <h1>Hindi Audio Intelligence Pipeline</h1>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Speech-to-Text • Diarization • Emotions • Entities • Claims • Timeline
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {activeJobId && (
            <button className="btn btn-outline" onClick={handleReset}>
              <RefreshCw size={16} />
              <span>New Audio</span>
            </button>
          )}
          {pipelineResult && activeJobId && (
            <ExportMenu jobId={activeJobId} />
          )}
        </div>
      </header>

      {/* Main Content Area */}
      <main>
        {!activeJobId && (
          <UploadModal onUploadComplete={(jobId) => setActiveJobId(jobId)} />
        )}

        {activeJobId && jobStatus && jobStatus.status !== 'COMPLETED' && (
          <ProgressTracker status={jobStatus} />
        )}

        {activeJobId && pipelineResult && (
          <div>
            {/* Audio Playback Bar */}
            <AudioPlayer
              jobId={activeJobId}
              currentTime={currentTime}
              onTimeUpdate={setCurrentTime}
              seekTime={seekTime}
            />

            {/* Speaker Metrics Bar */}
            {pipelineResult.speakers && pipelineResult.speakers.length > 0 && (
              <SpeakerMetricsView speakers={pipelineResult.speakers} />
            )}

            {/* Side-by-side Transcript & Intelligence Hub */}
            <div className="grid-main">
              <TranscriptView
                segments={pipelineResult.transcript}
                currentTime={currentTime}
                onSeek={handleSeek}
              />

              <IntelligenceTabs
                result={pipelineResult}
                onSeek={handleSeek}
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
