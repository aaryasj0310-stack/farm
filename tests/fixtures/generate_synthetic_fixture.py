"""Generates synthetic multi-turn audio fixture for automated pipeline testing."""
from pathlib import Path
import numpy as np
import soundfile as sf


def create_synthetic_audio(output_path: Path | str, sample_rate: int = 16000) -> Path:
    """Generates a 6-second multi-speaker synthetic audio waveform."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sr = sample_rate
    # Speaker 1 Turn 1 (0.5s to 2.5s) - 200 Hz tone harmonic
    t1 = np.linspace(0, 2.0, int(sr * 2.0), endpoint=False)
    turn1 = (0.35 * np.sin(2 * np.pi * 200 * t1) + 0.15 * np.sin(2 * np.pi * 400 * t1)).astype(np.float32)

    # Silence (0.8s)
    silence = np.zeros(int(sr * 0.8), dtype=np.float32)

    # Speaker 2 Turn 2 (3.3s to 5.5s) - 500 Hz tone harmonic
    t2 = np.linspace(0, 2.2, int(sr * 2.2), endpoint=False)
    turn2 = (0.35 * np.sin(2 * np.pi * 500 * t2) + 0.15 * np.sin(2 * np.pi * 1000 * t2)).astype(np.float32)

    # Concatenate: 0.5s silence + turn1 + silence + turn2 + 0.5s silence
    init_silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    end_silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    full_audio = np.concatenate([init_silence, turn1, silence, turn2, end_silence])

    sf.write(str(output_path), full_audio, sr)
    return output_path


if __name__ == "__main__":
    out = Path(__file__).parent / "sample_dialogue_16k.wav"
    create_synthetic_audio(out)
    print(f"Generated synthetic test fixture at: {out}")
