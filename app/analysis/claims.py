"""Claims Extraction and Contradiction Detection Evidence Engine."""
import re
from typing import List, Tuple
from app.models.schemas import (
    CanonicalTranscriptSegment,
    ClaimResult,
    ContradictionResult
)
from app.utils.logger import get_logger

logger = get_logger("analysis.claims")

# Claim extraction trigger patterns (statements of fact, transactions, actions, events)
CLAIM_TRIGGERS = [
    (r"\b(मैंने|हम|उसने|उन्होंने)\s+.*(दिए|लिया|भेजा|कहा|गया|पहुंचा|खरीदा|बेचा|कॉल किया|बात की)\b", "Action/Transaction Claim"),
    (r"\b(रुपये|हजार|लाख|₹|पैसे|payment)\b", "Financial Claim"),
    (r"\b(पुणे|दिल्ली|मुंबई|office|घर|स्थान|पहुंच)\b", "Locational Claim"),
    (r"\b(कोई\s+.*नहीं|कभी\s+नहीं|बिल्कुल\s+नहीं|नहीं\s+लिया|नहीं\s+दिया)\b", "Denial/Negative Claim")
]


class ClaimsAndContradictionsEngine:
    """Extracts verifiable claims and flags potential contradictions with rigorous provenance."""

    def extract_claims(
        self,
        transcript_segments: List[CanonicalTranscriptSegment]
    ) -> List[ClaimResult]:
        """Extracts substantive factual assertions tied to exact timestamps."""
        claims: List[ClaimResult] = []
        claim_idx = 1

        for seg in transcript_segments:
            text = seg.text.strip()
            # Ignore short greetings and one-word replies
            if len(text.split()) < 3 or text.endswith("?"):
                continue

            matched = False
            for pattern, _ in CLAIM_TRIGGERS:
                if re.search(pattern, text, re.IGNORECASE):
                    matched = True
                    break

            if matched or len(text.split()) >= 6:
                claim_text = f"Speaker states: \"{text}\""
                claims.append(ClaimResult(
                    claim_id=f"clm_{claim_idx:03d}",
                    speaker=seg.speaker,
                    claim_text=claim_text,
                    source_segment_ids=[seg.id],
                    source_start=seg.start,
                    source_end=seg.end,
                    confidence=seg.confidence or 0.85,
                    evidence_quote=text
                ))
                claim_idx += 1

        logger.info(f"Extracted {len(claims)} verifiable claims.")
        return claims

    def detect_contradictions(
        self,
        claims: List[ClaimResult]
    ) -> List[ContradictionResult]:
        """Scans speaker claims for potential factual inconsistencies or polarity reversals.
        
        Strictly reports 'Potential contradiction detected' without accusations of intent.
        """
        contradictions: List[ContradictionResult] = []
        contra_idx = 1

        # Group claims by speaker
        speaker_claims: dict[str, List[ClaimResult]] = {}
        for c in claims:
            speaker_claims.setdefault(c.speaker, []).append(c)

        for speaker, s_claims in speaker_claims.items():
            for i in range(len(s_claims)):
                for j in range(i + 1, len(s_claims)):
                    c1 = s_claims[i]
                    c2 = s_claims[j]

                    t1 = c1.evidence_quote.lower()
                    t2 = c2.evidence_quote.lower()

                    # Check 1: Explicit Negation Conflict (e.g. 'नहीं लिए' vs 'दिए थे / लिए थे')
                    negation_patterns = [
                        (r"नहीं (लिया|दिए|गया|किया|मिला|देखा)", r"(लिया|दिए|गया|किया|मिला|देखा) था"),
                        (r"कोई पैसे नहीं", r"(₹|रुपये|हजार|लाख|पैसे दिए)"),
                        (r"कभी नहीं मिला", r"मिला था"),
                        (r"नहीं जानता", r"जानता हूँ|पहचानता")
                    ]

                    is_conflict = False
                    explanation = ""

                    for neg_pat, pos_pat in negation_patterns:
                        if (re.search(neg_pat, t1) and re.search(pos_pat, t2)) or \
                           (re.search(pos_pat, t1) and re.search(neg_pat, t2)):
                            is_conflict = True
                            explanation = (
                                f"Potential polarity conflict: Speaker previously stated \"{c1.evidence_quote}\" "
                                f"at {c1.source_start}s, but later stated \"{c2.evidence_quote}\" at {c2.source_start}s."
                            )
                            break

                    # Check 2: Monetary Amount Conflict on same subject
                    if not is_conflict:
                        m1 = re.findall(r"(₹\s*[\d,]+|[\d,]+\s*(रुपये|हजार|लाख))", t1)
                        m2 = re.findall(r"(₹\s*[\d,]+|[\d,]+\s*(रुपये|हजार|लाख))", t2)
                        if m1 and m2 and m1[0][0] != m2[0][0]:
                            # If talking about same verb action
                            verbs = ["दिए", "लिया", "मांगे", "खर्च"]
                            if any(v in t1 and v in t2 for v in verbs):
                                is_conflict = True
                                explanation = (
                                    f"Potential financial amount discrepancy: Earlier mentioned {m1[0][0]} "
                                    f"vs later mentioned {m2[0][0]} regarding same transaction context."
                                )

                    if is_conflict:
                        contradictions.append(ContradictionResult(
                            contradiction_id=f"cntr_{contra_idx:03d}",
                            speaker=speaker,
                            earlier_statement=c1.evidence_quote,
                            earlier_timestamp=c1.source_start,
                            earlier_segment_id=c1.source_segment_ids[0],
                            later_statement=c2.evidence_quote,
                            later_timestamp=c2.source_start,
                            later_segment_id=c2.source_segment_ids[0],
                            explanation=explanation,
                            confidence=0.82,
                            uncertainty="MEDIUM",
                            disclaimer="Potential inconsistency detected; does not imply deliberate deception."
                        ))
                        contra_idx += 1

        logger.info(f"Detected {len(contradictions)} potential contradictions.")
        return contradictions

    def process(
        self,
        transcript_segments: List[CanonicalTranscriptSegment]
    ) -> Tuple[List[ClaimResult], List[ContradictionResult]]:
        """Processes transcript to generate claims and contradiction analysis."""
        claims = self.extract_claims(transcript_segments)
        contradictions = self.detect_contradictions(claims)
        return claims, contradictions


def extract_claims_and_contradictions(
    transcript_segments: List[CanonicalTranscriptSegment]
) -> Tuple[List[ClaimResult], List[ContradictionResult]]:
    """Convenience function to run claims and contradiction detection."""
    engine = ClaimsAndContradictionsEngine()
    return engine.process(transcript_segments)
