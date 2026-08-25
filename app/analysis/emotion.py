"""Multi-modal Emotion Analysis Engine (Acoustic Prosody + Hindi Linguistic Cues)."""
import re
from pathlib import Path
from typing import List, Optional, Tuple, Union
import librosa
import numpy as np
import soundfile as sf
from app.models.schemas import CanonicalTranscriptSegment, EmotionResult
from app.utils.logger import get_logger

logger = get_logger("analysis.emotion")

# Hindi & Hinglish Linguistic Emotion Lexicon
HINDI_EMOTION_LEXICON = {
    "happy": [
        "खुश", "प्रसन्न", "बधाई", "शानदार", "बढ़िया", "अच्छा", "मजा", "आनंद", "धन्यवाद", "शुक्रिया",
        "happy", "great", "awesome", "congrats", "good", "love", "zabardast", "badiya", "superb"
    ],
    "sad": [
        "दुख", "उदास", "रो", "तकलीफ", "दर्द", "मायूस", "नुकसान", "अफ़सोस", "खराब", "बेबस",
        "sad", "depressed", "unhappy", "loss", "pain", "sorry", "dukh", "afsos"
    ],
    "angry": [
        "गुस्सा", "क्रोध", "बकवास", "बदतमीज़", "घटिया", "चुप", "धोखा", "मार", "पागल", "खबरदार",
        "angry", "mad", "shut up", "cheat", "liar", "gussa", "bakwas", "bewakoof"
    ],
    "frustration": [
        "तंग", "परेशान", "दिमाग खराब", "झंझट", "उकता", "बोर", "अटक", "सिरदर्द", "मुसीबत",
        "frustrated", "fed up", "annoying", "irritated", "pareshaan", "musibat", "tang"
    ],
    "fear": [
        "डर", "भय", "खतरा", "घबराहट", "बचाओ", "कांप", "आशंका", "धमकी", "रिस्क",
        "scared", "fear", "danger", "threat", "risk", "dar", "khatra", "ghabrahat"
    ],
    "surprise": [
        "अरे", "वाह", "क्या बात", "अचानक", "आश्चर्य", "चौंक", "सच में", "गजब", "ओह",
        "wow", "really", "what", "omg", "surprise", "arey", "sach mein", "gazab"
    ],
    "disgust": [
        "घिनौना", "छी", "गंदा", "बेकार", "घृणा", "थू",
        "disgusting", "gross", "nasty", "chee", "ganda", "bekaar"
    ],
    "excitement": [
        "उत्साह", "धमाका", "जीत", "जश्न", "सुपर", "कमाल", "तैयार",
        "excited", "pumped", "win", "celebrate", "party", "kamaal", "dhamaaka"
    ],
    "uncertainty": [
        "शायद", "पता नहीं", "हो सकता है", "संदेह", "कन्फ्यूज", "उलझन", "संशय", "मालूम नहीं", "डाउट",
        "maybe", "not sure", "confused", "doubt", "perhaps", "shayad", "pata nahi"
    ]
}


class EmotionAnalyzer:
    """Multi-modal Emotion Analyzer combining acoustic prosody and linguistic semantics."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def _extract_acoustic_prosody(
        self,
        audio_slice: np.ndarray
    ) -> Tuple[float, float, float]:
        """Extracts acoustic prosody metrics: (arousal, valence, speech_rate_proxy).
        
        Arousal: Energy, pitch variance, spectral centroid.
        Valence: Harmonics-to-noise / spectral flatness proxy.
        """
        if len(audio_slice) < 512:
            return 0.5, 0.5, 1.0

        # 1. RMS Energy (Proxy for acoustic arousal)
        rms = float(np.sqrt(np.mean(audio_slice**2)))
        arousal = min(max(rms * 8.0, 0.0), 1.0)

        # 2. Pitch / F0 variance
        try:
            pitches, magnitudes = librosa.piptrack(y=audio_slice, sr=self.sample_rate, fmin=75, fmax=500)
            pitch_values = pitches[magnitudes > np.median(magnitudes)]
            if len(pitch_values) > 5:
                pitch_std = float(np.std(pitch_values))
                # High pitch variation elevates arousal
                arousal = min(max(arousal + (pitch_std / 500.0) * 0.3, 0.0), 1.0)
        except Exception:
            pass

        # 3. Spectral Centroid
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio_slice, sr=self.sample_rate)))
        valence = 0.5
        if centroid > 2500:
            # Brighter acoustic timbre often correlates with active positive/aggressive states
            valence = min(valence + 0.2, 1.0)
        elif centroid < 1200:
            valence = max(valence - 0.2, 0.0)

        return round(arousal, 2), round(valence, 2), 1.0

    def _analyze_linguistic_emotion(self, text: str) -> Tuple[str, float]:
        """Scores text against Hindi/Hinglish emotional keywords."""
        text_lower = text.lower()
        scores: dict[str, int] = {k: 0 for k in HINDI_EMOTION_LEXICON}

        for emotion, keywords in HINDI_EMOTION_LEXICON.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}", text_lower):
                    scores[emotion] += 1

        best_emotion = "neutral"
        best_count = 0
        for em, count in scores.items():
            if count > best_count:
                best_count = count
                best_emotion = em

        conf = 0.85 if best_count >= 2 else (0.65 if best_count == 1 else 0.50)
        return best_emotion, conf

    def analyze(
        self,
        audio_input: Union[str, Path, np.ndarray],
        transcript_segments: List[CanonicalTranscriptSegment]
    ) -> List[EmotionResult]:
        """Computes model-estimated emotional characteristics for each transcript segment."""
        if isinstance(audio_input, (str, Path)):
            audio_data, sr = sf.read(str(audio_input), dtype="float32")
        else:
            audio_data = audio_input.astype(np.float32)
            sr = self.sample_rate

        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=-1)

        results: List[EmotionResult] = []

        for seg in transcript_segments:
            start_samp = int(seg.start * sr)
            end_samp = min(int(seg.end * sr), len(audio_data))
            audio_slice = audio_data[start_samp:end_samp] if end_samp > start_samp else np.zeros(512, dtype=np.float32)

            # Acoustic analysis
            arousal, valence, _ = self._extract_acoustic_prosody(audio_slice)

            # Linguistic analysis
            ling_emotion, ling_conf = self._analyze_linguistic_emotion(seg.text)

            # Multi-modal fusion
            if ling_emotion != "neutral":
                final_emotion = ling_emotion
                confidence = round((ling_conf * 0.6) + (arousal * 0.4), 2)
            else:
                # Deduce from acoustic prosody if text is emotionally neutral
                if arousal > 0.75:
                    final_emotion = "excitement" if valence >= 0.5 else "frustration"
                    confidence = 0.65
                elif arousal < 0.20 and valence < 0.4:
                    final_emotion = "sad"
                    confidence = 0.60
                else:
                    final_emotion = "neutral"
                    confidence = 0.80

            confidence = min(max(confidence, 0.40), 0.95)

            uncertainty = "LOW" if confidence >= 0.80 else ("MEDIUM" if confidence >= 0.60 else "HIGH")

            results.append(EmotionResult(
                speaker=seg.speaker,
                start=seg.start,
                end=seg.end,
                segment_id=seg.id,
                emotion=final_emotion,
                confidence=confidence,
                acoustic_arousal=arousal,
                acoustic_valence=valence,
                uncertainty_level=uncertainty,
                note="Model-estimated emotional characteristics"
            ))

        logger.info(f"Analyzed emotions for {len(results)} transcript segments.")
        return results


def analyze_emotions(
    audio_path: Union[str, Path],
    transcript_segments: List[CanonicalTranscriptSegment]
) -> List[EmotionResult]:
    """Convenience function to analyze emotions."""
    analyzer = EmotionAnalyzer()
    return analyzer.analyze(audio_path, transcript_segments)
