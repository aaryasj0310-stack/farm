"""Voice Activity Detection package."""
from app.vad.silero_engine import SileroVADEngine, detect_voice_activity

__all__ = ["SileroVADEngine", "detect_voice_activity"]
