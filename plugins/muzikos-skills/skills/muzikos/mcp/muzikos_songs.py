"""Dalmappák és dallista (#346): zenekaronként és dalonként rendezett fájlok, a zenekar mappájában (#351).

    MuzikOS/Zenekarok/<zenekar>/Dalok/<dal>/
        reaper/      a Reaper-projekt (.rpp) és a felvételek (Media/)
        guitarpro/   .gp, .gp5, .gpx… (Guitar Pro, TuxGuitar)
        export/      wav, mp3 (keverések, masterek)
        kotta/       pdf, MusicXML, MuseScore
        sampler/     a szám előtt/után bejátszott hangok (#362)
        egyeb/       minden más
        jegyzet.md   a dal jegyzetei (a memóriából is)
    MuzikOS/Zenekarok/<zenekar>/dallista.html   a zenekar dalai egy oldalon
"""

import datetime
import glob
import html
import os
import shutil

import muzikos_memory as mem
import muzikos_style as style

SUBDIRS = {"reaper": (".rpp", ".rpp-bak"),
           "guitarpro": (".gp", ".gp3", ".gp4", ".gp5", ".gpx", ".tg"),
           "hydrogen": (".h2song",),      # a dobos Hydrogen-dalai (#327)
           "export": (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aif", ".aiff"),
           "kotta": (".pdf", ".musicxml", ".mxl", ".xml", ".mscz", ".mscx", ".mid", ".midi"),
           "sampler": (),      # a számok előtt bejátszott hangok: a sampler eszköz teszi ide (#362)
           "egyeb": ()}
STATUSES = ["ötlet", "próbálva", "felvéve", "keverve", "kész"]


def projects_root():
    """A zenekarok mappái (MuzikOS/Zenekarok); egy zenekaré: band_folder()."""
    return mem.bands_root()


def band_folder(band):
    return band.get("mappa") or mem.band_dir(band.get("nev") or "zenekar")


def band_and_song(args):
    bid = mem.find_band(args.get("band"))
    if not bid:
        raise ValueError("Nincs mostani zenekar (zenekar action=activate), vagy nincs ilyen zenekar.")
    band = mem.tool_zenekar({"action": "get", "name": bid})
    title = args.get("title")
    song = None
    if title:
        try:
            song = mem.tool_dal({"action": "get", "title": title, "band": bid})
        except ValueError:
            song = mem.tool_dal({"action": "set", "title": title, "band": bid, "data": {}})["dal"]
    return bid, band, song


def song_dir(band, song):
    return os.path.join(band_folder(band), "Dalok", song["cim"])


def ensure(band, song):
    d = song_dir(band, song)
    for sub in SUBDIRS:
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    note = os.path.join(d, "jegyzet.md")
    if not os.path.exists(note):
        with open(note, "w", encoding="utf-8") as f:
            f.write(f"# {song['cim']}\n\n{band.get('nev', '')} · létrehozva: {datetime.date.today()}\n\n")
    return d


def classify(name):
    low = name.lower()
    for sub, exts in SUBDIRS.items():
        if exts and low.endswith(exts):
            return sub
    return "egyeb"


def files_of(d):
    out = {}
    for sub in SUBDIRS:
        p = os.path.join(d, sub)
        fl = []
        for f in sorted(glob.glob(os.path.join(p, "**", "*"), recursive=True)):
            if os.path.isfile(f) and "/Backups/" not in f and not f.endswith(".rpp-bak"):
                fl.append(os.path.relpath(f, d))
        out[sub] = fl
    return out


def tool_dalmappa(args):
    """A dal mappája: create (létrehozza), files (mi van benne), sort (fájlok besorolása a helyükre)."""
    act = args.get("action", "files")
    bid, band, song = band_and_song(args)
    if not song:
        raise ValueError("Kell a title (a dal címe).")
    d = ensure(band, song)
    if act in ("create", "files"):
        if song.get("mappa") != d:
            mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"mappa": d}})
        return {"dal": song["cim"], "mappa": d, "fajlok": files_of(d)}
    if act == "sort":
        src = args.get("path")
        if not src or not os.path.exists(src):
            raise ValueError("Kell a path: egy fájl vagy egy mappa, amit a dalhoz kell sorolni.")
        items = [src] if os.path.isfile(src) else [f for f in glob.glob(os.path.join(src, "*")) if os.path.isfile(f)]
        moved = []
        for f in items:
            sub = classify(f)
            dst = os.path.join(d, sub, os.path.basename(f))
            if os.path.abspath(f) == os.path.abspath(dst):
                continue
            if os.path.exists(dst):
                root, ext = os.path.splitext(dst)
                dst = f"{root} ({datetime.datetime.now():%Y%m%d-%H%M%S}){ext}"
            (shutil.copy2 if args.get("copy", True) else shutil.move)(f, dst)
            moved.append(f"{os.path.basename(f)} → {sub}/")
        data = {"mappa": d}
        gps = [x for x in files_of(d)["guitarpro"]]
        if gps:
            data["guitarpro"] = os.path.join(d, gps[-1])
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": data})
        return {"dal": song["cim"], "besorolva": moved, "masolat": args.get("copy", True), "fajlok": files_of(d)}
    raise ValueError("action: create | files | sort")


OPEN_CSS = (".ob{display:inline-block;margin:2px 4px 2px 0;padding:4px 10px;border-radius:8px;border:1px solid #3a3e48;background:#1d2026;"
            "color:var(--ink);font:inherit;font-size:13px;cursor:pointer}.ob:hover{border-color:var(--or);color:var(--or2)}"
            ".ob[disabled]{opacity:.35;cursor:default}")
# a gombok a helyi szerveren át (127.0.0.1) nyitják a fájlokat; fájlként megnyitva a mappa-hivatkozás marad
OPEN_JS = """
document.querySelectorAll('.ob[data-p]').forEach(b => b.addEventListener('click', () => {
  if (!location.protocol.startsWith('http')) { alert('A gombokhoz a dallistát a Claude-dal nyisd meg (dallista render open=true), vagy a kezdőlapról.'); return; }
  fetch('/api/open', {method: 'POST', body: JSON.stringify({path: b.dataset.p})}).catch(() => alert('Nem sikerült megnyitni.'));
}));
document.querySelectorAll('a[data-adatlap]').forEach(a => { if (location.protocol.startsWith('http')) a.href = '/_f/' + encodeURIComponent(a.dataset.adatlap).replace(/%2F/g, '/'); });
"""


def first_file(song, sub, exts=None):
    for f in song["fajlok"].get(sub, []):
        if not exts or f.lower().endswith(exts):
            return os.path.join(song["mappa"], f)
    return None


def open_buttons(song):
    """A dal helyi fájljainak megnyitó gombjai: Reaper-projekt (a Reaperben), Guitar Pro-kotta (TuxGuitarban), jegyzet,
    a felvételek (a legutóbbi export lejátszása), a dal mappája. A hiányzó fájl gombja szürke."""
    d = song["mappa"]
    note = os.path.join(d, "jegyzet.md")
    exp = [os.path.join(d, f) for f in song["fajlok"].get("export", [])]
    exp.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    items = [("Reaper", first_file(song, "reaper", (".rpp",))), ("Kotta", first_file(song, "guitarpro")),
             ("Jegyzet", note if os.path.exists(note) else None), ("Felvétel", exp[-1] if exp else None),
             ("Mappa", d if os.path.isdir(d) else None)]
    out = []
    for label, path in items:
        if path:
            out.append(f"<button class=ob data-p='{html.escape(path)}' title='{html.escape(os.path.basename(path))}'>{label}</button>")
        else:
            out.append(f"<button class=ob disabled title='még nincs'>{label}</button>")
    return "".join(out)


def tool_dallista(args):
    """A zenekar dallistája: list, status (title + status), render (olvasható oldal)."""
    act = args.get("action", "list")
    bid, band, song = band_and_song(args)
    if act == "status":
        st = args.get("status")
        if st not in STATUSES:
            raise ValueError("status: " + " | ".join(STATUSES))
        if not song:
            raise ValueError("Kell a title.")
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"allapot": st, "jegyzet": f"állapot: {st}"}})
        act = "render"
    songs = []
    for s in mem.tool_dal({"action": "list", "band": bid}):
        full = mem.tool_dal({"action": "get", "title": s["munkacim"], "band": bid})
        d = full.get("mappa") or song_dir(band, full)
        songs.append({"cim": full["cim"], "publikus_cim": full.get("publikus_cim"), "allapot": full.get("allapot", "ötlet"), "tempo": full.get("tempo"),
                      "hangnem": full.get("hangnem"), "utemmutato": full.get("utemmutato"),
                      "szerkezet": " · ".join(f"{p.get('nev')}({p.get('utem')})" for p in full.get("szerkezet", [])),
                      "mappa": d, "fajlok": files_of(d) if os.path.isdir(d) else {},
                      "projekt": full.get("projekt"), "jegyzet": (full.get("jegyzetek") or [{}])[-1].get("szoveg", "")})
    if act == "list":
        return {"zenekar": band.get("nev"), "dalok": songs}
    if act == "render":
        out = os.path.join(band_folder(band), "dallista.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        rows = []
        for s in songs:
            buttons = open_buttons(s)
            adatlap = os.path.join(s["mappa"], "adatlap.html")
            mk = f" <span class=k>· munkacím: {html.escape(s['cim'])}</span>" if s.get("publikus_cim") else ""
            parts = "".join(style.part_chip(p) for p in s["szerkezet"].split(" · ") if p)
            title_html = html.escape(s.get('publikus_cim') or s['cim'])
            if os.path.exists(adatlap):                  # a dalra kattintva az adatlapja nyílik (adatok, szerkezet, jegyzetek)
                title_html = f"<a href='file://{html.escape(adatlap)}' data-adatlap='{html.escape(adatlap)}'>{title_html}</a>"
            rows.append(f"<tr><td><b>{title_html}</b>{mk}<div class=k>{html.escape(s['jegyzet'])}</div></td>"
                        f"<td>{style.status_chip(s['allapot'] if s['allapot'] in STATUSES else 'ötlet')}</td>"
                        f"<td class=num>{s['tempo'] or ''}</td><td class=num>{html.escape(s['hangnem'] or '')}</td><td class=num>{html.escape(s['utemmutato'] or '')}</td>"
                        f"<td>{parts}</td><td>{buttons}</td></tr>")
        legend = " ".join(style.status_chip(st) for st in STATUSES)
        body = (f"<div class=card><div class=lab>állapot</div><div class=row style='flex-wrap:wrap'>{legend}</div></div>"
                "<div class=card><div class=lab>dalok</div><table class=mz><tr><th>Dal</th><th>Állapot</th><th>Tempó</th>"
                f"<th>Hangnem</th><th>Ütem</th><th>Szerkezet</th><th>Fájlok</th></tr>{''.join(rows)}</table></div>")
        body += f"<style>{OPEN_CSS}</style><script>{OPEN_JS}</script>"
        page = style.page("dallista", body, brand=band,
                          sub=f"{len(songs)} dal · frissítve: {datetime.datetime.now():%Y-%m-%d %H:%M} · "
                              f"tagok: {', '.join(t.get('becenev') or t.get('nev', '') for t in band.get('tagok', []))}",
                          help_lines=["Az állapot színe: ötlet → próbálva → felvéve → keverve → kész.",
                                      "Szólj a Claude-nak: „a Leprusz kész”, „mutasd a dallistát”."])
        with open(out, "w", encoding="utf-8") as f:
            f.write(page)
        if args.get("open"):
            import subprocess
            import urllib.parse
            import muzikos_rig as rig
            port = rig.rig_http()
            url = f"http://127.0.0.1:{port}/_f/" + urllib.parse.quote(out.replace(os.sep, "/"), safe="/:") if port else out
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"dallista": out, "dalok": len(songs)}
    raise ValueError("action: list | status | render")


TILES = [("reaper", "R", "Reaper", "#2a1608", "var(--or)"), ("guitarpro", "GP", "Guitar Pro", "#0d2230", "var(--cyan)"),
         ("export", "▶", "Export", "#0e2a19", "var(--ok)"), ("kotta", "♪", "Kotta", "#24123a", "var(--vio)"),
         ("sampler", "◉", "Sampler", "#2b2418", "#e6cfae"), ("hydrogen", "H", "Hydrogen", "#2b1a12", "#ff9a3d")]
ADATLAP_CSS = """
.bar{display:flex;gap:5px;height:46px}.bar .part{margin:0;height:46px;justify-content:center;min-width:0;overflow:hidden}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
.tile{background:var(--well);border:1px solid #2c3038;border-radius:12px;padding:12px;text-decoration:none;color:var(--ink)}
.tile .ico{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-family:var(--head);
font-weight:800;font-size:14px;margin-bottom:8px}.tile .n{font-family:var(--mono);font-size:26px;color:var(--or2)}
.tile .s{color:var(--sub);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""


def tool_dal_adatlap(args):
    """A dal adatlapja egy oldalon (a dal mappájában: adatlap.html): kijelző, szerkezet, fájlok, jegyzet."""
    bid, band, song = band_and_song(args)
    if not song:
        raise ValueError("Kell a title (a dal).")
    d = ensure(band, song)
    files = files_of(d)
    parts = song.get("szerkezet") or []
    bars = sum(int(p.get("utem") or 0) for p in parts)
    tempo = song.get("tempo")
    num, den = (int(x) for x in (song.get("utemmutato") or "4/4").split("/"))
    length = ""
    if tempo and bars:
        sec = int(round(bars * num * 4 / den * 60 / float(tempo)))
        length = f"{sec // 60}:{sec % 60:02d}"
    changes = song.get("tempovaltasok") or []
    takes = sum(len(v) for v in (song.get("take_naplo") or {}).values())
    cells = [("tempó", tempo or "—", "bpm" + (f" · {len(changes)} váltás" if changes else "")),
             ("hangnem", song.get("hangnem") or "—", ""), ("ütemmutató", song.get("utemmutato") or "—", ""),
             ("hossz", length or "—", f"{bars} ütem" if bars else "")]
    if takes:
        cells.append(("take-jegyzet", takes, ""))
    title = song.get("publikus_cim") or song["cim"]
    sub = " · ".join(x for x in (f"munkacím: {song['cim']}" if song.get("publikus_cim") else "",
                                 song.get("allapot") or "ötlet") if x)
    tags = style.status_chip(song.get("allapot") if song.get("allapot") in STATUSES else "ötlet")
    tun = song.get("hangolas")
    if isinstance(tun, dict):
        tags += "".join(f"<span class=chip>{html.escape(k)}: {html.escape(v)}</span>" for k, v in tun.items())
    elif tun:
        tags += f"<span class=chip>{html.escape(str(tun))}</span>"
    body = f"<div class=card><div class=row style='flex-wrap:wrap;margin-bottom:12px'>{tags}</div>{style.lcd(cells)}</div>"
    if parts:
        blocks = "".join(f"<div class=part style='flex:{max(1, int(p.get('utem') or 1))};background:{style.part_color(p.get('nev'))}'>"
                         f"{html.escape(str(p.get('nev')))} {p.get('utem') or ''}</div>" for p in parts)
        body += f"<div class=card><div class=lab>szerkezet</div><div class=bar>{blocks}</div></div>"
    tiles = ""
    for sub_, ico, name, bg, fg in TILES:
        fl = files.get(sub_) or []
        last = os.path.basename(fl[-1]) if fl else "üres"
        tiles += (f"<a class=tile href='file://{html.escape(os.path.join(d, sub_))}'><div class=ico style='background:{bg};color:{fg}'>"
                  f"{ico}</div><b>{name}</b><div class=n>{len(fl)}</div><div class=s>{html.escape(last)}</div></a>")
    body += f"<div class=card><div class=lab>a dal mappája</div><div class=tiles>{tiles}</div></div>"
    notes = song.get("jegyzetek") or []
    if notes:
        items = "".join(f"<li><span class=k>{html.escape(str(n.get('mikor', ''))[:10])}</span> {html.escape(n.get('szoveg', ''))}</li>"
                        for n in notes[-5:][::-1])
        body += f"<div class=card><div class=lab>jegyzetek</div><ul style='margin:0;padding-left:18px'>{items}</ul></div>"
    out = os.path.join(d, "adatlap.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(style.page(title, body, sub=sub, kind="MUZIKOS · DAL", brand=band, extra_css=ADATLAP_CSS,
                           help_lines=["A csempére kattintva a mappa nyílik.",
                                       "Szólj a Claude-nak: „a refrén legyen 16 ütem”, „mi van a dal mappájában?”."]))
    if args.get("open"):
        import subprocess
        subprocess.Popen(["xdg-open", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"adatlap": out, "dal": title}


def tool_zenekar_logo(args):
    """A zenekar logója: path (kép) → a zenekar mappájába, feldolgozva a fejlécre; remove = vissza a névre."""
    import muzikos_logo as logo
    bid = mem.find_band(args.get("band"))
    if not bid:
        raise ValueError("Nincs mostani zenekar: add meg a band-et.")
    band = mem.tool_zenekar({"action": "get", "name": bid})
    if args.get("remove"):
        mem.tool_zenekar({"action": "set", "name": band.get("nev") or bid, "data": {"logo": None}})
        return {"logo": None, "mit_tegyel": "A fejlécekben újra a zenekar neve látszik (a következő frissítéskor)."}
    if not args.get("path"):
        raise ValueError("Kell a path: a logó képe (png, jpg, svg nélkül; a zenekar Drive-mappájából vagy a fotóládából).")
    info = logo.prepare(args["path"], band_folder(band), args.get("color") or "narancs")
    mem.tool_zenekar({"action": "set", "name": band.get("nev") or bid, "data": {"logo": info}})
    how = ("egyszínű: az arculat színére festettem" if info["egyszinu"] and info["szin"] != "eredeti" else
           "a saját színeivel" + (", világos lapon (sötét logó a sötét alapon nem látszana)" if info["sotet"] else ""))
    return {"logo": info, "hogyan": how,
            "mit_tegyel": "Frissítsd az oldalakat (dallista render, dal_adatlap, koncert_anyag), és mutasd meg. Ha más "
                          "szín kell: color = narancs | vilagos | eredeti."}


TOOLS = [
    ("dal_adatlap", tool_dal_adatlap,
     "A dal adatlapja egy oldalon (a dal mappájában: adatlap.html): a zenekar logója, a cím (a munkacím is), állapot, "
     "hangolás, kijelzőn tempó / hangnem / ütemmutató / hossz, a szerkezet színes sávként, a mappa fájljai csempéken, "
     "a legutóbbi jegyzetek. open=true megnyitja.",
     {"title": {"type": "string"}, "band": {"type": "string"}, "open": {"type": "boolean"}}),
    ("zenekar_logo", tool_zenekar_logo,
     "A zenekar logója a MuzikOS oldalainak fejlécében a név helyett (dallista, koncertlista, dalok adatlapja): path = a "
     "kép (png/jpg; pl. a zenekar Drive-mappájából vagy a fotóládából). Levágja a hátteret, fejlécre méretezi; az egyszínűt "
     "az arculat színére festi (color: narancs | vilagos | eredeti), a többszínűt meghagyja (sötétet világos lapon). "
     "remove=true: vissza a névre.",
     {"path": {"type": "string"}, "band": {"type": "string"},
      "color": {"type": "string", "enum": ["narancs", "vilagos", "eredeti"]}, "remove": {"type": "boolean"}}),
    ("dalmappa", tool_dalmappa,
     "A dal mappája (Zenekarok/<zenekar>/Dalok/<dal>/: reaper, guitarpro, export, kotta, egyeb, jegyzet.md): create; files (mi van benne); sort (path: egy fájl vagy mappa — a fájlok kiterjesztés szerint a helyükre; copy=false: áthelyezi).",
     {"action": {"type": "string", "enum": ["create", "files", "sort"]}, "title": {"type": "string"}, "band": {"type": "string"},
      "path": {"type": "string"}, "copy": {"type": "boolean"}}),
    ("dallista", tool_dallista,
     "A zenekar dallistája: list (dalonként állapot, tempó, hangnem, szerkezet, fájlok); status (title + status: ötlet / próbálva / felvéve / keverve / kész); render (olvasható oldal a Zenekarok/<zenekar>/dallista.html-ben; open=true megnyitja).",
     {"action": {"type": "string", "enum": ["list", "status", "render"]}, "title": {"type": "string"}, "band": {"type": "string"},
      "status": {"type": "string"}, "open": {"type": "boolean"}}),
]
