"""A hangrendszer egészsége (Bence mUSBic-tapasztalatai alapján, #381 #383 #384 #385):

    hangkimaradások (xrun): a PipeWire meghajtóinak hibaszámlálója (pw-top ERR) a felvétel elején és végén — a
             Claude take-enként megmondja, a rendszer recsegett-e (nem a játék);
    wifi:    a bekapcsolt, de nem csatlakozott wifi háttérkeresése kimaradásokat okoz (Bence mérése: 0 helyett 1
             kimaradás és 305 JACK-hiba): felvétel előtt szól, és kikapcsolja (utána vissza);
    Guitarix neurális modell 48 kHz-en: a 44,1 kHz-es RTNeural-modellek 48 kHz-en kimaradás nélkül is recsegnek
             (Bence megtalálta a Guitarix-hibát): ilyenkor 44,1 kHz-et ajánl;
    késleltetés-hangolás: terhelés alatt végigpróbálja a puffereket, és hangkártyánként elmenti a legkisebb
             biztonságosat (a profil a kártya neve szerint, nem a sorszáma szerint); a valódi oda-vissza késést
             hurokkábellel méri (jack_iodelay). A kijelzett pufferhossz nem azonos az oda-vissza késéssel.
"""
import json
import os
import re
import subprocess
import time

import muzikos_memory as mem

RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "muzikos-felvetelek.json")
QUANTA = [64, 96, 128, 192, 256, 512]


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


# ----------------------------------------------------------------------------- hangkimaradások

def parse_pwtop(out):
    """pw-top -b kimenetéből a meghajtók (nem „+” jelű követők) hibaszáma: {név: ERR}; az utolsó blokk számít."""
    blocks, cur = [], {}
    for ln in out.splitlines():
        if ln.lstrip().startswith("S ") and "ERR" in ln:
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        parts = ln.split()
        if len(parts) < 9 or "+" in parts or not parts[1].isdigit():
            continue                                     # a követők („+ REAPER”) a meghajtó alatt futnak
        try:
            err = int(parts[8])
        except ValueError:
            continue
        cur[parts[-1] if len(parts) > 9 else parts[1]] = err
    if cur:
        blocks.append(cur)
    return blocks[-1] if blocks else {}


def xruns():
    """Az összes meghajtó hibáinak száma most (a PipeWire indulása óta), vagy None, ha nem mérhető."""
    code, out, _ = sh("timeout 4 pw-top -b -n 2 2>/dev/null", timeout=8)
    d = parse_pwtop(out)
    return sum(d.values()) if d else None


def record_started():
    st = mem.read_json(RUN, {"felvetelek": []})
    st["most"] = {"kezd": time.time(), "hibak": xruns()}
    mem.write_json(RUN, st)


def record_stopped():
    """A felvétel alatti kimaradások; a felvételek naplója (a take-elemzés ebből olvas)."""
    st = mem.read_json(RUN, {"felvetelek": []})
    cur = st.pop("most", None)
    if not cur:
        return None
    now_err = xruns()
    n = None if (cur.get("hibak") is None or now_err is None) else max(0, now_err - cur["hibak"])
    st.setdefault("felvetelek", []).append({"kezd": cur["kezd"], "veg": time.time(), "kimaradas": n})
    st["felvetelek"] = st["felvetelek"][-200:]
    mem.write_json(RUN, st)
    return n


def xruns_for_file(path):
    """Egy felvett fájl alatti kimaradások: a fájl ideje szerint a naplóból (None, ha nem tudjuk)."""
    try:
        t = os.path.getmtime(path)
    except OSError:
        return None
    # a fájl utolsó írása a felvétel végére esik: az a felvétel, amelyik alatt íródott, és a vége a legközelebb van
    cands = [r for r in mem.read_json(RUN, {}).get("felvetelek", []) if r["kezd"] - 2 <= t <= r["veg"] + 30]
    if not cands:
        return None
    return min(cands, key=lambda r: abs(t - r["veg"]))["kimaradas"]


# ----------------------------------------------------------------------------- wifi

def wifi_state():
    code, radio, _ = sh("nmcli -t -f WIFI radio")
    if code != 0:
        return None
    code, dev, _ = sh("nmcli -t -f TYPE,STATE device")
    states = [ln.split(":", 1)[1] for ln in dev.splitlines() if ln.startswith("wifi:")]
    return {"radio": radio.strip() == "enabled", "csatlakozva": any(s.startswith("connected") for s in states),
            "van_wifi": bool(states)}


def wifi_set(on):
    code, _, err = sh(f"nmcli radio wifi {'on' if on else 'off'}")
    if code != 0:
        code, _, err = sh(f"sudo -n nmcli radio wifi {'on' if on else 'off'}")
    return code == 0, err.strip()


# ----------------------------------------------------------------------------- Guitarix neurális modell

def clock():
    code, out, _ = sh("pw-metadata -n settings 0")
    vals = dict(re.findall(r"key:'(clock\.[\w-]+)' value:'(\d+)'", out))
    rate = int(vals.get("clock.force-rate") or 0) or int(vals.get("clock.rate") or 0) or None
    q = int(vals.get("clock.force-quantum") or 0) or int(vals.get("clock.quantum") or 0) or None
    return rate, q


def guitarix_neural():
    """Fut-e a Guitarix RTNeural-modellel (a beállításai szerint)."""
    code, _, _ = sh("pgrep -x guitarix")
    if code != 0:
        return False
    cfg = os.path.expanduser("~/.config/guitarix")
    for root, _, files in os.walk(cfg):
        for f in files:
            if f.endswith((".gx", "_rc", ".json")):
                try:
                    txt = open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if re.search(r"rtneural|\.aidax|neural_amp_multi|neural_amp_mono", txt, re.I):
                    return True
    return False


def preflight():
    """Felvétel előtti figyelmeztetések (amit a Claude elmond, és megkérdez)."""
    out = []
    w = wifi_state()
    if w and w["radio"] and w["van_wifi"] and not w["csatlakozva"]:
        out.append({"mi": "wifi", "szoveg": "A wifi be van kapcsolva, de nincs hálózaton: a háttérben keresgél, ez "
                                             "recsegést okozhat. Kikapcsoljam a felvétel idejére? (hangrendszer action=wifi ki)"})
    rate, _ = clock()
    if rate == 48000 and guitarix_neural():
        out.append({"mi": "guitarix48k", "szoveg": "A Guitarix neurális (RTNeural) erősítőmodellel fut 48 kHz-en: ezek a "
                                                   "modellek 44,1 kHz-esek, és 48 kHz-en kimaradás nélkül is recseghetnek. "
                                                   "Átváltsak 44,1 kHz-re? (hangrendszer action=mintavetel 44100)"})
    return out


# ----------------------------------------------------------------------------- késleltetés-hangolás

def profiles_path():
    return os.path.join(mem.root(), "hangprofilok.json")


def soundcards():
    code, out, _ = sh("pw-link -o")
    cards = sorted({p.split(":", 1)[0] for p in out.split() if p.startswith("alsa_input.")})
    return [c for c in cards if not any(x in c.lower() for x in ("hda", "sof", "pci-"))] or cards


def card_key(node):
    """A kártya kulcsa a profilhoz: a neve (alsa_input.usb-BEHRINGER_UMC404HD_192k-00.pro-input-0 → usb-BEHRINGER_UMC404HD_192k-00)."""
    m = re.match(r"alsa_input\.(.+?)\.(pro-input|analog|multichannel|iec958|direct)", node)
    return m.group(1) if m else node.replace("alsa_input.", "")


def set_quantum(q, rate=None):
    sh(f"pw-metadata -n settings 0 clock.force-quantum {int(q)}")
    if rate:
        sh(f"pw-metadata -n settings 0 clock.force-rate {int(rate)}")


def apply_profile():
    """A bedugott kártya elmentett profilja (ha van) érvénybe lép: puffer és mintavétel."""
    prof = mem.read_json(profiles_path(), {})
    for c in soundcards():
        p = prof.get(card_key(c))
        if p and p.get("quantum"):
            rate, q = clock()
            if q != p["quantum"] or (p.get("rate") and rate != p["rate"]):
                set_quantum(p["quantum"], p.get("rate"))
            return {"kartya": card_key(c), **p}
    return None


def tune(args):
    cards = soundcards()
    want = (args.get("kartya") or "").lower()
    cards = [c for c in cards if want in c.lower()] if want else cards
    if not cards:
        raise ValueError("Nem látok hangkártyát (pw-link -o). Be van dugva?")
    card = cards[0]
    secs = int(args.get("mp") or 60)
    warm = int(args.get("bemelegites") or 15)
    rate = int(args["rate"]) if args.get("rate") else None
    cands = [int(q) for q in (args.get("pufferek") or QUANTA)]
    old_rate, old_q = clock()
    results = []
    for q in sorted(cands):
        set_quantum(q, rate)
        time.sleep(warm)                                # a váltás utáni kimaradások nem számítanak
        a = xruns()
        time.sleep(secs)
        b = xruns()
        n = None if a is None or b is None else max(0, b - a)
        r_, q_ = clock()
        results.append({"puffer": q, "mintavetel": r_, "periodus_ms": round(q / (r_ or 48000) * 1000, 2),
                        "kimaradas": n})
        if n == 0 and not args.get("mind"):
            break                                        # a legkisebb kimaradás nélküli megvan
    ok = [r for r in results if r["kimaradas"] == 0]
    if not ok:
        set_quantum(old_q or 128, old_rate)
        return {"kartya": card_key(card), "eredmenyek": results,
                "mit_tegyel": "Egyik puffer sem volt kimaradás nélküli ezen a terhelésen: nagyobbat próbálj (pufferek), "
                              "vagy nézd meg a wifit és a háttérprogramokat."}
    best = min(ok, key=lambda r: r["puffer"])
    safe = next((q for q in sorted(QUANTA) if q > best["puffer"]), best["puffer"]) if args.get("tartalek", True) else best["puffer"]
    prof = mem.read_json(profiles_path(), {})
    prof[card_key(card)] = {"quantum": safe, "rate": best["mintavetel"], "legkisebb_hibatlan": best["puffer"],
                            "mikor": mem.now(), "mp": secs, "eredmenyek": results}
    mem.write_json(profiles_path(), prof)
    set_quantum(safe, rate)
    return {"kartya": card_key(card), "profil": prof[card_key(card)],
            "mit_tegyel": f"Mondd el: {best['puffer']}-es pufferig ({best['periodus_ms']} ms/periódus) nem volt kimaradás; "
                          f"egy fokozat tartalékkal {safe} lett a profil, és ez a kártya bedugásakor magától beáll. Ez a "
                          "pufferhossz, nem az oda-vissza késés; azt hurokkábellel lehet mérni (action=korbeli)."}


def roundtrip(args):
    """Oda-vissza késés hurokkábellel: a kártya 1. kimenete egy kábellel a megadott bemenetére (jack_iodelay)."""
    card = (soundcards() or [None])[0]
    if not card:
        raise ValueError("Nem látok hangkártyát.")
    inp = int(args.get("bemenet") or 1)
    out_dev = card.replace("alsa_input.", "alsa_output.")
    code, outs, _ = sh("pw-link -i")
    play = sorted([p for p in outs.split() if p.startswith(out_dev + ":playback_")])
    code, ins, _ = sh("pw-link -o")
    cap = sorted([p for p in ins.split() if p.startswith(card + ":capture_")])
    if not play or len(cap) < inp:
        raise ValueError("Nem találom a kártya ki- vagy bemenetét.")
    p = subprocess.Popen("pw-jack jack_iodelay", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    sh(f"pw-link jack_delay:out '{play[0]}'; pw-link '{cap[inp - 1]}' jack_delay:in")
    time.sleep(8)
    p.terminate()
    out = p.communicate(timeout=5)[0]
    ms = re.findall(r"([\d.]+) frames\s+([\d.]+) ms total roundtrip latency", out)
    if not ms:
        return {"eredmeny": "nem mért", "mit_tegyel": "Nem jött mérés: be van dugva a hurokkábel (a kártya 1. kimenete → "
                                                       f"a(z) {inp}. bemenet), és szól a kimenet?",
                "naplo": out.strip().splitlines()[-5:]}
    frames, val = ms[-1]
    prof = mem.read_json(profiles_path(), {})
    k = card_key(card)
    prof.setdefault(k, {})["oda_vissza_ms"] = float(val)
    rate, q = clock()
    prof[k]["oda_vissza_meres"] = {"mikor": mem.now(), "puffer": q, "mintavetel": rate, "minta": float(frames)}
    mem.write_json(profiles_path(), prof)
    return {"kartya": k, "oda_vissza_ms": float(val), "puffer": q, "mintavetel": rate}


def tool_hangrendszer(args):
    act = args.get("action", "allapot")
    if act == "allapot":
        rate, q = clock()
        prof = apply_profile()
        return {"mintavetel": rate, "puffer": q, "periodus_ms": round(q / rate * 1000, 2) if rate and q else None,
                "kimaradasok_osszesen": xruns(), "wifi": wifi_state(), "guitarix_neuralis": guitarix_neural(),
                "profil": prof, "figyelmeztetesek": preflight()}
    if act == "wifi":
        on = str(args.get("kapcsolo", "ki")).lower() in ("be", "on", "true", "1")
        ok, err = wifi_set(on)
        return {"wifi": "be" if on else "ki", "sikerult": ok, **({"hiba": err} if not ok else {})}
    if act == "mintavetel":
        r = int(args.get("rate") or 44100)
        sh(f"pw-metadata -n settings 0 clock.force-rate {r}")
        return {"mintavetel": clock()[0], "mit_tegyel": "A Reaper és a Guitarix is ezen a mintavételen fut tovább "
                                                       "(ha a Reaper nem vált magától: indítsd újra)."}
    if act == "hangolas":
        return tune(args)
    if act == "korbeli":
        return roundtrip(args)
    raise ValueError("action: allapot | wifi | mintavetel | hangolas | korbeli")


TOOLS = [
    ("hangrendszer", tool_hangrendszer,
     "A hangrendszer egészsége: allapot (mintavétel, puffer, a kimaradások száma, wifi, Guitarix neurális modell, a "
     "kártya elmentett profilja — ha van, érvénybe lép — és a felvétel előtti figyelmeztetések); wifi (kapcsolo: ki | "
     "be — felvétel előtt, ha be van kapcsolva, de nincs hálózaton); mintavetel (rate: 44100 | 48000); hangolas "
     "(terhelés alatt — a Reaper játsszon egy valódi projektet effektekkel — végigpróbálja a puffereket, mp = "
     "próbánként mennyi ideig, alap 60; a legkisebb kimaradás nélküli + egy fokozat tartalék lesz a kártya profilja); "
     "korbeli (oda-vissza késés hurokkábellel: a kártya 1. kimenete → bemenet).",
     {"action": {"type": "string", "enum": ["allapot", "wifi", "mintavetel", "hangolas", "korbeli"]},
      "kapcsolo": {"type": "string"}, "rate": {"type": "integer"}, "kartya": {"type": "string"},
      "mp": {"type": "integer"}, "bemelegites": {"type": "integer"}, "pufferek": {"type": "array", "items": {"type": "integer"}},
      "mind": {"type": "boolean"}, "tartalek": {"type": "boolean"}, "bemenet": {"type": "integer"}}),
]
