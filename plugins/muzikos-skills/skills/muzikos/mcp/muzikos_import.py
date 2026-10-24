"""Átvitel a Reaperbe (#327): Guitar Pro-sávok (.gp GP7/8, .gp5/.gp4/.gp3) és Hydrogen-dalok (.h2song) hangjegyei
a Reaper egy-egy új sávjára, a dal tempóján.

A hangjegyek negyedekben (QN) a fájl elejétől; a Reaperbe a Lua-híd (muzikos.import_notes) írja be őket egyenként a
projekt tempótérképe szerint — így nincs „importáljam a tempót?” ablak, ami megakasztaná a hidat. A kotta tempóját
kérésre a projektbe is beállítja (tempójelölők ütemenként).
"""
import os
import zipfile
import xml.etree.ElementTree as ET

NV = {"Whole": 4.0, "Half": 2.0, "Quarter": 1.0, "Eighth": 0.5, "16th": 0.25, "32nd": 0.125, "64th": 0.0625,
      "128th": 0.03125}

# Hydrogen-készletek hangszerneveiből GM-dobhang
H2_GM = [("bassdrum", 36), ("kick", 36), ("bass drum", 36), ("bd", 36), ("stick", 37), ("rimshot", 40), ("rim", 37),
         ("clap", 39), ("snare", 38), ("sd", 38),
         ("semi", 46), ("hat open", 46), ("open hat", 46), ("open hh", 46), ("hh open", 46), ("pedal", 44), ("hat", 42),
         ("hh", 42), ("cup", 53), ("bell", 53), ("crash", 49), ("ride", 51), ("china", 52), ("splash", 55),
         ("cowbell", 56), ("tom hi", 48), ("high tom", 48), ("tom 1", 48), ("tom mid", 45), ("mid tom", 45),
         ("tom 2", 45), ("tom lo", 43), ("low tom", 43), ("floor", 41), ("tom", 47)]


# ----------------------------------------------------------------------------- Guitar Pro 7/8 (.gp)

def _gp_tracks(path):
    root = ET.fromstring(zipfile.ZipFile(path).read("Content/score.gpif"))
    by = lambda tag: {e.get("id"): e for e in root.find(tag)}
    bars, voices, beats, notes, rh = by("Bars"), by("Voices"), by("Beats"), by("Notes"), by("Rhythms")
    mbs = list(root.find("MasterBars"))
    starts, qn = [], 0.0
    for mb in mbs:
        starts.append(qn)
        num, den = (int(x) for x in (mb.findtext("Time") or "4/4").split("/"))
        qn += num * 4.0 / den
    tempos = []
    autos = root.find("MasterTrack/Automations")
    for a in (autos if autos is not None else []):
        if a.findtext("Type") == "Tempo":
            b = int(a.findtext("Bar") or 0)
            tempos.append({"utem": b + 1, "qn": starts[b] if b < len(starts) else 0.0,
                           "bpm": float((a.findtext("Value") or "120").split()[0])})
    times = [(i + 1, mb.findtext("Time") or "4/4") for i, mb in enumerate(mbs)]
    out = []
    for ti, t in enumerate(root.find("Tracks")):
        name = (t.findtext("Name") or f"{ti + 1}. sáv").strip()
        tun = None
        for p in t.iter("Property"):
            if p.get("name") == "Tuning":
                tun = [int(v) for v in p.findtext("Pitches").split()]
                break
        iset = t.find("InstrumentSet")
        drums = iset is not None and (iset.findtext("Type") or "") == "drumKit"
        arts = []
        if drums:
            for el in iset.find("Elements"):
                for ar in el.find("Articulations"):
                    arts.append(int(ar.findtext("OutputMidiNumber") or 0))
        ns, open_ties = [], {}
        for mi, mb in enumerate(mbs):
            bar_ids = (mb.findtext("Bars") or "").split()
            if ti >= len(bar_ids):
                continue
            for vid in (bars[bar_ids[ti]].findtext("Voices") or "").split():
                if vid == "-1":
                    continue
                pos = starts[mi]
                for bid in (voices[vid].findtext("Beats") or "").split():
                    b = beats[bid]
                    r = rh[b.find("Rhythm").get("ref")]
                    d = NV.get(r.findtext("NoteValue"), 1.0)
                    dot = r.find("AugmentationDot")
                    if dot is not None:
                        d *= 1.5 if dot.get("count") == "1" else 1.75
                    tp = r.find("PrimaryTuplet")
                    if tp is not None:
                        d *= int(tp.get("den")) / int(tp.get("num"))
                    vel = {"PPP": 30, "PP": 45, "P": 60, "MP": 75, "MF": 90, "F": 105, "FF": 115, "FFF": 125}.get(
                        b.findtext("Dynamic") or "MF", 90)
                    for nid in (b.findtext("Notes") or "").split():
                        n = notes[nid]
                        props = {p.get("name"): p for p in n.find("Properties")}
                        if drums and arts and n.findtext("InstrumentArticulation") is not None:
                            ia = int(n.findtext("InstrumentArticulation"))
                            midi = arts[ia] if ia < len(arts) else None
                        elif "String" in props and "Fret" in props and tun:
                            s, f = int(props["String"].findtext("String")), int(props["Fret"].findtext("Fret"))
                            midi = tun[s] + f if s < len(tun) else None
                        elif "Midi" in props:
                            midi = int(props["Midi"].findtext("Number"))
                        else:
                            midi = None
                        if midi is None:
                            continue
                        tie = n.find("Tie")
                        if tie is not None and tie.get("destination") == "true" and midi in open_ties:
                            open_ties[midi][1] += d                   # átkötés: az előző hang hosszabb
                            if tie.get("origin") != "true":
                                open_ties.pop(midi)
                            continue
                        e = [pos, d, midi, vel]
                        ns.append(e)
                        if tie is not None and tie.get("origin") == "true":
                            open_ties[midi] = e
                    pos += d
        out.append({"nev": name, "dob": drums, "hangok": ns})
    return {"savok": out, "tempok": tempos, "utemmutatok": times, "hossz_qn": qn}


# ----------------------------------------------------------------------------- Guitar Pro 3–5 (PyGuitarPro)

def _pgp_tracks(path):
    import guitarpro as gp
    song = gp.parse(path)
    q = 960.0
    tempos = [{"utem": 1, "qn": 0.0, "bpm": float(song.tempo)}]
    times = [(h.number, f"{h.timeSignature.numerator}/{h.timeSignature.denominator.value}") for h in song.measureHeaders]
    out = []
    for t in song.tracks:
        tun = {s.number: s.value for s in t.strings}
        ns, open_ties = [], {}
        for m in t.measures:
            for v in m.voices:
                for b in v.beats:
                    pos = (b.start - 960) / q
                    d = b.duration.time / q
                    mt = getattr(b.effect, "mixTableChange", None)
                    if mt is not None and getattr(mt, "tempo", None) is not None and mt.tempo.value > 0 \
                            and float(mt.tempo.value) != tempos[-1]["bpm"] and t is song.tracks[0]:
                        tempos.append({"utem": m.number, "qn": pos, "bpm": float(mt.tempo.value)})
                    for n in b.notes:
                        midi = n.value if t.isPercussionTrack else tun.get(n.string, 40) + n.value
                        if n.type == gp.NoteType.tie and (n.string, midi) in open_ties:
                            open_ties[(n.string, midi)][1] += d
                            continue
                        if n.type == gp.NoteType.dead or n.type == gp.NoteType.rest:
                            continue
                        e = [pos, d, midi, int(n.velocity)]
                        ns.append(e)
                        open_ties[(n.string, midi)] = e
        out.append({"nev": t.name, "dob": bool(t.isPercussionTrack), "hangok": ns})
    end = max((n[0] + n[1] for tr in out for n in tr["hangok"]), default=0.0)
    return {"savok": out, "tempok": tempos, "utemmutatok": times, "hossz_qn": end}


# ----------------------------------------------------------------------------- Hydrogen (.h2song)

def _gm_of(name):
    n = (name or "").lower()
    for k, v in H2_GM:
        if k in n:
            return v
    return 38


def _h2_tracks(path):
    root = ET.parse(path).getroot()
    bpm = float(root.findtext("bpm") or 120)
    inst = {}
    for i in root.iter("instrument"):
        if i.findtext("id") is None:
            continue
        out = int(i.findtext("midiOutNote") or -1)          # a GM-készleteknél ez a hang MIDI-száma
        inst[i.findtext("id")] = out if 35 <= out <= 59 else _gm_of(i.findtext("name"))
    pats = {}
    for p in root.find("patternList") or []:
        size = int(p.findtext("size") or 192)              # tick; 48 tick = negyed
        ns = []
        for n in p.iter("note"):
            ns.append((int(n.findtext("position") or 0) / 48.0, inst.get(n.findtext("instrument"), 38),
                       int(float(n.findtext("velocity") or 0.8) * 127)))
        pats[p.findtext("name")] = (size / 48.0, ns)
    notes, pos, cols = [], 0.0, []
    seq = root.find("patternSequence")
    for grp in (seq if seq is not None else []):
        cols.append(pos)
        names = [pi.text for pi in grp.iter("patternID")]
        longest = 0.0
        for nm in names:
            if nm in pats:
                ln, ns = pats[nm]
                longest = max(longest, ln)
                notes += [[pos + s, 0.25, m, v] for s, m, v in ns]
        pos += longest or 4.0
    tempos = [{"utem": 1, "qn": 0.0, "bpm": bpm}]
    tl = root.find("BPMTimeLine")                        # tempóváltások az idővonalon: oszlop (minta) szerint
    for h in (tl if tl is not None else []):
        col, b = int(h.findtext("BAR") or 0), float(h.findtext("BPM") or bpm)
        if col < len(cols) and cols[col] % 4 == 0:       # ütemre esik (4/4): a projekt ütemszámára
            if col == 0:
                tempos[0]["bpm"] = b
            else:
                tempos.append({"utem": int(cols[col] // 4) + 1, "qn": cols[col], "bpm": b})
    return {"savok": [{"nev": "Hydrogen dob", "dob": True, "hangok": sorted(notes)}],
            "tempok": tempos, "utemmutatok": [], "hossz_qn": pos}


def read(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gp":
        return _gp_tracks(path)
    if ext in (".gp5", ".gp4", ".gp3"):
        return _pgp_tracks(path)
    if ext == ".h2song":
        return _h2_tracks(path)
    if ext == ".gpx":
        raise ValueError("A .gpx (Guitar Pro 6) fájlt nem tudom olvasni: mentsétek el .gp-ként a Guitar Próban.")
    raise ValueError(f"Ezt a fájlt nem tudom átvinni: {os.path.basename(path)} (.gp, .gp5, .h2song megy).")


# ----------------------------------------------------------------------------- az eszköz

# a szerver adja (server.py: imp.reaper_call = reaper_call …), hogy ugyanazon a hídon és zárral menjen
reaper_call = None
json_to_lua = None
gp_file_of = None


def _source(args):
    """A fájl: a megadott út, különben a dal mappájából (forras = gp | hydrogen; alapból a Guitar Pro, ha van)."""
    import muzikos_memory as mem
    import muzikos_songs as songs
    if args.get("path"):
        if not os.path.exists(args["path"]):
            raise ValueError(f"Nincs ilyen fájl: {args['path']}")
        return args["path"]
    if not args.get("title"):
        raise ValueError("Kell a path (a fájl), vagy a title (a dal: a guitarpro/ vagy a hydrogen/ mappájából).")
    bid = mem.find_band(args.get("band"))
    song = mem.tool_dal({"action": "get", "title": args["title"], "band": bid})
    band = mem.tool_zenekar({"action": "get", "name": bid})
    d = songs.song_dir(band, song)
    want = (args.get("forras") or "").lower()
    gpf = None if want == "hydrogen" else gp_file_of(band, song)
    if gpf:
        return gpf
    h = os.path.join(d, "hydrogen")
    hs = [os.path.join(h, f) for f in os.listdir(h) if f.lower().endswith(".h2song")] if os.path.isdir(h) else []
    if hs:
        return max(hs, key=os.path.getmtime)
    raise ValueError(f"A(z) {mem.display_title(song)} mappájában nincs Guitar Pro- vagy Hydrogen-fájl "
                     "(guitarpro/, hydrogen/): adj meg egy path-t.")


def _pick(savok, want):
    """A kért sávok: név (részlet is) vagy sorszám 1-től; alapból minden sáv, amiben van hang."""
    if not want:
        return [(i, s) for i, s in enumerate(savok) if s["hangok"]]
    if isinstance(want, (str, int)):
        want = [want]
    out = []
    for w in want:
        if isinstance(w, int) or str(w).isdigit():
            i = int(w) - 1
            if not 0 <= i < len(savok):
                raise ValueError(f"Nincs {w}. sáv (1–{len(savok)}).")
            out.append((i, savok[i]))
            continue
        hit = [(i, s) for i, s in enumerate(savok) if str(w).lower() in s["nev"].lower()]
        if not hit:
            raise ValueError(f"Nincs „{w}” nevű sáv. A sávok: " + ", ".join(s["nev"] for s in savok))
        out += [h for h in hit if h not in out]
    return out


def _tempo_plan(data):
    """Ütemenként, ahol a tempó vagy az ütemmutató vált: {measure, bpm, num, den} (az 1. ütem mindig)."""
    times = dict(data["utemmutatok"]) if data["utemmutatok"] else {1: "4/4"}
    tempo = {t["utem"]: t["bpm"] for t in data["tempok"] if t.get("utem")}
    tempo.setdefault(1, data["tempok"][0]["bpm"] if data["tempok"] else 120.0)
    plan, last_t, last_b = [], None, None
    for b in sorted(set(times) | set(tempo)):
        t = times.get(b) or next((times[k] for k in sorted(times, reverse=True) if k <= b), "4/4")
        bpm = tempo.get(b, last_b)
        if t != last_t or bpm != last_b:
            num, den = (int(x) for x in t.split("/"))
            plan.append({"measure": b, "bpm": bpm, "num": num, "den": den})
        last_t, last_b = t, bpm
    return plan


def shorten(ln, ratio):
    """A hang hossza az eredeti ratio-szorosa, de legalább 0,1 negyed (vagy az eredeti, ha az rövidebb)."""
    if ratio >= 1.0:
        return ln
    return max(ln * ratio, min(ln, 0.1))


def is_bass(track):
    """Basszus-sáv: a neve vagy a hangjai alapján (a hangok mediánja E3 alatt, 52)."""
    name = track["nev"].lower()
    if "bass" in name or "basz" in name:
        return True
    midis = sorted(m for _, _, m, _ in track["hangok"])
    return bool(midis) and midis[len(midis) // 2] < 52


def tool_import_reaperbe(args):
    path = _source(args)
    data = read(path)
    if args.get("list"):
        return {"fajl": path, "savok": [{"sorszam": i + 1, "nev": s["nev"], "dob": s["dob"], "hangjegyek": len(s["hangok"])}
                                        for i, s in enumerate(data["savok"])],
                "tempo": data["tempok"][0]["bpm"] if data["tempok"] else None,
                "tempovaltasok": len(data["tempok"]) - 1}
    picked = _pick(data["savok"], args.get("tracks"))
    if not picked:
        raise ValueError("A fájlban nincs hangjegy.")
    at = int(args.get("at_measure") or 1)
    tempo_mode = args.get("tempo") or ("fajl" if at == 1 else "marad")
    out = {"fajl": path, "savok": []}
    if tempo_mode == "fajl":
        plan = _tempo_plan(data)
        d = reaper_call("return muzikos.tempo_clear(1)")
        if not d.get("ok"):
            raise ValueError(d.get("error") or "A Reaper nem válaszol.")
        for p in plan:
            d = reaper_call("return muzikos.tempo_set(" + json_to_lua(p) + ")")
            if not d.get("ok"):
                raise ValueError("Tempó: " + str(d.get("error")))
        out["tempo"] = plan
    for i, s in picked:
        flat = []
        # a hangok a következő hang kezdetéig nyúlnak, és a ReaSynth azonos hangmagasságnál nem üt újra: a hang hosszának
        # csak egy része szól (alap 55%, dobnál az eredeti), így az ismételt hang újra megszólal (#48)
        ratio = float(args["hossz"]) if args.get("hossz") is not None else (1.0 if s["dob"] else 0.55)
        for pos, ln, midi, vel in s["hangok"]:
            if 0 <= midi <= 127:
                flat += [round(pos, 6), round(shorten(ln, ratio), 6), int(midi), max(1, min(127, int(vel)))]
        base = args.get("name") if len(picked) == 1 and args.get("name") else s["nev"]
        o = {"name": base if base.lower().startswith("kotta:") else "Kotta: " + base,
             "drums": s["dob"], "at_measure": at, "len_qn": round(data["hossz_qn"], 6), "notes": flat}
        if not s["dob"] and is_bass(s):
            o["synth"] = "basszus"
        if args.get("fx"):
            o["fx"] = args["fx"]
        d = reaper_call("return muzikos.import_notes(" + json_to_lua(o) + ")", timeout=60)
        if not d.get("ok"):
            raise ValueError(f"{s['nev']}: " + str(d.get("error")))
        r = d.get("result") or {}
        out["savok"].append({"forras": s["nev"], "sav": r.get("name") or o["name"], "hangjegyek": r.get("hangjegyek"),
                             "hangszer": r.get("hangszer") or ("nincs: nem találom az AVL Drumkits-et (fx-szel más adható)" if s["dob"]
                                                  else "nincs: nem találom a ReaSynth-et (fx-szel más adható)"), "dob": s["dob"]})
    if tempo_mode != "fajl":
        out["figyelem"] = "A projekt tempója maradt: a hangjegyek a projekt tempóján szólnak (ütemre, nem másodpercre)."
    return out


TOOLS = [
    ("import_reaperbe", tool_import_reaperbe,
     "Guitar Pro-fájl (.gp, .gp5) sávjai vagy egy Hydrogen-dal (.h2song) dobja a Reaperbe, sávonként egy új sávra, "
     "hangjegyenként: a dob AVL Drumkits-szel (GM, 10. csatorna), a gitár és a basszus ReaSynth-szel (fx felülírja; a basszus basszusos hangszínnel). A sáv neve „Kotta: <név>”, hogy ne ütközzön a felvétel sávjával; a hangok az eredeti hosszuk 55%-áig szólnak (hossz). "
     "A fájl: path, vagy title (+band) — ekkor a dal guitarpro/ (forras=gp) vagy hydrogen/ (forras=hydrogen) "
     "mappájának legújabbja. list=true csak felsorolja a sávokat. tracks = nevek (részlet is) vagy sorszámok, alapból "
     "minden sáv, amiben van hang. at_measure: a projekt hányadik ütemétől (alap 1). tempo: fajl = a kotta tempója és "
     "ütemmutatói a projektbe (alap, ha az 1. ütemtől jön; a projekt eddigi tempójelölői törlődnek), marad = a projekté.",
     {"path": {"type": "string"}, "title": {"type": "string"}, "band": {"type": "string"},
      "forras": {"type": "string", "enum": ["gp", "hydrogen"]}, "list": {"type": "boolean"},
      "tracks": {"type": "array", "items": {"type": "string"}}, "at_measure": {"type": "integer"},
      "tempo": {"type": "string", "enum": ["fajl", "marad"]}, "name": {"type": "string"}, "fx": {"type": "string"},
      "hossz": {"type": "number", "description": "A hangok hossza az eredeti hányadrésze (alap 0,55; 1 = az eredeti): így az ismételt hang újra megszólal."}}),
]
