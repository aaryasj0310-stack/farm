"""Named Entity Recognition (NER) for Hindi and Hinglish transcripts."""
import re
from typing import List, Optional
from app.models.schemas import CanonicalTranscriptSegment, EntityResult
from app.utils.logger import get_logger

logger = get_logger("analysis.entities")

def _u_entity(keywords: list[str]) -> str:
    escaped = [re.escape(k) for k in keywords]
    return rf"(?:^|[^\w\u0900-\u097F])({'|'.join(escaped)})(?:$|[^\w\u0900-\u097F])"

# Indic Entity Pattern definitions
RAW_PATTERNS = [
    # MONEY: ₹50,000, 50 हजार, Rs. 500, 10 लाख, etc.
    (
        r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+|[\d,]+\s*(?:रुपये|रुपए|हजार|हज़ार|लाख|करोड़|rupees|rs|k|lakh))",
        "MONEY"
    ),
    # PHONE: Indian phone numbers
    (
        r"(?:\+91[\-\s]?)?[6789]\d{9}\b",
        "PHONE"
    ),
    # EMAIL:
    (
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "EMAIL"
    ),
    # TIME: 5 बजे, 10:30 AM, सुबह 9 बजे
    (
        r"(?:\b\d{1,2}(?::\d{2})?\s*(?:बजे|am|pm|सुबह|शाम|दोपहर|रात))",
        "TIME"
    ),
    # DATE: 24 अगस्त, कल, परसों, सोमवार
    (
        _u_entity([
            "कल", "आज", "परसों", "सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार",
            "january", "february", "august", "december"
        ]),
        "DATE"
    ),
    # LOCATION: Major Indian Cities and States
    (
        _u_entity([
            "पुणे", "दिल्ली", "मुंबई", "बेंगलुरु", "बैंगलोर", "चेन्नई", "कोलकाता", "हैदराबाद", "जयपुर",
            "अहमदाबाद", "लखनऊ", "कानपुर", "नागपुर", "पटना", "इंदौर", "भोपाल", "चंडीगढ़", "महाराष्ट्र",
            "गुजरात", "राजस्थान", "उत्तर प्रदेश", "pune", "delhi", "mumbai", "bangalore", "bengaluru", "jaipur"
        ]),
        "LOCATION"
    ),
    # ORGANIZATION: Companies, Banks, Institutions
    (
        _u_entity([
            "गूगल", "टाटा", "इन्फोसिस", "विप्रो", "रिलायंस", "एसबीआई", "एचडीएफसी", "पुलिस", "अदालत",
            "हाईकोर्ट", "सुप्रीम कोर्ट", "बैंक", "tcs", "infosys", "google", "reliance", "sbi", "hdfc",
            "police", "court", "bank"
        ]),
        "ORGANIZATION"
    ),
    # VEHICLE:
    (
        _u_entity([
            "कार", "गाड़ी", "बाइक", "मोटरसाइकिल", "स्कूटर", "ट्रक", "बस", "ऑटो", "रिक्शा", "car", "bike", "truck", "bus"
        ]),
        "VEHICLE"
    ),
    # PRODUCT:
    (
        _u_entity([
            "मोबाइल", "फ़ोन", "फोन", "लैपटॉप", "कंप्यूटर", "सॉफ्टवेयर", "ऐप", "दस्तावेज", "कागजात", "cheque", "laptop", "phone"
        ]),
        "PRODUCT"
    ),
    # PERSON Names (Common Indian names in Devanagari & Latin)
    (
        _u_entity([
            "राहुल", "अमित", "रोहित", "प्रिया", "नेहा", "संजय", "विकास", "राकेश", "अंजलि", "सुरेश",
            "महेश", "पूजा", "वर्मा", "शर्मा", "गुप्ता", "पाटिल", "देशमुख", "rahul", "amit", "rohit", "priya", "sharma", "verma"
        ]),
        "PERSON"
    )
]


class IndicEntityExtractor:
    """Extracts typed entities with temporal audio and speaker provenance."""

    def __init__(self):
        self.compiled = [(re.compile(p, re.IGNORECASE), t) for p, t in RAW_PATTERNS]

    def extract_from_segment(self, segment: CanonicalTranscriptSegment) -> List[EntityResult]:
        """Extracts entities found in a single transcript segment."""
        entities: List[EntityResult] = []
        text = segment.text
        seen_spans = set()

        for regex, entity_type in self.compiled:
            for match in regex.finditer(text):
                # If group 1 exists, use group 1 span
                if match.groups() and match.group(1):
                    span = (match.start(1), match.end(1))
                    entity_text = match.group(1).strip()
                else:
                    span = (match.start(), match.end())
                    entity_text = match.group(0).strip()

                if span in seen_spans or not entity_text:
                    continue
                seen_spans.add(span)

                normalized = entity_text
                char_ratio = (span[0] / max(len(text), 1))
                est_time = round(segment.start + (segment.end - segment.start) * char_ratio, 2)

                entities.append(EntityResult(
                    text=entity_text,
                    normalized_value=normalized,
                    type=entity_type,
                    speaker=segment.speaker,
                    timestamp=est_time,
                    segment_id=segment.id
                ))

        return entities

    def extract(self, transcript_segments: List[CanonicalTranscriptSegment]) -> List[EntityResult]:
        """Extracts all entities across all segments."""
        all_entities: List[EntityResult] = []
        for seg in transcript_segments:
            all_entities.extend(self.extract_from_segment(seg))

        logger.info(f"Extracted {len(all_entities)} named entities across conversation.")
        return all_entities


def extract_entities(transcript_segments: List[CanonicalTranscriptSegment]) -> List[EntityResult]:
    """Convenience function to extract entities."""
    extractor = IndicEntityExtractor()
    return extractor.extract(transcript_segments)
