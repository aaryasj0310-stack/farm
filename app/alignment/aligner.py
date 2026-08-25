"""Speaker and Transcript Alignment Module."""
from typing import List, Tuple
from app.models.schemas import (
    CanonicalTranscriptSegment,
    DiarizationSegment,
    SpeakerMetrics,
    WordTimestamp
)
from app.utils.logger import get_logger

logger = get_logger("alignment.aligner")


class SpeakerTranscriptAligner:
    """Aligns ASR segments and words to speaker diarization intervals."""

    @staticmethod
    def _calculate_overlap(start1: float, end1: float, start2: float, end2: float) -> float:
        """Computes overlap duration between two time intervals."""
        overlap_start = max(start1, start2)
        overlap_end = min(end1, end2)
        return max(0.0, overlap_end - overlap_start)

    def align(
        self,
        transcript_segments: List[CanonicalTranscriptSegment],
        diarization_segments: List[DiarizationSegment],
        total_audio_duration: float
    ) -> Tuple[List[CanonicalTranscriptSegment], List[SpeakerMetrics]]:
        """Attributes speakers to transcript segments based on temporal overlap and calculates metrics.
        
        Returns (aligned_segments, speaker_metrics).
        """
        if not transcript_segments:
            return [], []

        if not diarization_segments:
            # Fallback to SPEAKER_00 for all segments
            diarization_segments = [
                DiarizationSegment(
                    speaker="SPEAKER_00",
                    start=0.0,
                    end=total_audio_duration,
                    duration=total_audio_duration
                )
            ]

        aligned_segments: List[CanonicalTranscriptSegment] = []
        speaker_times: dict[str, float] = {}
        speaker_segment_counts: dict[str, int] = {}

        for seg in transcript_segments:
            seg_start = seg.start
            seg_end = seg.end
            seg_duration = max(seg_end - seg_start, 0.01)

            # Compute overlap with all diarization intervals
            overlap_by_speaker: dict[str, float] = {}
            for d_seg in diarization_segments:
                overlap = self._calculate_overlap(seg_start, seg_end, d_seg.start, d_seg.end)
                if overlap > 0:
                    overlap_by_speaker[d_seg.speaker] = overlap_by_speaker.get(d_seg.speaker, 0.0) + overlap

            if overlap_by_speaker:
                best_speaker = max(overlap_by_speaker, key=overlap_by_speaker.get)
                max_overlap = overlap_by_speaker[best_speaker]
                overlap_ratio = max_overlap / seg_duration
                
                # Check uncertainty
                uncertainty = seg.uncertainty
                if overlap_ratio < 0.6:
                    uncertainty = "HIGH"
                elif overlap_ratio < 0.8 and uncertainty == "LOW":
                    uncertainty = "MEDIUM"
            else:
                # Find the temporally nearest diarization segment
                nearest_d = min(
                    diarization_segments,
                    key=lambda d: min(abs(d.start - seg_end), abs(d.end - seg_start))
                )
                best_speaker = nearest_d.speaker
                uncertainty = "HIGH"

            # Align individual words if available
            aligned_words: List[WordTimestamp] = []
            for w in seg.words:
                w_speaker = best_speaker
                w_overlap = {}
                for d_seg in diarization_segments:
                    o = self._calculate_overlap(w.start, w.end, d_seg.start, d_seg.end)
                    if o > 0:
                        w_overlap[d_seg.speaker] = w_overlap.get(d_seg.speaker, 0.0) + o
                if w_overlap:
                    w_speaker = max(w_overlap, key=w_overlap.get)
                
                aligned_words.append(WordTimestamp(
                    word=w.word,
                    start=w.start,
                    end=w.end,
                    confidence=w.confidence
                ))

            # Track metrics
            speaker_times[best_speaker] = speaker_times.get(best_speaker, 0.0) + seg_duration
            speaker_segment_counts[best_speaker] = speaker_segment_counts.get(best_speaker, 0) + 1

            aligned_segments.append(CanonicalTranscriptSegment(
                id=seg.id,
                speaker=best_speaker,
                start=seg.start,
                end=seg.end,
                text=seg.text,
                confidence=seg.confidence,
                words=aligned_words,
                uncertainty=uncertainty
            ))

        # Calculate speaker metrics
        total_spoken_time = sum(speaker_times.values()) or 1.0
        metrics: List[SpeakerMetrics] = []
        for spk, duration in sorted(speaker_times.items()):
            metrics.append(SpeakerMetrics(
                speaker_id=spk,
                total_speech_time=round(duration, 2),
                percentage_of_conversation=round((duration / total_spoken_time) * 100.0, 1),
                segment_count=speaker_segment_counts.get(spk, 0)
            ))

        logger.info(f"Aligned {len(aligned_segments)} segments across {len(metrics)} speakers.")
        return aligned_segments, metrics


def align_speakers_and_transcript(
    transcript_segments: List[CanonicalTranscriptSegment],
    diarization_segments: List[DiarizationSegment],
    total_audio_duration: float
) -> Tuple[List[CanonicalTranscriptSegment], List[SpeakerMetrics]]:
    """Convenience function to run alignment."""
    aligner = SpeakerTranscriptAligner()
    return aligner.align(transcript_segments, diarization_segments, total_audio_duration)
