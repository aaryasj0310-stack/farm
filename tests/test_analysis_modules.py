"""Unit tests for Emotion, Intent, Entities, Topics, Claims, and Contradictions."""
import numpy as np
from app.analysis.claims import ClaimsAndContradictionsEngine
from app.analysis.emotion import EmotionAnalyzer
from app.analysis.entities import IndicEntityExtractor
from app.analysis.intent import IntentClassifier
from app.analysis.topics import TopicExtractor
from app.models.schemas import CanonicalTranscriptSegment, WordTimestamp


def sample_conversation() -> list[CanonicalTranscriptSegment]:
    return [
        CanonicalTranscriptSegment(
            id="seg_001",
            speaker="SPEAKER_00",
            start=1.0,
            end=3.5,
            text="नमस्ते अमित, क्या आपने राहुल को कॉल किया था?",
            confidence=0.95
        ),
        CanonicalTranscriptSegment(
            id="seg_002",
            speaker="SPEAKER_01",
            start=4.0,
            end=7.2,
            text="हाँ, मैंने राहुल से बात की थी। मैंने उससे कोई पैसे नहीं लिए।",
            confidence=0.92
        ),
        CanonicalTranscriptSegment(
            id="seg_003",
            speaker="SPEAKER_00",
            start=8.0,
            end=11.5,
            text="शानदार! कल 5 बजे पुणे की मीटिंग में चलना है।",
            confidence=0.90
        ),
        CanonicalTranscriptSegment(
            id="seg_004",
            speaker="SPEAKER_01",
            start=12.0,
            end=16.0,
            text="ठीक है, लेकिन राहुल ने मुझे ₹50,000 दिए थे पिछले हफ्ते।",
            confidence=0.91
        )
    ]


def test_intent_classification():
    classifier = IntentClassifier()
    conv = sample_conversation()
    intents = classifier.classify(conv)

    assert len(intents) == 4
    assert intents[0].intent in ("question", "greeting")
    assert intents[1].intent in ("agreement", "explanation", "denial")
    assert intents[2].intent in ("suggestion", "instruction", "explanation")


def test_entity_extraction():
    extractor = IndicEntityExtractor()
    conv = sample_conversation()
    entities = extractor.extract(conv)

    entity_types = {e.type for e in entities}
    entity_texts = {e.text for e in entities}

    assert "PERSON" in entity_types
    assert "LOCATION" in entity_types
    assert "MONEY" in entity_types
    assert "पुणे" in entity_texts
    assert "₹50,000" in entity_texts
    assert any(e.type == "PERSON" for e in entities)


def test_topic_extraction():
    extractor = TopicExtractor()
    conv = sample_conversation()
    topics = extractor.extract(conv)

    assert len(topics) >= 1
    for t in topics:
        assert len(t.timestamps) >= 1
        assert t.relevance_score > 0.0


def test_claims_and_contradictions():
    engine = ClaimsAndContradictionsEngine()
    conv = sample_conversation()
    claims, contradictions = engine.process(conv)

    assert len(claims) >= 2
    for c in claims:
        assert c.source_segment_ids
        assert c.source_start >= 0.0
        assert c.evidence_quote != ""

    # SPEAKER_01 said: "मैंने उससे कोई पैसे नहीं लिए" in seg_002 and "राहुल ने मुझे ₹50,000 दिए थे" in seg_004
    assert len(contradictions) >= 1
    cntr = contradictions[0]
    assert cntr.speaker == "SPEAKER_01"
    assert "inconsistency" in cntr.disclaimer.lower() or "deliberate" in cntr.disclaimer.lower()
    assert cntr.earlier_timestamp < cntr.later_timestamp


def test_emotion_analysis():
    sr = 16000
    dummy_audio = np.zeros(int(sr * 18.0), dtype=np.float32)
    analyzer = EmotionAnalyzer(sample_rate=sr)
    conv = sample_conversation()

    emotions = analyzer.analyze(dummy_audio, conv)
    assert len(emotions) == 4
    for em in emotions:
        assert em.emotion in (
            "neutral", "happy", "sad", "angry", "fear", "surprise",
            "disgust", "frustration", "excitement", "uncertainty"
        )
        assert em.confidence is not None
        assert "Model-estimated" in em.note
