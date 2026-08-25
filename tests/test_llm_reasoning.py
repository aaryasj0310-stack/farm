"""Unit tests for LLM Reasoning Layer."""
from app.llm.provider import LocalFallbackReasoningEngine, OpenAICompatibleProvider
from app.models.schemas import (
    CanonicalTranscriptSegment,
    ClaimResult,
    EmotionResult,
    EntityResult,
    SpeakerMetrics,
    TopicResult
)


def test_local_reasoning_fallback():
    engine = LocalFallbackReasoningEngine()

    transcript = [
        CanonicalTranscriptSegment(
            id="seg_01",
            speaker="SPEAKER_00",
            start=0.5,
            end=4.0,
            text="नमस्ते, क्या पुणे की मीटिंग 5 बजे तय है?"
        ),
        CanonicalTranscriptSegment(
            id="seg_02",
            speaker="SPEAKER_01",
            start=4.5,
            end=8.0,
            text="हाँ, मैंने ₹50,000 की पेमेंट कर दी है।"
        )
    ]
    speakers = [
        SpeakerMetrics(speaker_id="SPEAKER_00", total_speech_time=3.5, percentage_of_conversation=50.0, segment_count=1),
        SpeakerMetrics(speaker_id="SPEAKER_01", total_speech_time=3.5, percentage_of_conversation=50.0, segment_count=1)
    ]
    claims = [
        ClaimResult(
            claim_id="clm_01",
            speaker="SPEAKER_01",
            claim_text="Speaker paid ₹50,000",
            source_segment_ids=["seg_02"],
            source_start=4.5,
            source_end=8.0,
            confidence=0.95,
            evidence_quote="मैंने ₹50,000 की पेमेंट कर दी है।"
        )
    ]
    topics = [
        TopicResult(topic_name="Pune Meeting", relevance_score=0.9, timestamps=[0.5], summary="Meeting discussion")
    ]
    entities = [
        EntityResult(text="पुणे", type="LOCATION", speaker="SPEAKER_00", timestamp=1.2, segment_id="seg_01"),
        EntityResult(text="₹50,000", type="MONEY", speaker="SPEAKER_01", timestamp=5.0, segment_id="seg_02")
    ]
    emotions = [
        EmotionResult(speaker="SPEAKER_00", start=0.5, end=4.0, segment_id="seg_01", emotion="neutral", confidence=0.8),
        EmotionResult(speaker="SPEAKER_01", start=4.5, end=8.0, segment_id="seg_02", emotion="happy", confidence=0.85)
    ]

    summary, timeline = engine.generate_reasoning(
        transcript_segments=transcript,
        speakers=speakers,
        claims=claims,
        topics=topics,
        entities=entities,
        emotions=emotions
    )

    assert summary.high_level_summary != ""
    assert "SPEAKER_00" in summary.speaker_summaries
    assert "SPEAKER_01" in summary.speaker_summaries
    assert len(summary.key_takeaways) >= 1
    assert len(timeline) >= 1
    for event in timeline:
        assert event.timestamp >= 0.0
        assert event.speaker != ""
        assert event.event_description != ""
