"""Felvétel javítása (#326): MIDI-sáv ritmusra igazítása és dinamikájának kiegyenlítése, hangsáv elcsúszott
ütéseinek rácsra húzása (Reaper-nyújtásjelölőkkel: a hangfájl nem változik, nincs vágás), és egy rossz ütem
cseréje egy másik take ugyanazon ütemére (a „Végleges” rétegen, áttűnéssel).

Mindig két lépés: előbb megmutatja, mit változtatna (apply nélkül), és csak jóváhagyás után írja át (apply=true).
Az eredeti mindig megmarad: MIDI-nél az „eredeti” take az elemen, hangnál a forrásfájl, ütemcserénél a take-rétegek;
restore=true visszaállít, és a Reaperben a Ctrl+Z is visszavon.
"""
import muzikos_takes as takes

# a szerver adja (server.py: fix.reaper_call = reaper_call …), hogy ugyanazon a hídon és zárral menjen
reaper_call = None
json_to_lua = None

# dobok GM-hangjai: „a lábcin siet”, „csak a pergőt”
DRUMS = {"lábcin": [35, 36], "labcin": [35, 36], "lábdob": [35, 36], "kick": [35, 36],
         "pergő": [37, 38, 39, 40], "pergo": [37, 38, 39, 40], "snare": [37, 38, 39, 40],
         "lábhi": [44], "hihat": [42, 44, 46], "hi-hat": [42, 44, 46], "lábcin-hihat": [44],
         "tam": [41, 43, 45, 47, 48, 50], "tom": [41, 43, 45, 47, 48, 50],
         "cin": [49, 51, 52, 53, 55, 57, 59], "crash": [49, 57], "ride": [51, 53, 59]}

# rács: tizenhatod = 16, nyolcad = 8, triola-nyolcad = 12 (negyedben: 4 / grid)
GRIDS = {4: 1.0, 8: 0.5, 12: 1 / 3, 16: 0.25, 24: 1 / 6, 32: 0.125}


def _call(lua, timeout=20):
    d = reaper_call(lua, timeout=timeout)
    if not d.get("ok"):
        raise ValueError(d.get("error") or "A Reaper nem válaszol.")
    return d.get("result")


def _range(args):
    """A javítandó rész projektidőben: part (dalrész neve), vagy from_measure–to_measure (mindkettő benne), vagy az egész."""
    if args.get("part"):
        parts = takes.parts_now()
        want = str(args["part"]).lower()
        hit = [p for p in parts if p[0].lower() == want] or [p for p in parts if want in p[0].lower()]
        if not hit:
            raise ValueError(f"Nincs „{args['part']}” dalrész. A részek: " + ", ".join(p[0] for p in parts))
        return hit[0][1], hit[0][2], hit[0][0]
    if args.get("from_measure"):
        a = int(args["from_measure"])
        b = int(args.get("to_measure") or a)
        t = _call(f"return {{muzikos.bar_time({a}), muzikos.bar_time({b + 1})}}")
        return t[0], t[1], f"{a}–{b}. ütem" if b != a else f"{a}. ütem"
    return 0.0, 1e9, "az egész"


def _grid(args):
    g = int(args.get("grid") or 16)
    if g not in GRIDS:
        raise ValueError("A rács: 4, 8, 12 (triola), 16, 24 vagy 32.")
    return GRIDS[g]


def _strength(args, default=70):
    s = float(args.get("strength", default))
    return max(0.0, min(1.0, s / 100 if s > 1 else s))


def _pitches(spec):
    if not spec:
        return None
    if isinstance(spec, (str, int)):
        spec = [spec]
    out = []
    for s in spec:
        if isinstance(s, int) or str(s).isdigit():
            out.append(int(s))
        elif str(s).lower() in DRUMS:
            out += DRUMS[str(s).lower()]
        else:
            raise ValueError(f"Ismeretlen dob: {s} (lábcin, pergő, hihat, lábhi, tam, cin, crash, ride, vagy MIDI-szám).")
    return out


def tool_javitas_midi(args):
    t0, t1, where = _range(args)
    o = {"track": args.get("track", 1), "t0": t0, "t1": t1, "grid": _grid(args), "strength": _strength(args),
         "vel": _strength({"strength": args.get("velocity", 0)}, 0), "apply": bool(args.get("apply")),
         "restore": bool(args.get("restore"))}
    p = _pitches(args.get("drums"))
    if p:
        o["pitches"] = p
    r = _call("return muzikos.midi_fix(" + json_to_lua(o) + ")", timeout=30)
    if args.get("restore"):
        return {"visszaallitva": r.get("visszaallitva"), "mit_tegyel": "Az eredeti szól újra; a javított take megmaradt az elemen."}
    r["resz"] = where
    if not r.get("hangok"):
        raise ValueError(f"{where}: nincs itt hang a sávon" + (" ezekkel a dobokkal" if p else "") + ".")
    if suspicious:
        r["mit_tegyel"] = (f"GYANÚS: {len(o['onsets'])} ütést találtam, ütemenként {per_bar:.1f} (a játék ennél ritkább). Ne ajánld az "
                           "apply-t: nézzétek meg a felvételt (zaj, túlvezérlés, lecsengés), és csak utána igazítsunk.")
    elif not o["apply"]:
        r["mit_tegyel"] = (f"Mondd el: {r['hangok']} hang, átlagosan {r['atlag_elteres_ms']} ms-ot csúszik (legfeljebb "
                           f"{r['legnagyobb_ms']} ms), {int(o['strength'] * 100)}%-os igazítással ~{r['utana_ms']} ms marad. "
                           "Jóváhagyás után ugyanez apply=true-val.")
    else:
        r["mit_tegyel"] = "Hallgassátok meg. Az eredeti megmaradt („eredeti” take az elemen): restore=true visszaállítja."
    return r


def attacks(x, sr, hop=0.002, rise_db=6.0, floor_db=35.0, gap=0.3, win_s=0.006):
    """Ütések (hangkezdetek) mp-ben: a simított burkoló (RMS 6 ms, 2 ms-os lépés) 15 ms alatt legalább rise_db-t ugrik (a
    csúcs alatt legfeljebb floor_db-vel), és két ütés közt legalább `gap` másodperc van. A jelöltek közül az erősebb ugrás
    nyer (nem a korábbi): a torzított, lecsengő basszus hullámzása így nem lesz külön ütés (#49: 55 ms-onként „talált”).
    A rácsra húzáshoz a 2 ms-os felbontás kell, a hangmagasság-követő 10 ms-os lépése durva."""
    import numpy as np
    pad = int(0.02 * sr)                            # csend elé: a felvétel legelején induló ütés is ugrás legyen
    x = np.concatenate([np.zeros(pad, dtype=x.dtype), x]).astype(float)
    h = max(1, int(sr * hop))
    hop = h / sr                                    # a valódi lépés (44,1 kHz-en 88 minta ≠ 2 ms): különben az idő elcsúszna
    w = h * max(3, int(round(win_s / hop)))          # az RMS-ablak: egy basszushang periódusánál (10–33 ms) hosszabb ablak kell
    n = (len(x) - w) // h
    if n <= 0:
        return []
    frames = np.lib.stride_tricks.as_strided(x, shape=(n, w), strides=(x.strides[0] * h, x.strides[0]))
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
    k = max(1, int(0.015 / hop))
    low = np.array([db[max(0, i - k):i].min() if i else db[0] for i in range(n)])
    rise = db - low
    floor = db.max() - floor_db
    cand = [i for i in range(n) if rise[i] >= rise_db and db[i] >= floor]
    # a csúcsos ugrásokból: erősségi sorrendben, a már elfogadottak gap sugarú környezete kizárva
    chosen = []
    radius = max(1, int(gap / hop))
    for i in sorted(cand, key=lambda i: -rise[i]):
        if all(abs(i - j) >= radius for j in chosen):
            chosen.append(i)
    out = []
    for i in sorted(chosen):
        a = max(0, i - k - 1)                       # a hang eleje: a legmeredekebb pont a legerősebb ugrás körül (előtte is: a
        seg = np.diff(db[a:i + int(0.005 / hop) + 1])    # legnagyobb ugrás a felfutás végén van, a hang kezdete előbb)
        j = a + int(np.argmax(seg)) if len(seg) else i
        out.append((j + 0.5) * hop + w / sr / 2 - hop / 2 + 0.003 - pad / sr)     # +3 ms: a mért hangkezdet ennyivel korábbra esik
    return out


def _onsets(items, t0, t1, gap=0.3):
    """Ütések projektidőben a szóló hangelemekből."""
    import muzikos_tab as tab
    out, cache = [], {}
    for it in items:
        a, b = max(it["pos"], t0), min(it["pos"] + it["len"], t1)
        if b <= a:
            continue
        if it["file"] not in cache:
            cache[it["file"]] = tab.read_audio(it["file"])
        x, sr = cache[it["file"]]
        s0 = int((it["offs"] + (a - it["pos"]) * it["rate"]) * sr)
        s1 = int((it["offs"] + (b - it["pos"]) * it["rate"]) * sr)
        seg = x[max(0, s0):max(0, s1)]
        if len(seg) < sr * 0.1:
            continue
        out += [float(a + t / it["rate"]) for t in attacks(seg, sr, gap=gap)]
    return sorted(out)


def _bar_beat(t):
    """Projektidő → „ütem.ütés” (a zenésznek ez mond valamit, nem a másodperc)."""
    try:
        r = _call(f"local b, m = reaper.TimeMap2_timeToBeats(0, {t}) return {{m + 1, math.floor(b) + 1}}")
        return f"{r[0]}.{r[1]}"
    except ValueError:
        return None


def tool_javitas_hang(args):
    t0, t1, where = _range(args)
    o = {"track": args.get("track", 1), "t0": t0, "t1": t1, "grid": _grid(args), "strength": _strength(args),
         "min_ms": float(args.get("min_ms", 10)), "apply": bool(args.get("apply")), "restore": bool(args.get("restore"))}
    if o["restore"]:
        r = _call("return muzikos.audio_fix(" + json_to_lua(o) + ")")
        return {"resz": where, "torolt_jelolok": r.get("torolt_jelolok"),
                "mit_tegyel": "Az eredeti időzítés szól újra ezen a részen."}
    items = _call("return muzikos.audio_items(" + json_to_lua({"track": o["track"], "t0": t0, "t1": t1}) + ")")
    if not items:
        raise ValueError(f"{where}: a sávon itt nincs felvétel.")
    bpm = takes.tempo_now()
    bar_s = 240.0 / bpm                                   # egy 4/4-es ütem hossza
    # két ütés közt legalább az ütem nyolcadának 85%-a (a kézi mérésen bevált: ≥ 1/8 ütem); min_gap_ms felülírja
    gap = float(args["min_gap_ms"]) / 1000.0 if args.get("min_gap_ms") else max(0.05, bar_s / 8 * 0.85)
    o["onsets"] = [round(t, 5) for t in _onsets(items, t0, t1, gap)]
    if not o["onsets"]:
        raise ValueError(f"{where}: nem találok ütést (csend?).")
    bars = max((t1 - t0) / bar_s, 1e-6)
    per_bar = len(o["onsets"]) / bars
    suspicious = per_bar > 12 and not args.get("force")    # 4/4-ben 3 ütés/ütés fölött: valószínűleg hullámzás, nem ütés
    if suspicious and o["apply"]:
        raise ValueError(f"{where}: gyanúsan sok ütést találtam ({len(o['onsets'])}, ütemenként {per_bar:.1f}): ez nem "
                         "játék, hanem hullámzás vagy zaj lehet, és az igazítás szétnyújtaná a felvételt. Nem alkalmazom. "
                         "Nézzétek meg a felvételt (zajkapu? túlvezérlés?), vagy ha mégis így van, force=true.")
    r = _call("return muzikos.audio_fix(" + json_to_lua(o) + ")", timeout=30)
    moved = r.get("mozdul") or []
    r = {"resz": where, "utesek": len(o["onsets"]), "utes_utemenkent": round(per_bar, 1), "mozdul": len(moved), "helyen": r.get("helyen"),
         "eltolasok": [{"mp": round(m["mp"], 3), "elteres_ms": m["elteres_ms"],
                        "utem": _bar_beat(m["mp"])} for m in moved[:40]],
         "elojel": "+ késik, − siet (ms)",
         "atirva": r.get("atirva")}
    if not o["apply"]:
        r["mit_tegyel"] = (f"Mondd el: {r['utesek']} ütésből {r['mozdul']} csúszik {int(o['min_ms'])} ms-nál többet "
                           f"(a legnagyobbak: {sorted((abs(m['elteres_ms']) for m in moved), reverse=True)[:3]} ms, "
                           f"{bpm:g} bpm-en). Jóváhagyás után apply=true: nyújtásjelölőkkel a rácsra húzza "
                           f"{int(o['strength'] * 100)}%-ban, vágás nélkül.")
    else:
        r["mit_tegyel"] = "Hallgassátok meg. A hangfájl nem változott: restore=true visszaállítja ezt a részt."
    return r


def tool_utem_csere(args):
    if not args.get("take"):
        raise ValueError("Kell a take (melyik felvett változatból, 1-től).")
    t0, t1, where = _range(args)
    if t1 > 1e8:
        raise ValueError("Kell a rész: from_measure (és to_measure), vagy part.")
    r = _call("return muzikos.bar_replace(" + json_to_lua({"track": args.get("track", 1), "t0": t0, "t1": t1,
                                                            "lane": int(args["take"]) - 1,
                                                            "fade": float(args.get("fade_ms", 15)) / 1000}) + ")", timeout=30)
    r["resz"] = where
    r["mit_tegyel"] = ("Hallgassátok meg (reaper_transport). A „Végleges” rétegen cserélődött; az eredeti take-ek "
                       "megmaradtak (take_play), és a Reaperben a Ctrl+Z is visszavonja.")
    return r


_RANGE = {"track": {"type": "string"}, "part": {"type": "string"}, "from_measure": {"type": "integer"},
          "to_measure": {"type": "integer"}}

TOOLS = [
    ("javitas_midi", tool_javitas_midi,
     "MIDI-sáv (dob, MIDI-gitár, billentyű) ritmusra igazítása: a rész (part = dalrész, vagy from_measure–to_measure, "
     "különben az egész) hangjai a rácsra (grid: 16 = tizenhatod, 8, 12 = triola, …) strength erősséggel (0–100, alap "
     "70, hogy élő maradjon); drums = csak ezek a dobok (lábcin, pergő, hihat, tam, cin… vagy MIDI-szám); velocity = "
     "a dinamika kiegyenlítése az átlag felé (0–100). apply nélkül csak megmutatja (hány hang, mennyit csúszik); "
     "apply=true írja át, egy „javított” take-re (az „eredeti” megmarad); restore=true visszaállítja.",
     {**_RANGE, "grid": {"type": "integer"}, "strength": {"type": "number"}, "drums": {"type": "array", "items": {"type": "string"}},
      "velocity": {"type": "number"}, "apply": {"type": "boolean"}, "restore": {"type": "boolean"}}),
    ("javitas_hang", tool_javitas_hang,
     "Hangsáv (gitár, basszus, ének) elcsúszott ütései a rácsra: a rész hangkezdeteit felismeri, és a min_ms-nál (alap "
     "10) jobban csúszókat strength erősséggel (alap 70) a rácsra (grid) húzza, Reaper-nyújtásjelölőkkel — a hangfájl "
     "nem változik, nincs vágás, nem pattog. apply nélkül csak megmutatja; apply=true írja át; restore=true a rész "
     "jelölőit törli (visszaáll az eredeti).",
     {**_RANGE, "grid": {"type": "integer"}, "strength": {"type": "number"}, "min_ms": {"type": "number"},
      "apply": {"type": "boolean"}, "restore": {"type": "boolean"}}),
    ("utem_csere", tool_utem_csere,
     "Egy rossz ütem (vagy rész) cseréje egy másik felvett változat (take, 1-től) ugyanazon részére: from_measure–"
     "to_measure vagy part. A „Végleges” rétegen cserél (ha még nincs, a most szóló take-ből lesz), fade_ms "
     "áttűnéssel (alap 15) a vágásoknál; az eredeti take-ek megmaradnak. Csak jóváhagyás után.",
     {**_RANGE, "take": {"type": "integer"}, "fade_ms": {"type": "number"}}),
]
