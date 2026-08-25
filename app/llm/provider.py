"""Universal LLM Provider abstraction and Local Deterministic Reasoning Fallback."""
import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from openai import OpenAI
from app.config.settings import settings
from app.llm.prompts import SYSTEM_PROMPT, build_reasoning_prompt
from app.models.schemas import (
    AnalysisSummary,
    CanonicalTranscriptSegment,
    ClaimResult,
    EmotionResult,
    EntityResult,
    SpeakerMetrics,
    TimelineEvent,
    TopicResult
)
from app.utils.logger import get_logger

logger = get_logger("llm.provider")


class LLMProvider(ABC):
    """Abstract LLM Provider interface."""

    @abstractmethod
    def generate_reasoning(
        self,
        transcript_segments: List[CanonicalTranscriptSegment],
        speakers: List[SpeakerMetrics],
        claims: List[ClaimResult],
        topics: List[TopicResult],
        entities: List[EntityResult],
        emotions: List[EmotionResult]
    ) -> Tuple[AnalysisSummary, List[TimelineEvent]]:
        """Generates comprehensive conversation summary and chronological timeline."""
        pass


class LocalFallbackReasoningEngine(LLMProvider):
    """Deterministic local extractive reasoning engine (Zero cloud, zero API key required)."""

    def generate_reasoning(
        self,
        transcript_segments: List[CanonicalTranscriptSegment],
        speakers: List[SpeakerMetrics],
        claims: List[ClaimResult],
        topics: List[TopicResult],
        entities: List[EntityResult],
        emotions: List[EmotionResult]
    ) -> Tuple[AnalysisSummary, List[TimelineEvent]]:
        """Synthesizes structured summary and timeline purely from deterministic evidence."""
        logger.info("Executing local deterministic reasoning engine...")

        if not transcript_segments:
            return (
                AnalysisSummary(
                    high_level_summary="No audio dialogue detected.",
                    detailed_summary="The audio recording contained no transcribable speech segments.",
                    key_takeaways=[],
                    speaker_summaries={},
                    important_questions=[],
                    unresolved_issues=[]
                ),
                []
            )

        speaker_ids = [s.speaker_id for s in speakers] or ["SPEAKER_00"]
        topic_names = [t.topic_name for t in topics]
        topic_str = ", ".join(topic_names[:3]) if topic_names else "general matters"

        # 1. High Level Summary
        high_level = (
            f"Conversation between {len(speaker_ids)} speaker(s) ({', '.join(speaker_ids)}) "
            f"covering topics including {topic_str} across {len(transcript_segments)} spoken segments."
        )

        # 2. Detailed Summary
        key_claims_quotes = [f"\"{c.evidence_quote}\"" for c in claims[:3]]
        claims_summary = f" Notable statements included: {'; '.join(key_claims_quotes)}." if key_claims_quotes else ""
        detailed = (
            f"The dialogue commenced at {transcript_segments[0].start:.1f}s and concluded at {transcript_segments[-1].end:.1f}s. "
            f"Speakers actively exchanged views on {topic_str}.{claims_summary}"
        )

        # 3. Key Takeaways
        takeaways = []
        for c in claims[:5]:
            m = int(c.source_start // 60)
            s = int(c.source_start % 60)
            takeaways.append(f"{c.speaker}: {c.claim_text} [{m:02d}:{s:02d}]")

        if not takeaways:
            takeaways.append("Conversation recorded and structured into timestamped turns.")

        # 4. Speaker Summaries
        speaker_summaries: Dict[str, str] = {}
        for spk in speakers:
            spk_claims = [c for c in claims if c.speaker == spk.speaker_id]
            spk_segs = [s for s in transcript_segments if s.speaker == spk.speaker_id]
            sample_text = spk_segs[0].text if spk_segs else ""
            summary_txt = f"Spoke for {spk.total_speech_time}s ({spk.percentage_of_conversation}% of audio, {spk.segment_count} turns)."
            if spk_claims:
                summary_txt += f" Key statement: \"{spk_claims[0].evidence_quote}\"."
            elif sample_text:
                summary_txt += f" Opening utterance: \"{sample_text[:60]}\"."
            speaker_summaries[spk.speaker_id] = summary_txt

        # 5. Questions & Unresolved Issues
        questions = []
        for seg in transcript_segments:
            if "?" in seg.text or any(q in seg.text for q in ["क्या", "क्यों", "कब", "कहाँ", "कैसे"]):
                m = int(seg.start // 60)
                s = int(seg.start % 60)
                questions.append(f"{seg.speaker} asked: \"{seg.text}\" [{m:02d}:{s:02d}]")
            if len(questions) >= 4:
                break

        unresolved = []
        if len(speakers) > 1 and len(claims) > 1:
            unresolved.append(f"Follow-up required on claims regarding {topic_str}.")

        # 6. Timeline Events
        timeline: List[TimelineEvent] = []
        # Event 1: Conversation start
        timeline.append(TimelineEvent(
            timestamp=transcript_segments[0].start,
            speaker=transcript_segments[0].speaker,
            event_description=f"Discussion initiated with \"{transcript_segments[0].text[:50]}...\"",
            category="Opening"
        ))

        # Event 2+: Substantive claims & questions as milestones
        for c in claims[:6]:
            timeline.append(TimelineEvent(
                timestamp=c.source_start,
                speaker=c.speaker,
                event_description=f"Claim: \"{c.evidence_quote[:70]}\"",
                category="Factual Statement"
            ))

        # Sort timeline by timestamp
        timeline.sort(key=lambda e: e.timestamp)

        summary = AnalysisSummary(
            high_level_summary=high_level,
            detailed_summary=detailed,
            key_takeaways=takeaways,
            speaker_summaries=speaker_summaries,
            important_questions=questions,
            unresolved_issues=unresolved
        )

        return summary, timeline


class OpenAICompatibleProvider(LLMProvider):
    """Integrates OpenRouter, OpenAI, Groq, Ollama, or local vLLM API endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or settings.LLM_API_KEY or "dummy_key"
        self.base_url = base_url or settings.LLM_BASE_URL
        self.model_name = model_name or settings.LLM_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.fallback = LocalFallbackReasoningEngine()

    def generate_reasoning(
        self,
        transcript_segments: List[CanonicalTranscriptSegment],
        speakers: List[SpeakerMetrics],
        claims: List[ClaimResult],
        topics: List[TopicResult],
        entities: List[EntityResult],
        emotions: List[EmotionResult]
    ) -> Tuple[AnalysisSummary, List[TimelineEvent]]:
        """Sends structured evidence prompt to LLM and parses grounded JSON response."""
        try:
            logger.info(f"Invoking LLM reasoning via {self.base_url} ({self.model_name})...")
            
            # Format inputs
            transcript_text = "\n".join([
                f"[{seg.start:05.1f}s–{seg.end:05.1f}s] {seg.speaker}: {seg.text}"
                for seg in transcript_segments
            ])
            speakers_info = "\n".join([
                f"- {s.speaker_id}: {s.total_speech_time}s ({s.percentage_of_conversation}%)"
                for s in speakers
            ])
            claims_info = "\n".join([
                f"- [{c.source_start:.1f}s] {c.speaker}: {c.claim_text} (Evidence: \"{c.evidence_quote}\")"
                for c in claims
            ])
            topics_info = "\n".join([f"- {t.topic_name} (Relevance: {t.relevance_score})" for t in topics])
            entities_info = "\n".join([f"- {e.type}: {e.text} (Speaker: {e.speaker}, Time: {e.timestamp}s)" for e in entities])
            emotions_info = "\n".join([f"- [{em.start:.1f}s] {em.speaker}: {em.emotion} ({em.confidence})" for em in emotions[:10]])

            user_prompt = build_reasoning_prompt(
                transcript_text=transcript_text,
                speakers_info=speakers_info,
                claims_info=claims_info,
                topics_info=topics_info,
                entities_info=entities_info,
                emotions_info=emotions_info
            )

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content or "{}"
            data = json.loads(content)

            # Parse summary
            summary = AnalysisSummary(
                high_level_summary=data.get("high_level_summary", "Summary unavailable."),
                detailed_summary=data.get("detailed_summary", ""),
                key_takeaways=data.get("key_takeaways", []),
                speaker_summaries=data.get("speaker_summaries", {}),
                important_questions=data.get("important_questions", []),
                unresolved_issues=data.get("unresolved_issues", [])
            )

            # Parse timeline
            raw_timeline = data.get("timeline", [])
            timeline = [
                TimelineEvent(
                    timestamp=float(e.get("timestamp", 0.0)),
                    speaker=e.get("speaker", "SPEAKER_00"),
                    event_description=e.get("event_description", ""),
                    category=e.get("category", "General")
                )
                for e in raw_timeline
            ]

            logger.info("LLM reasoning synthesized successfully.")
            return summary, timeline

        except Exception as e:
            logger.warning(f"LLM call failed ({e}). Falling back to local deterministic reasoning.")
            return self.fallback.generate_reasoning(
                transcript_segments=transcript_segments,
                speakers=speakers,
                claims=claims,
                topics=topics,
                entities=entities,
                emotions=emotions
            )


def get_llm_provider() -> LLMProvider:
    """Factory function returning configured LLM provider."""
    if settings.LLM_PROVIDER in ("openrouter", "openai", "ollama") and settings.LLM_API_KEY:
        return OpenAICompatibleProvider()
    return LocalFallbackReasoningEngine()


def synthesize_conversation_reasoning(
    transcript_segments: List[CanonicalTranscriptSegment],
    speakers: List[SpeakerMetrics],
    claims: List[ClaimResult],
    topics: List[TopicResult],
    entities: List[EntityResult],
    emotions: List[EmotionResult]
) -> Tuple[AnalysisSummary, List[TimelineEvent]]:
    """Convenience function to generate reasoning summary and timeline."""
    provider = get_llm_provider()
    return provider.generate_reasoning(
        transcript_segments=transcript_segments,
        speakers=speakers,
        claims=claims,
        topics=topics,
        entities=entities,
        emotions=emotions
    )
