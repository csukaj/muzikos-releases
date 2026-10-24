"""Folyamatos fejlesztési napló (#69): a MuzikOS magától rögzíti, ami a fejlesztéshez hasznos, és naponta elküldi a
MuzikOS saját szerverének (muzikos-mcp, #44) — ugyanazon a csatornán, sorral és ismétlésmentesen, mint a
problémabejelentés (#3, muzikos_bejelentes).

    napló:    <tudás>/Bejelentesek/fejlesztesi-naplo.json — bejegyzésenként idő, típus, szöveg (mi történt → mi kellene),
              eszköz. Típusok: hiba, kezi_megoldas, elutasitas, eszrevetel (a zenész szavai szó szerint), selftest,
              hangkimaradas, gep. A szöveget a bejelentés tisztítása átmossa: hangfelvétel, dal, kotta, jelszó, e-mail
              és más személyes adat nem kerül bele.
    magától:  a háttérfigyelő naponta egyszer gép-pillanatképet ír (kép- és pluginverzió, hangeszközök, hangkimaradások
              száma a napló.log-ból) és a naplóba kerülő hibasorokat felveszi; a Claude a munkamenet végén vagy egy hiba
              után ír egy-két sort (`jegyez`).
    küldés:   naponta egyszer, egy csomagban; net nélkül a bejelentés sorába áll, és később egyszer megy el (a `ref`
              miatt a szerver nem veszi fel kétszer). Csak az megy, ami be van kapcsolva:
                be      — Józsi gépe (bejelentes.json: "naplo_alapbol": true), vagy a zenész igent mondott
                ki      — a zenész kikapcsolta
                kerdezni — még nem döntött: semmi nem megy el, a Claude az első indításkor megkérdezi
    átnézés:  `mit_kuldenel` a pontos szöveget mutatja, `beallit` be-/kikapcsol.
"""
import hashlib
import json
import os
import re
import time

import muzikos_bejelentes as bejel
import muzikos_memory as mem

TIPUSOK = ("hiba", "kezi_megoldas", "elutasitas", "eszrevetel", "selftest", "hangkimaradas", "gep")
MAX_BEJEGYZES = 500            # a helyi napló mérete: a régebbiek (már elküldöttek) kihullanak
NAPLO_LOG = os.path.expanduser("~/.local/state/muzikos/naplo.log")
HIBA_JEL = re.compile(r"\b(hiba|error|exception|traceback|failed|nem sikerült)\b", re.I)


def _fajl():
    return os.path.join(bejel.mappa(), "fejlesztesi-naplo.json")


def _allapot():
    return mem.read_json(_fajl(), {"bejegyzesek": [], "log_hely": 0, "utolso_pillanatkep": "", "utolso_kuldes": ""})


def _ment(a):
    a["bejegyzesek"] = a["bejegyzesek"][-MAX_BEJEGYZES:]
    mem.write_json(_fajl(), a)


def beallitas():
    """A küldés állapota: be | ki | kerdezni (a zenész döntése a bejelentes.json-ban, vagy Józsi gépe alapból be)."""
    for p in ("/etc/muzikos/bejelentes.json", os.path.join(mem.root(), "bejelentes.json")):
        c = mem.read_json(p, {})
        if c.get("naplo_kuldes") in ("be", "ki"):
            return c["naplo_kuldes"]
        if c.get("naplo_alapbol"):
            return "be"
    return "kerdezni"


def _dontes_ment(ertek):
    p = os.path.join(mem.root(), "bejelentes.json")
    c = mem.read_json(p, {})
    c["naplo_kuldes"] = ertek
    mem.write_json(p, c)


def felvesz(tipus, szoveg, eszkoz="", allapot=None):
    """Egy bejegyzés a naplóba (átmosva). Visszaadja, mennyi mindent takart ki a tisztítás."""
    szoveg, db = bejel.tisztit(szoveg)
    if not szoveg:
        return 0
    a = allapot if allapot is not None else _allapot()
    a["bejegyzesek"].append({"ido": mem.now(), "tipus": tipus, "szoveg": szoveg[:600],
                             "eszkoz": bejel.tisztit(eszkoz)[0][:80], "kuldve": False})
    if allapot is None:
        _ment(a)
    return db


# ----------------------------------------------------------------------------- magától

def _hangeszkozok():
    code, out, _ = bejel_sh("pactl list short cards | cut -f2")
    return [l.strip() for l in out.splitlines() if l.strip() and "bluez" not in l.lower()][:8] if code == 0 else []


def bejel_sh(cmd):
    import subprocess
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def pillanatkep(a):
    """Naponta egyszer: a kép és a plugin verziója, a bedugott hangeszközök."""
    nap = time.strftime("%Y-%m-%d")
    if a.get("utolso_pillanatkep") == nap:
        return
    a["utolso_pillanatkep"] = nap
    eszk = _hangeszkozok()
    felvesz("gep", f"Kép: {bejel.kep_verzio()} · plugin {bejel.plugin_verzio()} · hangeszközök: "
                   f"{', '.join(eszk) or 'nem mérhető'}", allapot=a)


def logbol(a):
    """A háttérfigyelők naplójából (naplo.log) az új hibasorok kerülnek a fejlesztési naplóba (a legutóbbi 20)."""
    try:
        meret = os.path.getsize(NAPLO_LOG)
        hely = a.get("log_hely", 0) if a.get("log_hely", 0) <= meret else 0     # megcsonkították: elölről
        with open(NAPLO_LOG, encoding="utf-8", errors="replace") as f:
            f.seek(hely)
            sorok = f.read().splitlines()
            a["log_hely"] = f.tell()
    except OSError:
        return
    for s in [s for s in sorok if HIBA_JEL.search(s)][-20:]:
        felvesz("hiba", s[:300], allapot=a)


# ----------------------------------------------------------------------------- küldés

def _csomag(a):
    """A még el nem küldött bejegyzések egy szövegben (ezt látja a zenész is) és az ujjlenyomata."""
    uj = [b for b in a["bejegyzesek"] if not b.get("kuldve")]
    if not uj:
        return None, [], ""
    sorok = [f"{b['ido'][:16]} [{b['tipus']}]" + (f" ({b['eszkoz']})" if b.get("eszkoz") else "") + f" {b['szoveg']}"
             for b in uj]
    szoveg = (f"MuzikOS fejlesztési napló · {bejel.gep() or 'ismeretlen gép'} · kép {bejel.kep_verzio()} · "
              f"plugin {bejel.plugin_verzio()}\n\n" + "\n".join(sorok))
    return szoveg, uj, hashlib.sha256(szoveg.encode("utf-8")).hexdigest()[:12]


def kuld(a, kenyszer=False):
    """Elküldi (vagy sorba állítja) a nem küldött bejegyzéseket. Csak bekapcsolt állapotban megy el valami."""
    if beallitas() != "be" and not kenyszer:
        return {"allapot": "nincs_bekapcsolva", "beallitas": beallitas()}
    szoveg, uj, ujj = _csomag(a)
    if not uj:
        return {"allapot": "nincs_uj_bejegyzes"}
    r = f"muzikos-naplo:{mem.slug(bejel.gep() or 'gep')}:{ujj}"
    t = {"ref": r, "title": f"Fejlesztési napló · {bejel.gep() or 'ismeretlen gép'} · {time.strftime('%Y-%m-%d')}",
         "body": szoveg, "source": f"muzikos-naplo {bejel.kep_verzio()} / plugin {bejel.plugin_verzio()}",
         "reporter": bejel.beküldő({}), "created_at": mem.now()}
    url = bejel.cel()
    elkuldve = False
    if url:
        try:
            elkuldve = bejel._kuld(t, url)
        except ValueError:
            elkuldve = False
    if not elkuldve:
        sor = bejel._olvas("sor.json", [])
        if not any(x["ref"] == r for x in sor):
            sor.append(t)
            bejel._ir("sor.json", sor)
    else:
        k = bejel._olvas("kuldve.json", {})
        k[r] = mem.now()
        bejel._ir("kuldve.json", k)
    for b in uj:                      # a sorba állt csomag is „kész”: a sor gondoskodik róla, ismétlés nélkül
        b["kuldve"] = True
    a["utolso_kuldes"] = time.strftime("%Y-%m-%d")
    _ment(a)
    return {"allapot": "elkuldve" if elkuldve else "sorba_allt", "bejegyzes": len(uj), "ref": r}


def hatterben():
    """A háttérfigyelő hívja percenként: a napi pillanatkép, az új hibasorok, és naponta egyszer a küldés."""
    try:
        a = _allapot()
        if beallitas() == "ki":
            return
        pillanatkep(a)
        logbol(a)
        _ment(a)
        if a.get("utolso_kuldes") != time.strftime("%Y-%m-%d"):
            kuld(a)
    except Exception:
        pass


# ----------------------------------------------------------------------------- az eszköz

def tool_fejlesztesi_naplo(args):
    act = args.get("action", "allapot")
    a = _allapot()

    if act == "jegyez":
        if beallitas() == "ki":
            return {"mentve": False, "ok": "a zenész kikapcsolta a fejlesztési naplót"}
        tipus = args.get("tipus") or "eszrevetel"
        if tipus not in TIPUSOK:
            raise ValueError(f"Ismeretlen tipus: {tipus}. Lehet: {', '.join(TIPUSOK)}.")
        if not (args.get("szoveg") or "").strip():
            raise ValueError("Kell a szoveg (egy-két sor: mi történt → mi kellene; észrevételnél a zenész szavai szó szerint).")
        db = felvesz(tipus, args["szoveg"], args.get("eszkoz", ""), allapot=a)
        _ment(a)
        return {"mentve": True, "kitakarva": db, "bejegyzesek": len(a["bejegyzesek"])}

    if act == "lista":
        n = int(args.get("db") or 30)
        return {"bejegyzesek": a["bejegyzesek"][-n:], "osszes": len(a["bejegyzesek"]),
                "nem_kuldve": sum(1 for b in a["bejegyzesek"] if not b.get("kuldve"))}

    if act == "mit_kuldenel":
        szoveg, uj, ujj = _csomag(a)
        return {"szoveg": szoveg or "(nincs el nem küldött bejegyzés)", "bejegyzes": len(uj), "ujjlenyomat": ujj,
                "beallitas": beallitas(), "mit_mondj": "Mutasd meg a zenésznek pontosan ezt; kikapcsolhatja (beallit)."}

    if act == "beallit":
        ertek = args.get("kuldes")
        if ertek not in ("be", "ki"):
            raise ValueError("A kuldes értéke be vagy ki (a zenész kifejezett válasza alapján).")
        _dontes_ment(ertek)
        return {"beallitas": ertek}

    if act == "kuld":
        return kuld(a, kenyszer=beallitas() == "be")

    if act == "allapot":
        return {"beallitas": beallitas(), "bejegyzesek": len(a["bejegyzesek"]),
                "nem_kuldve": sum(1 for b in a["bejegyzesek"] if not b.get("kuldve")),
                "utolso_kuldes": a.get("utolso_kuldes") or None, "beallitva_a_szerver": bejel.cel() is not None,
                "mit_tegyel": ("Kérdezd meg a zenészt: a MuzikOS naponta elküldhetné a fejlesztőknek a hibákat és az észrevételeit "
                               "(hangfelvétel, dal, kotta, jelszó, e-mail nélkül), megnézheti, mi menne el. Küldhetem? "
                               "A válasz alapján beallit.") if beallitas() == "kerdezni" else None}

    raise ValueError("Ismeretlen action: jegyez | lista | mit_kuldenel | beallit | kuld | allapot.")


TOOLS = [
    ("fejlesztesi_naplo", tool_fejlesztesi_naplo,
     "Folyamatos fejlesztési napló: ami a MuzikOS fejlesztéséhez hasznos, azt kérés nélkül jegyezd fel (jegyez: tipus = hiba | "
     "kezi_megoldas (amit kézzel kellett megkerülni, pl. pw-link) | elutasitas (a zenész kijavította vagy elvetette az "
     "eredményt) | eszrevetel (a zenész szavai SZÓ SZERINT, ha azt mondja „ezt jegyezd fel”) | selftest | hangkimaradas; "
     "szoveg = egy-két sor: mi történt → mi kellene; eszkoz = hangkártya, dob, pedál). Írj a munkamenet végén és minden hiba "
     "után. A gép-pillanatkép és a naplo.log hibái magától kerülnek bele, a napló naponta magától elmegy a fejlesztőknek "
     "(net nélkül később, egyszer). Hangfelvétel, dal, kotta, jelszó, e-mail nem megy bele. action=allapot: ha a beallitas "
     "„kerdezni”, az első indításkor kérdezd meg a zenészt (mit_tegyel), és a válasza szerint beallit be/ki. mit_kuldenel: a "
     "pontos szöveg, amit a zenész megnézhet; kuld: azonnali küldés.",
     {"action": {"type": "string", "enum": ["jegyez", "lista", "mit_kuldenel", "beallit", "kuld", "allapot"]},
      "tipus": {"type": "string", "enum": list(TIPUSOK)}, "szoveg": {"type": "string"}, "eszkoz": {"type": "string"},
      "kuldes": {"type": "string", "enum": ["be", "ki"]}, "db": {"type": "integer"}}),
]
