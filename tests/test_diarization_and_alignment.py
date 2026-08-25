"""Unit tests for Diarization and Speaker-Transcript Alignment."""
import numpy as np
from app.alignment.aligner import SpeakerTranscriptAligner
from app.diarization.spectral_engine import SpectralDiarizationEngine
from app.models.schemas import CanonicalTranscriptSegment, DiarizationSegment, VADSegment, WordTimestamp


def test_spectral_diarization_two_tones():
    sr = 16000
    # Speaker 1 (low pitch harmonic)
    t1 = np.linspace(0, 2.0, int(sr * 2.0), endpoint=False)
    spk1 = (0.4 * np.sin(2 * np.pi * 150 * t1) + 0.2 * np.sin(2 * np.pi * 300 * t1)).astype(np.float32)

    # Speaker 2 (higher pitch harmonic)
    t2 = np.linspace(0, 2.0, int(sr * 2.0), endpoint=False)
    spk2 = (0.4 * np.sin(2 * np.pi * 600 * t2) + 0.2 * np.sin(2 * np.pi * 1200 * t2)).astype(np.float32)

    audio = np.concatenate([spk1, spk2])
    vad_segments = [
        VADSegment(id="vad_01", start=0.1, end=1.9, duration=1.8),
        VADSegment(id="vad_02", start=2.1, end=3.9, duration=1.8),
    ]

    engine = SpectralDiarizationEngine(sample_rate=sr)
    segments = engine.diarize(audio, vad_segments=vad_segments)

    assert len(segments) >= 1
    for seg in segments:
        assert seg.speaker.startswith("SPEAKER_")
        assert seg.start >= 0.0
        assert seg.end <= 4.0


def test_speaker_transcript_alignment():
    # Transcript from ASR (unaligned default speaker)
    transcript = [
        CanonicalTranscriptSegment(
            id="seg_001",
            speaker="SPEAKER_00",
            start=1.0,
            end=3.0,
            text="मैं कल पुणे गया था।",
            confidence=0.95,
            words=[
                WordTimestamp(word="मैं", start=1.0, end=1.4),
                WordTimestamp(word="कल", start=1.4, end=1.8),
                WordTimestamp(word="पुणे", start=1.8, end=2.4),
                WordTimestamp(word="गया", start=2.4, end=2.8),
                WordTimestamp(word="था।", start=2.8, end=3.0)
            ]
        ),
        CanonicalTranscriptSegment(
            id="seg_002",
            speaker="SPEAKER_00",
            start=4.0,
            end=6.0,
            text="आप वहाँ क्यों गए थे?",
            confidence=0.92,
            words=[
                WordTimestamp(word="आप", start=4.0, end=4.4),
                WordTimestamp(word="वहाँ", start=4.4, end=4.8),
                WordTimestamp(word="क्यों", start=4.8, end=5.4),
                WordTimestamp(word="गए", start=5.4, end=5.8),
                WordTimestamp(word="थे?", start=5.8, end=6.0)
            ]
        )
    ]

    # Diarization intervals
    diarization = [
        DiarizationSegment(speaker="SPEAKER_00", start=0.5, end=3.5, duration=3.0),
        DiarizationSegment(speaker="SPEAKER_01", start=3.8, end=6.5, duration=2.7)
    ]

    aligner = SpeakerTranscriptAligner()
    aligned, metrics = aligner.align(transcript, diarization, total_audio_duration=7.0)

    assert len(aligned) == 2
    assert aligned[0].speaker == "SPEAKER_00"
    assert aligned[0].text == "मैं कल पुणे गया था।"
    assert aligned[1].speaker == "SPEAKER_01"
    assert aligned[1].text == "आप वहाँ क्यों गए थे?"

    assert len(metrics) == 2
    assert metrics[0].speaker_id == "SPEAKER_00"
    assert metrics[1].speaker_id == "SPEAKER_01"
    total_pct = sum(m.percentage_of_conversation for m in metrics)
    assert 99.0 <= total_pct <= 101.0
