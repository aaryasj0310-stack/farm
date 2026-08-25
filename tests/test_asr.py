"""Unit tests for Hindi ASR Engine."""
from unittest.mock import MagicMock, patch
from app.asr.whisper_engine import HindiASREngine
from app.models.schemas import CanonicalTranscriptSegment


def test_asr_engine_transcription_parsing():
    engine = HindiASREngine(model_size="tiny", device="cpu", compute_type="int8")

    # Mock faster_whisper segments generator
    mock_word = MagicMock()
    mock_word.word = "नमस्ते"
    mock_word.start = 0.5
    mock_word.end = 0.9
    mock_word.probability = -0.1

    mock_segment = MagicMock()
    mock_segment.start = 0.5
    mock_segment.end = 2.4
    mock_segment.text = "नमस्ते, आप कैसे हैं?"
    mock_segment.avg_logprob = -0.15
    mock_segment.words = [mock_word]

    mock_info = MagicMock()
    mock_info.language = "hi"
    mock_info.language_probability = 0.98

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    engine._model = mock_model

    results = engine.transcribe("dummy_audio.wav", language="hi")

    assert len(results) == 1
    seg = results[0]
    assert seg.id == "seg_001"
    assert seg.text == "नमस्ते, आप कैसे हैं?"
    assert seg.start == 0.5
    assert seg.end == 2.4
    assert seg.confidence is not None
    assert len(seg.words) == 1
    assert seg.words[0].word == "नमस्ते"
    assert seg.uncertainty in ("LOW", "MEDIUM", "HIGH")
