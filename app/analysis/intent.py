"""Intent Classification Engine for Hindi and Hinglish utterances."""
import re
from typing import List, Tuple
from app.models.schemas import CanonicalTranscriptSegment, IntentResult
from app.utils.logger import get_logger

logger = get_logger("analysis.intent")

# Helper for Unicode boundary matching
def _u_pat(keywords: list[str]) -> str:
    escaped = [re.escape(k) for k in keywords]
    return rf"(?:^|[^\w\u0900-\u097F])({'|'.join(escaped)})(?:$|[^\w\u0900-\u097F])"

# Configurable Intent Taxonomy
INTENT_KEYWORDS = {
    "greeting": [
        "नमस्ते", "नमस्कार", "प्रणाम", "हेलो", "हाय", "सुप्रभात", "शुभ संध्या",
        "hello", "hi", "hey", "good morning", "namaste"
    ],
    "farewell": [
        "अलविदा", "बाय", "फिर मिलेंगे", "शुभ रात्रि", "चलता हूँ", "चलते हैं",
        "bye", "goodbye", "see you", "good night", "take care"
    ],
    "question": [
        "क्या", "क्यों", "कब", "कहाँ", "कैसे", "किसने", "किसको", "कितना", "कितने", "किधर", "?",
        "what", "why", "when", "where", "how", "who", "whom", "which"
    ],
    "agreement": [
        "हाँ", "जी हाँ", "बिल्कुल", "सही बात", "सहमत", "ठीक है", "अवश्य", "ज़रूर",
        "yes", "yeah", "agree", "correct", "right", "sure", "true"
    ],
    "disagreement": [
        "नहीं", "गलत है", "असहमत", "ऐसा नहीं है", "बिलकुल नहीं", "झूठ",
        "no", "disagree", "wrong", "incorrect", "false", "not true"
    ],
    "refusal": [
        "मना", "इनकार", "नहीं करूँगा", "नहीं हो सकता", "नहीं दूंगा", "असंभव",
        "refuse", "deny", "cannot do", "won't do", "impossible"
    ],
    "request": [
        "कृपया", "प्लीज", "अनुरोध", "मदद", "दे दीजिए", "बताइए ना", "कर देंगे",
        "please", "request", "help", "could you", "would you"
    ],
    "instruction": [
        "करो", "जाओ", "देखो", "भेजो", "लाओ", "लिखो", "सुनो", "तुरंत करो",
        "do this", "send", "go", "bring", "listen", "execute"
    ],
    "suggestion": [
        "सुझाव", "सलाह", "राय", "करना चाहिए", "बेहतर होगा", "अगर हम",
        "suggest", "advice", "should", "better if", "recommend"
    ],
    "accusation": [
        "आरोप", "धोखा दिया", "चोरी की", "गलती तुम्हारी", "तुमने किया", "दोषी",
        "accuse", "blame", "cheat", "your fault", "you did it"
    ],
    "denial": [
        "मैंने नहीं किया", "मुझे नहीं पता", "मेरा कोई हाथ नहीं", "साफ़ इनकार",
        "didn't do", "not my fault", "deny", "had nothing to do"
    ],
    "confirmation": [
        "पुष्टि", "पक्का", "कंफर्म", "तय रहा", "फाइनल", "यकीन है",
        "confirm", "confirmed", "sure", "finalized", "certain"
    ],
    "uncertainty": [
        "शायद", "पता नहीं", "हो सकता है", "संदेह", "डाउट", "सोचना पड़ेगा",
        "maybe", "perhaps", "not sure", "doubtful", "unsure"
    ],
    "explanation": [
        "क्योंकि", "कारण यह है", "मतलब यह", "दरअसल", "इस वजह से", "बात यह है",
        "because", "reason is", "means that", "actually", "due to"
    ],
    "answer": [
        "उत्तर", "जवाब", "बता रहा हूँ", "यह रहा", "इस प्रकार",
        "answer", "reply", "here it is"
    ]
}


class IntentClassifier:
    """Classifies Hindi/Hinglish conversational intent per segment."""

    def __init__(self, taxonomy: dict = INTENT_KEYWORDS):
        self.taxonomy = taxonomy
        self.compiled_patterns = {
            intent: re.compile(_u_pat(kws), re.IGNORECASE)
            for intent, kws in self.taxonomy.items()
        }

    def classify_segment(self, text: str) -> Tuple[str, float]:
        """Matches utterance text against intent taxonomy rules."""
        scores: dict[str, int] = {}
        for intent_name, regex in self.compiled_patterns.items():
            matches = regex.findall(text)
            if matches:
                scores[intent_name] = len(matches)

        if not scores:
            # Check question mark explicitly
            if "?" in text:
                return "question", 0.80
            return "explanation", 0.60

        # Prioritize question/refusal/accusation over generic agreement/explanation if present
        priority_order = ["question", "accusation", "denial", "refusal", "request", "instruction", "agreement", "disagreement", "greeting", "farewell"]
        for p in priority_order:
            if p in scores:
                return p, min(0.70 + (scores[p] * 0.15), 0.95)

        best_intent = max(scores, key=scores.get)
        confidence = min(0.65 + (scores[best_intent] * 0.15), 0.95)
        return best_intent, round(confidence, 2)

    def classify(self, transcript_segments: List[CanonicalTranscriptSegment]) -> List[IntentResult]:
        """Processes all transcript segments and returns structured IntentResults."""
        results: List[IntentResult] = []
        for seg in transcript_segments:
            intent, conf = self.classify_segment(seg.text)
            snippet = seg.text if len(seg.text) <= 60 else seg.text[:57] + "..."
            results.append(IntentResult(
                speaker=seg.speaker,
                start=seg.start,
                end=seg.end,
                segment_id=seg.id,
                intent=intent,
                confidence=conf,
                utterance_snippet=snippet
            ))
        logger.info(f"Classified intents for {len(results)} transcript segments.")
        return results


def classify_intents(transcript_segments: List[CanonicalTranscriptSegment]) -> List[IntentResult]:
    """Convenience function to run intent classification."""
    classifier = IntentClassifier()
    return classifier.classify(transcript_segments)
