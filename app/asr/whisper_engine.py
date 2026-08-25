"""Hindi and Hinglish ASR engine powered by faster-whisper."""
import math
from pathlib import Path
from typing import List, Optional, Union
from faster_whisper import WhisperModel
from app.config.settings import settings
from app.models.schemas import CanonicalTranscriptSegment, WordTimestamp
from app.utils.logger import get_logger

logger = get_logger("asr.whisper")


class HindiASREngine:
    """Production ASR Engine using faster-whisper with Devanagari preservation."""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        cpu_threads: Optional[int] = None,
        download_root: Optional[Path] = None
    ):
        self.model_size = model_size or settings.ASR_MODEL_SIZE
        self.device = device or settings.get_effective_device()
        self.compute_type = compute_type or settings.get_compute_type()
        self.cpu_threads = cpu_threads or settings.CPU_THREADS
        self.download_root = str(download_root or settings.CACHE_DIR / "whisper")
        self._model: Optional[WhisperModel] = None

    def _load_model(self) -> WhisperModel:
        """Lazily loads the Whisper model."""
        if self._model is not None:
            return self._model

        logger.info(
            f"Loading faster-whisper model '{self.model_size}' on {self.device} ({self.compute_type})..."
        )
        try:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                download_root=self.download_root
            )
            logger.info(f"faster-whisper model '{self.model_size}' loaded successfully.")
            return self._model
        except Exception as e:
            logger.warning(f"Failed to load '{self.model_size}' ({e}). Attempting fallback to 'tiny'...")
            self.model_size = "tiny"
            self._model = WhisperModel(
                "tiny",
                device="cpu",
                compute_type="int8",
                cpu_threads=self.cpu_threads,
                download_root=self.download_root
            )
            logger.info("Fallback 'tiny' model loaded successfully.")
            return self._model

    def transcribe(
        self,
        audio_path: Union[str, Path],
        language: str = "hi",
        initial_prompt: Optional[str] = None,
        job_id: Optional[str] = None
    ) -> List[CanonicalTranscriptSegment]:
        """Transcribes audio into canonical Devanagari Hindi / Hinglish segments with word timestamps.
        
        Preserves original spoken language; does not forcibly translate to English.
        """
        model = self._load_model()
        audio_str = str(audio_path)

        prompt = initial_prompt or (
            "यह बातचीत हिंदी और हिंग्लिश में है। कृपया इसे सटीक देवनागरी लिपि में लिखें।"
        )

        logger.info(f"Transcribing audio '{Path(audio_str).name}' with language='{language}'...")
        
        segments_gen, info = model.transcribe(
            audio_str,
            language=language if language != "auto" else None,
            task="transcribe",  # strictly transcribe, never translate
            beam_size=5,
            word_timestamps=True,
            initial_prompt=prompt,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300)
        )

        canonical_segments: List[CanonicalTranscriptSegment] = []
        for i, seg in enumerate(segments_gen):
            text = seg.text.strip()
            if not text:
                continue

            # Calculate confidence from average log probability: P = exp(avg_logprob)
            conf = min(max(math.exp(seg.avg_logprob), 0.0), 1.0) if seg.avg_logprob is not None else 0.85

            word_list: List[WordTimestamp] = []
            if seg.words:
                for w in seg.words:
                    w_conf = min(max(math.exp(w.probability), 0.0), 1.0) if hasattr(w, "probability") and w.probability is not None else conf
                    word_list.append(WordTimestamp(
                        word=w.word.strip(),
                        start=round(w.start, 3),
                        end=round(w.end, 3),
                        confidence=round(w_conf, 2)
                    ))

            uncertainty = "LOW"
            if conf < 0.60:
                uncertainty = "HIGH"
            elif conf < 0.80:
                uncertainty = "MEDIUM"

            canonical_segments.append(CanonicalTranscriptSegment(
                id=f"seg_{i+1:03d}",
                speaker="SPEAKER_00",  # Default speaker, aligned downstream
                start=round(seg.start, 3),
                end=round(seg.end, 3),
                text=text,
                confidence=round(conf, 2),
                words=word_list,
                uncertainty=uncertainty
            ))

        logger.info(
            f"ASR complete. Generated {len(canonical_segments)} segments. Spoken language detected: {info.language} ({info.language_probability:.2f})"
        )
        return canonical_segments


_global_asr_engine: Optional[HindiASREngine] = None


def get_asr_engine() -> HindiASREngine:
    """Returns singleton ASR engine instance."""
    global _global_asr_engine
    if _global_asr_engine is None:
        _global_asr_engine = HindiASREngine()
    return _global_asr_engine
