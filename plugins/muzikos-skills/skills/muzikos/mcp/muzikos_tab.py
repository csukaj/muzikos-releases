"""Gitár- és basszusfelvételből Guitar Pro-kotta (.gp5) a MuzikOS-en (#319).

Egyszólamú felvétel (DI, effekt nélkül, metronómra) → hangmagasság-követés (YIN) → hangjegyek (hangkezdet és
hangmagasság-váltás) → ritmusrácsra igazítás a tempó alapján → húr és bund (a legkisebb kézmozgás) → .gp5
(PyGuitarPro). MIDI-s sávból (MIDI-hangszedő) a hangjegyek egyenesen jönnek, a hangfelismerés kimarad.
Csak numpy kell hozzá (és a .gp5-höz a PyGuitarPro); a szerver a Reaperből adja a felvételt és a tempót.
"""
import math
import wave

TUNINGS = {   # húrok a legmagasabbtól (1.) a legmélyebbig, MIDI-hangmagassággal
    "guitar": [64, 59, 55, 50, 45, 40],
    "drop d": [64, 59, 55, 50, 45, 38],
    "d": [62, 57, 53, 48, 43, 38],                 # D-hangolás (egy egész hanggal lejjebb): D G C F A D
    "drop c": [62, 57, 53, 48, 43, 36],
    "bass": [43, 38, 33, 28],
    "bass5": [43, 38, 33, 28, 23],
    "d bass": [41, 36, 31, 26],
    "d bass5": [41, 36, 31, 26, 21],
}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "H"]
PC = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
      "AB": 8, "A": 9, "A#": 10, "B": 10, "BB": 10, "H": 11}


def note_name(m):
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def parse_tuning(spec, instrument="guitar"):
    """Hangolás a legmagasabb húrtól lefelé (MIDI). Elfogad: nevet (TUNINGS: „d”, „drop d”, „bass5”…),
    MIDI-listát (bármilyen sorrendben), vagy hangneveket mélyről felfelé („D G C F A D”, „A D G C F”,
    oktávval is: „D2 G2 …”). Oktáv nélkül a legmélyebb húr gitárnál a 2., basszusnál a 0./1. oktávban van."""
    if not spec:
        return None
    if isinstance(spec, (list, tuple)):
        vals = [int(v) for v in spec]
        return sorted(vals, reverse=True)
    s = str(spec).strip().lower()
    key = s.replace("-hangolás", "").replace(" hangolás", "").strip()
    if instrument == "bass" and not key.startswith(("bass", "d bass")):
        key2 = ("d bass" if key == "d" else key)
        if key2 in TUNINGS:
            return TUNINGS[key2]
    if key in TUNINGS:
        return TUNINGS[key]
    toks = str(spec).replace(",", " ").split()
    out, prev = [], None
    for t in toks:
        m = __import__("re").match(r"^([A-Ha-h][#b]?)(-?\d)?$", t)
        if not m or m.group(1).upper() not in PC:
            raise ValueError(f"Ezt a hangolást nem értem: {spec}")
        pc = PC[m.group(1).upper()]
        if m.group(2) is not None:
            v = (int(m.group(2)) + 1) * 12 + pc
        elif prev is None:
            octave = 2 if instrument != "bass" else (0 if len(toks) >= 5 else 1)
            v = (octave + 1) * 12 + pc
        else:
            v = prev + ((pc - prev) % 12 or 12)
        out.append(v)
        prev = v
    return sorted(out, reverse=True)


# ----------------------------------------------------------------------------- hang beolvasása

def read_wav(path):
    """Mono float tömb és mintavétel; 16, 24 és 32 bites PCM-et olvas."""
    import numpy as np
    with wave.open(path, "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = (np.where(v & 0x800000, v - 0x1000000, v)).astype(np.float32) / 8388608.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Ezt a wav-ot nem tudom olvasni ({8 * width} bit).")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def read_audio(path):
    """wav közvetlenül, minden más (flac, mp3, ogg) ffmpeg-gel wav-vá alakítva."""
    if path.lower().endswith(".wav"):
        try:
            return read_wav(path)
        except (wave.Error, ValueError):
            pass   # pl. lebegőpontos wav: menjen ffmpeg-en át
    import subprocess
    import tempfile
    import os
    tmp = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1", "-c:a", "pcm_s16le", tmp],
                       check=True, capture_output=True, timeout=300)
        return read_wav(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def decimate(x, sr, target=12000):
    """Aluláteresztő szűrés (ablakolt sinc) és ritkítás: a gitár alaphangjához bőven elég ~12 kHz."""
    import numpy as np
    q = max(1, int(sr // target))
    if q == 1:
        return x, sr
    n = np.arange(-48, 49)
    h = np.sinc(n / q * 0.9) * np.hamming(len(n))
    h /= h.sum()
    return np.convolve(x, h, mode="same")[::q].astype(np.float32), sr / q


# ----------------------------------------------------------------------------- hangmagasság (YIN)

def pitch_track(x, sr, fmin=60.0, fmax=1400.0, hop_s=0.01, win_s=0.085, threshold=0.15):
    """Keretenként alaphang (Hz, 0 = nincs) és hangerő (dBFS). YIN: de Cheveigné és Kawahara, 2002."""
    import numpy as np
    x, sr = decimate(x, sr)
    W = int(win_s * sr)
    hop = max(1, int(hop_s * sr))
    tau_min, tau_max = max(2, int(sr / fmax)), min(W // 2, int(sr / fmin) + 1)
    if len(x) < W:
        x = np.pad(x, (0, W - len(x)))
    n = 1 + (len(x) - W) // hop
    idx = np.arange(W)[None, :] + hop * np.arange(n)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(axis=1, keepdims=True)
    rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    F = np.fft.rfft(fr, 2 * W, axis=1)
    acf = np.fft.irfft(F * np.conj(F), axis=1)[:, :tau_max + 1]
    cs = np.concatenate([np.zeros((n, 1)), np.cumsum(fr ** 2, axis=1)], axis=1)
    taus = np.arange(tau_max + 1)
    e0 = cs[:, W - taus]                 # sum x[j]^2, j < W - tau
    e1 = cs[:, W:W + 1] - cs[:, taus]    # sum x[j]^2, tau <= j < W
    d = np.maximum(e0 + e1 - 2 * acf, 0)
    cm = np.ones_like(d)
    csum = np.cumsum(d[:, 1:], axis=1)
    cm[:, 1:] = d[:, 1:] * taus[1:] / np.maximum(csum, 1e-12)
    f0 = np.zeros(n)
    for i in range(n):
        c = cm[i]
        tau = 0
        below = np.nonzero(c[tau_min:tau_max] < threshold)[0]
        if len(below):
            t = below[0] + tau_min
            while t + 1 < tau_max and c[t + 1] < c[t]:
                t += 1
            tau = t
        else:
            t = int(np.argmin(c[tau_min:tau_max])) + tau_min
            if c[t] < 0.35:
                tau = t
        if tau:
            a, b, cc = c[tau - 1], c[tau], c[tau + 1] if tau + 1 <= tau_max else c[tau]
            den = a - 2 * b + cc
            shift = 0.5 * (a - cc) / den if abs(den) > 1e-12 else 0.0
            f0[i] = sr / (tau + max(-0.5, min(0.5, shift)))
    times = (np.arange(n) * hop + W / 2) / sr
    # hangkezdet-erősség: a spektrum pozitív változása (spectral flux); az újrapengetés akkor is látszik, ha a
    # hang ugyanaz, és az előző még cseng
    lm = np.log1p(100 * np.abs(F))
    flux = np.zeros(n)
    flux[1:] = np.maximum(lm[1:] - lm[:-1], 0).sum(axis=1)
    return times, f0, db, flux


def onsets_from_flux(flux, db, gate, spread=3, window=25, k=1.6):
    """Hangkezdet-keretek: a flux helyi csúcsa, ami kiemelkedik a környezetéből, és van hang."""
    import numpy as np
    out = []
    for i in range(1, len(flux)):
        a, b = max(0, i - spread), min(len(flux), i + spread + 1)
        if flux[i] < flux[a:b].max() or db[i] < gate:
            continue
        loc = flux[max(0, i - window):i + window]
        if flux[i] > k * np.median(loc) + 0.05 * flux.max():
            if not out or i - out[-1] > spread:
                out.append(i)
    return out


# ----------------------------------------------------------------------------- hangjegyek

def segment_pitch(vals):
    """Egy szakasz hangja: a leggyakoribb hangnév (az oktávtévesztések is rá szavaznak), és ezen belül a
    leggyakoribb oktáv."""
    import numpy as np
    pcs = np.bincount(vals % 12, minlength=12)
    pc = int(pcs.argmax())
    same = vals[vals % 12 == pc]
    return int(np.bincount(same).argmax())


def play_level(db):
    """A játék szintje dBFS-ben: a nem csendes keretek 95. percentilise (a zaj és a legnagyobb csúcs sem húzza el).
    A kapu ehhez képest -30 dB, de nem mélyebb -60 dBFS-nél; a 38 mp-es felvételből, amiben csak 3–21 mp a játék,
    így a zajból nem lesz hang (#50)."""
    import numpy as np
    if not len(db):
        return -100.0
    loud = db[db > float(np.max(db)) - 40.0]
    return float(np.percentile(loud, 95)) if len(loud) else float(np.max(db))


def notes_from_pitch(times, f0, db, flux, min_len=0.05, gate_db=-30.0, settle=2):
    """Hangjegyek (kezdet mp, vég mp, MIDI, hangerő 0–1): a hangkezdetek (flux) közti szakaszok, és egy
    szakaszon belül új hang, ha a hangmagasság legalább 4 keretig (~40 ms) másik hangra vált (kötés, csúszás).
    A hangkezdet utáni első keretek (settle) nem szavaznak: a pengetés zaja ott még elviszi a hangmagasságot."""
    import numpy as np
    peak = play_level(db)
    gate = max(gate_db + peak, -60.0)            # a játék szintjéhez képest; a halk zaj (csend, zúgás) nem hang
    midi = np.full(len(f0), -1)
    ok = (f0 > 0) & (db > gate)
    midi[ok] = np.round(69 + 12 * np.log2(f0[ok] / 440.0)).astype(int)
    ons = onsets_from_flux(flux, db, gate)
    # hangkezdet ott is, ahol csend után hang indul (a flux nem mindig csúcsosodik)
    for i in range(1, len(midi)):
        if midi[i] >= 0 and all(midi[max(0, i - 3):i] < 0) and not any(abs(i - o) <= 3 for o in ons):
            ons.append(i)
    ons = sorted(ons)
    hop = times[1] - times[0] if len(times) > 1 else 0.01
    notes = []
    bounds = ons + [len(midi)]
    for a, b in zip(bounds, bounds[1:]):
        seg = list(range(a, b))
        # szakaszon belüli hangváltás: legalább 4 egymás utáni keret egy másik hangon (nem oktávnyira)
        cuts, run_m, run_n = [a], None, 0
        base = None
        for i in seg[settle:]:
            m = midi[i]
            if m < 0:
                run_m, run_n = None, 0
                continue
            if base is None:
                base = m
            if m != base and (m - base) % 12 != 0:
                run_n = run_n + 1 if m == run_m else 1
                run_m = m
                if run_n == 4:
                    cuts.append(i - 3)
                    base, run_m, run_n = m, None, 0
            else:
                run_m, run_n = None, 0
        cuts.append(b)
        for c0, c1 in zip(cuts, cuts[1:]):
            idx = [i for i in range(c0 + (settle if c0 == a else 0), c1) if midi[i] >= 0]
            if not idx:
                continue
            t0, t1 = float(times[c0]), float(times[idx[-1]] + hop)
            if t1 - t0 < min_len:
                continue
            m = segment_pitch(midi[idx])
            vel = min(1.0, max(0.1, (float(db[idx].max()) - gate) / 30.0))
            notes.append((t0, t1, m, vel))
    return notes


# ----------------------------------------------------------------------------- ritmus

def notes_from_envelope(x, sr, times, f0, db, gap, gate_db=-20.0, settle=0.04, win=0.25, rms_win=0.02):
    """Hangjegyek (kezdet mp, vég mp, MIDI, hangerő 0–1) egyszólamú, tiszta (akár torzított) jelből, a bevált „egyszerű riff”
    móddal (#50): a hangkezdet a simított burkoló ugrása (muzikos_fix.attacks, két hangkezdet közt legalább `gap` mp: a rács
    egysége), a hangmagasság a YIN-ből a hangkezdet után 40 ms-tól, legfeljebb 0,25 s-ig vett keretek leggyakoribb hangja.
    A flux-alapú felismerő a lecsengő, torzított basszuson ~70 ms-onként „hangot” talált (177 hang a valódi 53 helyett)."""
    import numpy as np
    import muzikos_fix as fix
    peak = play_level(db)
    gate = max(gate_db + peak, -60.0)
    ons = fix.attacks(x, sr, gap=gap, win_s=rms_win)
    hop = times[1] - times[0] if len(times) > 1 else 0.01
    notes = []
    for k, t in enumerate(ons):
        nxt = ons[k + 1] if k + 1 < len(ons) else None
        a, b = t + settle, min(t + win, (nxt - 0.01) if nxt else t + win)
        idx = np.nonzero((times >= a) & (times <= b) & (f0 > 0) & (db > gate))[0]
        if len(idx) < 2:
            continue
        midi = np.round(69 + 12 * np.log2(f0[idx] / 440.0)).astype(int)
        m = segment_pitch(midi)
        lim = nxt if nxt else t + 2.0
        live = np.nonzero((times >= t) & (times < lim) & (db > gate))[0]
        t1 = float(times[live[-1]] + hop) if len(live) else t + 0.1
        t1 = min(t1, lim)
        vel = min(1.0, max(0.1, (float(db[idx].max()) - gate) / 30.0))
        notes.append((float(t), float(t1), int(m), vel))
    return notes


def clean_notes(notes, tuning, max_fret=20, merge_gap=0.08, min_gap=0.0):
    """A felismert hangjegyek (kezdet mp, vég mp, MIDI, hangerő) tisztítása; visszaad: (hangok, jelentés).
    - hangtartomány a hangolásból: a legmélyebb húr alatti és a legmagasabb hang + max_fret feletti hang kitalált, eldobjuk;
    - oktáv: az a hang, ami a két szomszédjától is oktávnyira van (és a szomszédokhoz az oktávval közelebb kerül), a
      szomszédokhoz legközelebbi oktávra kerül (az oktávugrás-hang, ami mindkét szomszédjához közel van, marad);
    - szellemhangok: az rövid (< 0,15 s), azonos hangmagasságú, merge_gap-nél közelebbi töredék az előző hanggal egy hanggá olvad (a teljes hosszú ismételt hang nem); min_gap > 0 esetén
      az előző hangtól ennél közelebb induló hang eldobódik (egyszerű riffhez: ≥ az ütem nyolcada)."""
    rep = {"tartomany_alatt_felett": 0, "oktav_javitva": 0, "osszevont": 0, "tul_kozeli": 0}
    lo, hi = min(tuning) - 1, max(tuning) + max_fret + 1
    kept = []
    for n in notes:
        if lo <= n[2] <= hi:
            kept.append(list(n))
        else:
            rep["tartomany_alatt_felett"] += 1
    # oktáv-kiugrók
    orig = [n[2] for n in kept]                 # az eredeti hangokból számolunk: egy javítás nem téveszt meg egy másikat
    for i, n in enumerate(kept):
        if not 0 < i < len(kept) - 1:           # a két szélső hang oktávját egy szomszéd nem dönti el
            continue
        nb = [orig[i - 1], orig[i + 1]]
        for shift in (-12, 12, -24, 24):
            m2 = n[2] + shift
            if lo <= m2 <= hi and all(abs(m2 - b) <= 7 for b in nb) and all(abs(n[2] - b) > 7 for b in nb):
                n[2] = m2
                rep["oktav_javitva"] += 1
                break
    # azonos hang rövid szünettel: egy hang
    merged = []
    for n in kept:
        if merged and n[2] == merged[-1][2] and n[0] - merged[-1][1] < merge_gap and n[1] - n[0] < 0.15:
            merged[-1][1] = max(merged[-1][1], n[1])
            rep["osszevont"] += 1
        else:
            merged.append(n)
    if min_gap > 0:
        out = []
        for n in merged:
            if out and n[0] - out[-1][0] < min_gap:
                rep["tul_kozeli"] += 1
                continue
            out.append(n)
        merged = out
    return [tuple(n) for n in merged], rep


def quantize(notes, qn_of, grid=16):
    """Hangjegyek a ritmusrácson: (kezdet, hossz) rácsegységben (grid = 16 → tizenhatod), a dal elejétől.
    qn_of(mp) a felvétel ideje negyedekben a dal elejétől (a Reaper tempója szerint)."""
    per_qn = grid / 4.0
    out = []
    for t0, t1, m, vel in notes:
        s = int(round(qn_of(t0) * per_qn))
        e = int(round(qn_of(t1) * per_qn))
        out.append([s, max(1, e - s), m, vel])
    out.sort(key=lambda n: n[0])
    merged = []
    for n in out:                                 # egyszólamú: két hang nem kezdődhet egy helyen
        if merged and merged[-1][0] == n[0]:
            if n[1] > merged[-1][1]:
                merged[-1] = n
            continue
        merged.append(n)
    for a, b in zip(merged, merged[1:]):
        a[1] = max(1, min(a[1], b[0] - a[0]))
    return merged


# ----------------------------------------------------------------------------- húr és bund

def fret_notes(midis, tuning, max_fret=20, strings_hint=None):
    """Húr és bund minden hanghoz, Viterbivel: a kéz a lehető legkevesebbet mozduljon, a mély fekvés és az
    üres húr jó, a nagy nyújtás rossz. strings_hint: ismert húr (pl. MIDI-hangszedő csatornájából)."""
    cands = []
    for i, m in enumerate(midis):
        c = [(s + 1, m - o) for s, o in enumerate(tuning) if 0 <= m - o <= max_fret]
        if strings_hint and strings_hint[i]:
            c = [x for x in c if x[0] == strings_hint[i]] or c
        if not c:   # a hangszer hangterjedelmén kívül: oktávval a legközelebbi húrra
            o = min(range(len(tuning)), key=lambda s: abs(m - tuning[s]))
            f = (m - tuning[o]) % 12
            c = [(o + 1, f)]
        cands.append(c)

    def place(c):
        return 0.04 * c[1] + (0.0 if c[1] == 0 else 0.1)

    def move(a, b):
        if b[1] == 0 or a[1] == 0:
            return 0.3 + 0.05 * abs(a[0] - b[0])
        d = abs(a[1] - b[1])
        return d + (2.0 if d > 4 else 0.0) + 0.1 * abs(a[0] - b[0])

    if not cands:
        return []
    cost = [place(c) for c in cands[0]]
    back = []
    for prev, cur in zip(cands, cands[1:]):
        nc, nb = [], []
        for c in cur:
            j = min(range(len(prev)), key=lambda k: cost[k] + move(prev[k], c))
            nc.append(cost[j] + move(prev[j], c) + place(c))
            nb.append(j)
        cost, back = nc, back + [nb]
    k = min(range(len(cost)), key=lambda i: cost[i])
    path = [k]
    for nb in reversed(back):
        k = nb[k]
        path.append(k)
    path.reverse()
    return [cands[i][p] for i, p in enumerate(path)]


def quantize_poly(notes, qn_of, grid=16, max_voices=6):
    """Többszólamú hangjegyek a rácson: az egy helyre eső hangok egy ütés (akkord, vagy akkordbontás csengő
    hangjai közül az új). (kezdet, hossz, [MIDI…], hangerő) rácsegységben; a hossz a következő ütésig tart."""
    per_qn = grid / 4.0
    by = {}
    for t0, t1, m, vel in notes:
        s = int(round(qn_of(t0) * per_qn))
        e = max(s + 1, int(round(qn_of(t1) * per_qn)))
        g = by.setdefault(s, {"e": e, "m": set(), "v": 0.0})
        g["e"] = max(g["e"], e)
        g["m"].add(m)
        g["v"] = max(g["v"], vel)
    starts = sorted(by)
    out = []
    for i, s in enumerate(starts):
        g = by[s]
        ms = sorted(g["m"], reverse=True)[:max_voices]
        nxt = starts[i + 1] if i + 1 < len(starts) else g["e"]
        out.append([s, max(1, min(g["e"], nxt) - s), sorted(ms), min(1.0, max(0.1, g["v"]))])
    return out


def fret_chords(chords, tuning, max_fret=20):
    """Húr és bund akkordonként: minden hang külön húron, a fogás a lehető legszűkebb, és a kéz akkordról
    akkordra a legkevesebbet mozdul (Viterbi). Ami nem fogható le (több hang, mint húr), az kimarad."""
    import itertools

    def options(m):
        return [(s + 1, m - o) for s, o in enumerate(tuning) if 0 <= m - o <= max_fret]

    cands = []
    for ms in chords:
        ms = sorted(ms, reverse=True)[:len(tuning)]
        per = [options(m) for m in ms]
        per = [p for p in per if p] or [[(1, 0)]]
        combos = []
        for combo in itertools.product(*per):
            strings = [c[0] for c in combo]
            if len(set(strings)) != len(strings):
                continue
            fr = [c[1] for c in combo if c[1] > 0]
            span = (max(fr) - min(fr)) if fr else 0
            combos.append((span + (6 if span > 4 else 0) + 0.04 * (sum(fr) / len(fr) if fr else 0), list(combo)))
            if len(combos) > 400:
                break
        if not combos:   # nem fogható le együtt: a legmagasabb hang egyedül
            combos = [(0.0, [per[0][0]])]
        combos.sort(key=lambda c: c[0])
        cands.append(combos[:60])

    def center(c):
        fr = [f for _, f in c if f > 0]
        return sum(fr) / len(fr) if fr else None

    def move(a, b):
        ca, cb = center(a), center(b)
        return 0.3 if ca is None or cb is None else abs(ca - cb)

    if not cands:
        return []
    cost = [c[0] for c in cands[0]]
    back = []
    for prev, cur in zip(cands, cands[1:]):
        nc, nb = [], []
        for pc, c in cur:
            j = min(range(len(prev)), key=lambda k: cost[k] + move(prev[k][1], c))
            nc.append(cost[j] + move(prev[j][1], c) + pc)
            nb.append(j)
        cost, back = nc, back + [nb]
    k = min(range(len(cost)), key=lambda i: cost[i])
    path = [k]
    for nb in reversed(back):
        k = nb[k]
        path.append(k)
    path.reverse()
    return [cands[i][p][1] for i, p in enumerate(path)]


# ----------------------------------------------------------------------------- Guitar Pro

DUR32 = [(32, 1, False), (24, 2, True), (16, 2, False), (12, 4, True), (8, 4, False),
         (6, 8, True), (4, 8, False), (3, 16, True), (2, 16, False), (1, 32, False)]


def split32(n):
    """Hossz harmincketted egységben → kottaértékek (érték, pontozott), mohón."""
    out = []
    while n > 0:
        for u, v, dot in DUR32:
            if u <= n:
                out.append((u, v, dot))
                n -= u
                break
    return out


def write_gp5(path, notes, frets, tuning, bpm, num=4, den=4, grid=16, title="", track_name="Gitár",
              instrument=27, first_bar=None, artist="", drums=False):
    """A rácsra igazított hangjegyekből .gp5: ütemenként, a hangok kottaértékekre bontva, ütemhatáron átkötve."""
    import guitarpro as gp
    u = 32 // grid                                   # egy rácsegység harmincketted-egységben
    bar32 = num * 32 // den
    ev = [(s * u, l * u, m, v, f) for (s, l, m, v), f in zip(notes, frets)]
    if first_bar is None:
        first_bar = (ev[0][0] // bar32) if ev else 0
    origin = first_bar * bar32
    ev = [(s - origin, l, m, v, f) for s, l, m, v, f in ev if s >= origin]
    total = max((s + l for s, l, *_ in ev), default=bar32)
    nbars = max(1, -(-total // bar32))

    song = gp.Song(title=title, artist=artist, tempo=int(round(bpm)))
    song.measureHeaders = []
    track = gp.Track(song, number=1, name=track_name,
                     strings=[gp.GuitarString(i + 1, o) for i, o in enumerate(tuning)])
    track.channel.instrument = instrument
    if drums:                                        # dobsáv: a „bund” a GM-dobhang, a 10. csatornán
        track.isPercussionTrack = True
        track.channel.channel = track.channel.effectChannel = 9
        track.channel.instrument = 0
    song.tracks = [track]
    start = 960
    for b in range(nbars):
        h = gp.MeasureHeader(number=b + 1, start=start,
                             timeSignature=gp.TimeSignature(numerator=num, denominator=gp.Duration(value=den)))
        song.measureHeaders.append(h)
        start += num * 3840 // den
        track.measures.append(gp.Measure(track, h))

    def add(voice, units, fret=None, tie=False, vel=0.8):
        """fret: (húr, bund) egy hangnál, vagy ezek listája akkordnál; None = szünet."""
        sf = [fret] if fret and isinstance(fret, tuple) else (fret or [])
        first = True
        for _, val, dot in split32(units):
            beat = gp.Beat(voice, duration=gp.Duration(value=val, isDotted=dot),
                           status=gp.BeatStatus.normal if sf else gp.BeatStatus.rest)
            for s, f in sf:
                beat.notes.append(gp.Note(beat, value=f, string=s, velocity=int(15 + 112 * vel),
                                          type=gp.NoteType.tie if (tie or not first) else gp.NoteType.normal))
            voice.beats.append(beat)
            first = False

    for b in range(nbars):
        voice = track.measures[b].voices[0]
        pos, end = b * bar32, (b + 1) * bar32
        for s, l, m, v, f in ev:
            if s + l <= pos or s >= end:
                continue
            a, z = max(s, pos), min(s + l, end)
            if a > pos:
                add(voice, a - pos)
            add(voice, z - a, f, tie=a > s, vel=v)
            pos = z
        if pos < end:
            add(voice, end - pos)
    gp.write(song, path, version=(5, 1, 0))
    return {"utemek": nbars, "hangjegyek": len(ev), "elso_utem_a_dalban": first_bar + 1}


def transcribe(path, qn_of, bpm, num=4, den=4, grid=16, instrument="guitar", tuning=None, max_fret=20):
    """Hangfájlból hangjegyek, rácson, húrral és bunddal; a .gp5-öt a write_gp5 írja."""
    tun = tuning or TUNINGS["bass" if instrument == "bass" else "guitar"]
    fmin = 30.0 if instrument == "bass" else 65.0
    x, sr = read_audio(path)
    times, f0, db, flux = pitch_track(x, sr, fmin=fmin)
    raw = notes_from_pitch(times, f0, db, flux)
    q = quantize(raw, qn_of, grid)
    frets = fret_notes([n[2] for n in q], tun, max_fret)
    return q, frets, tun, raw
