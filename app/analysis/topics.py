"""Topic Extraction Engine for Hindi and Hinglish transcripts."""
import re
from collections import Counter
from typing import List
from app.models.schemas import CanonicalTranscriptSegment, TopicResult
from app.utils.logger import get_logger

logger = get_logger("analysis.topics")

# Hindi & English Common Stopwords
HINDI_STOPWORDS = {
    "है", "हैं", "था", "थी", "थे", "का", "के", "की", "को", "में", "पर", "से", "ने", "और", "या",
    "यह", "वह", "इस", "उस", "तो", "भी", "ही", "कर", "किया", "रहा", "रहे", "रही", "हो", "होता",
    "गया", "गए", "गई", "दिया", "लिए", "अपने", "अपनी", "मुझे", "तुम", "आप", "हम", "वे", "एक",
    "is", "the", "and", "or", "in", "at", "to", "for", "with", "that", "this", "it", "was", "were"
}


class TopicExtractor:
    """Extracts substantive conversation topics with anchored timestamps."""

    def extract(self, transcript_segments: List[CanonicalTranscriptSegment]) -> List[TopicResult]:
        """Identifies prominent topics and maps occurrences to timestamps."""
        if not transcript_segments:
            return []

        # Collect words and phrases with their segment timestamps
        phrase_timestamps: dict[str, List[float]] = {}
        phrase_contexts: dict[str, List[str]] = {}

        for seg in transcript_segments:
            # Clean tokens
            tokens = re.findall(r"[\w\u0900-\u097F]+", seg.text.lower())
            filtered = [w for w in tokens if len(w) > 2 and w not in HINDI_STOPWORDS]

            # Bi-grams and single substantive keywords
            for i in range(len(filtered)):
                w = filtered[i]
                if w not in phrase_timestamps:
                    phrase_timestamps[w] = []
                    phrase_contexts[w] = []
                phrase_timestamps[w].append(seg.start)
                phrase_contexts[w].append(seg.text)

                if i < len(filtered) - 1:
                    bigram = f"{filtered[i]} {filtered[i+1]}"
                    if bigram not in phrase_timestamps:
                        phrase_timestamps[bigram] = []
                        phrase_contexts[bigram] = []
                    phrase_timestamps[bigram].append(seg.start)
                    phrase_contexts[bigram].append(seg.text)

        # Rank by frequency and spread across conversation
        candidates = sorted(
            phrase_timestamps.keys(),
            key=lambda p: len(phrase_timestamps[p]),
            reverse=True
        )

        selected_topics: List[TopicResult] = []
        seen_words = set()

        for cand in candidates:
            if len(selected_topics) >= 5:
                break
            
            # Avoid subset redundancy
            cand_words = set(cand.split())
            if cand_words.issubset(seen_words):
                continue

            timestamps = sorted(list(set(phrase_timestamps[cand])))
            count = len(timestamps)

            if count >= 1:
                seen_words.update(cand_words)
                topic_title = cand.title()
                summary_snippet = phrase_contexts[cand][0] if phrase_contexts[cand] else ""
                
                score = min(round(0.4 + (count * 0.15), 2), 0.95)
                selected_topics.append(TopicResult(
                    topic_name=topic_title,
                    relevance_score=score,
                    timestamps=timestamps[:8],  # first 8 occurrences
                    summary=f"Discussion regarding '{cand}' (e.g., \"{summary_snippet[:80]}...\")"
                ))

        if not selected_topics:
            selected_topics.append(TopicResult(
                topic_name="General Conversation",
                relevance_score=0.70,
                timestamps=[seg.start for seg in transcript_segments[:5]],
                summary="General discussion across conversation turns."
            ))

        logger.info(f"Extracted {len(selected_topics)} major topics.")
        return selected_topics


def extract_topics(transcript_segments: List[CanonicalTranscriptSegment]) -> List[TopicResult]:
    """Convenience function to extract topics."""
    extractor = TopicExtractor()
    return extractor.extract(transcript_segments)
