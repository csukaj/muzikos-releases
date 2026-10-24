"""Guitar Pro-fájl és a dal memóriája (#346, második rész): tempó, tempóváltások, ütemmutató és dalszerkezet
kiolvasása a Guitar Pro-fájlból, és visszaírása bele.

    .gp  (Guitar Pro 7/8): zip, benne a Content/score.gpif (XML) — a tempó a MasterTrack automatizálása, az
         ütemmutató és a dalrész (Section) ütemenként a MasterBar-on.
    .gp5 / .gp4 / .gp3: PyGuitarPro — a tempó a dal tempója, a dalrész az ütem jelölője (marker).
    .gpx (Guitar Pro 6): saját tömörített formátum, nem olvassuk: nyissátok meg és mentsétek el .gp-ként.

Írás előtt az eredeti fájl a dal guitarpro/.elozmenyek/ mappájába kerül, időbélyeggel.
"""
import datetime
import os
import shutil
import zipfile
import xml.etree.ElementTree as ET

GP_EXT = (".gp", ".gp5", ".gp4", ".gp3", ".gpx")
END = "(vége)"          # a szerkezet vége, ha a kotta hosszabb (olvasáskor kimarad)


def newest(folder):
    """A dal guitarpro/ mappájának legutóbb módosított Guitar Pro-fájlja."""
    if not os.path.isdir(folder):
        return None
    fs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(GP_EXT)]
    return max(fs, key=os.path.getmtime) if fs else None


# ----------------------------------------------------------------------------- olvasás

def _structure(sections, nbars):
    """[(ütemindex 0-tól, név)] → [{nev, utem}] (a rész a következő rész elejéig tart)."""
    out = []
    for i, (b, name) in enumerate(sections):
        end = sections[i + 1][0] if i + 1 < len(sections) else nbars
        if end > b and name != END:
            out.append({"nev": name, "utem": end - b})
    return out


def read_gpif(path):
    root = ET.fromstring(zipfile.ZipFile(path).read("Content/score.gpif"))
    mbs = list(root.find("MasterBars"))
    times, sections = [], []
    for i, mb in enumerate(mbs):
        times.append(mb.findtext("Time") or "4/4")
        sec = mb.find("Section")
        if sec is not None:
            name = (sec.findtext("Text") or "").strip() or (sec.findtext("Letter") or "").strip()
            if name:
                sections.append((i, name))
    tempos = []
    autos = root.find("MasterTrack/Automations")
    for a in (autos if autos is not None else []):
        if a.findtext("Type") == "Tempo":
            v = (a.findtext("Value") or "120").split()
            tempos.append((int(a.findtext("Bar") or 0), float(v[0])))
    tempos.sort()
    return {"format": "gp", "utemek": len(mbs), "times": times, "tempos": tempos, "sections": sections}


def read_pgp(path):
    import guitarpro as gp
    song = gp.parse(path)
    times, sections, tempos = [], [], [(0, float(song.tempo))]
    for i, h in enumerate(song.measureHeaders):
        times.append(f"{h.timeSignature.numerator}/{h.timeSignature.denominator.value}")
        if h.marker is not None and (h.marker.title or "").strip():
            sections.append((i, h.marker.title.strip()))
    # a tempóváltások a hangütések keverőjében vannak (mixTableChange): az első sávból
    if song.tracks:
        for i, m in enumerate(song.tracks[0].measures):
            for v in m.voices:
                for b in v.beats:
                    mt = getattr(b.effect, "mixTableChange", None)
                    if mt is not None and getattr(mt, "tempo", None) is not None and mt.tempo.value > 0:
                        if i > 0 and float(mt.tempo.value) != tempos[-1][1]:
                            tempos.append((i, float(mt.tempo.value)))
    return {"format": os.path.splitext(path)[1][1:], "utemek": len(song.measureHeaders), "times": times,
            "tempos": tempos, "sections": sections}


def read(path):
    """A Guitar Pro-fájl a memória nyelvén: tempo, utemmutato, tempovaltasok, szerkezet, utemek."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gpx":
        raise ValueError(f"{os.path.basename(path)}: ez Guitar Pro 6-os (.gpx) fájl, ezt nem tudom olvasni. "
                         "Nyissátok meg a Guitar Próban, és mentsétek el .gp-ként.")
    raw = read_gpif(path) if ext == ".gp" else read_pgp(path)
    times, tempos = raw["times"], raw["tempos"] or [(0, 120.0)]
    changes, last_t = [], times[0] if times else "4/4"
    tmap = dict(tempos)
    for i in range(1, raw["utemek"]):
        t = times[i] if i < len(times) else last_t
        if t != last_t or (i in tmap and tmap[i] != dict(tempos).get(0)):
            ch = {"utem": i + 1}
            if i in tmap:
                ch["bpm"] = tmap[i]
            if t != last_t:
                ch["utemmutato"] = t
            changes.append(ch)
        last_t = t
    return {"fajl": path, "formatum": raw["format"], "tempo": tempos[0][1], "utemmutato": times[0] if times else "4/4",
            "tempovaltasok": changes, "szerkezet": _structure(raw["sections"], raw["utemek"]), "utemek": raw["utemek"]}


# ----------------------------------------------------------------------------- írás

def backup(path):
    d = os.path.join(os.path.dirname(path), ".elozmenyek")
    os.makedirs(d, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    dst = os.path.join(d, f"{stem} {datetime.datetime.now():%Y-%m-%d %H%M%S}{ext}")
    shutil.copy2(path, dst)
    return dst


def _bar_plan(song, nbars):
    """Ütemenként (0-tól): ütemmutató, tempó (ha ott vált), rész neve (ha ott kezdődik) — a memória szerint."""
    ts = [song.get("utemmutato") or "4/4"] * nbars
    tempo_at = {0: float(song.get("tempo") or 120)}
    for ch in sorted(song.get("tempovaltasok") or [], key=lambda c: int(c.get("utem", 1))):
        i = int(ch.get("utem", 1)) - 1
        if 0 <= i < nbars:
            if ch.get("bpm"):
                tempo_at[i] = float(ch["bpm"])
            if ch.get("utemmutato"):
                for j in range(i, nbars):
                    ts[j] = ch["utemmutato"]
    secs, b = {}, 0
    for p in song.get("szerkezet") or []:
        if b < nbars:
            secs[b] = p.get("nev") or ""
        b += int(p.get("utem") or 0)
    if secs and b < nbars:          # a kotta hosszabb: a szerkezet végét jelöljük, hogy az utolsó rész ne nyúljon tovább
        secs[b] = END
    return ts, tempo_at, secs, b


def write_gpif(path, song):
    z = zipfile.ZipFile(path)
    items = {n: z.read(n) for n in z.namelist()}
    infos = {i.filename: i for i in z.infolist()}
    z.close()
    root = ET.fromstring(items["Content/score.gpif"])
    mbs = list(root.find("MasterBars"))
    ts, tempo_at, secs, total = _bar_plan(song, len(mbs))
    for i, mb in enumerate(mbs):
        t = mb.find("Time")
        if t is not None:
            t.text = ts[i]
        for s in mb.findall("Section"):
            mb.remove(s)
        if i in secs:
            sec = ET.Element("Section")
            ET.SubElement(sec, "Letter").text = ""
            ET.SubElement(sec, "Text").text = secs[i]
            kids = list(mb)
            pos = next((k for k, e in enumerate(kids) if e.tag == "Bars"), len(kids))
            mb.insert(pos, sec)
    autos = root.find("MasterTrack/Automations")
    if autos is None:
        autos = ET.SubElement(root.find("MasterTrack"), "Automations")
    for a in [a for a in autos if a.findtext("Type") == "Tempo"]:
        autos.remove(a)
    for i, bpm in sorted(tempo_at.items()):
        a = ET.SubElement(autos, "Automation")
        for tag, val in (("Type", "Tempo"), ("Linear", "false"), ("Bar", str(i)), ("Position", "0"),
                         ("Visible", "true"), ("Value", f"{bpm:g} 2")):
            ET.SubElement(a, tag).text = val
    items["Content/score.gpif"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w") as out:
        for n, data in items.items():
            info = infos[n]
            out.writestr(info, data, compress_type=info.compress_type)
    os.replace(tmp, path)
    return {"utemek": len(mbs), "kellene": total}


def write_pgp(path, song):
    import guitarpro as gp
    g = gp.parse(path)
    ts, tempo_at, secs, total = _bar_plan(song, max(len(g.measureHeaders), 0))
    # ha a szerkezet hosszabb, mint a kotta: üres ütemek a végére, minden sávba
    while len(g.measureHeaders) < total:
        last = g.measureHeaders[-1]
        h = gp.MeasureHeader(number=last.number + 1, start=last.start + last.length,
                             timeSignature=gp.TimeSignature(numerator=last.timeSignature.numerator,
                                                            denominator=gp.Duration(value=last.timeSignature.denominator.value)))
        g.measureHeaders.append(h)
        for tr in g.tracks:
            tr.measures.append(gp.Measure(tr, h))
    ts, tempo_at, secs, total = _bar_plan(song, len(g.measureHeaders))
    g.tempo = int(round(tempo_at[0]))
    for i, h in enumerate(g.measureHeaders):
        num, den = (int(x) for x in ts[i].split("/"))
        h.timeSignature = gp.TimeSignature(numerator=num, denominator=gp.Duration(value=den))
        h.marker = gp.Marker(title=secs[i]) if i in secs else None
    gp.write(g, path)
    return {"utemek": len(g.measureHeaders), "kellene": total}


def write(path, song):
    """A memória (tempó, ütemmutató, tempóváltások, szerkezet) a Guitar Pro-fájlba; előtte mentés."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gpx":
        raise ValueError("A .gpx (Guitar Pro 6) fájlt nem tudom írni: mentsétek el .gp-ként a Guitar Próban.")
    saved = backup(path)
    info = write_gpif(path, song) if ext == ".gp" else write_pgp(path, song)
    info["mentes"] = saved
    if ext != ".gp" and any(c.get("bpm") for c in song.get("tempovaltasok") or []):
        info["figyelem_tempo"] = ("A .gp5-be csak az első tempó került (a tempóváltások ott a hangjegyek keverőjében "
                                  "vannak); a tempóváltásokat a Guitar Próban kell beírni, vagy .gp-be menteni.")
    if ext == ".gp" and info["kellene"] > info["utemek"]:
        info["figyelem"] = (f"A szerkezet {info['kellene']} ütem, a kotta csak {info['utemek']}: a .gp-be új ütemet nem "
                            "teszek, a dalrészek a meglévő ütemekre kerültek.")
    return info


def diff(song, g):
    """Mi tér el a memória és a Guitar Pro-fájl közt (emberi mondatokban)."""
    out = []
    if song.get("tempo") and abs(float(song["tempo"]) - g["tempo"]) > 0.01:
        out.append(f"tempó: a memóriában {song['tempo']}, a Guitar Próban {g['tempo']:g}")
    if song.get("utemmutato") and song["utemmutato"] != g["utemmutato"]:
        out.append(f"ütemmutató: a memóriában {song['utemmutato']}, a Guitar Próban {g['utemmutato']}")
    ms = [(p.get("nev"), int(p.get("utem", 0))) for p in song.get("szerkezet", [])]
    gs = [(p["nev"], p["utem"]) for p in g["szerkezet"]]
    if ms and gs and ms != gs:
        out.append("szerkezet: a memóriában " + ", ".join(f"{n}({u})" for n, u in ms) +
                   " — a Guitar Próban " + ", ".join(f"{n}({u})" for n, u in gs))
    elif ms and not gs:
        out.append("szerkezet: a Guitar Pro-fájlban nincsenek dalrészek")
    return out
