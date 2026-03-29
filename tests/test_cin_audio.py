"""Tests for audio analysis module."""
import pytest
import numpy as np


def test_compute_energy_envelope():
    from app.cin.audio_analysis import compute_energy_envelope
    sr = 44100
    t = np.linspace(0, 1.0, sr)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    envelope = compute_energy_envelope(audio, sr, hop_size=4410)
    assert len(envelope) == 10
    assert all(e >= 0 for e in envelope)


def test_find_emphasis_points():
    from app.cin.audio_analysis import find_emphasis_points
    envelope = [0.1, 0.2, 0.9, 0.2, 0.1, 0.8, 0.1, 0.1, 0.7, 0.1]
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    peaks = find_emphasis_points(envelope, times, threshold=0.6)
    assert len(peaks) >= 2


def test_detect_pauses():
    from app.cin.audio_analysis import detect_pauses
    envelope = [0.5, 0.5, 0.01, 0.01, 0.01, 0.5, 0.5, 0.01, 0.01, 0.5]
    times = [i * 0.1 for i in range(10)]
    pauses = detect_pauses(envelope, times, silence_threshold=0.05, min_duration=0.2)
    assert len(pauses) >= 1


def test_analyze_audio_full(tmp_path):
    from app.cin.audio_analysis import analyze_audio
    import wave, struct
    sr = 16000
    duration = 2.0
    samples = int(sr * duration)
    audio_data = [int(32767 * np.sin(2 * np.pi * 440 * i / sr)) for i in range(samples)]
    wav_path = str(tmp_path / "test.wav")
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"{len(audio_data)}h", *audio_data))
    result = analyze_audio(wav_path)
    assert "energy_envelope" in result
    assert "emphasis_points" in result
    assert "pauses" in result
    assert "duration" in result
