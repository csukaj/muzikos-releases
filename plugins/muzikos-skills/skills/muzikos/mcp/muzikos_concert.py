"""Koncerttámogatás (#362): a sampler (a számok előtt bejátszott hangok) mint hangszer, setlistek, és a koncertanyag:
számonként egy sztereó wav, az egyik oldalon a klikk a dobos fülébe (a dal tempója, ütemmutatója és szerkezete
szerint, előszámolással), a másikon a samplerhangok a közönségnek. A samplert a próbán is le lehet játszani.

    MuzikOS/Zenekarok/<zenekar>/Dalok/<dal>/sampler/  a dal samplerhangjai (a memóriában: dal → sampler)
    MuzikOS/Zenekarok/<zenekar>/memoria/setlistek/    a setlistek
    MuzikOS/Zenekarok/<zenekar>/koncert/<setlist>/    a koncertanyag (NN - dal.wav, egyben.wav, lista.html)
"""
import datetime
import glob
import html
import os
import shutil
import subprocess
import wave

import muzikos_memory as mem
import muzikos_songs as songs
import muzikos_style as style

SR = 48000


# ----------------------------------------------------------------------------- hang be és ki

def load_audio(path, sr=SR):
    """Bármilyen hangfájl mono float32-ként, 48 kHz-en (ffmpeg)."""
    import numpy as np
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=600).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def write_stereo(path, left, right):
    """Sztereó wav, 48 kHz, 24 bit."""
    import numpy as np
    n = max(len(left), len(right))
    lr = np.zeros((n, 2), dtype=np.float64)
    lr[:len(left), 0] = left
    lr[:len(right), 1] = right
    v = (np.clip(lr, -1, 1) * 8388607).astype(np.int32).reshape(-1)
    b = np.stack([v & 255, (v >> 8) & 255, (v >> 16) & 255], axis=1).astype(np.uint8).tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b)
    return n / SR


# ----------------------------------------------------------------------------- klikk

def tempo_segments(song):
    """A dal tempója ütemenként: [(első ütem, bpm, számláló, nevező)] a memóriából (tempo, utemmutato,
    tempovaltasok: [{utem, bpm, utemmutato}]), és az ütemek száma (a szerkezet összege, vagy utemek)."""
    num, den = (int(x) for x in str(song.get("utemmutato") or "4/4").split("/"))
    segs = [(1, float(song.get("tempo") or 0), num, den)]
    for t in sorted(song.get("tempovaltasok") or [], key=lambda t: int(t.get("utem", 1))):
        n2, d2 = (int(x) for x in str(t.get("utemmutato") or f"{segs[-1][2]}/{segs[-1][3]}").split("/"))
        segs.append((int(t.get("utem", 1)), float(t.get("bpm") or segs[-1][1]), n2, d2))
    bars = int(song.get("utemek") or sum(int(p.get("utem") or 0) for p in song.get("szerkezet") or []))
    return segs, bars


def click_track(song, count_in=1, volume_db=-6.0, accent=True):
    """A klikk mono tömbként: előszámolás (count_in ütem az első ütem tempójával), aztán a dal minden ütésére
    egy rövid hang, az ütem elején magasabban. Visszaadja a tömböt és a dal kezdetének helyét (mp)."""
    import numpy as np
    segs, bars = tempo_segments(song)
    if not segs[0][1]:
        raise ValueError(f"A(z) {mem.display_title(song)} dalnak nincs tempója a memóriában (dal set tempo).")
    if not bars:
        raise ValueError(f"A(z) {mem.display_title(song)} dalnak nem tudom a hosszát: kell a szerkezet "
                         "(dal set szerkezet) vagy az ütemek száma (dal set utemek).")
    times = []                                       # (idő mp, kiemelt)
    t = 0.0
    _, bpm0, n0, d0 = segs[0]
    for _ in range(count_in):
        for b in range(n0):
            times.append((t, b == 0))
            t += 60.0 / bpm0 * 4.0 / d0
    start = t
    for bar in range(1, bars + 1):
        _, bpm, num, den = [s for s in segs if s[0] <= bar][-1]
        for b in range(num):
            times.append((t, b == 0))
            t += 60.0 / bpm * 4.0 / den
    amp = 10 ** (volume_db / 20)
    n = int(0.03 * SR)
    env = np.exp(-np.arange(n) / (0.006 * SR))
    hi = np.sin(2 * np.pi * 1600 * np.arange(n) / SR) * env
    lo = np.sin(2 * np.pi * 1000 * np.arange(n) / SR) * env * 0.8
    y = np.zeros(int((t + 0.5) * SR))
    for tt, acc in times:
        i = int(tt * SR)
        z = hi if (acc and accent) else lo
        y[i:i + n] += z[:len(y) - i] * amp
    return y, start


# ----------------------------------------------------------------------------- sampler

def band_song(args):
    bid, band, song = songs.band_and_song(args)
    if not song:
        raise ValueError("Kell a title: melyik dal.")
    return bid, band, song


def sampler_dir(band, song):
    d = os.path.join(songs.ensure(band, song), "sampler")
    os.makedirs(d, exist_ok=True)
    return d


def tool_sampler(args):
    """A dal samplerhangjai: add (path → a dal sampler/ mappájába, mikor: előtte | utána), list, play, remove."""
    act = args.get("action", "list")
    bid, band, song = band_song(args)
    items = list(song.get("sampler") or [])
    if act == "add":
        src = args.get("path")
        if not src or not os.path.exists(src):
            raise ValueError("Kell a path: a hangfájl (pl. a fotóládából, pendrive-ról, letöltésből).")
        d = sampler_dir(band, song)
        dst = os.path.join(d, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        nev = args.get("name") or os.path.splitext(os.path.basename(src))[0]
        items = [i for i in items if i.get("nev") != nev] + [{
            "nev": nev, "fajl": os.path.relpath(dst, songs.song_dir(band, song)),
            "mikor": args.get("mikor", "előtte"), "hangero_dB": float(args.get("volume_db", 0)),
            "szunet_utana_mp": float(args.get("gap", 0.5))}]
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"sampler": items}})
        return {"dal": mem.display_title(song), "sampler": items}
    if act == "remove":
        items = [i for i in items if i.get("nev") != args.get("name")]
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"sampler": items}})
        return {"dal": mem.display_title(song), "sampler": items}
    if act == "list":
        return {"dal": mem.display_title(song), "sampler": items,
                "mappa": os.path.join(songs.song_dir(band, song), "sampler")}
    if act == "play":
        pick = [i for i in items if not args.get("name") or mem.slug(args["name"]) in mem.slug(i["nev"])]
        if not pick:
            raise ValueError("Ennek a dalnak nincs ilyen samplerhangja: sampler action=list")
        f = os.path.join(songs.song_dir(band, song), pick[0]["fajl"])
        player = shutil.which("pw-play") or shutil.which("paplay")
        cmd = [player, f] if player else ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", f]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"szol": pick[0]["nev"], "dal": mem.display_title(song),
                "megallitas": "run_command: pkill pw-play (vagy ffplay)"}
    raise ValueError("action: add | list | play | remove")


# ----------------------------------------------------------------------------- setlist

def setlist_dir(bid):
    d = os.path.join(mem.band_dir(bid), "memoria", "setlistek")
    os.makedirs(d, exist_ok=True)
    return d


def tool_setlist(args):
    act = args.get("action", "list")
    bid = mem.find_band(args.get("band"))
    if not bid:
        raise ValueError("Nincs mostani zenekar (zenekar action=activate).")
    d = setlist_dir(bid)
    if act == "list":
        return [{"nev": s.get("nev"), "datum": s.get("datum"), "helyszin": s.get("helyszin"), "dalok": len(s.get("dalok", []))}
                for s in (mem.read_json(p, {}) for p in sorted(glob.glob(os.path.join(d, "*.json"))))]
    name = args.get("name")
    if not name:
        raise ValueError("Kell a name (pl. „Szombat, Dürer”).")
    p = os.path.join(d, mem.slug(name) + ".json")
    if act == "set":
        cur = mem.read_json(p, {"nev": name})
        data = dict(args.get("data") or {})
        if "dalok" in data:                         # a dalok a memóriából: munkacímen vagy publikus címen
            ok, missing = [], []
            for t in data["dalok"]:
                try:
                    ok.append(mem.tool_dal({"action": "get", "title": t, "band": bid})["cim"])
                except ValueError:
                    missing.append(t)
            if missing:
                raise ValueError("Ezeket a dalokat nem ismerem: " + ", ".join(missing) + " (dal action=list)")
            data["dalok"] = ok
        cur.update(data)
        cur["modositva"] = datetime.datetime.now().isoformat(timespec="seconds")
        mem.write_json(p, cur)
        return cur
    cur = mem.read_json(p, None)
    if cur is None:
        raise ValueError(f"Nincs ilyen setlist: {name}. A setlistek: setlist action=list")
    return cur


# ----------------------------------------------------------------------------- koncertanyag

def tool_koncert_anyag(args):
    """Egy setlist minden dalához sztereó wav: klikk az egyik oldalon, sampler a másikon; kérésre egyben is."""
    import numpy as np
    bid = mem.find_band(args.get("band"))
    if not bid:
        raise ValueError("Nincs mostani zenekar (zenekar action=activate).")
    band = mem.tool_zenekar({"action": "get", "name": bid})
    sl = tool_setlist({"action": "get", "name": args.get("setlist"), "band": bid})
    click_left = (args.get("click_side", "L").upper() != "R")
    count_in = int(args.get("count_in", 1))
    out_dir = os.path.join(songs.band_folder(band), "koncert", mem.slug(sl["nev"]))
    os.makedirs(out_dir, exist_ok=True)
    files, rows, whole_l, whole_r, problems = [], [], [], [], []
    gap = np.zeros(int(float(args.get("gap", 4.0)) * SR))
    for k, t in enumerate(sl.get("dalok", []), 1):
        song = mem.tool_dal({"action": "get", "title": t, "band": bid})
        name = mem.display_title(song)
        try:
            click, start = click_track(song, count_in, float(args.get("click_volume_db", -6)))
        except ValueError as e:
            problems.append(str(e))
            continue
        pre, post = [], []
        for s in song.get("sampler") or []:
            f = os.path.join(songs.song_dir(band, song), s["fajl"])
            if not os.path.exists(f):
                problems.append(f"{name}: hiányzik a samplerfájl: {s['fajl']}")
                continue
            a = load_audio(f) * 10 ** (float(s.get("hangero_dB", 0)) / 20)
            (post if s.get("mikor") == "utána" else pre).append((a, float(s.get("szunet_utana_mp", 0.5))))
        lead = np.concatenate([np.concatenate([a, np.zeros(int(g * SR))]) for a, g in pre]) if pre else np.zeros(0)
        song_len = len(click)
        samp = np.concatenate([lead, np.zeros(song_len)] + [a for a, _ in post])
        clk = np.concatenate([np.zeros(len(lead)), click, np.zeros(sum(len(a) for a, _ in post))])
        left, right = (clk, samp) if click_left else (samp, clk)
        path = os.path.join(out_dir, f"{k:02d} - {name}.wav")
        dur = write_stereo(path, left, right)
        files.append(path)
        whole_l += [left, gap]
        whole_r += [right, gap]
        rows.append({"sorszam": k, "dal": name, "tempo": song.get("tempo"), "utemmutato": song.get("utemmutato") or "4/4",
                     "hossz": f"{int(dur // 60)}:{int(dur % 60):02d}", "sampler": [s["nev"] for s in song.get("sampler") or []],
                     "a_dal_indul_mp": round(len(lead) / SR + start, 2), "fajl": os.path.basename(path)})
    if args.get("together") and whole_l:
        p = os.path.join(out_dir, "egyben.wav")
        write_stereo(p, np.concatenate(whole_l), np.concatenate(whole_r))
        files.append(p)
    side = ("bal", "jobb") if click_left else ("jobb", "bal")
    page = os.path.join(out_dir, "lista.html")
    rows_html = "".join(
        f"<tr><td class=num>{r['sorszam']:02d}</td><td><b>{html.escape(r['dal'])}</b></td><td class=num>{r['tempo']} · {r['utemmutato']}</td>"
        f"<td class=num>{r['hossz']}</td><td>{html.escape(', '.join(r['sampler']) or '—')}</td></tr>" for r in rows)
    total = sum(int(r["hossz"].split(":")[0]) * 60 + int(r["hossz"].split(":")[1]) for r in rows)
    body = (style.lcd([("számok", len(rows), ""), ("hossz", f"{total // 60}:{total % 60:02d}", "szünetek nélkül"),
                       ("klikk", side[0].upper(), "a dobos fülébe"), ("sampler", side[1].upper(), "a közönségnek")])
            + f"<div class=card style='margin-top:14px'><div class=lab>setlist</div><div class=row style='margin-bottom:8px'>"
            f"<span class=chip>{style.led(style.INSTRUMENT_COLORS['dob'])}🎧 {side[0]}: klikk</span>"
            f"<span class=chip>{style.led(style.INSTRUMENT_COLORS['sampler'])}🔊 {side[1]}: sampler</span></div>"
            f"<table class=mz><tr><th>#</th><th>Dal</th><th>Tempó</th><th>Hossz</th><th>Sampler</th></tr>{rows_html}</table></div>")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(style.page(sl["nev"], body, kind="MUZIKOS · KONCERT", brand=band, sub=" · ".join(x for x in (sl.get("datum"), sl.get("helyszin")) if x),
                            help_lines=[f"Számonként egy fájl: {side[0]} oldal a klikk a dobosnak, {side[1]} a sampler.",
                                        "A szám előtt a sampler szól, utána az előszámolás."]))
    return {"mappa": out_dir, "fajlok": files, "lista": page, "dalok": rows, "hibak": problems,
            "bekotes": [f"Lejátszó (pl. Bálint iPadje vagy egy telefon) sztereó kimenete → Y-kábel (3,5 mm TRS → 2× 6,3 mm TS)",
                        f"{side[0]} oldal (klikk) → a dobos fülese (fejhallgató-erősítőn át, hogy a hangereje külön állítható legyen)",
                        f"{side[1]} oldal (sampler) → a Nitro sampler-bemenete / a PA (a rider szerint egy csatornán a lábdob-triggerrel)",
                        "A lejátszón számonként egy fájl: a szám előtt Bálint indítja; az előszámolás után indul a szám."],
            "mit_tegyel": "Mondd el, mi készült (hány szám, hossz, hol vannak), és ha a hibak nem üres, mit kell pótolni "
                          "(tempó, szerkezet, samplerfájl). A koncert felállását (felallas activate koncert) egészítsd ki a "
                          "lejátszóval és a két kábellel, ha még nincs benne."}


TOOLS = [
    ("sampler", tool_sampler,
     "A dal samplerhangjai (a számok előtt vagy után bejátszott hangok: fájlokból, játékokból, saját felolvasás; koncerten és próbán is): add (title, path: a hangfájl, name, mikor: „előtte” | „utána”, volume_db, gap: szünet utána mp) — a dal sampler/ mappájába másolja; list; play (most lejátssza, pl. a próbán); remove (name).",
     {"action": {"type": "string", "enum": ["add", "list", "play", "remove"]}, "title": {"type": "string"},
      "band": {"type": "string"}, "path": {"type": "string"}, "name": {"type": "string"},
      "mikor": {"type": "string", "enum": ["előtte", "utána"]}, "volume_db": {"type": "number"}, "gap": {"type": "number"}}),
    ("setlist", tool_setlist,
     "A zenekar setlistjei: list; get (name); set (name, data: {dalok: [a dalok munka- vagy publikus címe, sorrendben], datum, helyszin, megjegyzes}).",
     {"action": {"type": "string", "enum": ["list", "get", "set"]}, "name": {"type": "string"},
      "band": {"type": "string"}, "data": {"type": "object"}}),
    ("koncert_anyag", tool_koncert_anyag,
     "Koncertanyag egy setlistből: számonként egy sztereó wav (48 kHz/24 bit), az egyik oldalon (click_side: L | R) a klikk a dobos fülébe a dal tempója, ütemmutatója, tempóváltásai és szerkezete szerint, count_in ütem előszámolással; a másik oldalon a dal samplerhangjai a szám előtt (és után). together=true: egyben is, gap mp szünettel. Mellé egy áttekintő oldal (lista.html) és a bekötés javaslata.",
     {"setlist": {"type": "string"}, "band": {"type": "string"}, "click_side": {"type": "string", "enum": ["L", "R"]},
      "count_in": {"type": "integer"}, "click_volume_db": {"type": "number"}, "together": {"type": "boolean"},
      "gap": {"type": "number"}}),
]
