"""Application configuration using Pydantic Settings."""
import os
import torch
from pathlib import Path
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings for Hindi Audio Intelligence Pipeline."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Application
    APP_NAME: str = "Hindi Audio Intelligence Pipeline"
    APP_ENV: Literal["development", "production", "testing"] = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Hardware / Device
    MODEL_DEVICE: Literal["auto", "cpu", "cuda"] = "auto"
    COMPUTE_TYPE: Literal["int8", "float16", "float32"] = "int8"
    CPU_THREADS: int = 4

    # ASR Settings
    ASR_MODEL_SIZE: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    ASR_LANGUAGE: str = "hi"

    # VAD Settings
    VAD_THRESHOLD: float = 0.5
    VAD_MIN_SPEECH_DURATION_MS: int = 250
    VAD_MIN_SILENCE_DURATION_MS: int = 200

    # Diarization Settings
    DIARIZATION_ENGINE: Literal["auto", "pyannote", "spectral"] = "auto"
    HF_TOKEN: Optional[str] = None

    # LLM Settings
    LLM_PROVIDER: Literal["none", "openrouter", "openai", "ollama"] = "none"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: Optional[str] = None
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Paths and Storage
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_DIR: Path = BASE_DIR / "data" / "jobs"
    CACHE_DIR: Path = BASE_DIR / "data" / "cache"
    DB_PATH: Path = BASE_DIR / "data" / "jobs.db"
    
    # Limits & Security
    MAX_AUDIO_FILE_SIZE_MB: int = 100
    MAX_AUDIO_DURATION_SEC: int = 3600  # 60 minutes
    ALLOWED_EXTENSIONS: set[str] = {"wav", "mp3", "m4a", "flac", "aac", "ogg"}

    def get_effective_device(self) -> str:
        """Resolve 'auto' to 'cuda' if CUDA is actually available, else 'cpu'."""
        if self.MODEL_DEVICE == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if self.MODEL_DEVICE == "cuda" and not torch.cuda.is_available():
            return "cpu"
        return self.MODEL_DEVICE

    def get_compute_type(self) -> str:
        """Resolve compute type safely for device."""
        device = self.get_effective_device()
        if device == "cpu":
            # On CPU, int8 is the fastest and most memory efficient for CTranslate2
            return "int8" if self.COMPUTE_TYPE in ("int8", "float16") else "float32"
        return self.COMPUTE_TYPE

    def ensure_directories(self) -> None:
        """Ensure necessary storage and cache directories exist."""
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
