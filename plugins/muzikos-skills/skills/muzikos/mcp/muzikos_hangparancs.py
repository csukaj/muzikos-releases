"""Hangparancsok a felvételhez (#255): kéz nélkül, a gitárral a kézben — „felvétel”, „stop”, „vissza az elejére”,
„újra az utolsó ütemtől”, „ez jó volt”.

    működés:  belépéskor háttérfigyelő indul (server.py --hangparancs-figyelo). A mikrofont (alapból az asztal
              alapértelmezett bemenetét, vagy a beállított `forras`-t) 16 kHz-en hallgatja, a rövid (0,25–3,2 s)
              beszédszerű darabokat helyben, net nélkül ismeri fel (faster-whisper, magyarul, a parancsszavakkal
              előhangolva), és a szöveg csak akkor parancs, ha EGÉSZ egy fix parancsra hasonlít. A hosszabb vagy
              folyamatos hang (játék, beszélgetés) nem is kerül felismerésre.
    téves felismerés ellen:
              biztos találat (hasonlóság ≥ 0,88 és jó felismerési bizonyosság) azonnal fut; a bizonytalan (≥ 0,72)
              előbb rákérdez („felvétel? mondd: igen”), és 6 másodpercig vár az „igen”-re. A „felvétel” nem indul
              újra, ha már megy; a „vissza az elejére” felvétel közben nem fut.
    adat:     hang nem mentődik és nem megy sehova; a naplóba (naplo.log) csak a végrehajtott parancs kerül.
    kapcsoló: ~/.config/muzikos/hangparancs.json — be (alap: igen), forras (eszköznévrész), modell (mappa).
"""
import difflib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import unicodedata
import wave

import muzikos_memory as mem

reaper_call = None      # a server.py köti be (a Reaper-híd hívása)

CONF = os.path.expanduser("~/.config/muzikos/hangparancs.json")
MODELL = os.environ.get("MUZIKOS_WHISPER", "/usr/share/muzikos/whisper")
NAPLO = os.path.expanduser("~/.local/state/muzikos/naplo.log")
RATE = 16000
KOCKA = 480                      # 30 ms
MIN_KOCKA, MAX_KOCKA = 9, 107    # 0,27 s … 3,2 s
CSEND_KOCKA = 15                 # ennyi csend zár egy darabot (0,45 s)
ELOZO_KOCKA = 8                  # a darab elé tett, az indulást nem levágó előzmény
KUSZOB_ALAP = 0.012              # teljes skála törtrésze, ez alatt nincs beszéd
KUSZOB_SZORZO = 3.0              # a zajszint ennyiszerese kell az induláshoz
BIZTOS, BIZONYTALAN = 0.88, 0.72
IGEN_VARAKOZAS = 6.0
SZUNET_ZAJ = (6, 10.0)           # ennyi darab ennyi másodperc alatt: zajos a környezet, 10 s szünet
PROMPT = "felvétel, stop, vissza az elejére, újra az utolsó ütemtől, ez jó volt, igen."

PARANCSOK = {
    "felvetel": ["felvétel", "indul a felvétel"],
    "stop": ["stop", "állj"],
    "elejere": ["vissza az elejére"],
    "utolso_utem": ["újra az utolsó ütemtől"],
    "jo_volt": ["ez jó volt"],
}
IGEN = ["igen"]


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def illesztes(szoveg, lista=None):
    """(parancs, hasonlóság): a szöveg melyik fix parancsra hasonlít legjobban. Az egész szövegnek kell hasonlítania."""
    n = norm(szoveg)
    if not n:
        return None, 0.0
    jelolt = lista if lista is not None else [(k, a) for k, v in PARANCSOK.items() for a in v]
    best = (None, 0.0)
    for k, a in jelolt:
        r = difflib.SequenceMatcher(None, n, norm(a)).ratio()
        if r > best[1]:
            best = (k, r)
    return best


def dontes(parancs, hasonlo, logprob, nincs_beszed):
    """'fut' | 'kerdez' | 'figyelmen kívül' — a találat és a felismerés bizonyossága alapján."""
    if parancs is None or nincs_beszed > 0.7:
        return "figyelmen kívül"
    if hasonlo >= BIZTOS and logprob >= -0.9 and nincs_beszed < 0.5:
        return "fut"
    return "kerdez" if hasonlo >= BIZONYTALAN else "figyelmen kívül"


# ----------------------------------------------------------------------------- beállítás

def konfig():
    c = mem.read_json(CONF, {})
    return {"be": c.get("be", True), "forras": c.get("forras") or "", "modell": c.get("modell") or MODELL}


def naplo(*a):
    try:
        os.makedirs(os.path.dirname(NAPLO), exist_ok=True)
        with open(NAPLO, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "[hangparancs] " + " ".join(map(str, a)) + chr(10))
    except OSError:
        pass


def ertesit(szoveg):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-t", "2500", "-i", "audio-input-microphone", "MuzikOS", szoveg],
                       capture_output=True, timeout=5)


def _sip(magas):
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "muzikos-hangparancs")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "magas.wav" if magas else "mely.wav")
    if not os.path.exists(p):
        f0, hossz = (1040, 0.09) if magas else (520, 0.18)
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * f0 * i / RATE)))
                                   for i in range(int(RATE * hossz))))
    return p


def sip(magas=True):
    """Rövid hangjelzés: magas = a parancs lefutott, mély = rákérdezés."""
    if shutil.which("paplay"):
        subprocess.Popen(["paplay", _sip(magas)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------------------------------------------------------- beszédszakaszok a hangfolyamból

class Szegmentalo:
    """Kockánként (30 ms, 16 bites mono) kapja a hangot; beszédszerű, rövid darabot ad vissza (bájtok), a többit eldobja."""

    def __init__(self):
        self.zaj = 0.004
        self.elo = []
        self.darab = None
        self.csend = 0
        self.indito = 0
        self.eldob = False

    @staticmethod
    def szint(kocka):
        n = len(kocka) // 2
        if not n:
            return 0.0
        s = struct.unpack("<%dh" % n, kocka[:n * 2])
        return math.sqrt(sum(x * x for x in s) / n) / 32768.0

    def betesz(self, kocka):
        r = self.szint(kocka)
        kuszob = max(KUSZOB_ALAP, self.zaj * KUSZOB_SZORZO)
        hang = r > kuszob
        if self.darab is None:
            if not hang:
                self.zaj = 0.98 * self.zaj + 0.02 * r          # csak csendben tanulja a zajszintet
            self.elo = (self.elo + [kocka])[-ELOZO_KOCKA:]
            self.indito = self.indito + 1 if hang else 0
            if self.indito >= 3:
                self.darab, self.csend, self.indito, self.eldob = list(self.elo), 0, 0, False
            return None
        self.darab.append(kocka)
        self.csend = 0 if r > kuszob * 0.7 else self.csend + 1
        if len(self.darab) - self.csend > MAX_KOCKA:           # túl hosszú: játék vagy beszélgetés, nem parancs
            self.eldob = True
        if self.csend >= CSEND_KOCKA:
            kesz, self.darab, self.elo = self.darab, None, []
            if self.eldob or len(kesz) - self.csend < MIN_KOCKA:
                return None
            return b"".join(kesz)
        return None


# ----------------------------------------------------------------------------- felismerés

class Felismero:
    def __init__(self, mappa):
        self.mappa = mappa
        self.modell = None

    def kesz(self):
        return os.path.isdir(self.mappa) and os.path.exists(os.path.join(self.mappa, "model.bin"))

    def felismer(self, pcm):
        """(szöveg, átlagos logprob, nincs-beszéd valószínűség)"""
        import numpy as np
        if self.modell is None:
            from faster_whisper import WhisperModel
            self.modell = WhisperModel(self.mappa, device="cpu", compute_type="int8", cpu_threads=1, num_workers=1,
                                       local_files_only=True)
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        szakaszok, _ = self.modell.transcribe(audio, language="hu", beam_size=1, temperature=0.0, vad_filter=False,
                                              condition_on_previous_text=False, initial_prompt=PROMPT,
                                              without_timestamps=True)
        sz = list(szakaszok)
        if not sz:
            return "", -9.0, 1.0
        return (" ".join(s.text.strip() for s in sz), min(s.avg_logprob for s in sz), max(s.no_speech_prob for s in sz))


# ----------------------------------------------------------------------------- parancsok a Reaperben

REC = "reaper.Main_OnCommand(40252, 0) reaper.Main_OnCommand(1013, 0)"      # normál mód, felvétel (ahogy a reaper_transport)


def allapot():
    d = reaper_call("return muzikos.transport()")
    return (d.get("result") or {}).get("allapot") if d.get("ok") else None


def vegrehajt(parancs):
    """A parancs végrehajtása; a visszaadott szöveg a zenésznek szóló jelzés (None: nincs mit mondani)."""
    import muzikos_rendszer as hr
    st = allapot()
    if st is None:
        return "A Reaper nem válaszol (fut, és fut benne a híd?)."
    if parancs == "felvetel":
        if st == "felvétel":
            return "Már megy a felvétel."
        warn = hr.preflight()
        hr.record_started()
        d = reaper_call(REC + "\nreturn muzikos.transport()")
        extra = (" — figyelem: " + "; ".join(w["szoveg"] for w in warn)) if warn else ""
        return ("Felvétel indul" if d.get("ok") else "A felvétel nem indult: " + str(d.get("error"))) + extra
    if parancs == "stop":
        if st == "áll":
            return None
        d = reaper_call("reaper.OnStopButton()\nreturn muzikos.transport()")
        n = hr.record_stopped() if st == "felvétel" else None
        return "Leállítva" + (f" — {n} hangkimaradás volt a felvétel alatt, érdemes újravenni" if n else "")
    if parancs == "elejere":
        if st == "felvétel":
            return "Felvétel közben nem ugrom vissza: előbb mondd, hogy stop."
        reaper_call("reaper.CSurf_GoStart()\nreturn muzikos.transport()")
        return "Vissza az elejére"
    if parancs == "utolso_utem":
        if st == "felvétel":
            hr.record_stopped()
        lua = ("local st = reaper.GetPlayState()\nlocal rec = st & 4 ~= 0\n"
               "local pos = (st & 1 ~= 0) and reaper.GetPlayPosition() or reaper.GetCursorPosition()\n"
               "if st & 5 ~= 0 then reaper.OnStopButton() end\n"
               "local bar, kezd = muzikos.bar_of(pos)\n"
               "if bar > 1 and pos - kezd < 0.05 then bar = bar - 1 end\n"          # épp az ütem elején: az előző ütem
               "reaper.SetEditCurPos(muzikos.bar_time(bar), true, true)\n"
               f"if rec then {REC} else reaper.OnPlayButton() end\n"
               "local t = muzikos.transport() t.utem = bar return t")
        if st == "felvétel":
            hr.record_started()
        d = reaper_call(lua)
        return f"Újra a(z) {(d.get('result') or {}).get('utem', '?')}. ütemtől" + (" (felvétel)" if st == "felvétel" else "")
    if parancs == "jo_volt":
        d = reaper_call("local st = reaper.GetPlayState()\n"
                        "local pos = (st & 1 ~= 0) and reaper.GetPlayPosition() or reaper.GetCursorPosition()\n"
                        "reaper.AddProjectMarker2(0, false, pos, 0, \"Jó volt\", -1, 0)\n"
                        "return (muzikos.bar_of(pos))")
        return f"Megjelöltem: jó volt ({d.get('result')}. ütem)" if d.get("ok") else "A jelölő nem sikerült."
    return None


# ----------------------------------------------------------------------------- háttérfigyelő

def forras_neve(resz):
    if not resz:
        return None
    out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
    for sor in out.splitlines():
        nev = sor.split("\t")[1] if "\t" in sor else ""
        if nev and not nev.endswith(".monitor") and resz.lower() in nev.lower():
            return nev
    return None


def feldolgoz(szoveg, logprob, nincs, varakozo):
    """Egy felismert szöveg sorsa. varakozo = (parancs, határidő) vagy None. Visszatér: (végrehajtandó parancs vagy None,
    új varakozo, jelzés a zenésznek vagy None)."""
    if varakozo and time.time() < varakozo[1]:
        k, r = illesztes(szoveg, [("igen", a) for a in IGEN])
        if k and r >= BIZTOS:
            return varakozo[0], None, None
    k, r = illesztes(szoveg)
    d = dontes(k, r, logprob, nincs)
    if d == "fut":
        return k, None, None
    if d == "kerdez":
        return None, (k, time.time() + IGEN_VARAKOZAS), f"„{PARANCSOK[k][0]}”? Mondd: igen"
    return None, (varakozo if varakozo and time.time() < varakozo[1] else None), None


def figyelo():
    """Blokkol: a mikrofont hallgatja, és végrehajtja a parancsokat. Belépéskor indul (autostart)."""
    fel = None
    varakozo = None
    darabok = []
    szunet_ig = 0.0
    jelzett_hiany = False
    while True:
        c = konfig()
        if fel is None or fel.mappa != c["modell"]:
            fel = Felismero(c["modell"])
        if not c["be"] or not fel.kesz():
            if c["be"] and not jelzett_hiany:
                naplo("nincs beszédfelismerő modell:", c["modell"])
                jelzett_hiany = True
            time.sleep(5)
            continue
        cmd = ["parec", "--format=s16le", f"--rate={RATE}", "--channels=1", "--latency-msec=30"]
        forras = forras_neve(c["forras"])
        if forras:
            cmd += ["-d", forras]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            naplo("a parec nem indult:", e)
            time.sleep(10)
            continue
        naplo("figyel:", forras or "alapértelmezett bemenet")
        sz = Szegmentalo()
        utolso_konfig = time.time()
        try:
            while True:
                kocka = p.stdout.read(KOCKA * 2)
                if len(kocka) < KOCKA * 2:
                    break                                  # a hangforrás eltűnt (kártya kihúzva): újrakezdjük
                if time.time() - utolso_konfig > 5:
                    utolso_konfig = time.time()
                    if konfig() != c:
                        break                              # a beállítás változott (be/ki, forrás)
                pcm = sz.betesz(kocka)
                if pcm is None or time.time() < szunet_ig:
                    continue
                darabok = [t for t in darabok if time.time() - t < SZUNET_ZAJ[1]] + [time.time()]
                if len(darabok) >= SZUNET_ZAJ[0]:
                    naplo("zajos környezet, 10 s szünet")
                    szunet_ig, darabok = time.time() + 10, []
                    continue
                try:
                    szoveg, lp, nincs = fel.felismer(pcm)
                except Exception as e:
                    naplo("felismerési hiba:", repr(e))
                    time.sleep(2)
                    continue
                parancs, varakozo, jelzes = feldolgoz(szoveg, lp, nincs, varakozo)
                if jelzes:
                    sip(False)
                    ertesit(jelzes)
                if parancs:
                    try:
                        if parancs == "felvetel":
                            sip(True)
                            time.sleep(0.25)                # a jelzés a felvétel indulása előtt lecsengjen
                        uzenet = vegrehajt(parancs)
                    except Exception as e:
                        naplo("a parancs hibázott:", parancs, repr(e))
                        uzenet = "A parancs nem sikerült."
                    naplo("parancs:", parancs, f"({szoveg!r}, logprob {lp:.2f})", "→", uzenet)
                    if uzenet:
                        if parancs != "felvetel":
                            sip(True)
                        ertesit(uzenet)
        finally:
            p.kill()
            p.wait()
        time.sleep(2)


# ----------------------------------------------------------------------------- eszköz a Claude-nak

def tool_hangparancs(args):
    act = args.get("action") or "allapot"
    c = konfig()
    if act == "allapot":
        fel = Felismero(c["modell"])
        return {"be": c["be"], "forras": c["forras"] or "(az asztal alapértelmezett bemenete)",
                "felismero_modell": "megvan" if fel.kesz() else "HIÁNYZIK: " + c["modell"],
                "parancsok": {k: v[0] for k, v in PARANCSOK.items()},
                "mit_mondj": "Gitárral a kézben: „felvétel”, „stop”, „vissza az elejére”, „újra az utolsó ütemtől”, „ez jó volt”. "
                             "Bizonytalan felismerésnél rákérdez, és „igen”-t vár. Ha a parancs hangja belekerül a felvételbe, "
                             "használj fejhallgatós mikrofont (forras)."}
    if act in ("be", "ki"):
        mem.write_json(CONF, {**mem.read_json(CONF, {}), "be": act == "be"})
        return {"be": act == "be", "megjegyzes": "A figyelő 5 másodpercen belül átveszi."}
    if act == "forras":
        resz = (args.get("forras") or "").strip()
        mem.write_json(CONF, {**mem.read_json(CONF, {}), "forras": resz})
        return {"forras": resz or "(alapértelmezett)", "talalt_eszkoz": forras_neve(resz) if resz else None}
    if act == "proba":
        k, r = illesztes(args.get("szoveg") or "")
        return {"parancs": k, "hasonlosag": round(r, 2), "dontes": dontes(k, r, 0.0, 0.0)}
    raise ValueError("Ismeretlen action: allapot | be | ki | forras | proba.")


TOOLS = [
    ("hangparancs", tool_hangparancs,
     "Hangparancsok a felvételhez, kéz nélkül (helyben, net nélkül): „felvétel”, „stop”, „vissza az elejére”, „újra az utolsó "
     "ütemtől”, „ez jó volt” (jelölőt tesz a Reaperbe). action=allapot: be van-e kapcsolva, megvan-e a felismerő, melyik "
     "mikrofont hallgatja; be / ki: kapcsoló; forras: a mikrofon eszköznévrésze (pl. a fejhallgatós mikrofon); proba: a szöveg "
     "melyik parancs lenne (szoveg). Bizonytalan felismerésnél a MuzikOS rákérdez, és „igen”-t vár.",
     {"action": {"type": "string", "enum": ["allapot", "be", "ki", "forras", "proba"]},
      "forras": {"type": "string"}, "szoveg": {"type": "string"}}),
]
