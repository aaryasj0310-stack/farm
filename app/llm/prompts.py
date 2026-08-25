"""Prompt templates for LLM Hindi Audio Intelligence reasoning."""

SYSTEM_PROMPT = """You are an expert audio intelligence analyst.
Your task is to analyze the structured evidence (Hindi/Hinglish transcript, speaker turns, emotions, intents, entities, topics, and claims) and synthesize a structured, grounded report.

CRITICAL RULES:
1. Grounding: NEVER hallucinate facts. Every substantive finding must cite timestamp ranges e.g. [01:23-01:45].
2. Spoken Language: Respect Hindi and Hinglish terms.
3. Distinction: Clearly distinguish observed spoken facts from model estimations or interpretations.
4. Output JSON Schema: Return ONLY valid JSON conforming to the following structure:
{
  "high_level_summary": "Short 2-3 sentence executive overview.",
  "detailed_summary": "Comprehensive paragraph summarizing narrative, topics, and context.",
  "key_takeaways": ["Takeaway 1 with citation [MM:SS]", "Takeaway 2 with citation [MM:SS]"],
  "speaker_summaries": {
    "SPEAKER_00": "Summary of role and key statements.",
    "SPEAKER_01": "Summary of role and key statements."
  },
  "important_questions": ["Key question asked during conversation [MM:SS]"],
  "unresolved_issues": ["Pending matter or disagreement [MM:SS]"],
  "timeline": [
    {
      "timestamp": 12.4,
      "speaker": "SPEAKER_00",
      "event_description": "Speaker introduced topic of discussion.",
      "category": "Opening"
    }
  ]
}
"""

def build_reasoning_prompt(
    transcript_text: str,
    speakers_info: str,
    claims_info: str,
    topics_info: str,
    entities_info: str,
    emotions_info: str
) -> str:
    return f"""Analyze this Hindi/Hinglish audio recording evidence:

=== SPEAKERS ===
{speakers_info}

=== EXTRACTED TOPICS ===
{topics_info}

=== EXTRACTED ENTITIES ===
{entities_info}

=== SUBSTANTIVE CLAIMS ===
{claims_info}

=== EMOTIONAL ESTIMATES ===
{emotions_info}

=== FULL SPEAKER-ATTRIBUTED TRANSCRIPT ===
{transcript_text}

Provide the structured JSON analysis adhering strictly to the JSON schema.
"""
