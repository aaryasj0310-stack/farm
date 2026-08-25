"""Quality and Performance Benchmarking Script for Hindi Audio Intelligence Pipeline."""
import argparse
import json
import time
import os
import sys
from pathlib import Path
import psutil

# Add repository root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import settings
from app.pipeline.orchestrator import AudioIntelligencePipeline
from tests.fixtures.generate_synthetic_fixture import create_synthetic_audio


def calculate_wer(reference: str, hypothesis: str) -> float:
    """Calculates Word Error Rate (WER) using Levenshtein distance."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j] + 1,      # deletion
                    d[i][j - 1] + 1,      # insertion
                    d[i - 1][j - 1] + 1   # substitution
                )
    return d[len(ref_words)][len(hyp_words)] / len(ref_words)


def calculate_cer(reference: str, hypothesis: str) -> float:
    """Calculates Character Error Rate (CER) for Devanagari Hindi text."""
    ref_chars = list(reference.replace(" ", ""))
    hyp_chars = list(hypothesis.replace(" ", ""))

    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0

    d = [[0] * (len(hyp_chars) + 1) for _ in range(len(ref_chars) + 1)]
    for i in range(len(ref_chars) + 1):
        d[i][0] = i
    for j in range(len(hyp_chars) + 1):
        d[0][j] = j

    for i in range(1, len(ref_chars) + 1):
        for j in range(1, len(hyp_chars) + 1):
            if ref_chars[i - 1] == hyp_chars[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j] + 1,
                    d[i][j - 1] + 1,
                    d[i - 1][j - 1] + 1
                )
    return d[len(ref_chars)][len(hyp_chars)] / len(ref_chars)


def run_benchmark(audio_file: Optional[str] = None, reference_transcript: Optional[str] = None, output_json: Optional[str] = None):
    print("=" * 60)
    print(" HINDI AUDIO INTELLIGENCE PIPELINE — PERFORMANCE BENCHMARK")
    print("=" * 60)

    if not audio_file or not Path(audio_file).exists():
        temp_audio = Path("data/cache/benchmark_sample.wav")
        temp_audio.parent.mkdir(parents=True, exist_ok=True)
        create_synthetic_audio(temp_audio)
        audio_path = temp_audio
        print(f"Generated synthetic test audio at: {audio_path}")
    else:
        audio_path = Path(audio_file)

    process = psutil.Process(os.getpid())
    mem_before_mb = process.memory_info().rss / (1024 * 1024)

    pipeline = AudioIntelligencePipeline()

    job_id = f"bench_{int(time.time())}"
    start_time = time.time()
    
    result = pipeline.process_job(job_id=job_id, audio_path=audio_path, language="hi")
    
    total_time = time.time() - start_time
    mem_after_mb = process.memory_info().rss / (1024 * 1024)
    mem_peak_mb = mem_after_mb - mem_before_mb

    audio_duration = result.audio_metadata.duration_seconds if result.audio_metadata else 1.0
    rtf = total_time / max(audio_duration, 0.001)

    hypothesis_text = " ".join([s.text for s in result.transcript])

    wer, cer = None, None
    if reference_transcript:
        wer = round(calculate_wer(reference_transcript, hypothesis_text) * 100, 2)
        cer = round(calculate_cer(reference_transcript, hypothesis_text) * 100, 2)

    bench_data = {
        "job_id": job_id,
        "audio_file": str(audio_path.name),
        "audio_duration_sec": audio_duration,
        "processing_time_sec": round(total_time, 2),
        "real_time_factor_rtf": round(rtf, 3),
        "memory_peak_mb": round(mem_peak_mb, 2),
        "speakers_detected": len(result.speakers),
        "speech_segments": len(result.transcript),
        "claims_extracted": len(result.claims),
        "contradictions_detected": len(result.contradictions),
        "device_used": settings.get_effective_device(),
        "asr_model": settings.ASR_MODEL_SIZE,
        "wer_percentage": wer,
        "cer_percentage": cer
    }

    print("\nBENCHMARK RESULTS:")
    print(f"  • Audio Duration:     {audio_duration:.2f} seconds")
    print(f"  • Total Processing:   {total_time:.2f} seconds")
    print(f"  • Real-Time Factor:   {rtf:.3f}x RTF (Lower is faster)")
    print(f"  • Memory delta:       {mem_peak_mb:.1f} MB")
    print(f"  • Speakers Count:     {len(result.speakers)}")
    print(f"  • Speech Segments:    {len(result.transcript)}")
    print(f"  • Claims Extracted:   {len(result.claims)}")
    if wer is not None:
        print(f"  • Word Error Rate:    {wer}%")
        print(f"  • Char Error Rate:    {cer}%")
    print("=" * 60)

    if output_json:
        Path(output_json).write_text(json.dumps(bench_data, indent=2), encoding="utf-8")
        print(f"Saved benchmark data to: {output_json}")

    return bench_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pipeline benchmark")
    parser.add_argument("--audio", type=str, default=None, help="Input audio file")
    parser.add_argument("--ref", type=str, default=None, help="Reference transcript string")
    parser.add_argument("--output", type=str, default="benchmark_results.json", help="Output JSON path")
    args = parser.parse_args()

    run_benchmark(audio_file=args.audio, reference_transcript=args.ref, output_json=args.output)
