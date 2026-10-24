"""Többszólamú hangfelismerés a gitárkottához (#319): a Spotify basic-pitch modellje (ICASSP 2022, Apache-2.0)
ONNX-ben, a basic-pitch előfeldolgozása és hangjegy-kiolvasása numpy-ra átírva (a csomag maga a sok
függőségével nem kell). Kell hozzá: numpy, onnxruntime, ffmpeg, és a modell (nmp.onnx).
Forrás: https://github.com/spotify/basic-pitch (inference.py, note_creation.py, constants.py).
"""
import os
import subprocess

FFT_HOP = 256
SR = 22050
WINDOW_S = 2
FPS = SR // FFT_HOP
ANNOT_N_FRAMES = FPS * WINDOW_S
N_SAMPLES = SR * WINDOW_S - FFT_HOP
N_OVERLAP_FRAMES = 30
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87

MODEL_PATHS = [os.environ.get("MUZIKOS_BASIC_PITCH", ""), "/usr/share/muzikos/basic-pitch/nmp.onnx",
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "nmp.onnx"),
               os.path.expanduser("~/.local/share/muzikos/nmp.onnx")]


def model_path():
    for p in MODEL_PATHS:
        if p and os.path.exists(p):
            return p
    return None


def available():
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return model_path() is not None


def load_audio(path):
    """Mono, 22 050 Hz float32 (ffmpeg-gel: bármilyen formátumból)."""
    import numpy as np
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=600).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def infer(audio):
    """A modell kimenete: hang- és hangkezdet-valószínűség (keret × 88 félhang)."""
    import numpy as np
    import onnxruntime as ort
    sess = ort.InferenceSession(model_path(), providers=["CPUExecutionProvider"])
    overlap = N_OVERLAP_FRAMES * FFT_HOP
    hop = N_SAMPLES - overlap
    orig = len(audio)
    a = np.concatenate([np.zeros(overlap // 2, dtype=np.float32), audio])
    wins = []
    for i in range(0, len(a), hop):
        w = a[i:i + N_SAMPLES]
        if len(w) < N_SAMPLES:
            w = np.pad(w, (0, N_SAMPLES - len(w)))
        wins.append(w)
    notes, onsets = [], []
    for k in range(0, len(wins), 16):
        batch = np.stack(wins[k:k + 16])[:, :, None].astype(np.float32)
        n, o = sess.run(["StatefulPartitionedCall:1", "StatefulPartitionedCall:2"], {"serving_default_input_2:0": batch})
        notes.append(n)
        onsets.append(o)

    def unwrap(x):
        x = np.concatenate(x)
        h = N_OVERLAP_FRAMES // 2
        x = x[:, h:-h, :]
        x = x.reshape(-1, x.shape[2])
        return x[:int(np.floor(orig * (FPS / SR)))]

    return unwrap(notes), unwrap(onsets)


def frames_to_time(n):
    import numpy as np
    t = np.arange(n) * FFT_HOP / SR
    win = np.floor(np.arange(n) / ANNOT_N_FRAMES)
    off = (FFT_HOP / SR) * (ANNOT_N_FRAMES - (N_SAMPLES / FFT_HOP)) + 0.0018
    return t - off * win


def inferred_onsets(onsets, frames, n_diff=2):
    import numpy as np
    diffs = []
    for n in range(1, n_diff + 1):
        fa = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(fa[n:, :] - fa[:-n, :])
    fd = np.min(diffs, axis=0)
    fd[fd < 0] = 0
    fd[:n_diff, :] = 0
    if fd.max() > 0:
        fd = onsets.max() * fd / fd.max()
    return np.maximum(onsets, fd)


def to_notes(frames, onsets, onset_thresh=0.5, frame_thresh=0.3, min_note_ms=127.7, min_midi=None, max_midi=None,
             energy_tol=11, melodia=True):
    """A basic-pitch output_to_notes_polyphonic-ja: (kezdet mp, vég mp, MIDI, erősség 0–1)."""
    import numpy as np
    frames, onsets = frames.copy(), onsets.copy()
    if max_midi is not None:
        frames[:, max(0, max_midi - MIDI_OFFSET + 1):] = 0
        onsets[:, max(0, max_midi - MIDI_OFFSET + 1):] = 0
    if min_midi is not None:
        frames[:, :max(0, min_midi - MIDI_OFFSET)] = 0
        onsets[:, :max(0, min_midi - MIDI_OFFSET)] = 0
    min_len = int(np.round(min_note_ms / 1000 * (SR / FFT_HOP)))
    n_frames = frames.shape[0]
    onsets = inferred_onsets(onsets, frames)
    peak = np.zeros_like(onsets)
    if n_frames > 2:     # helyi csúcs időben (scipy.signal.argrelmax, axis=0)
        mid = (onsets[1:-1] > onsets[:-2]) & (onsets[1:-1] > onsets[2:])
        peak[1:-1][mid] = onsets[1:-1][mid]
    ti, fi = np.where(peak >= onset_thresh)
    order = np.argsort(-ti, kind="stable")      # visszafelé az időben
    rem = frames.copy()
    events = []
    for s, f in zip(ti[order], fi[order]):
        if s >= n_frames - 1:
            continue
        i, k = s + 1, 0
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if rem[i, f] < frame_thresh else 0
            i += 1
        i -= k
        if i - s <= min_len:
            continue
        rem[s:i, f] = 0
        if f < MAX_FREQ_IDX:
            rem[s:i, f + 1] = 0
        if f > 0:
            rem[s:i, f - 1] = 0
        events.append((s, i, f + MIDI_OFFSET, float(frames[s:i, f].mean())))
    if melodia:
        while rem.max() > frame_thresh:
            im, f = np.unravel_index(np.argmax(rem), rem.shape)
            rem[im, f] = 0
            i, k = im + 1, 0
            while i < n_frames - 1 and k < energy_tol:
                k = k + 1 if rem[i, f] < frame_thresh else 0
                rem[i, f] = 0
                if f < MAX_FREQ_IDX:
                    rem[i, f + 1] = 0
                if f > 0:
                    rem[i, f - 1] = 0
                i += 1
            i_end = i - 1 - k
            i, k = im - 1, 0
            while i > 0 and k < energy_tol:
                k = k + 1 if rem[i, f] < frame_thresh else 0
                rem[i, f] = 0
                if f < MAX_FREQ_IDX:
                    rem[i, f + 1] = 0
                if f > 0:
                    rem[i, f - 1] = 0
                i -= 1
            i_start = i + 1 + k
            if i_end - i_start <= min_len:
                continue
            events.append((i_start, i_end, f + MIDI_OFFSET, float(frames[i_start:i_end, f].mean())))
    t = frames_to_time(n_frames + 1)
    return sorted(((float(t[a]), float(t[b]), int(m), amp) for a, b, m, amp in events), key=lambda e: (e[0], e[2]))


def transcribe(path, min_midi=None, max_midi=None, onset_thresh=0.5, frame_thresh=0.3):
    frames, onsets = infer(load_audio(path))
    return to_notes(frames, onsets, onset_thresh, frame_thresh, min_midi=min_midi, max_midi=max_midi)
