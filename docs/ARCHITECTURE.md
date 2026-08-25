# Architecture & System Design

**Project:** Hindi Audio Intelligence Pipeline  
**Version:** 1.0.0  

---

## 1. High-Level Architecture Overview

```
                          ┌──────────────────────┐
                          │   Audio Input (WAV,  │
                          │ MP3, M4A, FLAC, etc) │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ Audio Preprocessing  │
                          │   (16kHz Mono PCM)   │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         ┌─────────────────────┐           ┌─────────────────────┐
         │ Voice Activity Det. │           │ Speaker Diarization │
         │    (Silero VAD)     │           │ (Pyannote / Spectral│
         └──────────┬──────────┘           │     Clustering)     │
                    │                      └──────────┬──────────┘
                    ▼                                 │
         ┌─────────────────────┐                      │
         │   Hindi/Hinglish    │                      │
         │      ASR Engine     │                      │
         │  (faster-whisper)   │                      │
         └──────────┬──────────┘                      │
                    │                                 │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ Speaker & Transcript │
                          │  Temporal Alignment  │
                          └──────────┬───────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  Emotion Analysis   │   │   Intent & Entity   │   │ Claim & Contradict. │
│(Acoustic + Lexical) │   │ Extraction (Indic)  │   │   Evidence Engine   │
└──────────┬──────────┘   └──────────┬──────────┘   └──────────┬──────────┘
           │                         │                         │
           └─────────────────────────┼─────────────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ LLM Reasoning Layer  │
                          │ (Hybrid / Local Det) │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ Canonical JSON Report│
                          │ (Export: JSON/PDF/MD)│
                          └──────────────────────┘
```

---

## 2. Component Breakdown

### 2.1. Backend Directory Structure
```
app/
├── api/                  # FastAPI routers, schemas, dependencies
│   ├── routes.py         # Audio upload, status, transcript, analysis, export endpoints
│   └── websocket.py      # Real-time progress updates
├── audio/                # Ingestion, validation, ffmpeg wrapper, normalization
│   └── preprocess.py
├── vad/                  # Voice Activity Detection (Silero VAD)
│   └── silero_engine.py
├── diarization/          # Speaker diarization & clustering
│   ├── pyannote_engine.py
│   └── spectral_engine.py
├── asr/                  # Hindi / Hinglish speech recognition
│   └── whisper_engine.py
├── alignment/            # Speaker & transcript boundary alignment
│   └── aligner.py
├── analysis/             # Intelligence extraction modules
│   ├── emotion.py        # Prosodic & lexical emotion classification
│   ├── intent.py         # Intent taxonomy classifier
│   ├── entities.py       # Indic & Devanagari named entity recognizer
│   ├── topics.py         # Topic extractor
│   └── claims.py         # Claims & contradiction detector
├── llm/                  # LLM reasoning & provider abstraction
│   ├── provider.py       # OpenAI, OpenRouter, Ollama, and Local Fallback
│   └── prompts.py
├── pipeline/             # Orchestrator & job worker
│   ├── orchestrator.py
│   └── worker.py
├── storage/              # SQLite / JSON job metadata & audio storage
│   └── db.py
├── reporting/            # Exporters (JSON, TXT, Markdown, HTML, PDF)
│   └── export.py
├── config/               # Settings & environment variables
│   └── settings.py
└── utils/                # Logging, security sanitizers, audio helpers
    ├── logger.py
    └── security.py
```

### 2.2. Frontend Architecture (React + Vite + TypeScript)
- Single-page application with modular panels:
  1. **Upload Component:** Drag-and-drop audio, immediate metadata extraction, validation feedback.
  2. **Pipeline Progress Bar:** Live stage tracking (Preprocessing → VAD → Diarization → ASR → Analysis → LLM).
  3. **Synchronized Audio Player:** Interactive waveform / playback scrubber that highlights active words and speakers.
  4. **Transcript Inspector:** Devanagari text, speaker tags, timestamps, confidence pills. Clicking seeks audio.
  5. **Speaker Metrics Dashboard:** Speaking time, conversation percentage, speaker segment distribution.
  6. **Intelligence Hub:** Tabbed views for Emotions, Intents, Entities, Topics, Claims, and Contradictions.
  7. **Export Dialog:** Instant download in JSON, Markdown, Text, HTML, or PDF.

---

## 3. Data Flow & Provenance
Every claim, entity, and contradiction is linked via **Timestamp & Segment ID Provenance**:
```json
{
  "claim_id": "clm_01",
  "speaker": "SPEAKER_00",
  "claim_text": "वक्ता ने राहुल को ₹50,000 देने का दावा किया।",
  "source_segment_ids": ["seg_004"],
  "source_start": 14.2,
  "source_end": 17.8,
  "confidence": 0.92,
  "evidence_quote": "मैंने राहुल को ₹50,000 दिए थे।"
}
```
This guarantees complete auditability from final report back to the raw audio millisecond.
