# Test Audio Fixtures & Instructions

## 1. Automated Synthetic Audio Generation
To allow completely self-contained automated testing without committing copyrighted audio binaries to version control, run:
```powershell
python tests/fixtures/generate_synthetic_fixture.py
```
This will generate `tests/fixtures/sample_dialogue_16k.wav`.

## 2. Using Real Hindi Audio Recordings
To test the pipeline with your own real-world Hindi or Hinglish audio recordings:
1. Place your audio file in `data/` or any local folder (e.g. `meeting_hindi.mp3`).
2. Supported formats:
   - MP3 (`.mp3`)
   - WAV (`.wav`)
   - M4A (`.m4a`)
   - FLAC (`.flac`)
   - AAC (`.aac`)
   - OGG (`.ogg`)
3. Run analysis via CLI:
   ```powershell
   python -m app analyze meeting_hindi.mp3 --output meeting_report.json
   ```
4. Or launch the Web Dashboard:
   ```powershell
   python -m app serve
   ```
   Open `http://localhost:8000` in your browser and upload the recording.
