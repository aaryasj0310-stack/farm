"""Offline Acoustic & Spectral Feature Clustering Speaker Diarization Engine."""
from pathlib import Path
from typing import List, Optional, Union
import librosa
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
import soundfile as sf
from app.models.schemas import DiarizationSegment, VADSegment
from app.utils.logger import get_logger

logger = get_logger("diarization.spectral")


class SpectralDiarizationEngine:
    """Zero-dependency local offline speaker diarization using acoustic feature clustering."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def _extract_acoustic_features(self, audio_slice: np.ndarray) -> np.ndarray:
        """Extracts dense acoustic embedding vector (MFCCs, spectral features, chroma)."""
        if len(audio_slice) < 512:
            return np.zeros(64, dtype=np.float32)

        # 1. 20 MFCCs + deltas
        mfccs = librosa.feature.mfcc(y=audio_slice, sr=self.sample_rate, n_mfcc=20)
        mfcc_mean = np.mean(mfccs, axis=1)
        mfcc_std = np.std(mfccs, axis=1)

        delta_mfccs = librosa.feature.delta(mfccs)
        delta_mean = np.mean(delta_mfccs, axis=1)

        # 2. Spectral centroid & bandwidth
        centroid = librosa.feature.spectral_centroid(y=audio_slice, sr=self.sample_rate)
        centroid_mean = np.mean(centroid)
        bandwidth = librosa.feature.spectral_bandwidth(y=audio_slice, sr=self.sample_rate)
        bandwidth_mean = np.mean(bandwidth)

        # 3. Zero crossing rate & RMS
        zcr = np.mean(librosa.feature.zero_crossing_rate(y=audio_slice))
        rms = np.mean(librosa.feature.rms(y=audio_slice))

        # 4. Spectral rolloff
        rolloff = np.mean(librosa.feature.spectral_rolloff(y=audio_slice, sr=self.sample_rate))

        # Concatenate into normalized feature vector
        features = np.concatenate([
            mfcc_mean,
            mfcc_std,
            delta_mean,
            [centroid_mean, bandwidth_mean, zcr, rms, rolloff]
        ])
        
        # Normalize
        norm = np.linalg.norm(features)
        if norm > 1e-6:
            features = features / norm
        return features.astype(np.float32)

    def diarize(
        self,
        audio_input: Union[str, Path, np.ndarray],
        vad_segments: Optional[List[VADSegment]] = None,
        max_speakers: int = 6
    ) -> List[DiarizationSegment]:
        """Segments speech into speaker turns with SPEAKER_00, SPEAKER_01, etc."""
        if isinstance(audio_input, (str, Path)):
            data, sr = sf.read(str(audio_input), dtype="float32")
        else:
            data = audio_input.astype(np.float32)
            sr = self.sample_rate

        if data.ndim > 1:
            data = np.mean(data, axis=-1)

        total_duration = len(data) / sr

        # If no VAD segments provided, create uniform 1.5s sliding windows
        slices = []
        if vad_segments and len(vad_segments) > 0:
            for seg in vad_segments:
                start_sample = int(seg.start * sr)
                end_sample = min(int(seg.end * sr), len(data))
                if (end_sample - start_sample) > int(0.2 * sr):  # min 200ms
                    slices.append((seg.start, seg.end, data[start_sample:end_sample]))
        else:
            window_size = int(1.5 * sr)
            hop_size = int(0.75 * sr)
            for s in range(0, len(data) - window_size // 2, hop_size):
                e = min(s + window_size, len(data))
                slices.append((s / sr, e / sr, data[s:e]))

        if not slices:
            return [DiarizationSegment(speaker="SPEAKER_00", start=0.0, end=round(total_duration, 3), duration=round(total_duration, 3))]

        # Single segment case
        if len(slices) == 1:
            return [DiarizationSegment(speaker="SPEAKER_00", start=slices[0][0], end=slices[0][1], duration=round(slices[0][1] - slices[0][0], 3))]

        # Extract feature vectors
        feature_matrix = np.array([self._extract_acoustic_features(slice_data) for _, _, slice_data in slices])

        # Determine optimal number of clusters (speakers) using silhouette score
        best_k = 1
        best_score = -1.0
        max_k = min(max_speakers, len(slices) - 1)

        if max_k >= 2:
            for k in range(2, max_k + 1):
                clustering = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
                labels = clustering.fit_predict(feature_matrix)
                # Ensure at least 2 distinct clusters were actually assigned
                if len(set(labels)) > 1:
                    score = silhouette_score(feature_matrix, labels, metric="cosine")
                    # Require minimum separation score to avoid over-clustering mono-dialogues
                    if score > 0.15 and score > best_score:
                        best_score = score
                        best_k = k

        logger.info(f"Optimal speaker count determined: {best_k} (separation score: {best_score:.2f})")

        if best_k == 1:
            assigned_labels = [0] * len(slices)
        else:
            clustering = AgglomerativeClustering(n_clusters=best_k, metric="cosine", linkage="average")
            assigned_labels = clustering.fit_predict(feature_matrix).tolist()

        # Map cluster IDs to sorted speaker labels based on first appearance
        label_map = {}
        speaker_idx = 0
        raw_segments = []

        for (start, end, _), label in zip(slices, assigned_labels):
            if label not in label_map:
                label_map[label] = f"SPEAKER_{speaker_idx:02d}"
                speaker_idx += 1
            speaker_name = label_map[label]
            raw_segments.append(DiarizationSegment(
                speaker=speaker_name,
                start=round(start, 3),
                end=round(end, 3),
                duration=round(end - start, 3)
            ))

        # Merge adjacent segments of the same speaker
        merged: List[DiarizationSegment] = []
        for seg in raw_segments:
            if not merged:
                merged.append(seg)
            else:
                last = merged[-1]
                if last.speaker == seg.speaker and (seg.start - last.end) < 0.5:
                    # Extend previous segment
                    merged[-1] = DiarizationSegment(
                        speaker=last.speaker,
                        start=last.start,
                        end=seg.end,
                        duration=round(seg.end - last.start, 3)
                    )
                else:
                    merged.append(seg)

        return merged
