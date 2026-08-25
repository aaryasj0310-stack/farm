# Third-Party Licenses

This project incorporates the following open-source dependencies and models. All components comply with permissive open-source licensing.

| Dependency / Component | Version | License | Source / Repository | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | 3.12 | PSF License | python.org | Backend execution environment |
| **FastAPI** | 0.131.0 | MIT | github.com/fastapi/fastapi | REST API framework |
| **Uvicorn** | 0.41.0 | BSD-3-Clause | github.com/encode/uvicorn | ASGI web server |
| **Pydantic** | 2.12.5 | MIT | github.com/pydantic/pydantic | Schema validation & data modeling |
| **faster-whisper** | 1.2.1 | MIT | github.com/SYSTRAN/faster-whisper | Fast local ASR engine |
| **ctranslate2** | 4.8.1 | MIT | github.com/OpenNMT/CTranslate2 | Optimized transformer runtime |
| **Silero VAD** | 6.2.1 | MIT | github.com/snakers4/silero-vad | Voice Activity Detection |
| **PyTorch** | 2.10.0 | BSD-3-Clause | pytorch.org | Machine learning framework |
| **torchaudio** | 2.11.0 | BSD-3-Clause | github.com/pytorch/audio | Audio tensor utilities |
| **SoundFile** | 0.14.0 | BSD-3-Clause | github.com/bastibe/python-soundfile | Audio I/O |
| **imageio-ffmpeg** | 0.6.0 | BSD-2-Clause / LGPL | github.com/imageio/imageio-ffmpeg | Bundled FFmpeg static binaries |
| **pydub** | 0.25.1 | MIT | github.com/jiaaro/pydub | Audio manipulation & conversion |
| **librosa** | 1.0.0 | ISC | github.com/librosa/librosa | Acoustic feature extraction |
| **scikit-learn** | 1.8.0 | BSD-3-Clause | github.com/scikit-learn/scikit-learn | Acoustic clustering & NLP |
| **numpy** | 2.5.1 | BSD-3-Clause | numpy.org | Numerical computation |
| **scipy** | 1.17.0 | BSD-3-Clause | scipy.org | Scientific computing & signal processing |
| **openai** | 2.53.0 | Apache-2.0 | github.com/openai/openai-python | OpenAI / OpenRouter client |
| **httpx** | 0.28.1 | BSD-3-Clause | github.com/encode/httpx | Async HTTP client |
| **reportlab** | 4.4.10 | BSD-3-Clause | reportlab.com | PDF report generation |
| **pytest** | 9.0.2 | MIT | pytest.org | Automated test framework |
| **React** | 19.x | MIT | github.com/facebook/react | Frontend UI library |
| **Vite** | 6.x | MIT | github.com/vitejs/vite | Frontend build tool |
| **Lucide Icons** | 0.x | ISC | lucide.dev | UI icons |

---

## Authentication & Tokens
- **Hugging Face Token:** Optional. Only required if using gated models such as `pyannote/speaker-diarization-3.1`. If not provided, the local offline clustering diarizer is automatically utilized.
- **LLM API Key:** Optional. Configurable via `LLM_API_KEY` for OpenAI / OpenRouter / Anthropic compatible endpoints. If omitted, the deterministic local reasoning engine operates offline.
