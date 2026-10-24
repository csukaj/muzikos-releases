"""MuzikOS-memória (#325): zenekarok, tagok, dalok, tanult eljárások (receptek) és szokások.

Ember által is olvasható fájlok, amiket a Claude Code és a Claude Desktop is elér (a muzikos MCP-szerveren át), és
amik túlélik az újraindítást. Egy zenekar = egy mappa (#351): minden adata együtt, hogy egyben szinkronizálható
legyen a zenekar Drive-mappájával:
    MuzikOS/Zenekarok/<zenekar>/zenekar.json             név, tagok (hangszer, bemenet, sáv…), hangolás, logó
    MuzikOS/Zenekarok/<zenekar>/memoria/dalok/<dal>.json tempó, hangnem, ütemmutató, szerkezet, jegyzetek
    MuzikOS/Zenekarok/<zenekar>/memoria/setlistek/       a koncertek számsorrendje
    MuzikOS/Zenekarok/<zenekar>/felallasok/              a felállások (szobapróba, terem, koncert, otthoni)
    MuzikOS/Zenekarok/<zenekar>/Dalok/<dal>/             a dal fájljai (reaper, guitarpro, export, kotta…)
    MuzikOS/Zenekarok/<zenekar>/dallista.html, logo/, koncert/
A gépé (nem a zenekaré) a <tudás>:
    <tudás>/aktiv.json                        a mostani zenekar
    <tudás>/receptek/<recept>.md               egy megtanított teendő (hívószavak + lépések)
    <tudás>/szokasok.json                      ki mit szeret, ki mit javított ki
A <tudás> helye: $MUZIKOS_TUDAS, különben a PenSSD-Adat MuzikOS/Tudas mappája (a Windows is látja), különben
~/MuzikOS/Tudas (a tartós fájlban). A Zenekarok mappa a <tudás> mellett van.
"""

import datetime
import glob
import json
import os
import re
import shutil
import unicodedata


def moved(base):
    """A régi MusicOS-mappa egyszer átköltözik MuzikOS-ra (#361): a memória, a projektek, a felállások."""
    new, old = os.path.join(base, "MuzikOS"), os.path.join(base, "MusicOS")
    if not os.path.exists(new) and os.path.isdir(old):
        try:
            os.rename(old, new)
        except OSError:
            return old          # nem írható (pl. csak olvasható meghajtó): a régi helyen dolgozunk
    return new


def root():
    env = os.environ.get("MUZIKOS_TUDAS") or os.environ.get("MUSICOS_TUDAS")
    if env:
        return env
    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    for base in (f"/media/{user}/PenSSD-Adat", f"/run/media/{user}/PenSSD-Adat"):
        if os.path.isdir(base):
            return os.path.join(moved(base), "Tudas")
    return os.path.join(moved(os.path.expanduser("~")), "Tudas")


def slug(s):
    s = unicodedata.normalize("NFKD", str(s).strip().lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "nevtelen"


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def merge(base, new):
    """A new mezői felülírják a base-t; listánál a tagok név szerint frissülnek, a többi lista cserélődik."""
    out = dict(base)
    for k, v in (new or {}).items():
        if k == "tagok" and isinstance(v, list) and isinstance(base.get(k), list):
            byname = {slug(t.get("nev", "")): t for t in base[k]}
            for t in v:
                key = slug(t.get("nev", ""))
                if t.get("_torles"):
                    byname.pop(key, None)
                else:
                    byname[key] = {**byname.get(key, {}), **t}
            out[k] = list(byname.values())
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = merge(base[k], v)
        else:
            out[k] = v
    return out


# ----------------------------------------------------------------------------- zenekarok

def bands_root():
    """MuzikOS/Zenekarok: zenekaronként egy mappa (#351)."""
    return os.path.join(os.path.dirname(root()), "Zenekarok")


def folder_name(name):
    """A zenekar mappájának neve: a neve, a fájlnévben tiltott jelek nélkül (a Drive és a Windows is látja)."""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().rstrip(".")
    return n or slug(name)


def band_dirs():
    migrate()
    return sorted(os.path.dirname(p) for p in glob.glob(os.path.join(bands_root(), "*", "zenekar.json")))


def band_dir(name):
    """A zenekar mappája (azonosító vagy név alapján); ha még nincs, ahova kerülni fog."""
    want = slug(name)
    for d in band_dirs():
        if slug(os.path.basename(d)) == want or slug(read_json(os.path.join(d, "zenekar.json"), {}).get("nev") or "") == want:
            return d
    return os.path.join(bands_root(), folder_name(name))


def songs_mem_dir(bid):
    return os.path.join(band_dir(bid), "memoria", "dalok")


def bands():
    out = []
    for d in band_dirs():
        b = read_json(os.path.join(d, "zenekar.json"), {})
        dalok = glob.glob(os.path.join(d, "memoria", "dalok", "*.json"))
        out.append({"nev": b.get("nev"), "azonosito": slug(b.get("nev") or os.path.basename(d)), "mappa": d,
                    "tagok": [t.get("nev") for t in b.get("tagok", [])], "dalok": len(dalok)})
    return out


MIGRATED = ".zenekari-mappak"          # a <tudás>-ban: az átköltöztetés kész (#351)


def _rewrite_paths(folder, pairs):
    """A mappában (json, rpp, html, md) a régi útvonalak az újra: [(régi, új)], a hosszabb előbb."""
    pairs = sorted(pairs, key=lambda x: -len(x[0]))
    for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
        if not p.lower().endswith((".json", ".rpp", ".html", ".md")) or not os.path.isfile(p):
            continue
        if p.endswith(".json"):                       # mezőnként: a json escape-eli a jeleket a szövegben
            data = read_json(p, None)

            def fix(v):
                if isinstance(v, str):
                    for a, b in pairs:
                        v = v.replace(a, b)
                    return v
                if isinstance(v, list):
                    return [fix(x) for x in v]
                if isinstance(v, dict):
                    return {k: fix(x) for k, x in v.items()}
                return v
            if data is not None and fix(data) != data:
                write_json(p, fix(data))
            continue
        try:
            with open(p, encoding="utf-8") as f:
                txt = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new = txt
        for a, b in pairs:
            new = new.replace(a, b)
        if new != txt:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)


def migrate():
    """Egyszer: a régi szerkezet (Tudas/zenekarok, Tudas/felallasok, Projektek/<zenekar>) átköltözik a zenekarok
    mappáiba, és a fájlokban (memória, Reaper-projekt, oldalak) az útvonalak átíródnak. Semmi nem törlődik: ami nem
    költözhet (a célban már van ilyen), a régi helyén marad."""
    r = root()
    mark = os.path.join(r, MIGRATED)
    if os.path.exists(mark):
        return
    old_bands = os.path.join(r, "zenekarok")
    projects = os.path.join(os.path.dirname(r), "Projektek")
    rigs_old = os.path.join(r, "felallasok")
    done = []
    for zj in sorted(glob.glob(os.path.join(old_bands, "*", "zenekar.json"))):
        src = os.path.dirname(zj)
        bid = os.path.basename(src)
        name = read_json(zj, {}).get("nev") or bid
        dst = os.path.join(bands_root(), folder_name(name))
        mdir = os.path.join(dst, "memoria")
        os.makedirs(mdir, exist_ok=True)
        pairs = [(src, mdir)]
        shutil.move(zj, os.path.join(dst, "zenekar.json"))
        for item in os.listdir(src):                  # dalok/, setlistek/, … → memoria/
            if not os.path.exists(os.path.join(mdir, item)):
                shutil.move(os.path.join(src, item), os.path.join(mdir, item))
        pj = os.path.join(projects, name)
        if os.path.isdir(pj):
            pairs.append((pj, dst))
            for item in os.listdir(pj):
                s_ = os.path.join(pj, item)
                if os.path.isdir(s_) and item not in ("koncert", "logo"):
                    t = os.path.join(dst, "Dalok", item)          # egy dal mappája
                    pairs.append((s_, t))
                else:
                    t = os.path.join(dst, item)                   # dallista.html, koncert/, logo/
                if not os.path.exists(t):
                    os.makedirs(os.path.dirname(t), exist_ok=True)
                    shutil.move(s_, t)
        for rj in sorted(glob.glob(os.path.join(rigs_old, "*.json"))):
            if os.path.basename(rj) == "aktiv.json" or read_json(rj, {}).get("zenekar") != bid:
                continue
            rd = os.path.join(dst, "felallasok")
            os.makedirs(rd, exist_ok=True)
            stem = os.path.basename(rj)[:-5]
            for f in glob.glob(os.path.join(rigs_old, stem + ".*")) + glob.glob(os.path.join(rigs_old, stem + "-fotok")):
                if not os.path.exists(os.path.join(rd, os.path.basename(f))):
                    shutil.move(f, os.path.join(rd, os.path.basename(f)))
            pairs.append((os.path.join(rigs_old, stem), os.path.join(rd, stem)))
        _rewrite_paths(dst, pairs)
        # a Reaper legutóbbi projektjei is az új helyre mutassanak (különben induláskor egy ablak kérdezne)
        ini = os.path.expanduser("~/.config/REAPER/reaper.ini")
        if os.path.exists(ini):
            try:
                with open(ini, encoding="utf-8", errors="surrogateescape") as f:
                    txt = f.read()
                new = txt
                for a, b in sorted(pairs, key=lambda x: -len(x[0])):
                    new = new.replace(a, b)
                if new != txt:
                    with open(ini, "w", encoding="utf-8", errors="surrogateescape") as f:
                        f.write(new)
            except OSError:
                pass
        for d in (src, pj):
            try:
                os.rmdir(d)                            # csak ha üresen maradt
            except OSError:
                pass
        done.append({"zenekar": name, "ide": dst})
    os.makedirs(r, exist_ok=True)
    write_json(mark, {"mikor": now(), "atkoltozott": done})


def active():
    a = read_json(os.path.join(root(), "aktiv.json"), {})
    return a.get("zenekar")


def find_band(name):
    """Név, azonosító vagy névrész alapján; üresen a mostani zenekar."""
    if not name:
        name = active()
        if not name:
            return None
    want = slug(name)
    all_b = bands()
    for b in all_b:
        if b["azonosito"] == want or slug(b["nev"] or "") == want:
            return b["azonosito"]
    for b in all_b:
        if want in b["azonosito"]:
            return b["azonosito"]
    return None


def tool_zenekar(args):
    act = args.get("action", "list")
    if act == "list":
        return {"tudas_helye": root(), "mostani": active(), "zenekarok": bands()}
    name = args.get("name")
    if act == "set":
        if not name:
            raise ValueError("Kell a name (a zenekar neve).")
        bid = find_band(name)
        p = os.path.join(band_dir(bid or name), "zenekar.json")
        bid = bid or slug(name)
        cur = read_json(p, {"nev": name, "tagok": [], "letrehozva": now()})
        cur = merge(cur, args.get("data") or {})
        cur["nev"] = cur.get("nev") or name
        cur["modositva"] = now()
        write_json(p, cur)
        if not active():
            write_json(os.path.join(root(), "aktiv.json"), {"zenekar": bid, "ota": now()})
        return {"mentve": p, "zenekar": cur}
    bid = find_band(name)
    if not bid:
        raise ValueError(f"Nincs ilyen zenekar: {name or '(nincs mostani)'}. A zenekarok: " + ", ".join(b["nev"] or b["azonosito"] for b in bands()))
    p = os.path.join(band_dir(bid), "zenekar.json")
    if act == "get":
        b = read_json(p, {})
        b["dalok"] = [read_json(d, {}).get("cim") for d in sorted(glob.glob(os.path.join(songs_mem_dir(bid), "*.json")))]
        b["mappa"] = os.path.dirname(p)
        return b
    if act == "activate":
        write_json(os.path.join(root(), "aktiv.json"), {"zenekar": bid, "ota": now()})
        b = read_json(p, {})
        return {"mostani": bid, "zenekar": b,
                "dalok": [read_json(d, {}).get("cim") for d in sorted(glob.glob(os.path.join(songs_mem_dir(bid), "*.json")))]}
    if act == "delete":
        d = band_dir(bid)
        if not args.get("confirm"):
            return {"elonezet": f"Törölném a(z) {bid} zenekar memóriáját (zenekar.json és memoria/, a dalok jegyzetei is): {d}. "
                                "A dalok mappái (Dalok/), a felállások és a fájlok maradnak. confirm=true kell."}
        os.remove(os.path.join(d, "zenekar.json"))
        shutil.rmtree(os.path.join(d, "memoria"), ignore_errors=True)
        if active() == bid:
            os.remove(os.path.join(root(), "aktiv.json"))
        return {"torolve": bid}
    raise ValueError("action: list | get | set | activate | delete")


# ----------------------------------------------------------------------------- dalok

def song_path(bid, title):
    return os.path.join(songs_mem_dir(bid), slug(title) + ".json")


def display_title(d):
    """A dal neve kifelé: a publikus cím, ha már van, különben a munkacím (#365)."""
    return d.get("publikus_cim") or d.get("cim")


def find_song(bid, title):
    """A dal a munkacímén (cim: ebből a fájl- és mappanév) és a publikus címén is megtalálható."""
    want = slug(title)
    paths = sorted(glob.glob(os.path.join(songs_mem_dir(bid), "*.json")))
    for p in paths:
        if os.path.basename(p)[:-5] == want or slug(read_json(p, {}).get("publikus_cim") or "") == want:
            return p
    for p in paths:
        d = read_json(p, {})
        if want in os.path.basename(p) or want in slug(d.get("cim", "")) or want in slug(d.get("publikus_cim") or ""):
            return p
    return None


def tool_dal(args):
    act = args.get("action", "list")
    bid = find_band(args.get("band"))
    if not bid:
        raise ValueError("Nincs mostani zenekar (zenekar action=activate), vagy nincs ilyen zenekar.")
    if act == "list":
        return [{"cim": display_title(d), "munkacim": d.get("cim"), "tempo": d.get("tempo"), "hangnem": d.get("hangnem"),
                 "projekt": d.get("projekt"), "reszek": len(d.get("szerkezet", []))}
                for d in (read_json(p, {}) for p in sorted(glob.glob(os.path.join(songs_mem_dir(bid), "*.json"))))]
    title = args.get("title")
    if not title:
        raise ValueError("Kell a title (a dal címe).")
    if act == "set":
        p = find_song(bid, title) or song_path(bid, title)
        cur = read_json(p, {"cim": title, "letrehozva": now()})
        data = dict(args.get("data") or {})
        note = data.pop("jegyzet", None)
        # dalírás közben a szerkezet változik: a régi változat megmarad (#341)
        if "szerkezet" in data and cur.get("szerkezet") and data["szerkezet"] != cur["szerkezet"]:
            cur.setdefault("korabbi_szerkezetek", []).append(
                {"meddig": now(), "nev": data.pop("valtozat_neve", None) or f"{len(cur.get('korabbi_szerkezetek', [])) + 1}. változat",
                 "szerkezet": cur["szerkezet"]})
        data.pop("valtozat_neve", None)
        cur = merge(cur, data)
        if note:
            cur.setdefault("jegyzetek", []).append({"mikor": now(), "szoveg": note})
        cur["modositva"] = now()
        write_json(p, cur)
        return {"mentve": p, "dal": cur}
    p = find_song(bid, title)
    if not p:
        raise ValueError(f"Nincs ilyen dal a(z) {bid} zenekarnál: {title}. A dalok: dal action=list")
    if act == "get":
        return read_json(p, {})
    if act == "delete":
        if not args.get("confirm"):
            return {"elonezet": f"Törölném a dal jegyzeteit: {p} (a Reaper-projekt marad). confirm=true kell."}
        os.remove(p)
        return {"torolve": p}
    raise ValueError("action: list | get | set | delete")


# ----------------------------------------------------------------------------- receptek és szokások

def tool_recept(args):
    act = args.get("action", "list")
    d = os.path.join(root(), "receptek")
    if act == "list":
        out = []
        for p in sorted(glob.glob(os.path.join(d, "*.md"))):
            txt = open(p, encoding="utf-8").read()
            m = re.search(r"^Hívószavak:\s*(.+)$", txt, re.M)
            out.append({"nev": os.path.basename(p)[:-3], "hivoszavak": m.group(1) if m else ""})
        return out
    name = args.get("name")
    if not name:
        raise ValueError("Kell a name (a recept neve).")
    p = os.path.join(d, slug(name) + ".md")
    if act == "set":
        steps = args.get("text") or ""
        trig = args.get("triggers") or ""
        if isinstance(trig, list):
            trig = ", ".join(trig)
        body = f"# {name}\n\nHívószavak: {trig}\nFelvéve: {now()}\n\n{steps.strip()}\n"
        os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return {"mentve": p}
    if not os.path.exists(p):
        cands = [os.path.basename(x)[:-3] for x in glob.glob(os.path.join(d, "*.md")) if slug(name) in os.path.basename(x)]
        if len(cands) == 1:
            p = os.path.join(d, cands[0] + ".md")
        else:
            raise ValueError(f"Nincs ilyen recept: {name}. A receptek: recept action=list")
    if act == "get":
        return {"recept": open(p, encoding="utf-8").read()}
    if act == "delete":
        os.remove(p)
        return {"torolve": p}
    raise ValueError("action: list | get | set | delete")


def tool_szokas(args):
    act = args.get("action", "list")
    p = os.path.join(root(), "szokasok.json")
    items = read_json(p, [])
    if act == "list":
        who = slug(args.get("who", "")) if args.get("who") else None
        return [i for i in items if not who or slug(i.get("ki", "")) == who]
    if act == "add":
        if not args.get("text"):
            raise ValueError("Kell a text (mit szeret / mit javított ki).")
        item = {"ki": args.get("who", "mindenki"), "mit": args["text"], "mikor": now(),
                "zenekar": find_band(args.get("band")) or active()}
        items.append(item)
        write_json(p, items)
        return {"felveve": item, "osszes": len(items)}
    if act == "delete":
        q = slug(args.get("text", ""))
        keep = [i for i in items if q not in slug(i.get("mit", ""))]
        write_json(p, keep)
        return {"torolve": len(items) - len(keep)}
    raise ValueError("action: list | add | delete")


def tool_tudas(args):
    """A tudástár egy pillantásra, vagy keresés benne (query)."""
    q = args.get("query")
    if not q:
        bid = active()
        b = read_json(os.path.join(band_dir(bid), "zenekar.json"), {}) if bid else {}
        return {"tudas_helye": root(), "mostani_zenekar": b.get("nev") or bid,
                "tagok": [f"{t.get('nev')}: {t.get('hangszer', '')}" + (f", {t['bemenet']}. bemenet" if t.get("bemenet") else "")
                          + (f", sáv: {t['sav']}" if t.get("sav") else "") for t in b.get("tagok", [])],
                "dalok": tool_dal({"action": "list"}) if bid else [],
                "receptek": tool_recept({"action": "list"}), "szokasok": read_json(os.path.join(root(), "szokasok.json"), []),
                "zenekarok": [x["nev"] for x in bands()]}
    hits = []
    want = slug(q)
    files = glob.glob(os.path.join(root(), "**", "*.*"), recursive=True)
    for d in band_dirs():                     # a zenekarok memóriája és felállásai (a dalok fájljai nem)
        files += [os.path.join(d, "zenekar.json")] + glob.glob(os.path.join(d, "memoria", "**", "*.*"), recursive=True) \
            + glob.glob(os.path.join(d, "felallasok", "*.json"))
    for p in files:
        if not p.endswith((".json", ".md")):
            continue
        try:
            for n, line in enumerate(open(p, encoding="utf-8"), 1):
                if all(w in slug(line) for w in want.split("-") if w):
                    hits.append({"fajl": os.path.relpath(p, os.path.dirname(root())), "sor": n, "szoveg": line.strip()[:200]})
        except OSError:
            continue
    return {"talalat": hits[:50]}


TOOLS = [
    ("tudas", tool_tudas,
     "A MuzikOS-memória egy pillantásra: a mostani zenekar (tagok, hangszer, bemenet, sáv), a dalai, a tanult receptek és a szokások — vagy keresés benne (query). MINDEN munkamenet elején ezt nézd meg.",
     {"query": {"type": "string"}}),
    ("zenekar", tool_zenekar,
     "Zenekarok: list; get (name); set (name + data: {tagok: [{nev, hangszer, hangszer_tipus, effektlanc, bemenet, sav, megjegyzes}], megjegyzes…} — a tagok név szerint frissülnek, {_torles: true} törli); activate (váltás: „most a másikkal próbálunk”); delete (confirm).",
     {"action": {"type": "string", "enum": ["list", "get", "set", "activate", "delete"]},
      "name": {"type": "string"}, "data": {"type": "object"}, "confirm": {"type": "boolean"}}),
    ("dal", tool_dal,
     "A zenekar dalai (band nélkül: a mostani zenekaré): list; get / set (title + data: {tempo, hangnem, utemmutato, szerkezet: [{nev, utem}], projekt, hangolas: {„Csabi”: „C G C F A D”}, publikus_cim, jegyzet: „egy megjegyzés”}); delete (confirm). A dal a munkacímével indul (title; ebből a mappa és a fájlnevek, és nem változik); a végleges címet a publikus_cim adja, és a dal mindkettőn megtalálható.",
     {"action": {"type": "string", "enum": ["list", "get", "set", "delete"]},
      "title": {"type": "string"}, "band": {"type": "string"}, "data": {"type": "object"}, "confirm": {"type": "boolean"}}),
    ("recept", tool_recept,
     "Tanult eljárások: amit egyszer elmagyaráztak („a próba eleje mindig így megy…”), névvel, hívószavakkal és lépésekkel elmentve; legközelebb ebből dolgozz. list / get / set (name, triggers, text) / delete.",
     {"action": {"type": "string", "enum": ["list", "get", "set", "delete"]},
      "name": {"type": "string"}, "triggers": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string"}}),
    ("szokas", tool_szokas,
     "Szokások és javítások: ki mit szeret, mit javított ki („az én sávom mindig a 2-es”, „ne legyen metronóm a szólónál”). list (who) / add (who, text) / delete (text).",
     {"action": {"type": "string", "enum": ["list", "add", "delete"]},
      "who": {"type": "string"}, "text": {"type": "string"}, "band": {"type": "string"}}),
]
