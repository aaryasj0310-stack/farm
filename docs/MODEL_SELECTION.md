# Model Selection & Compatibility Report

**Date:** 2026-08-24  
**Project:** Hindi Audio Intelligence Pipeline  
**Target Languages:** Hindi (`hi`), Hinglish (code-mixed Hindi/English)  

---

## 1. Pipeline Model Roster

| Pipeline Stage | Selected Primary Model | Fallback Model | Framework / Engine | License | RAM / VRAM Req |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VAD** | Silero VAD v6.2 (JIT/ONNX) | Energy-based silence detector | ONNX Runtime / PyTorch | MIT | ~50 MB RAM |
| **ASR** | faster-whisper `small` / `base` (int8) | faster-whisper `tiny` (int8) | CTranslate2 | MIT / Apache-2.0 | ~400 MB – 1.0 GB RAM |
| **Diarization** | Pyannote Audio 3.1 (when HF token set) | Feature-based Spectral/Agglomerative Clustering | Pyannote / Scikit-learn | MIT / Apache-2.0 | ~200 MB – 800 MB RAM |
| **Emotion Analysis** | Multi-modal Acoustic (Prosodic) + Hindi Lexical Model | Prosodic acoustic-only estimator | Librosa + Scikit-learn + Rules | MIT / Apache-2.0 | ~100 MB RAM |
| **Intent Analysis** | Configurable Hindi/Hinglish Semantic Intent Engine | Lexical grammar matcher | Python Regex + Scikit-learn + LLM | MIT / Apache-2.0 | ~50 MB RAM |
| **Entity Extraction** | Hybrid Devanagari/Hinglish Regex & Gazetteers + LLM | Indic Regex Entity Matcher | Rule Engine + LLM Adapter | MIT / Apache-2.0 | ~20 MB RAM |
| **Claims & Contradictions** | Semantic Evidence Alignment Engine | Polarity & Numerical Conflict Matrix | Python Engine + LLM | MIT / Apache-2.0 | ~20 MB RAM |
| **LLM Reasoning** | OpenRouter / OpenAI-compatible endpoint | Deterministic Extractive Offline Reasoner | HTTP / Local Engine | MIT / Apache-2.0 | ~10 MB RAM |

---

## 2. Detailed Stage Evaluations

### 2.1. ASR (Speech-to-Text)
- **Candidate 1: faster-whisper (`small` / `medium`) [SELECTED]**
  - *Repository:* `Systran/faster-whisper` & `openai/whisper-small`
  - *License:* MIT
  - *Rationale:* CTranslate2 engine provides up to 4x faster CPU inference with `int8` quantization compared to vanilla PyTorch. Demonstrates high Devanagari Hindi transcription accuracy, handles Hinglish code-switching, and reliably produces word/segment timestamps.
  - *Language Support:* Hindi (`hi`), English, 90+ languages.
  - *Limitations:* Code-mixed Hinglish with rare slang may occasionally transcribe phonetically in Devanagari script.

### 2.2. Voice Activity Detection (VAD)
- **Candidate 1: Silero VAD v6.2 [SELECTED]**
  - *Repository:* `snakers4/silero-vad`
  - *License:* MIT
  - *Rationale:* Ultra-fast (<1ms per chunk), high precision on noisy Indian speech and telephony audio, runs locally in ONNX without requiring GPU.
  - *Limitations:* Needs 16kHz mono audio (handled by our audio preprocessing pipeline).

### 2.3. Speaker Diarization
- **Candidate 1: pyannote.audio (with HF token)**
  - *Repository:* `pyannote/pyannote-audio`
  - *License:* MIT (Model gated under HF terms)
  - *Rationale:* State of the art speaker clustering.
- **Candidate 2: Autonomous Local Spectral/Agglomerative Clustering Diarizer [DEFAULT LOCAL FALLBACK]**
  - *Repository:* Built-in (`sklearn.cluster.AgglomerativeClustering` on MFCC/Chroma/Spectral embeddings)
  - *License:* BSD-3-Clause
  - *Rationale:* 100% offline, zero HF token required, fast execution on CPU, segments conversation cleanly into `SPEAKER_00`, `SPEAKER_01`, etc.

### 2.4. Emotion Analysis
- **Selected: Dual-stream Acoustic + Hindi/Hinglish Linguistic Classifier**
  - *Acoustic:* F0 (pitch contour/variance), RMS energy dynamics, speech rate, spectral tilt and jitter.
  - *Linguistic:* Devanagari emotional vocabulary, sentiment markers, and Hinglish exclamation patterns.
  - *Output:* Calibrated confidence score, explicit uncertainty indicator, and non-accusatory terminology ("Model-estimated emotional characteristics").

---

## 3. Graceful Fallback Strategy
If any stage encounters missing dependencies or low system resources:
1. **ASR:** Automatically drops from `medium` -> `small` -> `base` -> `tiny` depending on memory.
2. **Diarization:** Falls back to spectral clustering or single-speaker fallback without halting transcription.
3. **Emotion / Intent / NER:** Pure deterministic rule-based analysis if optional models are missing.
4. **LLM:** Falls back to deterministic timeline extraction, claim mapping, and extractive summary if no API key is provided or network is down.
