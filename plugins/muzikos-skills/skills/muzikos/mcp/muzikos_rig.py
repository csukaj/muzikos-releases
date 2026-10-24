"""Bekötési térkép (#323): a próba felállása (eszközök, portok, kábelek, zenészek, sávok), a kattintható rajza
helyi weboldalként, a próba előtti útmutató, és a potiállások (fotóról leolvasva, névvel mentve).

A felállások a zenekar mappájában vannak (#351): Zenekarok/<zenekar>/felallasok/<felállás>.json, a rajz ugyanott
.html-ként; a zenekar nélküliek és a „legutóbb használt” jel a <tudás>/felallasok/-ban.
Egy felállás:
    {"nev": "Otthon — Józsi",
     "eszkozok": [{"id": "umc", "nev": "Behringer UMC404HD", "tipus": "hangkártya", "portok": ["1. bemenet", …],
                   "megjegyzes": "…", "kep": "<fájl>"}],
     "kabelek": [{"honnan": "nitro: mono kimenet", "hova": "umc: 1. bemenet", "fajta": "6,3 mm mono jack (TS)",
                  "mire": "a dob hangja"}],
     "zeneszek": [{"nev": "Józsi", "hangszer": "…"}], "reaper_savok": [{"sav": "Dob", "forras": "UMC 1. bemenet"}],
     "potiallasok": [{"eszkoz": "umc", "nev": "Próba – alap", "mikor": "…", "foto": "<fájl>",
                      "allasok": {"Gain 1": "2 óra", "48V": "ki", "Hi-Z 2": "be"}}],
     "zenekar": "lem", "fajta": "szobapróba", "tag": "Csuka József", "teendok": ["…"]}

Egy zenekarnak több felállása van (#363): szobapróba (ötletelés, számkialakítás), próbaterem (gyakorlás koncertre),
koncert, és a tagok otthoni setupja; „most a teremben vagyunk” → activate a fajta szerint.
"""

import datetime
import glob
import html
import json
import os
import re
import shutil
import subprocess

import muzikos_memory as mem
import muzikos_style as style


def common_dir():
    """A gépé: a zenekar nélküli felállások és a legutóbb használt felállás jele (aktiv.json)."""
    return os.path.join(mem.root(), "felallasok")


def rig_dirs():
    return [common_dir()] + [os.path.join(d, "felallasok") for d in mem.band_dirs()]


def rig_dir(rid=None, band=None):
    """Ahol a felállás van (rid), vagy ahova egy zenekar új felállása kerül (band; különben a mostani zenekaré)."""
    if rid:
        for d in rig_dirs():
            if os.path.exists(os.path.join(d, rid + ".json")):
                return d
    bid = band or mem.active()
    return os.path.join(mem.band_dir(bid), "felallasok") if bid and mem.find_band(bid) else common_dir()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


FAJTAK = ["szobapróba", "próbaterem", "koncert", "otthoni", "egyéb"]
FAJTA_SZAVAK = {"szoba": "szobapróba", "szobaproba": "szobapróba", "otletelo": "szobapróba", "terem": "próbaterem",
                "probaterem": "próbaterem", "proba terem": "próbaterem", "koncert": "koncert", "fellepes": "koncert",
                "buli": "koncert", "otthon": "otthoni", "otthoni": "otthoni", "itthon": "otthoni"}


def fajta_of(words):
    w = mem.slug(words or "").replace("-", " ")
    for k, v in FAJTA_SZAVAK.items():
        if mem.slug(k).replace("-", " ") in w:
            return v
    return None


def rigs(band=None):
    """A felállások; band megadva: csak azé a zenekaré (és a zenekar nélküliek)."""
    out = []
    for p in sorted(sum((glob.glob(os.path.join(d, "*.json")) for d in rig_dirs()), [])):
        if os.path.basename(p) == "aktiv.json":
            continue
        r = mem.read_json(p, {})
        if band and r.get("zenekar") not in (None, band):
            continue
        out.append({"nev": r.get("nev"), "azonosito": os.path.basename(p)[:-5], "fajta": r.get("fajta"),
                    "tag": r.get("tag"), "zenekar": r.get("zenekar"),
                    "eszkozok": len(r.get("eszkozok", [])), "kabelek": len(r.get("kabelek", [])),
                    "potiallasok": len(r.get("potiallasok", []))})
    return out


def active_rig():
    """A mostani felállás: a mostani zenekaré (zenekar.json: felallas), különben az utoljára használt."""
    bid = mem.active()
    if bid:
        b = mem.read_json(os.path.join(mem.band_dir(bid), "zenekar.json"), {})
        if b.get("felallas"):
            return b["felallas"]
    return mem.read_json(os.path.join(common_dir(), "aktiv.json"), {}).get("felallas")


def find_rig(name):
    """Név, azonosító, vagy a mostani zenekarnál a fajta szavai („terem”, „koncert”, „Bence otthon”)."""
    name = name or active_rig()
    if not name:
        return None
    want = mem.slug(name)
    all_ = rigs()
    for r in all_:
        if r["azonosito"] == want or mem.slug(r["nev"] or "") == want:
            return r["azonosito"]
    mine = rigs(mem.active()) if mem.active() else all_
    kind = fajta_of(name)
    if kind:
        hits = [r for r in mine if r.get("fajta") == kind]
        if kind == "otthoni" and len(hits) > 1:      # kinek az otthoni setupja: a név is benne van a kérésben
            hits = [r for r in hits if r.get("tag") and any(
                mem.slug(p) in want for p in str(r["tag"]).split() if len(p) > 2)] or hits
        if hits:
            return hits[0]["azonosito"]
    for r in all_:
        if want in r["azonosito"]:
            return r["azonosito"]
    return None


def missing_soundcards(r):
    """A felállás hangkártyái közül amelyik nem látszik a PipeWire-ben (nincs bedugva). Ha nem tudjuk megnézni: []."""
    try:
        out = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=10).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return []
    if not out.strip():
        return []
    miss = []
    for e in r.get("eszkozok", []):
        if "hangk" not in (e.get("tipus") or "").lower():
            continue
        words = [w for w in re.split(r"[^a-z0-9]+", (e.get("nev") or "").lower()) if len(w) >= 4]
        if words and not any(w in out for w in words):
            miss.append(e.get("nev"))
    return miss


def summary(rid):
    """Amit a Claude-nak a felállásról tudnia kell, ha átvált rá: eszközök, bekötés, sávok, teendők."""
    r = load(rid)
    return {"felallas": r.get("nev"), "fajta": r.get("fajta"), "tag": r.get("tag"),
            "eszkozok": [f"{e.get('nev')} ({e.get('tipus', '')})" for e in r.get("eszkozok", [])],
            "bekotes": [f"{c['honnan']} → {c['hova']}" + (f" ({c['mire']})" if c.get("mire") else "")
                        for c in r.get("kabelek", [])],
            "reaper_savok": r.get("reaper_savok", []), "zeneszek": r.get("zeneszek", []),
            "teendok": r.get("teendok", []), "megjegyzes": r.get("megjegyzes", "")}


def rig_path(rid, band=None):
    return os.path.join(rig_dir(rid, band), rid + ".json")


def load(rid):
    return mem.read_json(rig_path(rid), {})


def dev_of(end):
    """„umc: 1. bemenet” → („umc”, „1. bemenet”)."""
    if isinstance(end, dict):
        return end.get("eszkoz"), end.get("port")
    a, _, b = str(end).partition(":")
    return a.strip(), b.strip()


def same_port(x, y):
    """Ugyanaz a port-e: az eszköz egyezik, a portnév egyik a másik eleje (a zárójeles kiegészítés nem számít)."""
    (da, pa), (db, pb) = dev_of(x), dev_of(y)
    if da != db:
        return False
    sa, sb = mem.slug(re.sub(r"\(.*?\)", "", pa)), mem.slug(re.sub(r"\(.*?\)", "", pb))
    return bool(sa and sb) and (sa.startswith(sb) or sb.startswith(sa))


# ----------------------------------------------------------------------------- eszközök

def tool_felallas(args):
    act = args.get("action", "list")
    if act == "list":
        bid = mem.find_band(args.get("band")) if (args.get("band") or mem.active()) else None
        return {"helye": rig_dir(band=bid), "mostani": active_rig(), "zenekar": bid, "felallasok": rigs(bid)}
    if act == "import":
        # egy kész felállásfájl (pl. a PenSSD-Adat MuzikOS/felallas-otthon.json-ja) felvétele
        path = args.get("path")
        if not path or not os.path.exists(path):
            raise ValueError("Kell a path: egy felállás JSON-fájlja.")
        data = mem.read_json(path, None)
        if not isinstance(data, dict) or not data.get("eszkozok"):
            raise ValueError("Ez nem felállásfájl (nincs benne eszkozok).")
        return tool_felallas({"action": "set", "name": args.get("name") or data.get("nev") or os.path.basename(path)[:-5],
                              "data": data, "band": args.get("band")})
    name = args.get("name")
    if act == "set":
        if not name and not active_rig():
            raise ValueError("Kell a name (a felállás neve, pl. „Otthon — Józsi”).")
        rid = find_rig(name) or mem.slug(name)
        cur = load(rid) or {"nev": name, "eszkozok": [], "kabelek": [], "letrehozva": now()}
        data = dict(args.get("data") or {})
        if data.get("fajta") and data["fajta"] not in FAJTAK:
            data["fajta"] = fajta_of(data["fajta"]) or data["fajta"]
        if not cur.get("zenekar") and (args.get("band") or mem.active()):
            cur["zenekar"] = mem.find_band(args.get("band"))
        for key in ("eszkozok", "zeneszek", "reaper_savok"):
            if key in data:
                idk = "id" if key == "eszkozok" else ("nev" if key == "zeneszek" else "sav")
                byid = {str(x.get(idk)): x for x in cur.get(key, [])}
                for x in data.pop(key):
                    k = str(x.get(idk))
                    if x.get("_torles"):
                        byid.pop(k, None)
                    else:
                        byid[k] = {**byid.get(k, {}), **x}
                cur[key] = list(byid.values())
        if "kabelek" in data:
            cur["kabelek"] = data.pop("kabelek")      # a kábellistát egyben cseréli (egyenként: felallas_kabel)
        cur.update(data)
        cur["nev"] = cur.get("nev") or name
        cur["modositva"] = now()
        mem.write_json(rig_path(rid, cur.get("zenekar")), cur)
        mem.write_json(os.path.join(common_dir(), "aktiv.json"), {"felallas": rid})
        if args.get("band") or mem.active():
            bid = mem.find_band(args.get("band"))
            if bid:
                mem.tool_zenekar({"action": "set", "name": bid, "data": {"felallas": rid}})
        return {"mentve": rig_path(rid), "felallas": cur, "rajz": render(rid)}
    rid = find_rig(name)
    if not rid:
        raise ValueError(f"Nincs ilyen felállás: {name or '(nincs mostani)'}. A felállások: " + ", ".join(r["nev"] or r["azonosito"] for r in rigs()))
    if act == "get":
        return load(rid)
    if act == "activate":
        mem.write_json(os.path.join(common_dir(), "aktiv.json"), {"felallas": rid})
        missing = missing_soundcards(load(rid))
        bid = load(rid).get("zenekar") or (mem.active() if mem.active() else None)
        if bid:
            mem.tool_zenekar({"action": "set", "name": bid, "data": {"felallas": rid}})
        out = {"mostani": rid, **summary(rid), "rajz": render(rid),
               "mit_tegyel": "Ebből dolgozz: a bekötés, a sávok és a bemenetek ehhez a felálláshoz tartoznak. "
                             "Ha a valóság más („ma a basszus a 3-asba megy”), felallas_kabel."}
        if missing:
            out["hianyzik"] = missing
            out["mit_tegyel"] = ("A felállás hangkártyája nem látszik: " + ", ".join(missing) + ". Szólj, hogy dugják be; "
                                 "addig ne válassz helyette másik kártyát vagy bemenetet, csak ha kérik (#386).")
        return out
    raise ValueError("action: list | get | set | activate | import")


def tool_felallas_kabel(args):
    """Egy kábel hozzáadása vagy törlése: „ma a basszus a 3-asba megy”."""
    rid = find_rig(args.get("name"))
    if not rid:
        raise ValueError("Nincs mostani felállás (felallas action=set).")
    r = load(rid)
    act = args.get("action", "add")
    honnan, hova = args.get("honnan"), args.get("hova")
    cables = r.get("kabelek", [])
    if act == "add":
        if not honnan or not hova:
            raise ValueError("Kell a honnan és a hova („eszköz-id: port”).")
        # ugyanabból a kimenetből egy kábel megy: a régi ugyanonnan induló kábel cserélődik
        # egy kimenetből egy kábel indul, és egy bemenetbe egy dugó megy: a régi, ütköző kábel cserélődik
        replaced = [c for c in cables if same_port(c["honnan"], honnan) or same_port(c["hova"], hova)]
        cables = [c for c in cables if c not in replaced]
        cables.append({"honnan": honnan, "hova": hova, "fajta": args.get("fajta", ""), "mire": args.get("mire", "")})
    elif act == "remove":
        cables = [c for c in cables if not ((not honnan or same_port(c["honnan"], honnan)) and (not hova or same_port(c["hova"], hova)))]
    else:
        raise ValueError("action: add | remove")
    r["kabelek"] = cables
    r["modositva"] = now()
    mem.write_json(rig_path(rid), r)
    out = {"kabelek": cables, "rajz": render(rid)}
    if act == "add" and replaced:
        out["kicserelt"] = [f"{c['honnan']} → {c['hova']}" for c in replaced]
    return out


# ----------------------------------------------------------------------------- potiállások

def tool_potiallas(args):
    """Potiállás mentése (a Claude a fotóról olvassa le), listázása, egy állás lekérése."""
    rid = find_rig(args.get("name"))
    if not rid:
        raise ValueError("Nincs mostani felállás (felallas action=set).")
    r = load(rid)
    act = args.get("action", "list")
    states = r.get("potiallasok", [])
    if act == "list":
        return [{"eszkoz": s["eszkoz"], "nev": s["nev"], "mikor": s.get("mikor"), "foto": s.get("foto")} for s in states]
    dev, nev = args.get("eszkoz"), args.get("allas")
    if act == "save":
        if not dev or not nev or not args.get("allasok"):
            raise ValueError("Kell az eszkoz (id), az allas (név, pl. „Próba – alap”) és az allasok ({poti: érték}).")
        foto = args.get("foto")
        if foto and os.path.exists(foto):
            dst_dir = os.path.join(rig_dir(rid), rid + "-fotok")
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, f"{mem.slug(dev)}-{mem.slug(nev)}-{datetime.datetime.now():%Y%m%d-%H%M%S}{os.path.splitext(foto)[1]}")
            shutil.copyfile(foto, dst)
            foto = dst
        states = [s for s in states if not (s["eszkoz"] == dev and mem.slug(s["nev"]) == mem.slug(nev))]
        states.append({"eszkoz": dev, "nev": nev, "mikor": now(), "foto": foto, "allasok": args["allasok"],
                       "megjegyzes": args.get("megjegyzes", "")})
        r["potiallasok"] = states
        mem.write_json(rig_path(rid), r)
        return {"mentve": nev, "eszkoz": dev, "rajz": render(rid)}
    if act == "get":
        for s in states:
            if s["eszkoz"] == dev and (not nev or mem.slug(nev) in mem.slug(s["nev"])):
                return s
        raise ValueError(f"Nincs ilyen mentett állás: {dev} / {nev}. A lista: potiallas action=list")
    if act == "delete":
        r["potiallasok"] = [s for s in states if not (s["eszkoz"] == dev and mem.slug(s["nev"]) == mem.slug(nev or ""))]
        mem.write_json(rig_path(rid), r)
        return {"torolve": nev}
    raise ValueError("action: list | get | save | delete")


# ----------------------------------------------------------------------------- fotóláda a telefonoknak

INBOX_PORT = 8765


def inbox_dir():
    return os.path.join(mem.root(), "fotok", "beerkezett")


def local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


INBOX_PAGE = """<!doctype html><html lang=hu><head><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">
<title>MuzikOS — fotó küldése</title><style>body{font-family:"Saira",sans-serif;margin:20px;background:#0b0c0f;color:#eef0f3}
.b{display:block;width:100%;padding:18px;font-size:20px;border-radius:12px;border:0;background:#ff7a1a;color:#1a0c02;font-weight:700;margin:12px 0}
#m{font-size:16px;margin-top:12px}</style></head><body><h2>Fotó a MuzikOS-nek</h2>
<p>Fotózd le az eszköz előlapját szemből, jó fénnyel (a potik skálája látsszon), vagy válassz képeket.</p>
<form id=f><input id=i type=file accept="image/*" capture=environment multiple style="display:none">
<button class=b type=button onclick="i.click()">📷 Fotó / kép kiválasztása</button>
<input name=nev id=n placeholder="mi ez? (pl. UMC előlap)" style="width:100%;padding:12px;font-size:16px;border-radius:8px;border:1px solid #9aa6b2"></form>
<div id=m></div><script>
i.onchange=async()=>{for(const f of i.files){m.textContent='Küldés: '+f.name+'…';const r=await fetch(location.pathname+'?nev='+encodeURIComponent(n.value||''),{method:'POST',headers:{'Content-Type':f.type||'image/jpeg','X-Fajlnev':encodeURIComponent(f.name)},body:f});m.textContent=r.ok?'✔ Megérkezett: '+f.name+' — küldhetsz még.':'Hiba: '+r.status;}i.value=''};
</script></body></html>"""


def inbox_server(token, minutes):
    """Kis HTTP-szerver a helyi hálózaton: GET /<token> = a feltöltő oldal, POST /<token> = egy kép mentése."""
    import http.server
    import threading
    import time as _t
    import urllib.parse

    os.makedirs(inbox_dir(), exist_ok=True)
    deadline = _t.time() + minutes * 60

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok_path(self):
            return urllib.parse.urlparse(self.path).path.strip("/") == token

        def do_GET(self):
            if not self._ok_path():
                self.send_error(404)
                return
            body = INBOX_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self._ok_path():
                self.send_error(404)
                return
            ctype = self.headers.get("Content-Type", "")
            n = int(self.headers.get("Content-Length", "0"))
            if not ctype.startswith("image/") or n <= 0 or n > 40 * 1024 * 1024:
                self.send_error(415)
                return
            data = self.rfile.read(n)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            label = mem.slug(q.get("nev", [""])[0])[:40]
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic", "image/webp": ".webp"}.get(ctype.split(";")[0], ".jpg")
            name = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{label or 'foto'}{ext}"
            with open(os.path.join(inbox_dir(), name), "wb") as f:
                f.write(data)
            self.send_response(200)
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", INBOX_PORT), H)

    def run():
        srv.timeout = 1
        while _t.time() < deadline:
            srv.handle_request()
        srv.server_close()

    threading.Thread(target=run, daemon=True).start()
    return srv


_inbox = {}


def tool_fotolada(args):
    """Fotóláda: a telefonok a helyi hálózaton (QR-kóddal) küldhetnek képet a MuzikOS-nek."""
    import secrets
    act = args.get("action", "open")
    if act == "open":
        if _inbox.get("srv") and _inbox.get("until", 0) > datetime.datetime.now().timestamp():
            url = _inbox["url"]
        else:
            token = secrets.token_urlsafe(9)
            minutes = int(args.get("minutes", 15))
            try:
                _inbox["srv"] = inbox_server(token, minutes)
            except OSError as e:
                raise ValueError(f"A fotóládát nem tudom elindítani a {INBOX_PORT}-es porton: {e}")
            url = f"http://{local_ip()}:{INBOX_PORT}/{token}"
            _inbox.update({"url": url, "until": datetime.datetime.now().timestamp() + minutes * 60})
        qr = os.path.join(mem.root(), "fotok", "fotolada-qr.png")
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-s", "10", "-o", qr, url], capture_output=True)
            if args.get("show", True) and os.path.exists(qr):
                subprocess.Popen(["xdg-open", qr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"url": url, "qr": qr if os.path.exists(qr) else None, "ervenyes_eddig": datetime.datetime.fromtimestamp(_inbox["until"]).strftime("%H:%M"),
                "mondd": "A telefon legyen ugyanazon a wifin. Olvassák be a képernyőn a QR-kódot (vagy írják be a címet), és fotózzanak.",
                "beerkezett_mappa": inbox_dir()}
    if act == "list":
        files = sorted(glob.glob(os.path.join(inbox_dir(), "*")), key=os.path.getmtime, reverse=True)
        return [{"fajl": f, "mikor": datetime.datetime.fromtimestamp(os.path.getmtime(f)).isoformat(timespec="seconds"),
                 "meret_kB": os.path.getsize(f) // 1024} for f in files[: int(args.get("limit", 20))]]
    raise ValueError("action: open | list (a képet a foto_megnezes mutatja meg)")


def camera_snapshot(args):
    """Kép a kamerából (a laptopé vagy egy USB-s), az MCP-válaszba és fájlba."""
    dev = args.get("device") or "/dev/video0"
    if not os.path.exists(dev):
        cams = sorted(glob.glob("/dev/video*"))
        raise ValueError(f"Nincs ilyen kamera: {dev}. A kamerák: {', '.join(cams) or 'egy sincs'}")
    d = os.path.join(mem.root(), "fotok")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"kamera-{datetime.datetime.now():%Y%m%d-%H%M%S}.jpg")
    # néhány képkocka bemelegítésnek (a kamera fényereje beáll), és az utolsó marad
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "v4l2", "-video_size", args.get("size", "1280x720"),
           "-i", dev, "-vf", "select=gte(n\\,10)", "-frames:v", "1", "-q:v", "3", out]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if p.returncode != 0 or not os.path.exists(out):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "v4l2", "-i", dev, "-frames:v", "1", out]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if not os.path.exists(out):
        raise ValueError("Nem sikerült képet készíteni: " + (p.stderr or "")[-400:])
    return out


# ----------------------------------------------------------------------------- a rajz

KIND = [("usb", style.CABLE_COLORS["usb"], "USB"), ("xlr", style.CABLE_COLORS["xlr"], "XLR"),
        ("midi", style.CABLE_COLORS["midi"], "MIDI"), ("3,5", "#ffd479", "3,5 mm jack"),
        ("tap", style.CABLE_COLORS["táp"], "táp"), ("táp", style.CABLE_COLORS["táp"], "táp"),
        ("dc", style.CABLE_COLORS["táp"], "táp"), ("adapter", style.CABLE_COLORS["táp"], "táp"),
        ("bluetooth", style.CABLE_COLORS["bluetooth"], "Bluetooth"), ("hdmi", "#6b7785", "HDMI"),
        ("hangszóró", style.CABLE_COLORS["hangszóró"], "hangszóró"), ("jack", style.CABLE_COLORS["jack"], "6,3 mm jack")]

COLUMN = {"hangszer": 0, "mikrofon": 0, "basszusgitár": 0, "gitár": 0,
          "multieffekt": 1, "pedál": 1, "effekt": 1, "elektromos dob": 1, "dobmodul": 1, "di": 1, "táp": 1,
          "hangkártya": 2, "keverő": 2, "számítógép": 2,
          "hangszóró": 3, "fejhallgató": 3, "fejhallgató-erősítő": 3, "monitor": 3, "erősítő": 3}


def kind_of(fajta):
    f = (fajta or "").lower()
    for k, col, label in KIND:
        if k in f:
            return col, label
    return "#8a7f78", "egyéb"


def column_of(dev):
    t = (dev.get("tipus") or "").lower()
    for k, c in COLUMN.items():
        if k in t:
            return c
    return 1


def device_images(devs):
    """Az eszközök képe a képtárból (eszkoz): {eszköz-azonosító a felállásban: a kép útvonala}; előlap, különben az első."""
    try:
        import muzikos_eszkoz as esz
    except ImportError:
        return {}
    out = {}
    for d in devs:
        try:
            eid = esz.find(d.get("nev") or d.get("id"))
            g = esz.load(eid) if eid else None
        except Exception:
            continue
        views = (g or {}).get("kepek") or {}
        if not views:
            continue
        view = "elolap" if "elolap" in views else sorted(views)[0]
        p = os.path.join(esz.base(), eid, views[view]["fajl"])
        if os.path.exists(p):
            out[d["id"]] = p
    return out


def render(rid):
    """A felállás rajza: önálló HTML (net nélkül is), SVG + oldalsáv a részletekkel + útmutató."""
    r = load(rid)
    devs = r.get("eszkozok", [])
    cols = {0: [], 1: [], 2: [], 3: []}
    for d in devs:
        cols[column_of(d)].append(d)
    # a számítógép a középső oszlop tetejére
    cols[2].sort(key=lambda d: 0 if "számítógép" in (d.get("tipus") or "") else 1)
    W, colw, boxw, boxh, gap = 1240, 300, 230, 96, 40
    pos = {}
    height = 140
    # a kézzel elhelyezett eszközök (x, y a felállásban, #62) maradnak; az újak az oszlopuk szabad helyére kerülnek
    for d in devs:
        if isinstance(d.get("x"), (int, float)) and isinstance(d.get("y"), (int, float)):
            pos[d["id"]] = (int(d["x"]), int(d["y"]))

    def free(x, y):
        return all(abs(x - px) >= boxw + 10 or abs(y - py) >= boxh + 10 for px, py in pos.values())
    for c, lst in cols.items():
        for d in lst:
            if d["id"] in pos:
                continue
            x, y = 40 + c * colw + (colw - boxw) // 2, 110
            while not free(x, y):
                y += boxh + gap
            pos[d["id"]] = (x, y)
    height = max([height] + [py + boxh + gap for _, py in pos.values()])
    data = {"felallas": r, "pos": pos, "box": [boxw, boxh], "rid": rid, "kepek": device_images(devs)}
    cables = []
    for i, c in enumerate(r.get("kabelek", [])):
        a, pa = dev_of(c.get("honnan"))
        b, pb = dev_of(c.get("hova"))
        if a not in pos or b not in pos:
            continue
        col, label = kind_of(c.get("fajta"))
        cables.append({"i": i, "a": a, "b": b, "pa": pa, "pb": pb, "col": col, "label": label,
                       "dash": "8 6" if label == "táp" else "", "fajta": c.get("fajta", ""), "mire": c.get("mire", "")})
    data["cables"] = cables
    steps = []
    names = {d["id"]: d.get("nev", d["id"]) for d in devs}
    for c in cables:
        steps.append(f"<b>{html.escape(names.get(c['a'], c['a']))}</b> {html.escape(c['pa'])} → "
                     f"<b>{html.escape(names.get(c['b'], c['b']))}</b> {html.escape(c['pb'])}"
                     + (f" <span class=k>({html.escape(c['fajta'])})</span>" if c['fajta'] else "")
                     + (f" — {html.escape(c['mire'])}" if c['mire'] else ""))
    page = TEMPLATE.replace("__TITLE__", html.escape(r.get("nev", rid))) \
        .replace("__DATA__", json.dumps(data, ensure_ascii=False)) \
        .replace("__H__", str(height + 40)).replace("__W__", str(W)) \
        .replace("__STEPS__", "\n".join(f"<li><label><input type=checkbox data-i={n}> {s}</label></li>" for n, s in enumerate(steps))) \
        .replace("__RID__", html.escape(rid)) \
        .replace("__WHEN__", html.escape(" · ".join(x for x in (r.get("fajta"), r.get("tag")) if x)
                                         + (" · " if r.get("fajta") or r.get("tag") else "") + "frissítve: " + r.get("modositva", "")[:16].replace("T", " ")))
    out = os.path.join(rig_dir(rid), rid + ".html")
    os.makedirs(rig_dir(rid), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — bekötés</title>
<style>
:root { --bg:#0b0c0f; --card:#1b1d23; --ink:#eef0f3; --sub:#8a909c; --line:#2a2d35; --yellow:#ff7a1a; --red:#ff3b30; }
body { margin:0; font-family: "Saira", "DejaVu Sans", "Segoe UI", Arial, sans-serif; background:var(--bg); color:var(--ink); font-size:15px; }
header { margin:16px 16px 0; padding:14px 20px; border-radius:14px; border:1px solid var(--line); background:linear-gradient(180deg,#20232a,#15171c); box-shadow:inset 0 1px 0 #ffffff12; }
h1 { margin:0; font-size:28px; font-family:"Orbitron","Saira",sans-serif; font-weight:700; } .sub { color:var(--sub); font-size:14px; }
main { display:flex; flex-direction:column; gap:14px; padding:10px 20px 20px; }
#map { background:var(--card); border:1px solid var(--line); border-radius:12px; width:100%; overflow:hidden; }
#svg { display:block; width:100%; height:auto; max-height:78vh; }   /* a teljes rajz a kijelző szélességében, görgetés nélkül (#53) */
aside { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:12px; align-items:start; }   /* alatta az adatok */
.panel { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.panel h2 { font-size:12px; margin:0 0 8px; color:var(--sub); font-family:"Orbitron","Saira",sans-serif; font-weight:700; letter-spacing:2px; text-transform:uppercase; }
.dev { cursor:grab; touch-action:none; } .dev:active { cursor:grabbing; }
.dev rect { fill:#1d2026; stroke:#3a3e48; stroke-width:2; cursor:pointer; } .dev:hover rect { stroke:var(--yellow); }
.dev.sel rect { stroke:var(--yellow); stroke-width:3; } .dev text { pointer-events:none; fill:var(--ink); }
.cab { fill:none; stroke-width:4; stroke-linecap:round; cursor:pointer; } .cab:hover, .cab.sel { stroke-width:7; }
ol { padding-left:20px; margin:0; } li { margin:4px 0; font-size:13px; } .k { color:var(--sub); }
.leg span { display:inline-block; margin:0 10px 4px 0; font-size:12px; } .leg i { display:inline-block; width:22px; height:4px; vertical-align:middle; margin-right:4px; }
.dial { display:inline-block; text-align:center; width:84px; font-size:11px; margin:4px; vertical-align:top; }
.state h3 { font-size:13px; margin:10px 0 2px; } .state img { max-width:100%; border-radius:8px; margin-top:4px; }
.btn { font:inherit; font-size:13px; padding:4px 10px; border-radius:6px; border:1px solid var(--line); background:#2a1f22; color:var(--ink); cursor:pointer; }
a { color:var(--yellow); }
</style></head><body>
<header><h1>__TITLE__</h1><div class="sub">bekötési térkép · __WHEN__ · kattints egy eszközre vagy kábelre · <span id="drag"></span> <span id="savenote" class="k"></span></div></header>
<main>
 <div id="map"><svg id="svg" viewBox="0 0 __W__ __H__" preserveAspectRatio="xMidYMin meet"></svg></div>
 <aside>
  <div class="panel" id="info"><h2>Részletek</h2><div class="k">Kattints egy eszközre vagy kábelre.</div></div>
  <div class="panel"><h2>Próba előtti bekötés</h2><ol id="steps">__STEPS__</ol>
   <div style="margin-top:8px"><button class="btn" onclick="resetSteps()">Újrakezdés</button>
   <span class="k">A végén a Claude bemenetenként megméri, hogy minden a helyén szól-e.</span></div></div>
  <div class="panel leg" id="legend"></div>
 </aside>
</main>
<script>
const D = __DATA__; const R = D.felallas; const [BW, BH] = D.box;
const svg = document.getElementById('svg'); const NS = 'http://www.w3.org/2000/svg';
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); (p || svg).appendChild(e); return e; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const devById = Object.fromEntries((R.eszkozok || []).map(d => [d.id, d]));
const center = id => { const [x, y] = D.pos[id]; return [x + BW / 2, y + BH / 2]; };
// kábelek (alul)
const cabEls = [];
function cabPath(c, n) {
  const [x1, y1] = center(c.a), [x2, y2] = center(c.b);
  const dx = Math.max(60, Math.abs(x2 - x1) / 2);
  const off = (n % 5 - 2) * 9;
  return `M${x1},${y1 + off} C${x1 + (x2 >= x1 ? dx : -dx)},${y1 + off} ${x2 - (x2 >= x1 ? dx : -dx)},${y2 - off} ${x2},${y2 - off}`;
}
D.cables.forEach((c, n) => {
  const p = el('path', { d: cabPath(c, n), class: 'cab', stroke: c.col, 'stroke-dasharray': c.dash, style: `filter:drop-shadow(0 0 3px ${c.col})` });
  p.addEventListener('click', ev => { ev.stopPropagation(); select(p); showCable(c); });
  cabEls.push([p, c, n]);
});
const routeCables = () => cabEls.forEach(([p, c, n]) => p.setAttribute('d', cabPath(c, n)));
// az eszközök egérrel áthúzhatók, a kábelek követik, és az elrendezés magától mentődik (helyi szerveren át, Mentés gomb nélkül)
const EDIT = location.protocol.startsWith('http');
const note = t => { const e = document.getElementById('savenote'); if (e) e.textContent = t; };
document.getElementById('drag').textContent = EDIT ? 'húzd át az eszközöket, magától mentődik' : '(átrendezni a Claude-tól nyitva lehet: felallas_rajz)';
let dragMoved = false, saveTimer = null;
function savePos() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch('/api/pos/' + encodeURIComponent(D.rid), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(D.pos) })
      .then(r => note(r.ok ? '· elrendezés mentve' : '· a mentés nem sikerült')).catch(() => note('· a mentés nem sikerült'));
  }, 300);
}
function svgPoint(ev) { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; return pt.matrixTransform(svg.getScreenCTM().inverse()); }
// eszközök
for (const d of (R.eszkozok || [])) {
  const [x, y] = D.pos[d.id]; const g = el('g', { class: 'dev', transform: `translate(${x},${y})` });
  el('rect', { width: BW, height: BH, rx: 12 }, g);
  if (D.kepek[d.id]) {                                           // az eszköz valódi képe a dobozban (a képtárból)
    const cid = 'clip-' + d.id.replace(/[^a-z0-9]/gi, '_');
    const cp = el('clipPath', { id: cid }, g); el('rect', { width: BW, height: BH, rx: 12 }, cp);
    el('image', { href: imgUrl(D.kepek[d.id]), x: 0, y: 0, width: BW, height: BH, preserveAspectRatio: 'xMidYMid slice', opacity: 0.5, 'clip-path': `url(#${cid})` }, g);
  }
  const t = el('text', { x: BW / 2, y: 34, 'text-anchor': 'middle', 'font-size': 15, 'font-weight': 700 }, g); t.textContent = d.nev || d.id;
  const s = el('text', { x: BW / 2, y: 56, 'text-anchor': 'middle', 'font-size': 12, fill: '#8a909c' }, g); s.textContent = d.tipus || '';
  const nstates = (R.potiallasok || []).filter(p => p.eszkoz === d.id).length;
  if (nstates) { const q = el('text', { x: BW / 2, y: 80, 'text-anchor': 'middle', 'font-size': 12, fill: '#ffa04d' }, g); q.textContent = `◉ ${nstates} mentett potiállás`; }
  g.addEventListener('click', ev => { ev.stopPropagation(); if (dragMoved) return; select(g); showDev(d); });
  if (EDIT) g.addEventListener('pointerdown', ev => {
    const start = svgPoint(ev), orig = [...D.pos[d.id]]; let moved = false;
    g.setPointerCapture(ev.pointerId);
    const move = e => {
      const q = svgPoint(e), dx = q.x - start.x, dy = q.y - start.y;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      const W = +svg.viewBox.baseVal.width, H = +svg.viewBox.baseVal.height;
      D.pos[d.id] = [Math.round(Math.max(0, Math.min(W - BW, orig[0] + dx))), Math.round(Math.max(0, Math.min(H - BH, orig[1] + dy)))];
      g.setAttribute('transform', `translate(${D.pos[d.id][0]},${D.pos[d.id][1]})`);
      routeCables();
    };
    const up = () => {
      g.removeEventListener('pointermove', move); g.removeEventListener('pointerup', up);
      if (moved) { dragMoved = true; setTimeout(() => { dragMoved = false; }, 0); savePos(); }
    };
    g.addEventListener('pointermove', move); g.addEventListener('pointerup', up);
  });
}
function select(x) { document.querySelectorAll('.sel').forEach(e => e.classList.remove('sel')); x.classList.add('sel'); }
// óraállás → szög: 7 óra = minimum, 5 óra = maximum (a legtöbb potin), 12 óra = közép
function angleOf(v) {
  const s = String(v).trim().toLowerCase();
  let m = s.match(/^(\d{1,2})(?:[:.,](\d{1,2}))?\s*(?:óra|ora|h)?$/);
  if (m && (s.includes('ó') || s.includes('o') || s.includes(':') || s.includes('h'))) {
    let h = (+m[1]) % 12 + (+(m[2] || 0)) / 60; return h * 30;            // 0° = 12 óra, az óramutató járásával
  }
  m = s.match(/^(-?\d+(?:[.,]\d+)?)\s*(%|\/10)?$/);
  if (m) { const x = parseFloat(m[1].replace(',', '.')); const f = m[2] === '%' ? x / 100 : x / 10; return -150 + Math.max(0, Math.min(1, f)) * 300; }
  return null;
}
function dial(name, val) {
  const a = angleOf(val); const on = /^(be|on|igen|1)$/i.test(String(val)); const off = /^(ki|off|nem|0)$/i.test(String(val));
  let g = `<svg width="56" height="56" viewBox="-28 -28 56 56"><circle r="22" fill="#f6f8fa" stroke="#2b3a4a" stroke-width="2"/>`;
  if (a !== null) { const r = a * Math.PI / 180; g += `<path d="M-15.6,15.6 A22,22 0 1,1 15.6,15.6" fill="none" stroke="#3d2b2e" stroke-width="3"/><line x1="0" y1="0" x2="${(17 * Math.sin(r)).toFixed(1)}" y2="${(-17 * Math.cos(r)).toFixed(1)}" stroke="#ff7a1a" stroke-width="4" stroke-linecap="round"/>`; }
  else if (on || off) { g += `<rect x="-8" y="-14" width="16" height="28" rx="4" fill="${on ? '#5cbf7d' : '#8a7f78'}"/><circle cx="0" cy="${on ? -6 : 6}" r="6" fill="#f2ece4"/>`; }
  g += `</svg>`; return `<div class="dial">${g}<div><b>${esc(name)}</b></div><div>${esc(val)}</div></div>`;
}
function showDev(d) {
  const cabs = D.cables.filter(c => c.a === d.id || c.b === d.id);
  const states = (R.potiallasok || []).filter(p => p.eszkoz === d.id);
  let h = `<h2>${esc(d.nev || d.id)}</h2><div class="k">${esc(d.tipus || '')}</div>`;
  if (d.megjegyzes) h += `<p>${esc(d.megjegyzes)}</p>`;
  if (d.portok) h += `<p><b>Portok:</b> ${d.portok.map(esc).join(' · ')}</p>`;
  if (cabs.length) h += `<p><b>Kábelek:</b><br>${cabs.map(c => `${esc(devById[c.a]?.nev || c.a)} ${esc(c.pa)} → ${esc(devById[c.b]?.nev || c.b)} ${esc(c.pb)} <span class=k>${esc(c.fajta)}</span>`).join('<br>')}</p>`;
  for (const s of states) {
    h += `<div class="state"><h3>◉ ${esc(s.nev)} <span class=k>${esc((s.mikor || '').replace('T', ' '))}</span></h3>`;
    h += Object.entries(s.allasok || {}).map(([k, v]) => dial(k, v)).join('');
    if (s.megjegyzes) h += `<div class=k>${esc(s.megjegyzes)}</div>`;
    if (s.foto) h += `<img src="${esc(relPath(s.foto))}" alt="fotó">`;
    h += `</div>`;
  }
  if (D.kepek[d.id]) h += `<img src="${esc(imgUrl(D.kepek[d.id]))}" style="max-width:100%;border-radius:8px;margin-top:8px" alt="${esc(d.nev || d.id)}">`;
  else if (d.kep) h += `<img src="${esc(relPath(d.kep))}" style="max-width:100%;border-radius:8px">`;
  document.getElementById('info').innerHTML = h;
}
function imgUrl(p) { return EDIT ? '/_f/' + encodeURIComponent(p).replace(/%2F/g, '/') : 'file://' + p; }
function relPath(p) { const i = p.indexOf('/felallasok/'); return i >= 0 ? p.slice(i + 12) : (EDIT ? '/_f/' + encodeURIComponent(p).replace(/%2F/g, '/') : 'file://' + p); }
function showCable(c) {
  document.getElementById('info').innerHTML = `<h2>Kábel</h2><p><b>${esc(devById[c.a]?.nev || c.a)}</b> ${esc(c.pa)}<br>→ <b>${esc(devById[c.b]?.nev || c.b)}</b> ${esc(c.pb)}</p><p><span style="display:inline-block;width:26px;height:5px;background:${c.col};vertical-align:middle"></span> ${esc(c.fajta || c.label)}</p>${c.mire ? `<p>${esc(c.mire)}</p>` : ''}`;
}
// jelmagyarázat
const seen = {}; for (const c of D.cables) seen[c.label] = c.col;
document.getElementById('legend').innerHTML = '<h2>Kábelek</h2>' + Object.entries(seen).map(([l, c]) => `<span><i style="background:${c}"></i>${esc(l)}</span>`).join('');
// az útmutató pipái megmaradnak (böngészőnként)
const KEY = 'muzikos-bekotes-__RID__';
function loadSteps() { let s = {}; try { s = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {} document.querySelectorAll('#steps input').forEach(i => { i.checked = !!s[i.dataset.i]; i.onchange = saveSteps; }); }
function saveSteps() { const s = {}; document.querySelectorAll('#steps input').forEach(i => { if (i.checked) s[i.dataset.i] = 1; }); try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
function resetSteps() { try { localStorage.removeItem(KEY); } catch (e) {} loadSteps(); }
loadSteps();
svg.addEventListener('click', () => document.querySelectorAll('.sel').forEach(e => e.classList.remove('sel')));
</script></body></html>
"""


RIG_PORT = 8777
OPENER = ["xdg-open"]
_rig_srv = {}


def save_positions(rid, body):
    """Az áthúzott eszközök helye a felállásba (eszkozok[].x, .y); csak a megadottak változnak, más nem."""
    cur = load(rid)
    if not cur:
        raise ValueError("nincs ilyen felállás")
    n = 0
    for d in cur.get("eszkozok", []):
        v = body.get(str(d.get("id")))
        if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(t, (int, float)) for t in v):
            d["x"], d["y"] = int(v[0]), int(v[1])
            n += 1
    cur["modositva"] = now()
    mem.write_json(rig_path(rid, cur.get("zenekar")), cur)
    return n


def rig_http():
    """Helyi szerver (csak 127.0.0.1) a felállás-rajzokhoz: kiszolgálja az oldalt, és menti az áthúzott eszközök helyét
    (POST /api/pos/<felállás>), Mentés gomb nélkül (#62). Egyszer indul, a Claude-folyamattal együtt él; a portja: port."""
    import http.server
    import mimetypes
    import threading
    import urllib.parse
    if _rig_srv.get("port"):
        return _rig_srv["port"]
    base = os.path.realpath(os.path.dirname(mem.root()))

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            f = None
            if path.startswith("/_f/"):                       # egy kép (pl. potiállás-fotó) a MuzikOS-mappából
                c = os.path.realpath(path[4:])
                if c.startswith(base + os.sep) and os.path.isfile(c):
                    f = c
            else:
                rel = path.lstrip("/")
                for d in rig_dirs():
                    c = os.path.realpath(os.path.join(d, rel))
                    if c.startswith(os.path.realpath(d) + os.sep) and os.path.isfile(c):
                        f = c
                        break
            if not f:
                return self._send(404, b"nincs ilyen")
            with open(f, "rb") as fh:
                self._send(200, fh.read(), (mimetypes.guess_type(f)[0] or "application/octet-stream") +
                           ("; charset=utf-8" if f.endswith(".html") else ""))

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path == "/api/open":     # a dallista gombjai: Reaper, kotta, jegyzet, mappa (#64)
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    target = os.path.realpath(json.loads(self.rfile.read(n).decode("utf-8"))["path"]) if 0 < n < 5000 else ""
                except (ValueError, KeyError, TypeError, OSError):
                    return self._send(400)
                if not (target.startswith(base + os.sep) and os.path.exists(target)):
                    return self._send(403, "csak a MuzikOS-mappán belüli fájl nyitható".encode("utf-8"))
                subprocess.Popen(OPENER + [target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return self._send(200, b"ok")
            m = re.match(r"^/api/pos/([^/]+)$", urllib.parse.urlparse(self.path).path)
            if not m:
                return self._send(404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 < n < 200000:
                    return self._send(413)
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(body, dict):
                    return self._send(400)
                save_positions(urllib.parse.unquote(m.group(1)), body)
            except (ValueError, OSError):
                return self._send(400)
            self._send(200, b"ok")

    srv = None
    for port in range(RIG_PORT, RIG_PORT + 10):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    if not srv:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _rig_srv["port"] = srv.server_address[1]
    return _rig_srv["port"]


def tool_felallas_rajz(args):
    rid = find_rig(args.get("name"))
    if not rid:
        raise ValueError("Nincs mostani felállás (felallas action=set).")
    out = render(rid)
    port = rig_http()
    url = f"http://127.0.0.1:{port}/{rid}.html" if port else out
    if args.get("open", True):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    devs = load(rid).get("eszkozok", [])
    imgs = device_images(devs)
    nokep = [d.get("nev") or d.get("id") for d in devs if d["id"] not in imgs]
    return {"rajz": out, "cim": url, "megnyitva": bool(args.get("open", True)),
            **({"kep_nelkul": nokep, "mit_tegyel": "Ezeknek az eszközöknek még nincs képe a képtárban: ajánld fel a zenésznek, hogy beszerzed "
                "(a gyártó vagy egy bolt termékfotója netről, vagy a fotóláda: eszkoz action=kep); addig a rajz dobozt mutat."} if nokep else {}),
            "megjegyzes": "Az eszközök egérrel áthúzhatók, a kábelek követik, és az elrendezés magától mentődik (a felállás x/y-jába); "
                          "a Claude által hozzáadott új eszköz szabad helyre kerül, a kézzel elrendezetteket nem mozgatja."}


TOOLS = [
    ("felallas", tool_felallas,
     "A zenekar felállásai (bekötési térkép); egy zenekarnak több is van: szobapróba (ötletelés), próbaterem (gyakorlás koncertre), koncert, és a tagok otthoni setupja. list (a mostani zenekaré); get; set (name + data: fajta, tag (otthoninál kié), eszkozok [{id, nev, tipus, portok, megjegyzes}], kabelek [{honnan: \"id: port\", hova, fajta, mire}], zeneszek, reaper_savok, teendok — az eszközök id szerint frissülnek, {_torles: true} töröl); activate (name: név vagy szóban: „terem”, „szobapróba”, „koncert”, „Bence otthon” — visszaadja a bekötést, a sávokat és a teendőket). Mentés után a rajz is frissül.",
     {"action": {"type": "string", "enum": ["list", "get", "set", "activate", "import"]},
      "name": {"type": "string"}, "data": {"type": "object"}, "band": {"type": "string"},
      "path": {"type": "string", "description": "import: egy kész felállás JSON-fájlja"}}),
    ("felallas_kabel", tool_felallas_kabel,
     "Egy kábel a felállásban: add (honnan, hova „id: port”, fajta, mire — az ugyanonnan induló régi kábel cserélődik: „ma a basszus a 3-asba megy”) vagy remove (honnan és/vagy hova).",
     {"action": {"type": "string", "enum": ["add", "remove"]}, "honnan": {"type": "string"}, "hova": {"type": "string"},
      "fajta": {"type": "string"}, "mire": {"type": "string"}, "name": {"type": "string"}}),
    ("felallas_rajz", tool_felallas_rajz,
     "A felállás kattintható rajza (helyi weboldal, net nélkül): eszközök, kábelek fajta szerint színezve, részletek kattintásra, mentett potiállások számlappal, próba előtti útmutató pipálható lépésekkel. Az eszközök egérrel áthúzhatók (a kábelek követik), az elrendezés magától mentődik. open=true a böngészőben megnyitja.",
     {"name": {"type": "string"}, "open": {"type": "boolean"}}),
    ("fotolada", tool_fotolada,
     "Fotóláda a telefonoknak: open = egy kis feltöltő oldal a helyi hálózaton (QR-kód a képernyőn, egyszer használatos cím, 15 percig él), amin egy tag lefotózza az eszközt vagy képeket küld; list = a beérkezett képek (a legújabb elöl). A képet a foto_megnezes mutatja meg neked.",
     {"action": {"type": "string", "enum": ["open", "list"]}, "minutes": {"type": "integer"}, "show": {"type": "boolean"}, "limit": {"type": "integer"}}),
    ("potiallas", tool_potiallas,
     "Potiállások: save (eszkoz = az eszköz id-je, allas = név, allasok = {\"Gain 1\": \"2 óra\", \"48V\": \"ki\", \"Hi-Z 2\": \"be\"}, foto = a kép útvonala) — az értékeket TE olvasod le a fotóról; list; get (eszkoz, allas); delete.",
     {"action": {"type": "string", "enum": ["list", "get", "save", "delete"]}, "eszkoz": {"type": "string"},
      "allas": {"type": "string"}, "allasok": {"type": "object"}, "foto": {"type": "string"},
      "megjegyzes": {"type": "string"}, "name": {"type": "string"}}),
]
