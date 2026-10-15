"""Tempo and beat-phase estimation for background music (NumPy only, deterministic).

Onset strength = positive spectral flux of a log-magnitude STFT. Tempo = autocorrelation peak of the
onset envelope in 60-180 BPM with a mild preference around 120 BPM. Phase = offset whose beat grid
collects the most onset energy. Returns None when the rhythm is too weak to sync to honestly.
"""
from __future__ import annotations

import numpy as np

from video_editor.ffmpeg_ops import run_process

SR = 22050
HOP = 512
NFFT = 1024


def _decode(path: str, seconds: float) -> np.ndarray:
    res = run_process(["ffmpeg", "-v", "error", "-t", f"{seconds:.1f}", "-i", path, "-vn", "-ac", "1",
                       "-ar", str(SR), "-f", "s16le", "-"], text=False)
    if res.returncode != 0 or not res.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def onset_envelope(y: np.ndarray) -> np.ndarray:
    if len(y) < NFFT * 4:
        return np.zeros(0)
    frames = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(NFFT), axis=1))
    logspec = np.log1p(100 * spec)
    flux = np.maximum(0.0, np.diff(logspec, axis=0)).sum(axis=1)
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")  # remove slow loudness drift
    flux = np.maximum(flux, 0)
    return flux / (flux.max() or 1.0)


def estimate(path: str, seconds: float = 120.0) -> dict | None:
    env = onset_envelope(_decode(path, seconds))
    if len(env) < 200:
        return None
    fr = SR / HOP  # envelope frames per second
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0] or 1.0
    lags = np.arange(int(fr * 60 / 180), int(fr * 60 / 60) + 1)
    bpm = 60.0 * fr / lags
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = ac[lags] * prior
    best = int(np.argmax(score))
    lag = int(lags[best])
    # refine to sub-frame precision with a parabola through the peak
    if 0 < best < len(lags) - 1:
        a, b, c = score[best - 1], score[best], score[best + 1]
        denom = a - 2 * b + c
        lag_f = lag + (0.5 * (a - c) / denom if denom else 0.0)
    else:
        lag_f = float(lag)
    confidence = float(ac[lag])
    if confidence < 0.08:
        return None
    # Envelope index i measures the change into STFT frame i+1, whose centre is (i+1)*HOP + NFFT/2 samples.
    t0 = (HOP + NFFT / 2) / SR
    times = np.arange(len(env)) / fr + t0
    # Jointly refine period and phase so the grid stays locked over the whole track (no integer-lag drift).
    best_score, period, offset = -1.0, lag_f / fr, 0.0
    for p in np.linspace(lag_f / fr * 0.98, lag_f / fr * 1.02, 81):
        for ph in np.arange(0.0, p, 1.0 / fr):
            grid = np.arange(ph, times[-1], p)
            idx = np.clip(np.round((grid - t0) * fr).astype(int), 0, len(env) - 1)
            score = float(env[idx].mean())
            if score > best_score:
                best_score, period, offset = score, float(p), float(ph)
    return {"bpm": round(60.0 / period, 2), "period": round(period, 4), "offset": round(offset, 4),
            "confidence": round(confidence, 3)}
