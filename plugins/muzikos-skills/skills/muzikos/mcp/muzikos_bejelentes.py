"""Problémabejelentés (#3): ami a MuzikOS használata közben fejlesztésre szorul (visszatérő hiba, ismétlődő kérés,
amit nem tudott), azt helyben feljegyzi, és a zenész jóváhagyásával beküldi a MuzikOS saját szerverének
(muzikos-mcp, #44) — bármelyik MuzikOS-ról, a neten át.

    napló:    <tudás>/Bejelentesek/naplo.json — kulcsonként a gyakoriság, az első és utolsó előfordulás, a gép és a lépés.
              Hangfelvétel, jelszó és mások adata nem kerül bele: a szöveget a tisztítás (tisztit) átmossa.
    küldés:   a piszkozat pontos szövegét a zenész látja; a küldés csak az ő jóváhagyása után megy el, és csak az a
              szöveg, amelyiknek az ujjlenyomatát jóváhagyták (a szöveg közben nem változhat).
    sor:      ha nincs net (vagy a szerver nem válaszol), a bejelentés a sorba áll (sor.json), és a háttérfigyelő vagy a
              következő hívás elküldi; a `ref` (kulcs + a szöveg ujjlenyomata) miatt a szerver ugyanazt nem veszi fel
              kétszer.
    cél:      env MUZIKOS_BEJELENTES_URL / MUZIKOS_BEJELENTES_TITOK, vagy /etc/muzikos/bejelentes.json, vagy
              <tudás>/bejelentes.json: {"url": "https://…", "titok": "…"}. A titok csak beküldésre jó (a muzikos-mcp-é,
              nem a csukaj-é); a POST címe <url>/idea/<titok>.
"""
import hashlib
import json
import os
import platform
import re
import socket
import time
import urllib.error
import urllib.request

import muzikos_memory as mem

AJANLAS_KUSZOB = 3          # ugyanaz harmadszor: a Claude magától felajánlja a beküldést
PLUGIN_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".claude-plugin", "plugin.json")


def mappa():
    d = os.path.join(mem.root(), "Bejelentesek")
    os.makedirs(d, exist_ok=True)
    return d


def _olvas(nev, alap):
    return mem.read_json(os.path.join(mappa(), nev), alap)


def _ir(nev, adat):
    mem.write_json(os.path.join(mappa(), nev), adat)


# ----------------------------------------------------------------------------- tisztítás

_MINTAK = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[e-mail]"),
    (re.compile(r"(?i)\b(jelsz[óo]|password|passwd|token|titok|secret|api[_-]?key)\b\s*[:=]\s*\S+"), r"\1=[kitakarva]"),
    (re.compile(r"\b(sk|ghp|gho|xox[bp])-?[A-Za-z0-9_-]{16,}\b"), "[kulcs]"),
    (re.compile(r"[?&](token|key|sig|auth)=[^\s&]+", re.I), "?[kitakarva]"),
    (re.compile(r"(/(?:media|run/media|home)/)[^/\s]+"), r"\1[felhasznalo]"),
    (re.compile(r"\S+\.(?:wav|flac|mp3|ogg|aif|aiff|m4a|rpp|rpp-bak|rpp-prox)\b", re.I), "[hangfájl]"),
    (re.compile(r"\b[0-9a-f]{32,}\b", re.I), "[azonosító]"),
]


def tisztit(s):
    """(átmosott szöveg, hány helyen takart ki valamit)"""
    s = str(s or "")
    db = 0
    for minta, csere in _MINTAK:
        s, n = minta.subn(csere, s)
        db += n
    return s.strip(), db


# ----------------------------------------------------------------------------- beállítás, környezet

def cel():
    url, titok = os.environ.get("MUZIKOS_BEJELENTES_URL"), os.environ.get("MUZIKOS_BEJELENTES_TITOK")
    if not (url and titok):
        for p in ("/etc/muzikos/bejelentes.json", os.path.join(mem.root(), "bejelentes.json")):
            c = mem.read_json(p, {})
            if c.get("url") and c.get("titok"):
                url, titok = c["url"], c["titok"]
                break
    if not (url and titok):
        return None
    return url.rstrip("/") + "/idea/" + titok


def plugin_verzio():
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            return json.load(f).get("version", "?")
    except (OSError, ValueError):
        return "?"


def kep_verzio():
    for p in ("/etc/muzikos-release", "/etc/muzikos/kep"):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read().strip()[:80]
        except OSError:
            pass
    return "ismeretlen"


def beküldő(args):
    """A neve a zenekari profilból (bejelento mező), vagy a kérésből; ennél több személyes adat nem megy."""
    if args.get("nev"):
        return tisztit(args["nev"])[0][:60]
    bid = mem.active()
    if bid:
        b = mem.read_json(os.path.join(mem.band_dir(bid), "zenekar.json"), {})
        if b.get("bejelento"):
            return tisztit(b["bejelento"])[0][:60]
    return "névtelen"


# ----------------------------------------------------------------------------- szöveg és ujjlenyomat

def szoveg(kulcs, e, nev):
    lepesek = [f"- {l}" for l in e.get("lepesek", [])[-5:]]
    gepek = ", ".join(sorted(set(e.get("gepek", [])))) or "ismeretlen"
    sorok = [
        e["cim"], "",
        e["leiras"], "",
        f"Gyakoriság: {e['db']}× (először {e['elso'][:10]}, utoljára {e['utolso'][:10]})",
        f"Gép: {gepek}",
        f"Kép: {kep_verzio()} · plugin {plugin_verzio()}",
        f"Bejelentő: {nev}",
    ]
    if lepesek:
        sorok += ["", "Mit csináltunk, mielőtt előjött:"] + lepesek
    return "\n".join(sorok)


def ujjlenyomat(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def ref(kulcs, s):
    return f"muzikos:{mem.slug(kulcs)}:{ujjlenyomat(s)}"


def gep():
    return " ".join(x for x in (platform.node(), platform.machine()) if x)[:80]


# ----------------------------------------------------------------------------- sor és küldés

def _kuld(tartalom, url, timeout=15):
    """True: a szerver elfogadta (2xx, vagy már megvolt: 409). False: nincs net / nem válaszol (sorba megy).
    ValueError: a szerver visszautasította (rossz titok, hibás tartalom): ez nem javul magától."""
    req = urllib.request.Request(url, data=json.dumps(tartalom, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "muzikos-bejelentes"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return True
        if e.code in (401, 403, 404, 422):
            raise ValueError(f"A szerver visszautasította a bejelentést (HTTP {e.code}): a cím vagy a titok hibás?")
        return False
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def sor_kuldes():
    """A sorban várók elküldése; minden bejelentés egyszer ér célba. Visszaadja: (elment, marad)."""
    sor = _olvas("sor.json", [])
    url = cel()
    if not sor or not url:
        return 0, len(sor)
    marad, elment = [], 0
    for t in sor:
        try:
            ok = _kuld(t, url)
        except ValueError:
            ok = False
        if ok:
            elment += 1
            kuldve = _olvas("kuldve.json", {})
            kuldve[t["ref"]] = mem.now()
            _ir("kuldve.json", kuldve)
        else:
            marad.append(t)
    if elment:
        _ir("sor.json", marad)
    return elment, len(marad)


def hatterben():
    """A háttérfigyelő hívja percenként: ami sorban várt, a net megjöttével elmegy."""
    try:
        sor_kuldes()
    except Exception:
        pass


# ----------------------------------------------------------------------------- az eszköz

def tool_bejelentes(args):
    act = args.get("action", "lista")
    naplo = _olvas("naplo.json", {})
    if act != "sor_kuldes":
        sor_kuldes()

    if act == "jegyez":
        kulcs = mem.slug(args.get("kulcs") or args.get("cim") or "")
        if kulcs == "nevtelen":
            raise ValueError("Kell a kulcs (rövid, mindig ugyanaz ugyanarra a problémára) vagy a cim.")
        e = naplo.get(kulcs)
        cim, leiras = tisztit(args.get("cim") or (e or {}).get("cim"))[0], tisztit(args.get("leiras") or (e or {}).get("leiras"))[0]
        if not cim or not leiras:
            raise ValueError("Kell a cim (egy mondat) és a leiras (mi történt, mit vártunk).")
        if not e:
            e = {"cim": cim, "leiras": leiras, "db": 0, "elso": mem.now(), "gepek": [], "lepesek": []}
        e.update({"cim": cim, "leiras": leiras, "db": e["db"] + 1, "utolso": mem.now()})
        e["gepek"] = (e["gepek"] + [gep()])[-5:]
        if args.get("lepes"):
            e["lepesek"] = (e["lepesek"] + [tisztit(args["lepes"])[0][:200]])[-10:]
        naplo[kulcs] = e
        _ir("naplo.json", naplo)
        kuldve = any(r.split(":")[1] == kulcs for r in _olvas("kuldve.json", {})) or any(
            t["ref"].split(":")[1] == kulcs for t in _olvas("sor.json", []))
        out = {"kulcs": kulcs, "db": e["db"], "mentve": True}
        if e["db"] >= AJANLAS_KUSZOB and not kuldve:
            out["felajanlas"] = (f"Ez már {e['db']}. alkalom: ajánld fel a zenésznek, hogy beküldöd a problémát "
                                 "(bejelentes action=piszkozat, megmutatod a szöveget, a jóváhagyása után kuldes).")
        return out

    if act == "lista":
        return {"problemak": [{"kulcs": k, "cim": v["cim"], "db": v["db"], "utolso": v["utolso"]}
                              for k, v in sorted(naplo.items(), key=lambda kv: -kv[1]["db"])],
                "sorban_var": len(_olvas("sor.json", [])), "beallitva": cel() is not None}

    if act == "sor_kuldes":
        elment, marad = sor_kuldes()
        return {"elment": elment, "marad": marad, "beallitva": cel() is not None}

    kulcs = mem.slug(args.get("kulcs") or "")
    e = naplo.get(kulcs)
    if not e:
        raise ValueError(f"Nincs ilyen feljegyzett probléma: {kulcs}. A listához: action=lista.")
    nev = beküldő(args)
    s, db = tisztit(szoveg(kulcs, e, nev))

    if act == "piszkozat":
        return {"kulcs": kulcs, "szoveg": s, "ujjlenyomat": ujjlenyomat(s), "kitakarva": db,
                "mit_tegyel": "Mutasd meg a zenésznek pontosan ezt a szöveget, és kérdezd meg, elküldhetem-e. "
                              "Csak a kifejezett igen után hívd a kuldes-t, az ujjlenyomattal együtt."}

    if act == "kuldes":
        if args.get("ujjlenyomat") != ujjlenyomat(s):
            raise ValueError("A jóváhagyott szöveg nem egyezik a mostanival (vagy nincs ujjlenyomat): kérj újra piszkozatot, "
                             "és azt mutasd meg a zenésznek.")
        r = ref(kulcs, s)
        kuldve = _olvas("kuldve.json", {})
        if r in kuldve:
            return {"allapot": "mar_elkuldve", "ref": r, "mikor": kuldve[r]}
        if any(t["ref"] == r for t in _olvas("sor.json", [])):
            return {"allapot": "sorban_var", "ref": r}
        t = {"ref": r, "title": e["cim"], "body": s, "source": f"muzikos {kep_verzio()} / plugin {plugin_verzio()}",
             "reporter": nev, "created_at": mem.now()}
        url = cel()
        if url and _kuld(t, url):
            kuldve[r] = mem.now()
            _ir("kuldve.json", kuldve)
            return {"allapot": "elkuldve", "ref": r}
        sor = _olvas("sor.json", [])
        sor.append(t)
        _ir("sor.json", sor)
        return {"allapot": "sorba_allt", "ref": r,
                "ok": "nincs beállított cél (a muzikos-mcp még nincs bekötve)" if not url else "nincs net vagy a szerver nem válaszol",
                "mit_mondj": "Elmentettem, a net megjöttével magától elmegy, egyszer."}

    raise ValueError("Ismeretlen action: jegyez | lista | piszkozat | kuldes | sor_kuldes.")


TOOLS = [
    ("bejelentes", tool_bejelentes,
     "Problémabejelentés a MuzikOS fejlesztőinek. Amikor valami visszatérően elromlik, vagy a zenész olyat kér, amit a "
     "MuzikOS nem tud, jegyezd fel (jegyez: kulcs = rövid, ugyanarra a problémára mindig ugyanaz; cim = egy mondat; leiras = "
     "mi történt és mit vártunk; lepes = mit csináltunk előtte). Ugyanaz harmadszor: a válasz `felajanlas` mezője szól, "
     "ilyenkor ajánld fel a beküldést. Beküldés: piszkozat (a pontos szöveg és az ujjlenyomata) → MUTASD MEG a zenésznek → "
     "csak a kifejezett igen után kuldes az ujjlenyomattal. Hangfelvétel, jelszó, e-mail és mások adata nem megy bele (a "
     "szöveget átmossa). Net nélkül sorba áll, és később egyszer elmegy (sor_kuldes: azonnali újrapróbálás). lista: a "
     "feljegyzett problémák gyakorisággal. nev: a bejelentő neve (alap: a zenekari profil `bejelento` mezője).",
     {"action": {"type": "string", "enum": ["jegyez", "lista", "piszkozat", "kuldes", "sor_kuldes"]},
      "kulcs": {"type": "string"}, "cim": {"type": "string"}, "leiras": {"type": "string"}, "lepes": {"type": "string"},
      "ujjlenyomat": {"type": "string"}, "nev": {"type": "string"}}),
]
