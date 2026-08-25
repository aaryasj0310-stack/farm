# Development Environment Audit

**Date:** 2026-08-24  
**Project:** Hindi Audio Intelligence Pipeline  
**Auditor:** Principal Architecture Agent  

---

## 1. System Hardware & Operating System

| Component | Detected Specification | Evaluation / Constraints |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Home Single Language (64-bit) | Fully supported |
| **CPU Architecture** | x86_64 (AMD64) | Multi-core CPU available |
| **Total System RAM** | 8.0 GB (8,165,168 KB) | Moderate; models must be memory-efficient |
| **Free Physical RAM** | ~1.2 GB (dynamic paging active) | Model loading must use quantized/lazy caching |
| **GPU Model** | NVIDIA GeForce MX130 | Dedicated mobile GPU (Pascal architecture) |
| **GPU VRAM** | 2,048 MiB (2.0 GB) | Low VRAM; cannot host large 8B+ LLMs on GPU |
| **Storage (C: Drive)** | 6.79 GB Free | Keep system temp usage low |
| **Storage (D: Drive)** | 407.41 GB Free (`d:\website project\kaggri ox`) | Workspace and cache storage location |

---

## 2. Tooling & Runtimes

| Tool / Runtime | Detected Version | Status |
| :--- | :--- | :--- |
| **Python** | 3.12.10 (64-bit) | ✅ Installed & Verified |
| **Node.js** | v20.20.2 | ✅ Installed & Verified |
| **Git** | 2.52.0.windows.1 | ✅ Installed & Verified |
| **Docker** | Not available in PATH | ⚠️ Optional (CLI / Local execution mode) |
| **PyTorch** | 2.10.0+cpu | ✅ Verified CPU inference |
| **FFmpeg** | `imageio-ffmpeg` v7.1 bundled binary | ✅ Available via Python & binary path |
| **ONNX Runtime** | 1.29.0 | ✅ Installed & Verified |

---

## 3. Hardware Classification

**System Category:** **Category C / B (CPU Primary / Light Hardware Fallback)**

- **ASR & VAD:** Fast CPU inference using `faster-whisper` (`int8` quantization) and `silero-vad` (ONNX / Torch JIT).
- **GPU Acceleration:** Automatic detection (`MODEL_DEVICE=auto`) falls back gracefully to multi-threaded CPU without crashing on 2GB VRAM constraints.
- **LLM Reasoning:** Hybrid / Cloud-capable (OpenRouter, OpenAI-compatible, Ollama) with a high-fidelity local deterministic extractive reasoning engine when offline.

---

## 4. Cache & Storage Configuration

To avoid exhausting the 6.79 GB free space on drive `C:`, all model weights and audio pipeline scratch artifacts default to:
- Hugging Face Cache: `D:\website project\kaggri ox\.cache\huggingface`
- Torch Cache: `D:\website project\kaggri ox\.cache\torch`
- Job Storage: `D:\website project\kaggri ox\data\jobs`
