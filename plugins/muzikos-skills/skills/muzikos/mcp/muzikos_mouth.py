"""Szájjal felvett téma kottája (#375): dúdolt vagy énekelt dallamból gitár- vagy basszussáv, beatboxból dobsáv.

    dúdolás: a hangmagasság-követés (muzikos_tab.pitch_track) énekhangra: a vibrato és a hangok közti csúszás
             (glissando) simítva, a dallam oktávval a hangszer fekvésébe téve.
    beatbox: az ütések (muzikos_fix.attacks, 2 ms-os felbontás) és a hangszínük: mély energia = lábdob („b”, „pumm”),
             magas sziszegés = lábcin („ts”), a kettő közt = pergő („k”, „pf”, „csa”); a bizonytalanokat jelzi.
"""
import math

KICK, SNARE, HIHAT = 36, 38, 42
NAMES = {KICK: "lábdob", SNARE: "pergő", HIHAT: "lábcin", 46: "nyitott lábcin", 49: "cintányér", 45: "tam", 51: "ride"}
BY_NAME = {"lábdob": KICK, "labdob": KICK, "lábcin": HIHAT, "labcin": HIHAT, "hihat": HIHAT, "pergő": SNARE,
           "pergo": SNARE, "tam": 45, "cin": 49, "cintányér": 49, "nyitott lábcin": 46, "ride": 51}


# ----------------------------------------------------------------------------- dúdolás

def hum_notes(x, sr, min_len=0.09):
    """Dúdolt dallam hangjegyei (kezdet mp, vég mp, MIDI, hangerő 0–1). A hangmagasság 7 keretes mediánnal simítva
    (a vibrato ne ugráljon félhangot), a rövid csúszások a következő hangba olvadnak."""
    import numpy as np
    import muzikos_tab as tab
    times, f0, db, flux = tab.pitch_track(x, sr, fmin=65.0, fmax=1100.0)
    semi = np.where(f0 > 0, 69 + 12 * np.log2(np.maximum(f0, 1e-9) / 440.0), np.nan)
    sm = semi.copy()
    for i in range(len(semi)):
        w = semi[max(0, i - 3):i + 4]
        w = w[~np.isnan(w)]
        if len(w) >= 3 and not np.isnan(semi[i]):
            sm[i] = float(np.median(w))
    f_s = np.where(np.isnan(sm), 0.0, 440.0 * 2 ** ((np.nan_to_num(sm, nan=69.0) - 69) / 12))
    # a dúdolás hangkezdete lágy: a flux helyett a hangmagasság-váltás és a csend vágja a hangokat
    fl = np.zeros_like(flux)
    voiced = np.nonzero(f_s > 0)[0]
    if len(voiced):
        fl[max(1, voiced[0])] = 1.0                   # az első hang eleje (a felvétel elején nincs előtte csend)
    # ugyanaz a hang újra: a dúdolás a hangok közt elhalkul — ahol a hangerő 80 ms-on belül 3 dB-t nő, ott a
    # bemélyedés alja az új hang eleje
    for i in range(8, len(db)):
        if f_s[i] > 0 and db[i] - db[i - 8:i].min() >= 3.0:
            j = i - 8 + int(np.argmin(db[i - 8:i]))
            if fl[max(0, j - 10):j + 10].max() == 0:
                fl[j] = 1.0
    notes = tab.notes_from_pitch(times, f_s, db, fl, min_len=min_len, gate_db=-28.0, settle=3)
    return [n for n in notes if n[1] - n[0] >= min_len]


def fit_range(notes, tuning):
    """A dallam oktávval a hangszer fekvésébe: a medián a legmélyebb húr fölé kb. másfél oktávval kerüljön."""
    if not notes:
        return notes, 0
    ms = sorted(n[2] for n in notes)
    med = ms[len(ms) // 2]
    center = min(tuning) + 17
    shift = 12 * round((center - med) / 12)
    out = []
    for t0, t1, m, v in notes:
        m2 = m + shift
        while m2 < min(tuning):
            m2 += 12
        out.append((t0, t1, m2, v))
    return out, shift


# ----------------------------------------------------------------------------- beatbox

def _features(x, sr, t):
    import numpy as np
    a = int(t * sr)
    seg = x[a:a + int(0.06 * sr)].astype(float)
    if len(seg) < 64:
        return None
    seg = seg * np.hanning(len(seg))
    sp = np.abs(np.fft.rfft(seg, 4096)) ** 2
    fr = np.fft.rfftfreq(4096, 1 / sr)
    tot = sp.sum() + 1e-12
    return {"mely": float(sp[fr < 200].sum() / tot), "kozep_hz": float((sp * fr).sum() / tot),
            "magas": float(sp[fr > 5000].sum() / tot), "db": float(10 * np.log10(np.mean(seg ** 2) + 1e-12))}


def classify(f):
    """Egy ütés dobja a hangszínéből, és hogy mennyire biztos (0–1)."""
    if f["mely"] > 0.35 or f["kozep_hz"] < 500:
        return KICK, min(1.0, max(f["mely"] / 0.6, (800 - f["kozep_hz"]) / 600))
    if f["kozep_hz"] > 4500 or f["magas"] > 0.45:
        return HIHAT, min(1.0, max((f["kozep_hz"] - 3500) / 3000, f["magas"] / 0.7))
    return SNARE, min(1.0, 1 - abs(f["kozep_hz"] - 2500) / 2500)


def beatbox_hits(x, sr):
    """Beatbox ütései: [(mp, MIDI, biztos 0–1, jellemzők)]."""
    import muzikos_fix as fix
    out = []
    for t in fix.attacks(x, sr, rise_db=6.0, gap=0.06):
        f = _features(x, sr, t)
        if f is None:
            continue
        m, sure = classify(f)
        out.append((t, m, round(max(0.0, sure), 2), f))
    return out


def estimate_bpm(onsets, lo=70.0, hi=180.0):
    """Tempó a hangkezdetekből (metronóm nélkül): a nyolcad-rács, amire a legjobban illeszkednek."""
    if len(onsets) < 4:
        return None
    best, bb = 0.0, None
    b = lo
    while b <= hi:
        p = 60.0 / b / 2
        re = sum(math.cos(2 * math.pi * t / p) for t in onsets)
        im = sum(math.sin(2 * math.pi * t / p) for t in onsets)
        s = math.hypot(re, im) / len(onsets)
        if s > best + 1e-6:
            best, bb = s, b
        b += 0.5
    return bb
