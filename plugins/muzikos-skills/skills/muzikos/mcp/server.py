#!/usr/bin/env python3
"""MuzikOS MCP-szerver: a zenei gép eszközei a Claude-nak (hang, rendszer, képernyő, Reaper).

Csak a Python standard könyvtárát használja, hogy a MuzikOS élő rendszerén (és bármely Linuxon)
telepítés nélkül fusson. A protokoll: soronként egy JSON-RPC üzenet a stdin/stdout-on (MCP stdio).

A Reaperrel egy kis Lua-híd (reaper_bridge.lua) beszél, ami a Reaperen belül fut: a szerver egy
Lua-kódot ír a híd mappájába (request.lua), a híd lefuttatja, és JSON-ban válaszol (response.json).
Így a Reaper teljes ReaScript API-ja elérhető, nem csak az, amit az OSC vagy a webes felület tud.
"""

import base64
import glob
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

# A Claude Desktop a felhasználói munkamenet környezete nélkül indítja a szervert (lemérve a MuzikOS-en,
# 2026-10-23): XDG_RUNTIME_DIR nélkül a PipeWire (pw-dump, pactl) és a Reaper-híd mappája sem érhető el,
# DISPLAY nélkül a képernyő. Ezért a szerver maga pótolja őket, mielőtt bármit indítana.
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ.setdefault("DISPLAY", ":0")
if os.path.exists(os.path.join(os.environ["XDG_RUNTIME_DIR"], "bus")):
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus")

SERVER_NAME = "muzikos"
SERVER_VERSION = "0.30.1"
HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_SRC = os.path.join(HERE, "reaper_bridge.lua")
BRIDGE_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "muzikos-reaper")
REAPER_RESOURCE = os.path.expanduser(os.environ.get("MUZIKOS_REAPER_RESOURCE", "~/.config/REAPER"))
_reaper_lock = threading.Lock()


# ----------------------------------------------------------------------------- segédek

def sh(cmd, timeout=30, input_bytes=None, env=None):
    """Parancs futtatása bash-ban; (kilépési kód, stdout, stderr) szövegként."""
    full_env = dict(os.environ)
    full_env.setdefault("DISPLAY", ":0")
    if env:
        full_env.update(env)
    try:
        p = subprocess.run(["bash", "-lc", cmd], capture_output=True, timeout=timeout,
                           input=input_bytes, env=full_env)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        return 124, out, f"időtúllépés ({timeout} s)"


def have(binary):
    return shutil.which(binary) is not None


def text(s):
    return {"content": [{"type": "text", "text": s}]}


def error(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


def as_json(obj):
    return text(json.dumps(obj, ensure_ascii=False, indent=2))


def db(x):
    return round(20 * math.log10(x), 1) if x > 0 else None


# ----------------------------------------------------------------------------- rendszer

def tool_system_status(_args):
    info = {}
    _, uname, _ = sh("uname -r; uname -v")
    info["kernel"] = uname.strip().splitlines()
    info["valos_ideju_kernel"] = "PREEMPT_RT" in uname or os.path.exists("/sys/kernel/realtime")
    _, gov, _ = sh("cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort | uniq -c")
    info["processzor_uzemmod"] = gov.strip() or "ismeretlen"
    _, lim, _ = sh("echo rtprio=$(ulimit -r) memlock=$(ulimit -l); id -Gn")
    info["jogosultsag"] = lim.strip().splitlines()
    _, auto, _ = sh("cat /sys/module/usbcore/parameters/autosuspend 2>/dev/null")
    info["usb_autosuspend"] = auto.strip()
    _, disk, _ = sh("df -h / /run/live/persistence/* /media/* /run/media/*/* 2>/dev/null | awk 'NR==1 || !seen[$6]++'")
    info["lemezek"] = disk.strip().splitlines()
    _, net, _ = sh("nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null || ip -br addr")
    info["halozat"] = net.strip().splitlines()
    _, pers, _ = sh("grep -o 'persistence[^ ]*\\|nopersistence' /proc/cmdline; ls /run/live/persistence 2>/dev/null")
    info["tartos_fajl"] = pers.strip().splitlines() or ["nincs (tiszta indítás vagy nincs tartós fájl)"]
    _, up, _ = sh("uptime -p")
    info["fut"] = up.strip()
    return as_json(info)


def tool_run_command(args):
    cmd = args.get("command", "")
    if not cmd:
        return error("Hiányzik a command.")
    timeout = int(args.get("timeout", 120))
    if args.get("sudo"):
        cmd = "sudo -n bash -lc " + json.dumps(cmd)
    code, out, err = sh(cmd, timeout=timeout)
    limit = 60000
    res = f"kilépési kód: {code}\n--- stdout ---\n{out[-limit:]}"
    if err.strip():
        res += f"\n--- stderr ---\n{err[-limit:]}"
    return {"content": [{"type": "text", "text": res}], "isError": code != 0}


# ----------------------------------------------------------------------------- hang

def pw_nodes():
    """A PipeWire hangeszközei (források és nyelők) a pw-dump kimenetéből."""
    code, out, err = sh("pw-dump 2>/dev/null", timeout=15)
    if code != 0 or not out.strip():
        return None, "A PipeWire nem válaszol (pw-dump). Fut a hangrendszer? systemctl --user status pipewire"
    nodes = []
    for obj in json.loads(out):
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        cls = props.get("media.class", "")
        if cls not in ("Audio/Source", "Audio/Sink", "Audio/Duplex", "Midi/Bridge"):
            continue
        nodes.append({
            "id": obj.get("id"),
            "name": props.get("node.name"),
            "leiras": props.get("node.description") or props.get("node.nick"),
            "tipus": {"Audio/Source": "bemenet", "Audio/Sink": "kimenet",
                      "Audio/Duplex": "be- és kimenet", "Midi/Bridge": "MIDI"}[cls],
            "csatornak": props.get("audio.channels"),
            "csatorna_nevek": props.get("audio.position"),
            "eszkoz": props.get("api.alsa.card.name") or props.get("alsa.card_name"),
            "usb": "usb" in (props.get("device.bus", "") + props.get("api.alsa.path", "") + props.get("object.path", "")).lower(),
        })
    return nodes, None


def tool_audio_devices(_args):
    nodes, err = pw_nodes()
    res = {}
    if err:
        res["pipewire"] = err
    else:
        res["pipewire_eszkozok"] = nodes
    _, cards, _ = sh("cat /proc/asound/cards")
    res["hangkartyak"] = cards.strip().splitlines()
    _, midi, _ = sh("aconnect -l 2>/dev/null | grep -E '^client' || true")
    res["midi"] = midi.strip().splitlines()
    _, meta, _ = sh("pw-metadata -n settings 2>/dev/null | grep -E 'clock\\.(rate|quantum|force-rate|force-quantum|min-quantum|max-quantum)' | sed 's/.*key://'")
    res["orajel"] = meta.strip().splitlines()
    _, prof, _ = sh("pactl list cards 2>/dev/null | grep -E 'Name:|Active Profile:|alsa.card_name' | sed 's/^\\s*//'")
    res["profilok"] = prof.strip().splitlines()
    return as_json(res)


def pick_source(nodes, wanted):
    sources = [n for n in nodes if n["tipus"] in ("bemenet", "be- és kimenet") and not (n["name"] or "").endswith(".monitor")]
    if wanted:
        for n in sources:
            if wanted.lower() in ((n["name"] or "") + " " + (n["leiras"] or "")).lower():
                return n
        return None
    usb = [n for n in sources if n["usb"]]
    return (usb or sources or [None])[0]


def record_channels(device, seconds, rate=48000):
    """Felvétel egy bemeneti eszköz összes csatornájáról: (node, csatornaszám, [csatornánként a minták]) vagy hiba."""
    nodes, err = pw_nodes()
    if err:
        return None, None, None, err
    node = pick_source(nodes, device)
    if not node:
        return None, None, None, "Nincs ilyen bemeneti eszköz. Az audio_devices listázza, mi van."
    ch = int(node["csatornak"] or 2)
    want = int(rate * seconds) * ch * 4
    try:
        p = subprocess.Popen(["pw-record", "--target", str(node["name"]), "--channels", str(ch), "--format", "f32",
                              "--rate", str(rate), "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None, None, None, "Nincs pw-record (pipewire-bin csomag)."
    data = b""
    deadline = time.time() + seconds + 5
    while len(data) < want and time.time() < deadline:
        chunk = p.stdout.read(min(65536, want - len(data)))
        if not chunk:
            break
        data += chunk
    p.terminate()
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
    frames = len(data) // (4 * ch)
    if frames == 0:
        return node, ch, None, f"Nem jött hang a(z) {node['leiras']} eszközről."
    s = struct.unpack(f"<{frames * ch}f", data[:frames * ch * 4])
    return node, ch, [s[c::ch] for c in range(ch)], None


def tool_dob_fazis(args):
    """Két mikrofon fázisa egy ütésen: a legerősebb ütés körüli 100 ms kereszt-korrelációja."""
    import muzikos_drums as drums
    a, b = int(args.get("a", 1)) - 1, int(args.get("b", 2)) - 1
    node, ch, chans, err = record_channels(args.get("device"), max(1.0, min(float(args.get("seconds", 4)), 15)))
    if err:
        return error(err)
    if max(a, b) >= ch:
        return error(f"Az eszköznek {ch} csatornája van.")
    ca, cb = chans[a], chans[b]
    peak = max(range(len(ca)), key=lambda i: abs(ca[i]))
    lo, hi = max(0, peak - 2400), min(len(ca), peak + 2400)          # ±50 ms az ütés körül
    if max(abs(x) for x in ca[lo:hi]) < 0.01 or max(abs(x) for x in cb[lo:hi]) < 0.003:
        return error("Nem volt elég erős ütés mindkét mikrofonon. Kérd meg a dobost, hogy üssön erősen a lábdobra (vagy a pergőre).")
    lag, corr = drums.phase_check(ca[lo:hi], cb[lo:hi], 48000)
    verdict = ("rendben, egy irányba mozognak" if corr > 0.3 else
               "FORDÍTOTT FÁZIS — a második sáv fázisát fordítsd meg (reaper_track_set phase_invert)" if corr < -0.3 else
               "bizonytalan: a két mikrofon nagyon mást hall; üssön újra, egyetlen dobra")
    return as_json({"eszkoz": node["leiras"], "bemenetek": [a + 1, b + 1], "kesés_ms": lag, "korrelacio": corr, "itelet": verdict,
                    "megjegyzes": "A késés a hang útja a két mikrofon között (kb. 3 ms/méter); ha nagy (>5 ms) és zavar, a Reaperben a közelebbi sávot késleltetni lehet (D_PLAYOFFSET / item eltolás)."})


def tool_dob_mikrofon_terv(args):
    import muzikos_drums as drums
    out = drums.tool_dob_mikrofon_terv(args)
    if not args.get("apply"):
        out["kovetkezo"] = "apply=true: a Reaper-sávok és a bekötési térkép elkészül ezzel a tervvel."
        return as_json(out)
    made = []
    for m in out["terv"]:
        r = reaper_call("return muzikos.add_track(" + json_to_lua({"name": "Dob – " + m["mikrofon"], "kind": "audio",
                                                                     "input": m["bemenet"], "arm": True, "monitor": False}) + ")")
        made.append(f"{m['mikrofon']}: " + ("sáv kész" if r.get("ok") else f"hiba: {r.get('error')}"))
    out["reaper"] = made
    try:
        if rig.find_rig(args.get("felallas")):
            dev = args.get("interface_id", "umc")
            rig.tool_felallas({"action": "set", "name": args.get("felallas") or rig.active_rig(), "data": {"eszkozok": [
                {"id": "mic-" + mem.slug(m["mikrofon"]), "nev": "Mikrofon: " + m["mikrofon"], "tipus": "mikrofon",
                 "megjegyzes": f"{m['tipus']}; {m['hova']}; 48V: {m['fantomtap_48V']}"} for m in out["terv"]]}})
            for m in out["terv"]:
                rig.tool_felallas_kabel({"action": "add", "honnan": f"mic-{mem.slug(m['mikrofon'])}: kimenet",
                                         "hova": f"{dev}: {m['bemenet']}. bemenet", "fajta": "XLR", "mire": "dob – " + m["mikrofon"]})
            out["terkep"] = "a mikrofonok és a kábelek a bekötési térképen (felallas_rajz)"
    except ValueError as e:
        out["terkep"] = f"a térképre nem került fel: {e}"
    return as_json(out)


def gain_advice(peak_db, overload):
    """Mit tegyen a zenész a gain-nel: cél a -18…-6 dBFS közti csúcs. None = nincs jel (nincs teendő a gainnel)."""
    if peak_db is None:
        return None
    if overload or peak_db > -3:
        return "túlvezérel: vedd lejjebb a gain-t, amíg a csúcs -12 dBFS körül nem lesz (kb. %d dB-lel)" % max(3, round(peak_db + 12))
    if peak_db > -6:
        return "kicsit forró: vedd lejjebb a gain-t kb. %d dB-lel" % max(2, round(peak_db + 12))
    if peak_db >= -18:
        return "rendben van (-18…-6 dBFS)"
    if peak_db < -40:
        return "alig van jel (lehet, hogy csak zaj): nézd meg, hogy a hangszer erre a bemenetre megy-e; ha igen, tekerd feljebb a gain-t"
    return "halk: tekerd feljebb a gain-t kb. %d dB-lel (cél: -12 dBFS csúcs)" % round(-12 - peak_db)


def measure_node(node, seconds):
    """Egy bemeneti node megmérése: ([csatornánként {nev, csucs_dBFS, atlag_dBFS, jel, tulvezerles}], hiba)."""
    ch = int(node["csatornak"] or 2)
    rate = 48000
    want = int(rate * seconds) * ch * 4
    cmd = ["pw-record", "--target", str(node["name"]), "--channels", str(ch), "--format", "f32",
           "--rate", str(rate), "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None, "Nincs pw-record (pipewire-bin csomag)."
    data = b""
    deadline = time.time() + seconds + 5
    while len(data) < want and time.time() < deadline:
        chunk = p.stdout.read(min(65536, want - len(data)))
        if not chunk:
            break
        data += chunk
    p.terminate()
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
    frames = len(data) // (4 * ch)
    if frames == 0:
        return None, f"Nem jött hang a(z) {node['leiras']} eszközről: {p.stderr.read().decode('utf-8', 'replace')[-500:]}"
    samples = struct.unpack(f"<{frames * ch}f", data[:frames * ch * 4])
    names = (node["csatorna_nevek"] or "").strip("[]").replace(",", " ").split()
    result = []
    for c in range(ch):
        v = samples[c::ch]
        peak = max(abs(x) for x in v)
        rms = math.sqrt(sum(x * x for x in v) / len(v))
        result.append({"nev": names[c] if c < len(names) else f"{c + 1}. csatorna",
                       "csucs_dBFS": db(peak), "atlag_dBFS": db(rms),
                       "jel": "van" if peak > 0.003 else "nincs", "tulvezerles": peak >= 0.99})
    return result, None


def tool_input_levels(args):
    """Egy hívásban az ÖSSZES bemenet: ha a kártya több node-ra bomlik (Mic1–Mic4), mindet egyszerre méri."""
    seconds = max(0.5, min(float(args.get("seconds", 3)), 30))
    nodes, err = pw_nodes()
    if err:
        return error(err)
    node = pick_source(nodes, args.get("device"))
    if not node:
        return error("Nincs ilyen bemeneti eszköz. Az audio_devices listázza, mi van.")
    sources = [n for n in nodes if n["tipus"] in ("bemenet", "be- és kimenet") and not (n["name"] or "").endswith(".monitor")]
    same = sorted([n for n in sources if card_of(n["name"] or "") == card_of(node["name"] or "")], key=lambda n: n["name"])
    group = same if len(same) > 1 else [node]
    results = [None] * len(group)

    def work(i, n):
        results[i] = measure_node(n, seconds)
    threads = [threading.Thread(target=work, args=(i, n)) for i, n in enumerate(group)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    channels, num = [], 0
    for n, (res, e) in zip(group, results):
        if e:
            return error(e)
        for c in res:
            num += 1
            c["bemenet"] = num
            c["gain"] = gain_advice(c["csucs_dBFS"], c["tulvezerles"]) if c["jel"] == "van" else None
            channels.append(c)
    active = [c for c in channels if c["jel"] == "van"]
    summary = ("Jel a(z) " + ", ".join(str(c["bemenet"]) for c in active) + ". bemeneten van.") if active else "Egyik bemeneten sincs jel."
    return as_json({"eszkoz": node["leiras"], "node": node["name"], "masodperc": seconds, "osszefoglalo": summary,
                    "csatornak": channels,
                    "megjegyzes": "A gitárnál és a basszusnál -18 és -6 dBFS közti csúcs a jó; 0-hoz közel túlvezérel. "
                                  "A gain-teendő csatornánként a `gain` mezőben van: mondd meg, melyik bemenet gombját merre és mennyit tekerje, "
                                  "és mutasd meg a kártya képén (felallas_rajz, a kártya a térképen)."})


def tool_set_latency(args):
    quantum = args.get("quantum")
    rate = args.get("rate")
    cmds = []
    if quantum is not None:
        q = int(quantum)
        if q != 0 and (q < 16 or q > 8192 or q & (q - 1)):
            return error("A puffer 2 hatványa legyen 16 és 8192 között (pl. 64, 128, 256), vagy 0 = visszaállítás.")
        cmds.append(f"pw-metadata -n settings 0 clock.force-quantum {q}")
    if rate is not None:
        cmds.append(f"pw-metadata -n settings 0 clock.force-rate {int(rate)}")
    if not cmds:
        return error("Adj meg quantum-ot (puffer, minta) és/vagy rate-et (Hz).")
    code, out, err = sh(" && ".join(cmds))
    _, meta, _ = sh("pw-metadata -n settings 2>/dev/null | grep -E 'clock\\.(rate|quantum|force)' | sed 's/.*key://'")
    msg = meta.strip()
    if quantum:
        r = int(rate or 48000)
        msg += f"\n≈ {1000 * int(quantum) / r:.1f} ms egy puffer (oda-vissza legalább ennek a kétszerese + az átalakítók)"
    return text(msg) if code == 0 else error(err or out)


def pw_ports(direction):
    """A PipeWire portjai: direction 'o' = kimenő (forrás), 'i' = bemenő (nyelő)."""
    _, out, _ = sh(f"pw-link -{direction}")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def port_index(name):
    """capture_AUX3 → 3, capture_FL → 0, capture_FR → 1, in2 → 1 (a sorrendhez)."""
    tail = name.rsplit(":", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    if digits:
        n = int(digits)
        return n - 1 if tail.startswith(("in", "out")) else n
    return {"FL": 0, "FR": 1, "MONO": 0}.get(tail.rsplit("_", 1)[-1], 99)


def rig_soundcard():
    """A mostani felállás hangkártyájának neve (az eszközök közül a „hangkártya” típusú), ha van."""
    try:
        r = rig.load(rig.active_rig()) if rig.active_rig() else {}
    except Exception:
        return None
    for e in r.get("eszkozok", []):
        if "hangk" in (e.get("tipus") or "").lower():
            return e.get("nev")
    return None


def name_matches(rig_name, node):
    """A felállásbeli név („Behringer UMC404HD”) illik-e egy PipeWire-eszközre (alsa_input.usb-BEHRINGER_UMC404HD…)."""
    words = [w for w in re.split(r"[^a-z0-9]+", (rig_name or "").lower()) if len(w) >= 4]
    n = node.lower()
    return bool(words) and any(w in n for w in words)


def connected_inputs():
    """A Reaper bemenetei, amelyekbe hangkártya-csatorna van kötve: {REAPER:inN: forrás}."""
    _, out, _ = sh("pw-link -l")
    res, cur = {}, None
    for ln in out.splitlines():
        if not ln.startswith((" ", "\t", "|")):
            cur = ln.strip()
            continue
        s = ln.strip()
        if s.startswith("|->") and cur and cur.startswith("alsa_input."):
            dst = s[3:].strip()
            if dst.startswith("REAPER:in"):
                res[dst] = cur
        elif s.startswith("|<-") and cur and cur.startswith("REAPER:in"):
            src = s[3:].strip()
            if src.startswith("alsa_input."):
                res[cur] = src
    return res


def pw_links():
    """Az összes PipeWire-kötés: [(forrás-port, cél-port)] (pw-link -l)."""
    _, out, _ = sh("pw-link -l")
    res, cur = [], None
    for ln in out.splitlines():
        if not ln.startswith((" ", "\t", "|")):
            cur = ln.strip()
            continue
        s = ln.strip()
        if s.startswith("|->") and cur:
            res.append((cur, s[3:].strip()))
        elif s.startswith("|<-") and cur:
            res.append((s[3:].strip(), cur))
    return list(dict.fromkeys(res))


def is_builtin_audio(name):
    """A laptop saját hangja (beépített mikrofon, hangszóró), nem külső kártya."""
    return any(x in name.lower() for x in ("sof", "hda", "pci-"))


def card_of(port):
    """A port eszköze: alsa_input.usb-BEHRINGER_UMC404HD-00.pro-input-0:capture_AUX0 → alsa_input.usb-BEHRINGER_UMC404HD-00"""
    node = port.split(":", 1)[0]
    return node.rsplit(".", 1)[0] if node.startswith(("alsa_input.", "alsa_output.")) else node


def desk_to_card(card):
    """Az asztal hangja és a felvétel alapja a külső kártyára (A pár): a Pro Audio nyelő, különben a névsor szerinti első.
    Visszadugás után a PipeWire néha a kártya 3/4-es (B) kimenetét választja: ezt javítja. Visszaadja a kiválasztott nyelőt."""
    out_card = card_of(card).replace("alsa_input.", "alsa_output.")
    _, sinks, _ = sh("pactl list short sinks | cut -f2")
    mine = sorted(x for x in sinks.split() if card_of(x) == out_card)
    if not mine:
        return None
    sink = next((x for x in mine if "pro-output-0" in x), mine[0])
    sh(f"pactl set-default-sink {shlex.quote(sink)}")
    in_card = card_of(card).replace("alsa_output.", "alsa_input.")
    _, srcs, _ = sh("pactl list short sources | cut -f2 | grep -v '\\.monitor$'")
    mine = sorted(x for x in srcs.split() if card_of(x) == in_card)
    if mine:
        sh(f"pactl set-default-source {shlex.quote(next((x for x in mine if 'pro-input-0' in x), mine[0]))}")
    return sink


def tool_reaper_reconnect(args):
    """A Reaper JACK-portjainak összekötése egy hangkártyával (pl. a hangkártya ki-be dugása után).

    Alapból: a kártya 1. bemenete → REAPER:in1, a 2. → in2 …, REAPER:out1/out2 → a kártya A párja; a beépített mikrofon
    és hangszóró kötéseit leveszi, az asztal hangját az A párra állítja. `input` + `reaper_in`: csak egy kötés
    („a UMC 2-es bemenete menjen a Reaper 1-esére”)."""
    want = (args.get("device") or "").lower()
    outs, ins = pw_ports("o"), pw_ports("i")
    rin = sorted([p for p in ins if p.startswith("REAPER:in")], key=port_index)
    rout = sorted([p for p in outs if p.startswith("REAPER:out")], key=port_index)
    if not rin and not rout:
        return error("Nincs REAPER-port a PipeWire-ben: fut a Reaper, és JACK-en szól? (reaper_start, reaper_audio_system)")
    # a hangkártya: a megadott nevű, különben a legtöbb bemenetű külső (nem a laptop saját hangja)
    def devname(p):
        return p.split(":", 1)[0]
    caps = [p for p in outs if ":capture_" in p and p.startswith("alsa_input.")]
    devs = {}
    for p in caps:
        devs.setdefault(devname(p), []).append(p)
    everything = dict(devs)
    if want:
        devs = {d: ps for d, ps in devs.items() if want in d.lower()}
    else:
        card = rig_soundcard()
        if card:
            # a felállás hangkártyája; ha nincs bedugva, NEM kötünk helyette másikat (#386)
            devs = {d: ps for d, ps in devs.items() if name_matches(card, d)}
            if not devs:
                return error(f"A felállás hangkártyája ({card}) nincs bedugva, vagy nem látszik. Ezek vannak: "
                             + (", ".join(everything) or "semmi") + ". Nem kötöm helyette másikra: kérdezd meg, mi "
                             "legyen (bedugják, vagy melyik kártyára kössem: device).")
        else:
            devs = {d: ps for d, ps in devs.items() if not is_builtin_audio(d)}
    if not devs:
        return error("Nem találtam ilyen hangkártyát a PipeWire-ben. Ezek vannak: " + (", ".join(everything) or "semmi"))
    dev = max(devs, key=lambda d: len(devs[d]))
    cap = sorted(devs[dev], key=port_index)
    play_dev = dev.replace("alsa_input.", "alsa_output.")
    play = sorted([p for p in ins if p.startswith(play_dev + ":playback_")], key=port_index)
    card_in, reaper_in = args.get("input"), args.get("reaper_in")
    if card_in is not None or reaper_in is not None:
        ci = int(card_in if card_in is not None else reaper_in)
        ri = int(reaper_in if reaper_in is not None else card_in)
        if not 1 <= ci <= len(cap):
            return error(f"A(z) {dev} kártyán nincs {ci}. bemenet (van {len(cap)}).")
        if not 1 <= ri <= len(rin):
            return error(f"A Reaperben nincs {ri}. bemenet (van {len(rin)}). Előbb legyen elég bemenet a Reaper audióbeállításában.")
        pairs, only_in = [(cap[ci - 1], rin[ri - 1])], rin[ri - 1]
    else:
        pairs, only_in = list(zip(cap, rin)), None
    made, failed, removed = [], [], []
    links = pw_links()
    new_srcs = [a for a, _ in pairs]
    for src, dst in links:
        if only_in:
            # a megadott Reaper-bemenetre csak az új kötés kerül
            drop = dst == only_in and src.startswith("alsa_input.") and src not in new_srcs
        elif str(args.get("belso", "")).lower() == "marad":
            drop = False
        else:
            # a beépített mikrofon és hangszóró kötéseinek levétele külső kártya mellett (a Reaper csak a laptop
            # mikrofonját látta, a kimenet pedig a laptop hangszóróján maradt)
            drop = (dst.startswith("REAPER:in") and src.startswith("alsa_input.") and is_builtin_audio(src)
                    and card_of(src) != card_of(dev)) or \
                   (src.startswith("REAPER:out") and dst.startswith("alsa_output.") and is_builtin_audio(dst)
                    and card_of(dst) != card_of(play_dev))
        if drop and sh(f"pw-link -d {shlex.quote(src)} {shlex.quote(dst)}")[0] == 0:
            removed.append(f"{src} ✕ {dst}")
    for src, dst in pairs + ([] if only_in else list(zip(rout, play[:2]))):
        code, _, err = sh(f"pw-link {shlex.quote(src)} {shlex.quote(dst)}")
        if code == 0 or "File exists" in err:
            made.append(f"{src} → {dst}")
        else:
            failed.append(f"{src} → {dst}: {err.strip()}")
    res = {"hangkartya": dev, "kotesek": made}
    if removed:
        res["levett_kotesek"] = removed
    if not only_in:
        desk = desk_to_card(dev)
        if desk:
            res["asztal_alap_kimenet"] = desk
    if failed:
        res["nem_sikerult"] = failed
    return as_json(res)


def hangut_rendez():
    """Hangkártya ki-be dugása után: a Reaper kötései és az asztal alapkimenete (A pár) magától helyreállnak (#51)."""
    nodes, err = pw_nodes()
    if err:
        return {"hiba": err}
    out = {}
    if reaper_running():
        r = tool_reaper_reconnect({})
        txt = r["content"][0]["text"]
        out["reaper"] = {"hiba": txt} if r.get("isError") else json.loads(txt)
    else:
        usb = [n for n in nodes if n["usb"] and n["tipus"] == "bemenet" and n["name"] and not is_builtin_audio(n["name"])]
        if usb:
            sink = desk_to_card(card_of(usb[0]["name"]))
            if sink:
                out["asztal_alap_kimenet"] = sink
    return out


def log_hangut(*a):
    """Napló a hibakereséshez: ~/.local/state/muzikos/naplo.log (mutasd meg a Claude-nak, ha valami nem megy)."""
    try:
        p = os.path.expanduser("~/.local/state/muzikos/naplo.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "[hangut] " + " ".join(json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x for x in a) + chr(10))
    except OSError:
        pass


def hangut_figyelo():
    """Háttérfigyelő (a belépéskor indul): a hangkártya ki-be dugásakor 3 másodperc nyugalom után helyreállítja a
    kötéseket; induláskor a laptop mikrofonjának szintjét 25%-ra veszi (100%-on torzít)."""
    for src in sh("pactl list short sources | cut -f2 | grep -v '\\.monitor$'")[1].split():
        if is_builtin_audio(src):
            sh(f"pactl set-source-volume {shlex.quote(src)} 25%")
    hangut_rendez()
    p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True, bufsize=1)
    last = [0.0]

    def pump():
        for line in p.stdout:
            if re.search(r"'(new|remove)' on (card|sink|source)", line):
                last[0] = time.time()
    threading.Thread(target=pump, daemon=True).start()
    utolso_sor = [time.time()]
    while p.poll() is None:
        time.sleep(0.5)
        if time.time() - utolso_sor[0] >= 60:       # a net nélkül sorban álló bejelentések elmennek, ha megjött a net
            utolso_sor[0] = time.time()
            bejel.hatterben()
            fnaplo.hatterben()
        if last[0] and time.time() - last[0] >= 3:
            last[0] = 0.0
            try:
                log_hangut("rendez", hangut_rendez())
            except Exception as e:
                log_hangut("hiba", repr(e))


def tool_audio_default(args):
    """Az asztal alapértelmezett hangeszköze (lejátszás és felvétel) egy eszköznévrész alapján."""
    want = (args.get("device") or "").lower()
    if not want:
        _, d, _ = sh("echo kimenet: $(pactl get-default-sink); echo bemenet: $(pactl get-default-source)")
        return text(d.strip())
    _, sinks, _ = sh("pactl list short sinks | cut -f2")
    _, sources, _ = sh("pactl list short sources | cut -f2 | grep -v '\\.monitor$'")
    sink = next((s for s in sinks.split() if want in s.lower()), None)
    source = next((s for s in sources.split() if want in s.lower()), None)
    if not sink and not source:
        return error("Nincs ilyen hangeszköz. A lista: audio_devices")
    cmds = ([f"pactl set-default-sink {sink}"] if sink else []) + ([f"pactl set-default-source {source}"] if source else [])
    code, out, err = sh(" && ".join(cmds))
    return text(f"alapértelmezett kimenet: {sink or '(változatlan)'}\nalapértelmezett bemenet: {source or '(változatlan)'}") if code == 0 else error(err)


def tool_xrun_check(args):
    secs = int(args.get("seconds", 5))
    code, out, err = sh(f"timeout {secs + 2} pw-top -b -n {max(2, secs)} 2>&1 | tail -n 60", timeout=secs + 10)
    _, j, _ = sh("journalctl --user -u pipewire -u wireplumber --since '-10 min' --no-pager 2>/dev/null | grep -iE 'xrun|underrun|overrun|error' | tail -n 20")
    return text("pw-top (az ERR oszlop a kiesések száma):\n" + out + "\n\nnapló (10 perc):\n" + (j.strip() or "nincs hiba"))


# ----------------------------------------------------------------------------- képernyő

def tool_screenshot(args):
    width = int(args.get("max_width", 1280))
    path = os.path.join(tempfile.gettempdir(), f"muzikos-shot-{uuid.uuid4().hex}.png")
    if have("import"):
        cmd = f"import -window root -resize '{width}x>' {path}"
    elif have("scrot"):
        cmd = f"scrot -o {path}"
    else:
        return error("Nincs képernyőkép-készítő (imagemagick vagy scrot).")
    code, _, err = sh(cmd, timeout=20)
    if code != 0 or not os.path.exists(path):
        return error("Nem sikerült képernyőképet készíteni: " + err)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    os.remove(path)
    _, geo, _ = sh("xdotool getdisplaygeometry 2>/dev/null")
    return {"content": [
        {"type": "image", "data": data, "mimeType": "image/png"},
        {"type": "text", "text": f"A kijelző mérete (a kattintás koordinátái ebben értendők): {geo.strip()}; a kép legfeljebb {width} px széles."},
    ]}


def tool_mouse(args):
    if not have("xdotool"):
        return error("Nincs xdotool.")
    x, y = int(args["x"]), int(args["y"])
    button = {"left": 1, "middle": 2, "right": 3}.get(args.get("button", "left"), 1)
    repeat = 2 if args.get("double") else 1
    code, _, err = sh(f"xdotool mousemove {x} {y} click --repeat {repeat} {button}")
    return text(f"kattintás: {x},{y}") if code == 0 else error(err)


def tool_keyboard(args):
    if not have("xdotool"):
        return error("Nincs xdotool.")
    if args.get("text"):
        code, _, err = sh("xdotool type --delay 20 --file -", input_bytes=args["text"].encode())
    elif args.get("keys"):
        code, _, err = sh("xdotool key " + " ".join(json.dumps(k) for k in args["keys"].split()))
    else:
        return error("Adj meg text-et (begépelendő szöveg) vagy keys-t (pl. 'ctrl+s Return').")
    return text("rendben") if code == 0 else error(err)


# ----------------------------------------------------------------------------- Reaper

def reaper_running():
    code, out, _ = sh("pgrep -x reaper || pgrep -f '/REAPER/reaper' ")
    return code == 0


def install_bridge():
    """A Lua-híd a Reaper Scripts mappájába, és a __startup.lua indítja minden induláskor."""
    scripts = os.path.join(REAPER_RESOURCE, "Scripts")
    os.makedirs(scripts, exist_ok=True)
    dst = os.path.join(scripts, "muzikos_bridge.lua")
    shutil.copyfile(BRIDGE_SRC, dst)
    startup = os.path.join(scripts, "__startup.lua")
    line = 'dofile(reaper.GetResourcePath() .. "/Scripts/muzikos_bridge.lua") -- MuzikOS-híd (Claude)\n'
    existing = open(startup, encoding="utf-8").read() if os.path.exists(startup) else ""
    # a régi (MusicOS) híd sora kikerül: a fájlja már nincs, és a hiányzó fájl a Reaper indulásakor megakasztaná (#361)
    if "musicos_bridge.lua" in existing:
        existing = "".join(ln for ln in existing.splitlines(True) if "musicos_bridge.lua" not in ln)
        with open(startup, "w", encoding="utf-8") as f:
            f.write(existing)
        old = os.path.join(scripts, "musicos_bridge.lua")
        if os.path.exists(old):
            os.remove(old)
    if "muzikos_bridge.lua" not in existing:
        with open(startup, "a", encoding="utf-8") as f:
            f.write(line)
    return dst


def reaper_call(lua_body, timeout=10.0):
    """Lua-kód futtatása a Reaperben a hídon át. A kód egy függvény törzse, ami értéket ad vissza."""
    with _reaper_lock:
        os.makedirs(BRIDGE_DIR, exist_ok=True)
        rid = uuid.uuid4().hex
        req = os.path.join(BRIDGE_DIR, "request.lua")
        resp = os.path.join(BRIDGE_DIR, "response.json")
        if os.path.exists(resp):
            os.remove(resp)
        tmp = req + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"-- id:{rid}\nreturn function()\n{lua_body}\nend\n")
        os.replace(tmp, req)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(resp):
                try:
                    with open(resp, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    time.sleep(0.05)
                    continue
                if data.get("id") == rid:
                    os.remove(resp)
                    return data
            time.sleep(0.05)
        if os.path.exists(req):
            os.remove(req)
        return {"ok": False, "error": "A Reaper nem válaszolt. Fut a Reaper, és fut benne a MuzikOS-híd? (reaper_start)"}


def reaper_result(data):
    if data.get("ok"):
        out = {"eredmeny": data.get("result")}
        if data.get("log"):
            out["naplo"] = data["log"]
        return as_json(out)
    return error("Reaper-hiba: " + str(data.get("error")) + ("\n" + "\n".join(data.get("log") or []) if data.get("log") else ""))


def lua_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def tool_reaper_start(args):
    install_bridge()
    if not reaper_running():
        binary = shutil.which("reaper") or "/opt/REAPER/reaper"
        if not os.path.exists(binary):
            return error("Nincs Reaper a gépen (/opt/REAPER).")
        quantum = int(args.get("quantum", 128))
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        env["PIPEWIRE_QUANTUM"] = f"{quantum}/48000"
        project = args.get("project")
        # a felvétel leállításakor a Reaper egy ablakban kérdezné, mentse-e az új fájlokat, és az ablak megállítja
        # a hidat (a próbagépen lemérve, #328): a fájlok maradnak, a döntés (take-ek törlése) a Claude-on át megy
        ini = os.path.join(REAPER_RESOURCE, "reaper.ini")
        if os.path.exists(ini):
            set_ini(ini, "REAPER", "promptendrec", 0)
            set_ini(ini, "REAPER", "verchk", 0)   # nincs frissítés-ablak, ami a hidat megakasztaná (#6)
            # a legutóbbi projekt, ha már nincs meg (áthelyezték, pl. a zenekari mappába költözéskor): a Reaper egy
            # ablakban kérdezne, és az megállítja a hidat — ilyenkor üres projekttel indul
            last = get_ini(ini, "REAPER", "lastproject")
            if last and not os.path.exists(last):
                set_ini(ini, "REAPER", "lastproject", "")
        cmd = [binary] + ([project] if project else [])
        subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + float(args.get("wait", 40))
    while time.time() < deadline:
        data = reaper_call("return reaper.GetAppVersion()", timeout=2)
        if data.get("ok"):
            dev = reaper_call('return muzikos.status().hang', timeout=3)
            return as_json({"reaper": data.get("result"), "hang": dev.get("result"), "hid": "fut"})
        time.sleep(1)
    return error("A Reaper elindult, de a MuzikOS-híd nem válaszol. Ha a Reaper most indult először, lehet, hogy egy párbeszédablak vár (képernyőkép: screenshot). A híd: " + os.path.join(REAPER_RESOURCE, "Scripts", "muzikos_bridge.lua"))


def reaper_dirty():
    """A Reaper mentetlen dalai („3. fül: Dal neve”); üres lista, ha minden mentve van vagy a Reaper nem fut."""
    if not reaper_running():
        return []
    dirty = reaper_call("local d = {} for _, p in ipairs(muzikos.projects()) do if p.mentetlen then d[#d + 1] = p.ful .. '. fül: ' .. p.nev end end return d", timeout=3)
    return list(dirty.get("result") or []) if dirty.get("ok") else []


def reaper_stop(wait=20):
    """A Reaper bezárása a hídon át; mentetlen projektnél nem zárja be (az a felhasználó munkája)."""
    if not reaper_running():
        return True, ""
    # minden fület nézni kell: a Reaper kilépéskor bármelyik mentetlen dalra rákérdez, és az ablak megállítja a hidat
    dirty = reaper_call("local d = {} for _, p in ipairs(muzikos.projects()) do if p.mentetlen then d[#d + 1] = p.ful .. '. fül: ' .. p.nev end end return d", timeout=3)
    if dirty.get("ok") and dirty.get("result"):
        return False, ("A Reaperben mentetlen dal van (" + ", ".join(dirty["result"]) + "). Előbb mentsd "
                       "(reaper_transport action=save, vagy reaper_project save_as), vagy kérdezd meg, eldobható-e.")
    reaper_call("reaper.Main_OnCommand(40004, 0) return true", timeout=3)   # File: Quit REAPER
    deadline = time.time() + wait
    while time.time() < deadline:
        if not reaper_running():
            return True, ""
        time.sleep(0.5)
    return False, "A Reaper nem zárult be (párbeszédablak? screenshot)."


def set_ini(path, section, key, value):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(path) else []
    out, in_sec, done = [], False, False
    for ln in lines:
        if ln.startswith("["):
            if in_sec and not done:
                out.append(f"{key}={value}")
                done = True
            in_sec = ln.strip().lower() == f"[{section.lower()}]"
        elif in_sec and ln.split("=", 1)[0] == key:
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(ln)
    if not done:
        if not in_sec:
            out.append(f"[{section}]")
        out.append(f"{key}={value}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def get_ini(path, section, key):
    in_sec = False
    for ln in (open(path, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(path) else []):
        if ln.startswith("["):
            in_sec = ln.strip().lower() == f"[{section.lower()}]"
        elif in_sec and ln.split("=", 1)[0] == key:
            return ln.split("=", 1)[1].strip()
    return None


# A Reaper a bekapcsolt MIDI-bemeneteket a reaper.ini-ben bitmaszkként tartja (a próbagépen lemérve, #328):
# midiins = felvételi bemenet, midiins_all = benne van az „All MIDI Inputs”-ban; a _h változat a 32–63. eszköz.
# Futó Reaper kilépéskor felülírja, ezért csak bezárt Reaperrel írható.
MIDI_IN_KEYS = ("midiins", "midiins_all")


def midi_masks(ini):
    out = {}
    for k in MIDI_IN_KEYS:
        lo, hi = get_ini(ini, "REAPER", k), get_ini(ini, "REAPER", k + "_h")
        out[k] = (int(lo or 0) & 0xFFFFFFFF) | ((int(hi or 0) & 0xFFFFFFFF) << 32)
    return out


def tool_reaper_midi_inputs(args):
    """A Reaper MIDI-bemenetei: lista (eszköz, be van-e kapcsolva), és bekapcsolás név szerint (a Reaper újraindul)."""
    if not reaper_running():
        started = tool_reaper_start({"wait": 40})
        if started.get("isError"):
            return started
    lua = ("local t={} for i=0,63 do local ok,n=reaper.GetMIDIInputName(i,'') "
           "if ok and n~='' and not n:match('^MIDI Input %d+$') then t[#t+1]={id=i,nev=n} end end return t")
    data = reaper_call(lua, timeout=5)
    if not data.get("ok"):
        return reaper_result(data)
    devs = data.get("result") or []
    ini = os.path.join(REAPER_RESOURCE, "reaper.ini")
    masks = midi_masks(ini)
    for d in devs:
        d["bekapcsolva"] = bool(masks["midiins"] >> d["id"] & 1)
    act = args.get("action", "list")
    if act == "list":
        return as_json({"eszkozok": devs, "mit_tegyel": "Ami nincs bekapcsolva, azt action=enable, devices=[a név része] kapcsolja be."})
    if act not in ("enable", "disable"):
        return error("action: list | enable | disable")
    want = [norm(w) for w in (args.get("devices") or [])]
    hit = [d for d in devs if not want or any(w in norm(d["nev"]) for w in want)]
    if act == "enable":
        hit = [d for d in hit if "midi through" not in norm(d["nev"])]   # a visszacsatolás ne kerüljön be
    if not hit:
        return error("Nincs ilyen MIDI-eszköz. A Reaper ezeket látja: " + ", ".join(d["nev"] for d in devs))
    ok, msg = reaper_stop()
    if not ok:
        return error(msg)
    for k in MIDI_IN_KEYS:
        m = masks[k]
        for d in hit:
            m = m | (1 << d["id"]) if act == "enable" else m & ~(1 << d["id"])
        set_ini(ini, "REAPER", k, m & 0xFFFFFFFF)
        set_ini(ini, "REAPER", k + "_h", m >> 32)
    started = tool_reaper_start({"wait": 40})
    if started.get("isError"):
        return started
    _, ports, _ = sh("pw-link -i 2>/dev/null | grep -i '^REAPER:MIDI' || true", timeout=10)
    return as_json({("bekapcsolva" if act == "enable" else "kikapcsolva"): [d["nev"] for d in hit],
                    "reaper_midi_portok": ports.splitlines(), "mit_tegyel": "Üss meg egy pedált vagy billentyűt, és nézd meg: input_levels / reaper_status (a sáv bemenete), vagy reaper_lua MIDI_GetRecentInputEvent."})


def tool_reaper_audio_system(args):
    """A Reaper hangrendszerének beállítása; a linux_audio_mode számát kipróbálással keresi meg."""
    want = args.get("system", "jack").lower()
    label = {"jack": "JACK", "alsa": "ALSA", "pulse": "Pulse", "pulseaudio": "Pulse"}.get(want, want)
    ini = os.path.join(REAPER_RESOURCE, "reaper.ini")
    tried = []
    for mode in [args["mode"]] if args.get("mode") is not None else [1, 0, 2, 3]:
        ok, msg = reaper_stop()
        if not ok:
            return error(msg)
        set_ini(ini, "REAPER", "linux_audio_mode", int(mode))
        if args.get("bsize"):
            set_ini(ini, "REAPER", "linux_audio_bsize", int(args["bsize"]))
        started = tool_reaper_start({"wait": 40, "quantum": args.get("bsize", 128)})
        if started.get("isError"):
            return started
        dev = reaper_call("return muzikos.status().hang", timeout=3).get("result") or {}
        tried.append({"linux_audio_mode": mode, "mod": dev.get("mod"), "bemenetek": len(dev.get("bemenetek") or [])})
        if label.lower() in str(dev.get("mod", "")).lower():
            return as_json({"beallitva": label, "linux_audio_mode": mode, "hang": dev, "probak": tried})
    return error("Egyik érték sem adta a kért hangrendszert: " + json.dumps(tried, ensure_ascii=False))


def tool_reaper_status(_args):
    if not reaper_running():
        return error("A Reaper nem fut. Indítsd: reaper_start.")
    return reaper_result(reaper_call("return muzikos.status()"))


def tool_reaper_add_track(args):
    name = args.get("name", "Sáv")
    kind = args.get("kind", "audio")
    inp = int(args.get("input", 1))
    stereo = bool(args.get("stereo", False))
    fx = args.get("fx") or []
    if isinstance(fx, str):
        fx = [fx]
    opts = {
        "name": name, "kind": kind, "input": inp, "stereo": stereo,
        "arm": args.get("arm", True), "monitor": args.get("monitor", True), "fx": fx,
        "midi_channel": int(args.get("midi_channel", 0)),
    }
    if args.get("midi_device") is not None:
        opts["midi_device"] = int(args["midi_device"])
    if kind == "audio" and not args.get("force"):
        # a kért bemenetbe van-e hangkártya bekötve; ha nincs, nem választunk helyette másikat (#386)
        conn = connected_inputs()
        need = [f"REAPER:in{inp}"] + ([f"REAPER:in{inp + 1}"] if stereo else [])
        if conn and any(n not in conn for n in need):
            have = sorted({int(re.sub(r"\D", "", k)) for k in conn})
            return error(f"A(z) {inp}. bemenet{' (sztereó: és a ' + str(inp + 1) + '.)' if stereo else ''} nincs bekötve: "
                         f"a Reaperben most ezek a bemenetek kapnak hangot a hangkártyáról: {', '.join(map(str, have))}. "
                         "Nem választok helyette másikat. Kérdezd meg: más bemenetre dugták? (input_levels megmutatja, hol "
                         "szól), vagy a hangkártya hiányzik (reaper_reconnect)? Ha mégis ez kell: force=true.")
    return reaper_result(reaper_call("return muzikos.add_track(" + json_to_lua(opts) + ")"))


DRUM_KITS = {"black pearl": "Black Pearl Drumkit (Robin Gareus)", "red zeppelin": "Red Zeppelin Drumkit (Robin Gareus)",
             "blonde bop": "Blonde Bop Drumkit (Robin Gareus)", "hotrod": "Blonde Bop HotRod Drumkit (Robin Gareus)"}


def tool_dob_midi_sav(args):
    """Elektromos dob a Reaperben: a modul MIDI-bemenete bekapcsolva, egy MIDI-sáv a 10. csatornán AVL-dobkészlettel
    (a hangjegyek utólag is javíthatók, a készlet cserélhető), és kérésre a modul saját hangja egy hangsávon."""
    dev = args.get("device", "")
    en = tool_reaper_midi_inputs({"action": "enable", "devices": [dev] if dev else []})
    if en.get("isError"):
        return en
    lst = json.loads(tool_reaper_midi_inputs({"action": "list"})["content"][0]["text"])["eszkozok"]
    ids = [d["id"] for d in lst if d["bekapcsolva"] and (not dev or norm(dev) in norm(d["nev"]))]
    kit = DRUM_KITS.get(norm(args.get("kit", "black pearl")), args.get("kit") or DRUM_KITS["black pearl"])
    res = {"midi_bemenet": json.loads(en["content"][0]["text"])}
    t = tool_reaper_add_track({"name": args.get("name", "Dob (MIDI)"), "kind": "midi", "midi_channel": 10,
                               **({"midi_device": ids[0]} if len(ids) == 1 else {}), "fx": [kit]})
    if t.get("isError"):
        return t
    res["midi_sav"] = json.loads(t["content"][0]["text"])
    if args.get("audio_input"):
        a = tool_reaper_add_track({"name": args.get("audio_name", "Dob (modul hangja)"), "kind": "audio",
                                   "input": int(args["audio_input"]), "stereo": bool(args.get("audio_stereo", False)),
                                   "monitor": False})
        if a.get("isError"):
            return a
        res["hang_sav"] = json.loads(a["content"][0]["text"])
    res["mit_tegyel"] = ("Kérd meg a dobost, hogy üssön meg minden dobot és cintányért; reaper_status és "
                         "MIDI_GetRecentInputEvent mutatja, mi jön. A modul hangsávján a monitorozás ki van kapcsolva: "
                         "a dobos a modul fejhallgatóján hallja magát, késés nélkül.")
    return as_json(res)


def tool_reaper_transport(args):
    action = args.get("action")
    body = {
        "record": "reaper.Main_OnCommand(40252, 0) reaper.Main_OnCommand(1013, 0)",   # normál mód: az egészet veszi
        "stop": "reaper.OnStopButton()",
        "play": "reaper.OnPlayButton()",
        "pause": "reaper.OnPauseButton()",
        "start": "reaper.CSurf_GoStart()",
        "save": "reaper.Main_OnCommand(40026, 0)",
    }.get(action)
    extra = []
    # előszámolás felvételhez: a lejátszás n ütemmel korábban indul, de csak a mostani helytől vesz fel (auto-punch)
    if action == "record" and int(args.get("count_in", 0)) > 0:
        n = int(args["count_in"])
        body = ("local s = reaper.GetCursorPosition()\n"
                "reaper.GetSet_LoopTimeRange(true, false, s, s + 36000, false)\n"
                "reaper.Main_OnCommand(40076, 0)\n"
                f"local m = muzikos.bar_of(s) reaper.SetEditCurPos(muzikos.bar_time(math.max(1, m - {n})), true, true)\n"
                "reaper.Main_OnCommand(1013, 0)")
    # hova: másodperc (position) vagy ütem (measure, 1-től)
    if args.get("measure") is not None:
        extra.append(f"reaper.SetEditCurPos(reaper.TimeMap2_beatsToTime(0, 0, {int(args['measure']) - 1}), true, true)")
    elif args.get("position") is not None:
        extra.append(f"reaper.SetEditCurPos({float(args['position'])}, true, true)")
    # ismétlés: loop = {"from_measure": 9, "to_measure": 17} vagy {"from": 12.5, "to": 30}; false = ki
    loop = args.get("loop")
    if loop is False:
        extra.append("reaper.GetSetRepeat(0)")
    elif isinstance(loop, dict):
        if "from_measure" in loop:
            s = f"reaper.TimeMap2_beatsToTime(0, 0, {int(loop['from_measure']) - 1})"
            e = f"reaper.TimeMap2_beatsToTime(0, 0, {int(loop.get('to_measure', int(loop['from_measure']) + 4)) - 1})"
        else:
            s, e = str(float(loop.get("from", 0))), str(float(loop.get("to", 0)))
        extra.append(f"local s, e = {s}, {e}\nreaper.GetSet_LoopTimeRange(true, true, s, e, false)\n"
                     "reaper.GetSetRepeat(1)\nreaper.SetEditCurPos(s, true, true)")
    if args.get("tempo"):
        extra.append(f"reaper.SetCurrentBPM(0, {float(args['tempo'])}, true)")
    if args.get("metronome") is not None:
        want = 1 if args["metronome"] else 0
        extra.append(f"if reaper.GetToggleCommandState(40364) ~= {want} then reaper.Main_OnCommand(40364, 0) end")
    if not body and not extra:
        return error("action: record | stop | play | pause | start | save; vagy tempo / metronome.")
    import muzikos_rendszer as hr
    if action == "record":
        warn = hr.preflight()
        if warn and not args.get("ellenorzes_kesz"):
            # felvétel előtt: ami recsegést okozhat (wifi, Guitarix 48 kHz-en) — előbb kérdezz (#381, #383)
            return as_json({"nem_indult": True, "figyelmeztetesek": warn,
                            "mit_tegyel": "Kérdezd meg a zenészt; utána a felvétel ellenorzes_kesz=true-val indul."})
        hr.record_started()
    lua = "\n".join(extra + ([body] if body else []) + ["return muzikos.transport()"])
    data = reaper_call(lua)
    if action == "stop" and data.get("ok"):
        n = hr.record_stopped()
        if n is not None and isinstance(data.get("result"), dict):
            data["result"]["kimaradas_a_felvetel_alatt"] = n
            if n:
                data["result"]["figyelem"] = (f"A felvétel alatt {n} hangkimaradás volt (a rendszer recsegett, nem a "
                                              "játék): a take-et érdemes újravenni; hangrendszer allapot / hangolas.")
    return reaper_result(data)


def tool_reaper_project(args):
    """Dalok = Reaper-projektek, mindegyik a saját fülén; új, megnyitás, mentés másként, váltás, lista."""
    action = args.get("action", "list")
    path = args.get("path", "")
    if action == "list":
        lua = "return muzikos.projects()"
    elif action == "new":
        lua = "reaper.Main_OnCommand(40859, 0)\n"       # új projekt egy új fülön (a régit nem zárja be)
        if path:
            lua += f"muzikos.save_as({lua_str(path)})\n"
        lua += "return muzikos.projects()"
    elif action == "open":
        if not path:
            return error("Az open-hez kell a path (.rpp).")
        lua = (f"local want = {lua_str(path)}\n"
               "for i = 0, 99 do local p, f = reaper.EnumProjects(i, '') if not p then break end\n"
               "  if f == want then reaper.SelectProjectInstance(p) return muzikos.projects() end end\n"
               "local cur = reaper.EnumProjects(-1, '')\n"
               "if reaper.IsProjectDirty(cur) ~= 0 or select(2, reaper.EnumProjects(-1, '')) ~= '' then reaper.Main_OnCommand(40859, 0) end\n"
               "reaper.Main_openProject('noprompt:' .. want)\nreturn muzikos.projects()")
    elif action == "switch":
        lua = (f"local want, n = {lua_str(path)}, {int(args.get('tab', 0))}\n"
               "for i = 0, 99 do local p, f = reaper.EnumProjects(i, '') if not p then break end\n"
               "  if (want ~= '' and f:find(want, 1, true)) or (want == '' and i + 1 == n) then reaper.SelectProjectInstance(p) return muzikos.projects() end end\n"
               "error('nincs ilyen nyitott dal: ' .. want)")
    elif action == "save_as":
        if not path:
            return error("A save_as-hoz kell a path (.rpp).")
        lua = f"muzikos.save_as({lua_str(path)})\nreturn muzikos.projects()"
    else:
        return error("action: list | new | open | switch | save_as")
    return reaper_result(reaper_call(lua, timeout=30))


def tool_reaper_render(args):
    """Export (mixdown) WAV-ba; mp3-hoz utána ffmpeg. Egész dal, vagy ütemek/másodpercek közt."""
    out = args.get("path")
    if not out:
        return error("Kell a path: hova menjen az export (.wav vagy .mp3).")
    wav = out if out.lower().endswith(".wav") else os.path.splitext(out)[0] + ".wav"
    d, name = os.path.dirname(wav), os.path.splitext(os.path.basename(wav))[0]
    bounds = 1
    pre = ""
    if args.get("from_measure") is not None:
        bounds = 2
        pre = (f"reaper.GetSet_LoopTimeRange(true, false, reaper.TimeMap2_beatsToTime(0, 0, {int(args['from_measure']) - 1}), "
               f"reaper.TimeMap2_beatsToTime(0, 0, {int(args.get('to_measure', args['from_measure'])) - 1}), false)\n")
    elif args.get("from") is not None:
        bounds = 2
        pre = f"reaper.GetSet_LoopTimeRange(true, false, {float(args['from'])}, {float(args.get('to', 0))}, false)\n"
    if os.path.exists(wav):
        os.remove(wav)   # a Reaper rákérdezne a felülírásra, és az ablak megállítaná a hidat
    lua = ("if reaper.GetProjectLength(0) <= 0 then error('a dal üres, nincs mit exportálni') end\n" + pre +
           f"reaper.RecursiveCreateDirectory({lua_str(d)}, 0)\n"
           f"reaper.GetSetProjectInfo_String(0, 'RENDER_FILE', {lua_str(d)}, true)\n"
           f"reaper.GetSetProjectInfo_String(0, 'RENDER_PATTERN', {lua_str(name)}, true)\n"
           "reaper.GetSetProjectInfo_String(0, 'RENDER_FORMAT', 'ZXZhdxgAAQ==', true)\n"   # WAV, 24 bit
           "reaper.GetSetProjectInfo(0, 'RENDER_SETTINGS', 0, true)\n"                       # master mix
           f"reaper.GetSetProjectInfo(0, 'RENDER_BOUNDSFLAG', {bounds}, true)\n"
           "reaper.GetSetProjectInfo(0, 'RENDER_SRATE', 48000, true)\n"
           "reaper.Main_OnCommand(42230, 0)\n"                                               # export, a párbeszédablak bezárul
           "return true")
    data = reaper_call(lua, timeout=float(args.get("timeout", 300)))
    if not data.get("ok"):
        return reaper_result(data)
    if not os.path.exists(wav):
        return error(f"Az export lefutott, de nincs meg a fájl: {wav}")
    res = {"wav": wav, "meret_MB": round(os.path.getsize(wav) / 1e6, 1)}
    if out.lower().endswith(".mp3"):
        code, _, err = sh(f"ffmpeg -y -loglevel error -i {shlex.quote(wav)} -b:a 256k {shlex.quote(out)}", timeout=300)
        if code != 0:
            return error("Az mp3-átalakítás nem sikerült: " + err)
        res["mp3"] = out
    return as_json(res)


# ----------------------------------------------------------------------------- dalszerkezet (#336)

ORDINALS = {"első": 1, "elso": 1, "második": 2, "masodik": 2, "harmadik": 3, "negyedik": 4,
            "ötödik": 5, "otodik": 5, "hatodik": 6, "hetedik": 7, "nyolcadik": 8, "utolsó": -1, "utolso": -1}


def norm(s):
    """Kisbetű, ékezet nélkül, a „rész”/„resz” ugyanaz legyen."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).strip()


SUFFIXES = ("tol", "rol", "bol", "ban", "ben", "hoz", "hez", "hoz", "nal", "nel", "val", "vel", "nak", "nek",
            "ra", "re", "ba", "be", "at", "et", "ot", "t")


def stem(w):
    """Egy szó toldalék nélkül, durván: „refrénre” → „refren”, „szólótól” → „szolo”."""
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def find_part(markers, query):
    """A zenész szavaiból egy dalrész: „a második gyors résztől”, „2. refrén”, „szólóra”, „utolsó refrén”."""
    words = norm(query).replace("-", " ").split()
    nth, stems = 1, []
    ordinals = {norm(k): v for k, v in ORDINALS.items()}
    for w in words:
        if w in ("a", "az"):
            continue
        if stem(w) in ordinals or w in ordinals:
            nth = ordinals.get(w, ordinals.get(stem(w)))
        elif w.rstrip(".").isdigit():
            nth = int(w.rstrip("."))
        elif w.startswith("resz"):
            continue                                   # „rész”, „részt”, „résztől”: általános szó
        else:
            stems.append(stem(w))
    if not stems:
        return None, []
    pool = sorted([m for m in markers if all(s in norm(m["nev"]) for s in stems)], key=lambda m: m["kezd_mp"])
    if not pool:
        return None, pool
    if nth > len(pool) or nth == 0:
        return None, pool
    return (pool[nth - 1] if nth > 0 else pool[-1]), pool


def part_range(markers, part):
    """Egy dalrész eleje és vége: a régió vége, jelölőnél a következő jelölő/rész eleje."""
    if part.get("veg_mp"):
        return part["kezd_mp"], part["veg_mp"]
    later = sorted(m["kezd_mp"] for m in markers if m["kezd_mp"] > part["kezd_mp"] + 1e-6)
    return part["kezd_mp"], (later[0] if later else None)


def tool_reaper_markers(args):
    action = args.get("action", "list")
    if action == "list":
        return reaper_result(reaper_call("return muzikos.markers()"))
    if action == "add":
        name = args.get("name") or "jelölő"
        snap = "true" if args.get("snap", True) else "false"
        if args.get("measure") is not None:
            pos = f"muzikos.bar_time({int(args['measure'])})"
        elif args.get("position") is not None:
            pos = f"select(2, muzikos.bar_of({float(args['position'])}, {snap}))" if args.get("snap", True) else str(float(args["position"]))
        else:
            pos = f"select(2, muzikos.bar_of(muzikos.now(), {snap}))" if args.get("snap", True) else "muzikos.now()"
        if args.get("to_measure") is not None:
            lua = (f"local s = {pos}\nlocal e = muzikos.bar_time({int(args['to_measure'])})\n"
                   f"local id = reaper.AddProjectMarker2(0, true, s, e, {lua_str(name)}, -1, 0)\n")
        else:
            lua = f"local s = {pos}\nlocal id = reaper.AddProjectMarker2(0, false, s, 0, {lua_str(name)}, -1, 0)\n"
        lua += "reaper.UpdateTimeline()\nreturn {letett = id, kezd_utem = (muzikos.bar_of(s)), osszes = muzikos.markers()}"
        return reaper_result(reaper_call(lua))
    if action == "structure":
        # parts: [{"name": "verze", "bars": 8}, ...] egymás után, a start_measure-től; a régiókat (ha replace) előbb törli
        parts = args.get("parts") or []
        if not parts:
            return error("A structure-hez kell a parts: [{name, bars}, …].")
        lua = ""
        if args.get("replace"):
            lua += ("for _, m in ipairs(muzikos.markers()) do if m.tipus == 'resz' then "
                    "reaper.DeleteProjectMarker(0, m.azonosito, true) end end\n")
        lua += f"local m = {int(args.get('start_measure', 1))}\n"
        for p in parts:
            lua += (f"reaper.AddProjectMarker2(0, true, muzikos.bar_time(m), muzikos.bar_time(m + {int(p['bars'])}), "
                    f"{lua_str(p['name'])}, -1, 0)\nm = m + {int(p['bars'])}\n")
        lua += "reaper.UpdateTimeline()\nreturn muzikos.markers()"
        return reaper_result(reaper_call(lua))
    if action in ("rename", "delete", "move"):
        data = reaper_call("return muzikos.markers()")
        if not data.get("ok"):
            return reaper_result(data)
        target, pool = find_part(data["result"] or [], args.get("name", ""))
        if args.get("id") is not None:
            target = next((m for m in data["result"] if m["azonosito"] == int(args["id"])), None)
        if not target:
            return error("Nincs ilyen jelölő vagy dalrész. A lista: reaper_markers action=list")
        isr = "true" if target["tipus"] == "resz" else "false"
        if action == "delete":
            lua = f"reaper.DeleteProjectMarker(0, {target['azonosito']}, {isr})"
        elif action == "rename":
            lua = (f"reaper.SetProjectMarker3(0, {target['azonosito']}, {isr}, {target['kezd_mp']}, "
                   f"{target.get('veg_mp') or 0}, {lua_str(args.get('new_name', target['nev']))}, 0)")
        else:
            s = f"muzikos.bar_time({int(args['measure'])})" if args.get("measure") is not None else str(float(args.get("position", target["kezd_mp"])))
            length = (target.get("veg_mp") or target["kezd_mp"]) - target["kezd_mp"]
            lua = (f"local s = {s}\nreaper.SetProjectMarker3(0, {target['azonosito']}, {isr}, s, "
                   f"{'s + ' + str(length) if target['tipus'] == 'resz' else '0'}, {lua_str(target['nev'])}, 0)")
        return reaper_result(reaper_call(lua + "\nreaper.UpdateTimeline()\nreturn muzikos.markers()"))
    return error("action: list | add | structure | rename | move | delete")


def tool_reaper_part(args):
    """Egy dalrész a zenész szavaival: odaugrás, lejátszás, ismétlés, felvétel (előszámolással, csak arra a részre)."""
    data = reaper_call("return muzikos.markers()")
    if not data.get("ok"):
        return reaper_result(data)
    markers = data["result"] or []
    part, pool = find_part(markers, args.get("part", ""))
    if not part:
        names = ", ".join(m["nev"] for m in markers) or "nincs egy sem"
        return error(f"Nem találom ezt a részt: „{args.get('part')}”. A dal jelölői: {names}. (reaper_markers)")
    start, end = part_range(markers, part)
    action = args.get("action", "goto")
    count_in = int(args.get("count_in", 1 if action in ("play", "record") else 0))
    lua = f"local s, e = {start}, {end if end is not None else 'reaper.GetProjectLength(0)'}\n"
    lua += f"local pre = s\nif {count_in} > 0 then local m = muzikos.bar_of(s) pre = muzikos.bar_time(math.max(1, m - {count_in})) end\n"
    if action != "record":
        lua += "reaper.Main_OnCommand(40252, 0)\n"   # normál felvételi mód: egy korábbi „csak a részre” ne vágjon le egy későbbi felvételt
    if action == "loop":
        lua += "reaper.GetSet_LoopTimeRange(true, true, s, e, false)\nreaper.GetSetRepeat(1)\nreaper.SetEditCurPos(s, true, true)\nreaper.OnPlayButton()\n"
    elif action == "record":
        punch = args.get("punch", True)
        lua += "reaper.GetSet_LoopTimeRange(true, false, s, e, false)\n"
        lua += ("reaper.Main_OnCommand(40076, 0)\n" if punch else "reaper.Main_OnCommand(40252, 0)\n")   # auto-punch a kijelölésre / normál
        lua += "reaper.SetEditCurPos(pre, true, true)\nreaper.Main_OnCommand(1013, 0)\n"
    elif action == "play":
        lua += "reaper.GetSetRepeat(0)\nreaper.SetEditCurPos(pre, true, true)\nreaper.OnPlayButton()\n"
    else:
        lua += "reaper.SetEditCurPos(s, true, true)\n"
    lua += ("return {resz = " + lua_str(part["nev"]) + ", kezd_mp = s, veg_mp = e, kezd_utem = (muzikos.bar_of(s)), "
            "indul_mp = reaper.GetCursorPosition(), elotte_utem = " + str(count_in) + ", transport = muzikos.transport(), "
            "felvetel_mod = (reaper.GetToggleCommandState(40076) == 1) and 'csak a részre (auto-punch)' or 'normál'}")
    out = reaper_result(reaper_call(lua))
    if len(pool) > 1 and not out.get("isError"):
        out["content"].append({"type": "text", "text": "Több ilyen nevű rész van: " + ", ".join(f"{m['nev']} ({m['kezd_utem']}. ütem)" for m in pool)})
    return out


# ----------------------------------------------------------------------------- visszahallgatás (#331)

def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def tool_reaper_overdub(args):
    """Rájátszás: mit vegyen fel és mit halljanak a zenészek a Reaperből."""
    o = {"record": as_list(args.get("record")), "hear": as_list(args.get("hear")),
         "direct": args.get("direct_monitor", True), "mute_others": args.get("mute_others", True)}
    if not o["record"] and not o["hear"]:
        return error("Add meg, mit vegyen fel (record) és/vagy mit halljanak (hear) — sávnév vagy sorszám.")
    return reaper_result(reaper_call("return muzikos.overdub(" + json_to_lua(o) + ")"))


def tool_reaper_track_set(args):
    """Egy vagy több sáv beállítása: élesítés, monitorozás, némítás, szóló, hangerő, panoráma, bemenet."""
    tracks = as_list(args.get("track"))
    if not tracks:
        return error("Kell a track: sávnév vagy sorszám (lista is lehet).")
    sets = []
    mon = {"off": 0, "ki": 0, "on": 1, "be": 1, "auto": 2}
    if "arm" in args:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'I_RECARM', {1 if args['arm'] else 0})")
    if "monitor" in args:
        m = mon.get(str(args["monitor"]).lower(), 1 if args["monitor"] is True else 0)
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'I_RECMON', {m})")
    if "mute" in args:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'B_MUTE', {1 if args['mute'] else 0})")
    if "solo" in args:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'I_SOLO', {2 if args['solo'] else 0})")
    if args.get("volume_db") is not None:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'D_VOL', 10 ^ ({float(args['volume_db'])} / 20))")
    if args.get("pan") is not None:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'D_PAN', {max(-1.0, min(1.0, float(args['pan']) / 100))})")
    if "phase_invert" in args:
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'B_PHASE', {1 if args['phase_invert'] else 0})")
    if args.get("input") is not None:
        inp = int(args["input"]) - 1 + (1024 if args.get("stereo") else 0)
        sets.append(f"reaper.SetMediaTrackInfo_Value(t.tr, 'I_RECINPUT', {inp})")
    if not sets:
        return error("Mit állítsak? arm, monitor (off/on/auto), mute, solo, volume_db, pan (−100…100), input.")
    lua = ("local found = muzikos.find_tracks(" + json_to_lua(tracks) + ")\n"
           "if #found == 0 then error('nincs ilyen sáv') end\n"
           "for _, t in ipairs(found) do\n  " + "\n  ".join(sets) + "\nend\n"
           "return muzikos.status().savok")
    return reaper_result(reaper_call(lua))


def tool_reaper_cue_mix(args):
    """Fejhallgató-keverés egy kimenetpárra: sávonként dB-ben (pre-fader küldés)."""
    levels = args.get("levels") or {}
    if not levels:
        return error("Kell a levels: {\"Dob\": 0, \"Basszus\": -6, …} — mely sávok mekkora hangerővel menjenek erre a kimenetre.")
    out = int(args.get("out", 3))
    return reaper_result(reaper_call("return muzikos.cue_mix(" + json_to_lua({"out": out, "levels": levels}) + ")"))


# ----------------------------------------------------------------------------- dalok a memóriából (#325)

import muzikos_memory as mem   # a szerver mappájából (a script könyvtára a sys.path elején van)


def projects_root():
    """A zenekarok mappái (#351): a tudástár mellett (PenSSD-Adat/MuzikOS/Zenekarok), a dalok a zenekar Dalok/ mappájában."""
    return mem.bands_root()


def tool_dal_megnyitas(args):
    """Egy dal a memóriából: a projektje megnyitva (vagy létrehozva), a tempó és a dalrészek a helyükön."""
    title = args.get("title")
    if not title:
        return error("Kell a title (a dal címe).")
    bid = mem.find_band(args.get("band"))
    if not bid:
        return error("Nincs mostani zenekar: zenekar action=activate (vagy band).")
    band = mem.tool_zenekar({"action": "get", "name": bid})
    try:
        song = mem.tool_dal({"action": "get", "title": title, "band": bid})
    except ValueError:
        if not args.get("create", True):
            raise
        song = mem.tool_dal({"action": "set", "title": title, "band": bid, "data": {}})["dal"]
    steps = []
    # az új projekt a dal mappájának reaper/ almappájába kerül (#346)
    proj = song.get("projekt") or os.path.join(songs.ensure(band, song), "reaper", song["cim"] + ".rpp")
    new = not os.path.exists(proj)
    r = reaper_call("return muzikos.projects()")
    if not r.get("ok"):
        return reaper_result(r)
    if new:
        r = reaper_call(f"reaper.Main_OnCommand(40859, 0)\nmuzikos.save_as({lua_str(proj)})\nreturn muzikos.projects()", timeout=30)
        steps.append(f"új projekt: {proj}")
    else:
        r = reaper_call(f"local want = {lua_str(proj)}\n"
                        "for i = 0, 99 do local p, f = reaper.EnumProjects(i, '') if not p then break end\n"
                        "  if f == want then reaper.SelectProjectInstance(p) return muzikos.projects() end end\n"
                        "if reaper.IsProjectDirty(0) ~= 0 or select(2, reaper.EnumProjects(-1, '')) ~= '' then reaper.Main_OnCommand(40859, 0) end\n"
                        "reaper.Main_openProject('noprompt:' .. want)\nreturn muzikos.projects()", timeout=30)
        steps.append(f"megnyitva: {proj}")
    if not r.get("ok"):
        return reaper_result(r)
    if song.get("tempo") and (new or args.get("tempo_from_memory")):
        reaper_call(f"reaper.SetCurrentBPM(0, {float(song['tempo'])}, true) return true")
        steps.append(f"tempó: {song['tempo']}")
    parts = [{"name": p.get("nev"), "bars": int(p.get("utem", 0))} for p in song.get("szerkezet", []) if p.get("nev") and p.get("utem")]
    if parts:
        have = reaper_call("local n = 0 for _, m in ipairs(muzikos.markers()) do if m.tipus == 'resz' then n = n + 1 end end return n")
        if have.get("ok") and (not have.get("result") or args.get("replace_structure")):
            tool_reaper_markers({"action": "structure", "parts": parts, "replace": bool(args.get("replace_structure"))})
            steps.append(f"dalrészek: {', '.join(p['name'] for p in parts)}")
    if song.get("projekt") != proj:
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"projekt": proj}})
    # kézi változtatás a Reaperben? szólunk (#346)
    sync = tool_dal_szinkron({"action": "check", "title": song["cim"], "band": bid})
    try:
        chk = json.loads(sync["content"][0]["text"])
        if chk.get("elteresek"):
            steps.append("FIGYELEM, szinkronizálni való van: " + "; ".join(chk["elteresek"]))
    except (KeyError, ValueError, IndexError):
        pass
    return as_json({"zenekar": band.get("nev"), "dal": mem.display_title(song),
                    **({"munkacim": song["cim"]} if song.get("publikus_cim") else {}), "lepesek": steps,
                    "tagok_savjai": [f"{t.get('nev')}: {t.get('sav') or t.get('hangszer')}" + (f" ({t['bemenet']}. bemenet)" if t.get("bemenet") else "")
                                      for t in band.get("tagok", [])],
                    "jegyzetek": song.get("jegyzetek", [])[-5:]})


def parse_timesig(s):
    if not s:
        return 0, 0
    a, _, b = str(s).replace(" ", "").partition("/")
    return int(a), int(b or 4)


def tool_reaper_tempo(args):
    """A tempótérkép: set (ütemtől tempó és/vagy ütemmutató), ramp (fokozatos átmenet), list, clear."""
    act = args.get("action", "list")
    if act == "list":
        return reaper_result(reaper_call("return muzikos.tempo_list()"))
    if act == "clear":
        return reaper_result(reaper_call(f"return muzikos.tempo_clear({int(args.get('measure', 1))})"))
    m = int(args.get("measure", 1))
    num, den = parse_timesig(args.get("time_signature"))
    if act == "set":
        o = {"measure": m, "num": num, "den": den, "linear": False}
        if args.get("bpm"):
            o["bpm"] = float(args["bpm"])
        return reaper_result(reaper_call("return muzikos.tempo_set(" + json_to_lua(o) + ")"))
    if act == "ramp":
        to_m, to_bpm = args.get("to_measure"), args.get("to_bpm")
        if not to_m or not to_bpm:
            return error("A ramp-hoz kell a measure (honnan), a to_measure (hova) és a to_bpm.")
        start = {"measure": m, "linear": True}
        if args.get("bpm"):
            start["bpm"] = float(args["bpm"])
        lua = ("muzikos.tempo_set(" + json_to_lua(start) + ")\n"
               "return muzikos.tempo_set(" + json_to_lua({"measure": int(to_m), "bpm": float(to_bpm), "linear": False}) + ")")
        return reaper_result(reaper_call(lua))
    return error("action: list | set | ramp | clear")


def tool_reaper_metronome(args):
    """A Reaper saját metronómja be/ki (a klikksáv a reaper_click)."""
    want = 1 if args.get("on", True) else 0
    r = reaper_result(reaper_call(f"if reaper.GetToggleCommandState(40364) ~= {want} then reaper.Main_OnCommand(40364, 0) end\n"
                                  "return {metronom = reaper.GetToggleCommandState(40364) == 1}"))
    if want and not r.get("isError"):
        # a próbán lemérve (#47): a beépített metronóm nem a fő keverésbe szól, a UMC főkimenetén nem hallatszik
        r["content"][0]["text"] += ("\nFIGYELEM: a Reaper beépített metronómja a UMC főkimenetén nem biztos, hogy hallatszik. "
                                    "A hallható klikkhez használd a Klikk-sávot: reaper_click (a fő keverésen át szól).")
    return r


def tool_reaper_click(args):
    """Saját klikksáv: követi a tempótérképet, kiemelt első ütés, hangszín, hangerő, csak a fejhallgatóban."""
    if args.get("action") == "remove":
        return reaper_result(reaper_call("for _, t in ipairs(muzikos.find_tracks({'Klikk'})) do reaper.DeleteTrack(t.tr) end return true"))
    sub = {"none": 1, "negyed": 1, "8": 2, "nyolcad": 2, "triola": 3, "16": 4}.get(str(args.get("subdivision", "none")).lower(), 1)
    o = {"from": args.get("from_measure"), "to": args.get("to_measure"), "sound": args.get("sound", "magas"),
         "volume_db": args.get("volume_db", -6), "sub": sub, "accent": args.get("accent", True),
         "headphones_only": args.get("headphones_only", False), "out": args.get("out", 1), "skip": as_list(args.get("skip_parts"))}
    o = {k: v for k, v in o.items() if v is not None}
    return reaper_result(reaper_call("return muzikos.click(" + json_to_lua(o) + ")", timeout=30))


def tool_reaper_song_view(args):
    """A „hol tartunk” kijelző a Reaperben: open / close / state (mit mutat most)."""
    act = args.get("action", "open")
    if act == "open":
        return reaper_result(reaper_call(f"return muzikos.view_open({int(args.get('width', 1000))}, {int(args.get('height', 420))})"))
    if act == "close":
        return reaper_result(reaper_call("return muzikos.view_close()"))
    return reaper_result(reaper_call("return muzikos.view_state()"))


def tool_reaper_lua(args):
    code = args.get("code", "")
    if not code.strip():
        return error("Hiányzik a code.")
    return reaper_result(reaper_call(code, timeout=float(args.get("timeout", 15))))


def json_to_lua(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "nil"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return lua_str(v)
    if isinstance(v, list):
        return "{" + ", ".join(json_to_lua(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"[{lua_str(k)}]={json_to_lua(x)}" for k, x in v.items()) + "}"
    return lua_str(v)


# ----------------------------------------------------------------------------- eszközlista

TOOLS = [
    ("system_status", tool_system_status,
     "A gép állapota egy pillantásra: valós idejű-e a kernel, a processzor üzemmódja, a valós idejű jogosultságok, az USB-alvás, a lemezek, a hálózat, a tartós fájl.",
     {}),
    ("run_command", tool_run_command,
     "Bármilyen parancs futtatása a gépen (bash). sudo=true: rendszergazdaként, jelszó nélkül. A MuzikOS-en a Claude teljes hozzáféréssel dolgozik.",
     {"command": {"type": "string", "description": "A parancs (bash -lc)."},
      "sudo": {"type": "boolean", "description": "Rendszergazdaként fusson."},
      "timeout": {"type": "integer", "description": "Másodperc, alap: 120."}}),
    ("audio_devices", tool_audio_devices,
     "A hangkártyák és MIDI-eszközök: a PipeWire bemenetei és kimenetei a csatornaszámmal, a kártyák profilja (Pro Audio?), a mostani mintavétel és puffer.",
     {}),
    ("input_levels", tool_input_levels,
     "Belehallgat egy bemeneti eszközbe néhány másodpercig, és csatornánként megmondja, hol van jel, mekkora (dBFS), és túlvezérel-e. Ezzel derül ki, melyik bemenetre dugták a gitárt vagy a mikrofont.",
     {"seconds": {"type": "number", "description": "Meddig figyeljen, alap: 3."},
      "device": {"type": "string", "description": "A bemeneti eszköz nevének része (alap: az első USB-s)."}}),
    ("set_latency", tool_set_latency,
     "A PipeWire pufferének (quantum, mintában) és mintavételének állítása futás közben. 64 vagy 128 = kis késés; ha kattog, 256. 0 = vissza az alapra.",
     {"quantum": {"type": "integer"}, "rate": {"type": "integer"}}),
    ("audio_default", tool_audio_default,
     "Az asztal (böngésző, lejátszó) alapértelmezett hangeszköze: device = a név része (pl. 'UMC404HD'); üresen megmondja, mi a mostani. Akkor kell, ha egy újonnan bedugott eszköz (pl. egy pedál) elvitte a hangot.",
     {"device": {"type": "string"}}),
    ("dob_mikrofon_terv", tool_dob_mikrofon_terv,
     "Akusztikus dob mikrofonterve a hangkártya bemeneteihez (inputs, first_input): melyik mikrofon hova, hogyan, milyen típus, kell-e 48V. apply=true: a Reaper-sávok (élesítve) és a bekötési térkép (mikrofonok, XLR-kábelek) is elkészül.",
     {"inputs": {"type": "integer"}, "first_input": {"type": "integer"}, "apply": {"type": "boolean"},
      "felallas": {"type": "string"}, "interface_id": {"type": "string", "description": "a hangkártya id-je a térképen (alap: umc)"}}),
    ("dob_fazis", tool_dob_fazis,
     "Két mikrofon fázisa (pl. lábdob és overhead): a dobos üssön erősen egyet; a legerősebb ütésnél megméri a késést (ms) és a korrelációt. Negatívnál fordított a fázis: reaper_track_set phase_invert.",
     {"a": {"type": "integer"}, "b": {"type": "integer"}, "device": {"type": "string"}, "seconds": {"type": "number"}}),
    ("xrun_check", tool_xrun_check,
     "Kiesések (xrun, kattogás) keresése: a pw-top ERR oszlopa és a hangrendszer naplója.",
     {"seconds": {"type": "integer", "description": "Meddig figyeljen, alap: 5."}}),
    ("screenshot", tool_screenshot,
     "Képernyőkép a gép asztaláról. Akkor kell, ha egy programot nem lehet parancsból vagy a Reaper-hídon át kezelni.",
     {"max_width": {"type": "integer", "description": "Legfeljebb ilyen széles legyen a kép (px), alap: 1280."}}),
    ("mouse", tool_mouse,
     "Egérkattintás a kijelző egy pontjára (a screenshot után; a koordináták a kijelző méretében értendők).",
     {"x": {"type": "integer"}, "y": {"type": "integer"},
      "button": {"type": "string", "enum": ["left", "middle", "right"]},
      "double": {"type": "boolean"}}),
    ("keyboard", tool_keyboard,
     "Gépelés (text) vagy billentyűk (keys, pl. 'ctrl+s', 'Return', 'alt+F4') az éppen aktív ablakba.",
     {"text": {"type": "string"}, "keys": {"type": "string"}}),
    ("reaper_start", tool_reaper_start,
     "Elindítja a Reapert (ha még nem fut) a MuzikOS-híddal, és megvárja, hogy válaszoljon. Megmondja a hangeszközét is.",
     {"project": {"type": "string", "description": "Megnyitandó projekt (.rpp) vagy sablon."},
      "quantum": {"type": "integer", "description": "Puffer a Reapernek (PIPEWIRE_QUANTUM), alap: 128."},
      "wait": {"type": "number"}}),
    ("reaper_audio_system", tool_reaper_audio_system,
     "A Reaper hangrendszere (alap: JACK, ami a MuzikOS-en a PipeWire-en át szól). Bezárja a Reapert (mentetlen projektnél nem), átírja a beállítást, újraindítja, és visszaellenőrzi.",
     {"system": {"type": "string", "enum": ["jack", "alsa", "pulse"]},
      "bsize": {"type": "integer", "description": "Puffer (minta), alap: 128."},
      "mode": {"type": "integer", "description": "A reaper.ini linux_audio_mode értéke, ha már ismert."}}),
    ("reaper_reconnect", tool_reaper_reconnect,
     "A Reaper be- és kimeneteinek visszakötése a hangkártyára (JACK-portok, pw-link). Alapból a kártya 1. bemenete a Reaper 1-esére, a 2. a 2-esre …, a kimenetek a kártya A párjára; a beépített mikrofon és hangszóró kötéseit leveszi, az asztal hangját az A párra állítja (a kártya kihúzása és visszadugása után ez magától is megtörténik: a háttérfigyelő végzi). input + reaper_in: csak egy kötés („a UMC 2-es bemenete menjen a Reaper 1-esére”).",
     {"device": {"type": "string", "description": "A hangkártya nevének része (alap: a felállás kártyája, különben a legtöbb bemenetű külső kártya)."},
      "input": {"type": "integer", "description": "A kártya bemenetének száma (1-től); reaper_in nélkül ugyanennyedik Reaper-bemenetre megy."},
      "reaper_in": {"type": "integer", "description": "A Reaper bemenetének száma (1-től): erre a bemenetre csak a megadott kártyabemenet kerül."},
      "belso": {"type": "string", "description": "„marad”: a beépített mikrofon és hangszóró kötéseit ne vegye le."}}),
    ("reaper_status", tool_reaper_status,
     "A Reaper állapota: projekt, tempó, lejátszás/felvétel, és sávonként a név, a bemenet, az élesítés, a monitorozás, az effektek.",
     {}),
    ("reaper_add_track", tool_reaper_add_track,
     "Új sáv a Reaperben: hangbemenet (input = a hangkártya hányadik bemenete, 1-től) vagy MIDI (kind='midi'), élesítve, monitorozva, effektekkel (pl. fx=['Neural Amp Modeler'] vagy ['Guitarix']). Ha a kért bemenetbe nincs hangkártya bekötve, hibát ad és nem választ másikat (force=true: mégis).",
     {"name": {"type": "string"},
      "kind": {"type": "string", "enum": ["audio", "midi"]},
      "input": {"type": "integer", "description": "Hangbemenet sorszáma 1-től (sztereónál az első)."},
      "stereo": {"type": "boolean"},
      "arm": {"type": "boolean"}, "monitor": {"type": "boolean"},
      "fx": {"type": "array", "items": {"type": "string"}},
      "midi_channel": {"type": "integer", "description": "MIDI-csatorna (0 = mind)."},
      "midi_device": {"type": "integer", "description": "Csak ez a MIDI-eszköz (a reaper_midi_inputs id-je); alap: mind."},
      "force": {"type": "boolean", "description": "A bekötetlen bemenetre is (csak ha a zenész kérte)."}}),
    ("reaper_midi_inputs", tool_reaper_midi_inputs,
     "A Reaper MIDI-bemenetei (elektromos dob, billentyű, pedál): list = mit lát a Reaper, és mi van bekapcsolva; enable / disable devices=[a név része] (üresen: mind) — a Reaper ehhez újraindul (mentetlen dalnál nem). Egy frissen bedugott MIDI-eszköz alapból ki van kapcsolva, ezért nem jön belőle semmi.",
     {"action": {"type": "string", "enum": ["list", "enable", "disable"]},
      "devices": {"type": "array", "items": {"type": "string"}}}),
    ("dob_midi_sav", tool_dob_midi_sav,
     "Elektromos dob felvételre kész: a modul MIDI-bemenete bekapcsolva, MIDI-sáv a 10. csatornán AVL-dobkészlettel (kit: black pearl | red zeppelin | blonde bop | hotrod), és audio_input-tal a modul saját hangja is egy hangsávon (a hangkártya bemenete).",
     {"device": {"type": "string", "description": "a MIDI-eszköz nevének része (pl. Nitro); alap: minden bekapcsolható eszköz"},
      "kit": {"type": "string"}, "name": {"type": "string"},
      "audio_input": {"type": "integer"}, "audio_stereo": {"type": "boolean"}, "audio_name": {"type": "string"}}),
    ("reaper_overdub", tool_reaper_overdub,
     "Rájátszás egy felvett anyagra: record = a felveendő sáv(ok) (élesítve; direct_monitor=true esetén a szoftveres monitorozásuk KI, mert a zenész a hangkártyán közvetlenül hallja magát, késés nélkül), hear = amit a Reaperből hallani akarnak (a többi némítva, ha mute_others). Sávnév vagy sorszám.",
     {"record": {"type": "array", "items": {"type": "string"}}, "hear": {"type": "array", "items": {"type": "string"}},
      "direct_monitor": {"type": "boolean"}, "mute_others": {"type": "boolean"}}),
    ("reaper_track_set", tool_reaper_track_set,
     "Sáv(ok) beállítása név vagy sorszám szerint: arm, monitor (off/on/auto), mute, solo, volume_db, pan (−100 bal … 100 jobb), input (+stereo).",
     {"track": {"type": "array", "items": {"type": "string"}}, "arm": {"type": "boolean"},
      "monitor": {"type": "string", "enum": ["off", "on", "auto"]}, "mute": {"type": "boolean"}, "solo": {"type": "boolean"},
      "volume_db": {"type": "number"}, "pan": {"type": "number"}, "input": {"type": "integer"}, "stereo": {"type": "boolean"},
      "phase_invert": {"type": "boolean", "description": "a sáv fázisának megfordítása (mikrofonok fázishibájánál)"}}),
    ("reaper_cue_mix", tool_reaper_cue_mix,
     "Külön fejhallgató-keverés egy zenésznek: a hangkártya egy kimenetpárjára (out = az első kimenet sorszáma, pl. 3 = 3/4) a megadott sávok, sávonként dB (levels). A fő keverés hangerejétől független (pre-fader).",
     {"out": {"type": "integer"}, "levels": {"type": "object"}}),
    ("reaper_transport", tool_reaper_transport,
     "Felvétel, leállítás, lejátszás, szünet, az elejére, mentés; ugrás egy ütemre vagy másodpercre; egy rész ismétlése (loop); tempó és metronóm. Több is mehet egyszerre (pl. measure + loop + action=play). A felvétel előtt szól, ha valami recsegést okozhat (wifi, Guitarix 48 kHz-en); a leállítás megmondja, volt-e hangkimaradás a felvétel alatt.",
     {"action": {"type": "string", "enum": ["record", "stop", "play", "pause", "start", "save"]},
      "measure": {"type": "integer", "description": "Ugrás erre az ütemre (1-től)."},
      "position": {"type": "number", "description": "Ugrás erre a másodpercre."},
      "loop": {"description": "Ismétlés: {from_measure, to_measure} vagy {from, to} másodpercben; false = ismétlés ki.",
               "oneOf": [{"type": "object"}, {"type": "boolean"}]},
      "tempo": {"type": "number"}, "metronome": {"type": "boolean"},
      "count_in": {"type": "integer", "description": "record: előszámolás ütemben (a lejátszás korábban indul, a felvétel a mostani helytől)"},
      "ellenorzes_kesz": {"type": "boolean", "description": "record: a felvétel előtti figyelmeztetéseket (wifi, Guitarix 48 kHz) már megbeszélted"}}),
    ("reaper_project", tool_reaper_project,
     "Dalok (Reaper-projektek): list = a nyitott dalok (fülek); new = új dal új fülön (path: hova mentse); open = megnyitás (.rpp, új fülön, ha a mostani nem üres); switch = váltás egy nyitott dalra (path: a név része, vagy tab: sorszám); save_as = mentés másként.",
     {"action": {"type": "string", "enum": ["list", "new", "open", "switch", "save_as"]},
      "path": {"type": "string"}, "tab": {"type": "integer"}}),
    ("reaper_markers", tool_reaper_markers,
     "Dalszerkezet: jelölők és dalrészek (régiók). list = mind, ütemszámmal; add = jelölő (name; measure, position vagy most, ütemre kerekítve) vagy rész (+ to_measure); structure = részek egymás után (parts: [{name, bars}], start_measure, replace); rename / move / delete (name a zenész szavaival vagy id).",
     {"action": {"type": "string", "enum": ["list", "add", "structure", "rename", "move", "delete"]},
      "name": {"type": "string"}, "new_name": {"type": "string"}, "id": {"type": "integer"},
      "measure": {"type": "integer"}, "to_measure": {"type": "integer"}, "position": {"type": "number"},
      "snap": {"type": "boolean", "description": "Ütemre kerekítés (alap: igen)."},
      "parts": {"type": "array", "items": {"type": "object"}}, "start_measure": {"type": "integer"},
      "replace": {"type": "boolean"}}),
    ("reaper_part", tool_reaper_part,
     "Egy dalrész a zenész szavaival („a második gyors rész”, „2. refrén”, „utolsó refrén”, „szóló”): goto = oda; play = onnan, előszámolással; loop = a rész ismétlése; record = felvétel csak arra a részre (auto-punch), előszámolással (count_in ütem, alap 1).",
     {"part": {"type": "string"}, "action": {"type": "string", "enum": ["goto", "play", "loop", "record"]},
      "count_in": {"type": "integer"}, "punch": {"type": "boolean"}}),
    ("reaper_tempo", tool_reaper_tempo,
     "A tempótérkép: set (measure-től bpm és/vagy time_signature, pl. \"6/8\"); ramp (measure-től to_measure-ig fokozatosan to_bpm-re; bpm = a kiinduló, alap: a mostani); list; clear (measure-től). A klikk és a dalrészek ezt követik.",
     {"action": {"type": "string", "enum": ["list", "set", "ramp", "clear"]}, "measure": {"type": "integer"},
      "bpm": {"type": "number"}, "time_signature": {"type": "string"}, "to_measure": {"type": "integer"}, "to_bpm": {"type": "number"}}),
    ("reaper_metronome", tool_reaper_metronome,
     "A Reaper saját metronómja be (on=true) vagy ki. FIGYELEM: a beépített metronóm a UMC főkimenetén nem hallatszik, a hallható klikkhez a Klikk-sáv kell: reaper_click (hang, hangerő, csak fejhallgató, részek kihagyása).",
     {"on": {"type": "boolean"}}),
    ("reaper_click", tool_reaper_click,
     "Saját klikksáv („Klikk”): minden ütésre egy hang a tempótérkép szerint (ütemmutató-váltásnál is), kiemelt első ütés (accent), subdivision: none / 8 / triola / 16, sound: magas / mely / fa, volume_db, headphones_only (a fő keverésbe és az exportba nem megy; out = a kimenetpár első kimenete), from_measure / to_measure (alap: a dal hossza, de legalább 64 ütem), skip_parts (dalrészek, ahol hallgat: pl. [\"Szóló\"]). action=remove: törli. A tempó változása után hívd újra.",
     {"action": {"type": "string", "enum": ["create", "remove"]}, "sound": {"type": "string", "enum": ["magas", "mely", "fa"]},
      "volume_db": {"type": "number"}, "subdivision": {"type": "string"}, "accent": {"type": "boolean"},
      "headphones_only": {"type": "boolean"}, "out": {"type": "integer"}, "from_measure": {"type": "integer"},
      "to_measure": {"type": "integer"}, "skip_parts": {"type": "array", "items": {"type": "string"}}}),
    ("reaper_song_view", tool_reaper_song_view,
     "A „hol tartunk” kijelző egy Reaper-ablakban: nagy betűvel a mostani dalrész, hányadik ütem benne, a következő rész, a váltás előtt visszaszámlálás, alul a dal sávja a lejátszófejjel. open (width, height) / close / state (mit mutat most).",
     {"action": {"type": "string", "enum": ["open", "close", "state"]}, "width": {"type": "integer"}, "height": {"type": "integer"}}),
    ("reaper_render", tool_reaper_render,
     "Export (a teljes keverés) WAV-ba, vagy .mp3 útvonalnál mp3-ba is; az egész dal, vagy csak ütemek (from_measure, to_measure) vagy másodpercek (from, to) közt.",
     {"path": {"type": "string"}, "from_measure": {"type": "integer"}, "to_measure": {"type": "integer"},
      "from": {"type": "number"}, "to": {"type": "number"}, "timeout": {"type": "number"}}),
    ("reaper_lua", tool_reaper_lua,
     "Tetszőleges Lua-kód a Reaperben (a teljes ReaScript API: reaper.*). A kód egy függvény törzse; amit return-nel visszaad, az jön vissza JSON-ként; log(...) a naplóba ír. Minden, amit a többi Reaper-eszköz nem tud.",
     {"code": {"type": "string"}, "timeout": {"type": "number"}}),
]
def mem_wrap(fn):
    def call(args):
        try:
            return as_json(fn(args))
        except ValueError as e:
            return error(str(e))
    return call


TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in mem.TOOLS]

# ----------------------------------------------------------------------------- bekötési térkép (#323)
import muzikos_rig as rig

TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in rig.TOOLS]

# ----------------------------------------------------------------------------- dalmappák, dallista, szinkron (#346)
import muzikos_songs as songs

TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in songs.TOOLS]

import muzikos_home as home       # a zenekar kezdőlapja: minden aloldal egy helyen (#65)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in home.TOOLS]

import muzikos_concert as concert   # koncerttámogatás: sampler, setlist, koncertanyag (#362)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in concert.TOOLS]

import muzikos_takes as takes       # take-ek és összevágás (#332)
takes.reaper_call, takes.json_to_lua = reaper_call, json_to_lua
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in takes.TOOLS]

import muzikos_import as imp        # átvitel a Reaperbe: Guitar Pro-sávok, Hydrogen-dob (#327)
imp.reaper_call, imp.json_to_lua = reaper_call, json_to_lua
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in imp.TOOLS]

import muzikos_fix as fix           # felvétel javítása: MIDI és hang rácsra, ütemcsere (#326)
fix.reaper_call, fix.json_to_lua = reaper_call, json_to_lua
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in fix.TOOLS]

import muzikos_sync as sync         # a zenekar mappája a zenekar Drive-mappájával (#351)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in sync.TOOLS]

import muzikos_eszkoz as eszkoz     # fizikai teendők a valódi eszköz képén (#335)


def inline_image(path, max_px=1400):
    """A kép base64-ben a válaszba (JPEG, legfeljebb max_px; ~900 KB alatt); None, ha nem sikerült vagy nem fér be."""
    try:
        from PIL import Image
        import io
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        for q in (88, 78, 65, 50):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q)
            if buf.tell() <= 900 * 1024:
                return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass
    return None


def img_wrap(fn):
    """Mint a mem_wrap, de ha az eredményben van kép (kep), az a válasz része (a Claude beszélgetésében látszik), nem külön
    ablakban nyílik (#2). Ha a kép nem fér be, a Claude ezt mondja, és ablakban nyitja meg."""
    def call(args):
        try:
            res = fn(args)
        except ValueError as e:
            return error(str(e))
        kep = res.get("kep") if isinstance(res, dict) else None
        if kep and os.path.exists(kep):
            data = inline_image(kep)
            if data:
                return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"},
                                    {"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}
            res["figyelem"] = "A kép nem fér be a beszélgetésbe: külön ablakban nyitottam meg. Mondd el a zenésznek."
            res["megnyitva"] = eszkoz._open(kep)
        return as_json(res)
    return call


TOOLS += [(n, img_wrap(f) if n in ("mutasd", "eszkoz") else mem_wrap(f), d, p) for n, f, d, p in eszkoz.TOOLS]

import muzikos_rendszer as hangr    # hangkimaradás, wifi, Guitarix 48 kHz, késleltetés-hangolás (#381 #383 #384 #385)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in hangr.TOOLS]

import muzikos_tavproba as tav      # távpróba egy irányban: Tailscale + JackTrip, összerakás (#352)
tav.reaper_call, tav.json_to_lua = reaper_call, json_to_lua
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in tav.TOOLS]

import muzikos_bejelentes as bejel  # problémabejelentés: helyi napló, jóváhagyásos beküldés, net nélküli sor (#3)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in bejel.TOOLS]

import muzikos_fejlesztesi_naplo as fnaplo  # folyamatos fejlesztési napló: magától rögzít, naponta küld (#69)
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in fnaplo.TOOLS]

import muzikos_hangparancs as hang  # hangparancsok a felvételhez: „felvétel”, „stop”… kéz nélkül (#255)
hang.reaper_call = reaper_call
TOOLS += [(n, mem_wrap(f), d, p) for n, f, d, p in hang.TOOLS]


def reaper_song_state():
    """A mostani Reaper-projekt tempója, ütemmutatója és dalrészei, a memória alakjában."""
    t = reaper_call("return muzikos.tempo_list()")
    m = reaper_call("return muzikos.markers()")
    if not t.get("ok") or not m.get("ok"):
        return None
    marks = t["result"].get("jelolok") or []
    first = marks[0] if marks else {"bpm": t["result"]["alap"]["bpm"]}
    regs = sorted([x for x in (m["result"] or []) if x.get("tipus") == "resz"], key=lambda x: x["kezd_mp"])
    return {"tempo": round(first.get("bpm", 0), 2), "utemmutato": first.get("utemmutato"),
            "tempovaltasok": [x for x in marks[1:]],
            "szerkezet": [{"nev": r["nev"], "utem": r["veg_utem"] - r["kezd_utem"]} for r in regs]}


def gp_file_of(band, song, explicit=None):
    """A dal Guitar Pro-fájlja: a megadott, különben a dal guitarpro/ mappájának legújabbja."""
    import muzikos_gp as gpx
    if explicit:
        return explicit if os.path.exists(explicit) else None
    return gpx.newest(os.path.join(songs.song_dir(band, song), "guitarpro"))


imp.gp_file_of = gp_file_of


def tool_dal_szinkron(args):
    """A dal memóriája, a nyitott Reaper-projekt és a dal Guitar Pro-fájlja (#346): összevetés és egyeztetés."""
    import muzikos_gp as gpx
    bid = mem.find_band(args.get("band"))
    if not bid or not args.get("title"):
        return error("Kell a title (és a mostani zenekar).")
    try:
        song = mem.tool_dal({"action": "get", "title": args["title"], "band": bid})
    except ValueError as e:
        return error(str(e))
    band = mem.tool_zenekar({"action": "get", "name": bid})
    act = args.get("action", "check")
    ms = [(p.get("nev"), int(p.get("utem", 0))) for p in song.get("szerkezet", [])]

    # --- Guitar Pro ---
    gpf = gp_file_of(band, song, args.get("gp_file"))
    if act in ("from_gp", "to_gp"):
        if not gpf:
            return error("Nincs Guitar Pro-fájl a dal guitarpro/ mappájában (dalmappa sort / gp_file).")
        try:
            if act == "from_gp":
                g = gpx.read(gpf)
                data = {"tempo": g["tempo"], "utemmutato": g["utemmutato"], "tempovaltasok": g["tempovaltasok"],
                        "valtozat_neve": "a Guitar Próból való átvétel előtt"}
                if g["szerkezet"]:
                    data["szerkezet"] = g["szerkezet"]
                mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": data})
                return as_json({"atveve_a_guitar_probol": data, "fajl": gpf,
                                **({} if g["szerkezet"] else {"figyelem": "a kottában nincsenek dalrészek: a szerkezet maradt"})})
            info = gpx.write(gpf, song)
            return as_json({"a_guitar_proba_irva": {"tempo": song.get("tempo"), "utemmutato": song.get("utemmutato"),
                                                    "tempovaltasok": song.get("tempovaltasok") or [], "szerkezet": song.get("szerkezet") or []},
                            "fajl": gpf, **info})
        except ValueError as e:
            return error(str(e))
    gp_diffs, gp_note = [], None
    if gpf:
        try:
            gp_diffs = ["Guitar Pro — " + d for d in gpx.diff(song, gpx.read(gpf))]
        except ValueError as e:
            gp_note = str(e)

    # --- Reaper ---
    rs = reaper_song_state() if reaper_running() else None
    if rs is None and act in ("from_reaper", "to_reaper"):
        return error("A Reaper nem válaszol (reaper_start), vagy nincs nyitva a dal (dal_megnyitas).")
    diffs = []
    if rs is not None:
        if song.get("tempo") and abs(float(song["tempo"]) - rs["tempo"]) > 0.01:
            diffs.append(f"Reaper — tempó: a memóriában {song['tempo']}, a Reaperben {rs['tempo']}")
        if song.get("utemmutato") and rs.get("utemmutato") and song["utemmutato"] != rs["utemmutato"]:
            diffs.append(f"Reaper — ütemmutató: a memóriában {song['utemmutato']}, a Reaperben {rs['utemmutato']}")
        rp = [(p["nev"], p["utem"]) for p in rs["szerkezet"]]
        if ms and ms != rp:
            diffs.append("Reaper — szerkezet: a memóriában " + ", ".join(f"{n}({u})" for n, u in ms) +
                         " — a Reaperben " + (", ".join(f"{n}({u})" for n, u in rp) or "nincs"))
    if act == "check":
        all_d = diffs + gp_diffs
        return as_json({"dal": mem.display_title(song), "egyezik": not all_d, "elteresek": all_d,
                        "guitar_pro_fajl": gpf, **({"guitar_pro": gp_note} if gp_note else {}),
                        **({} if rs is not None else {"reaper": "nem fut, vagy nincs nyitva a dal: csak a Guitar Pro-t néztem"}),
                        "mit_tegyel": ("Kérdezd meg, melyik a jó, és aszerint: from_reaper / to_reaper, from_gp / to_gp "
                                       "(a memória a közös pont: pl. Reaper → memória → Guitar Pro).") if all_d else ""})
    if act == "from_reaper":
        data = {"tempo": rs["tempo"], "szerkezet": rs["szerkezet"], "valtozat_neve": "a Reaperből való átvétel előtt"}
        if rs.get("utemmutato"):
            data["utemmutato"] = rs["utemmutato"]
        mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": data})
        return as_json({"atveve_a_reaperbol": data, "elteresek_voltak": diffs})
    if act == "to_reaper":
        if song.get("tempo"):
            ts = parse_timesig(song.get("utemmutato"))
            tool_reaper_tempo({"action": "set", "measure": 1, "bpm": float(song["tempo"]),
                               **({"time_signature": song["utemmutato"]} if ts[0] else {})})
        parts = [{"name": n, "bars": u} for n, u in ms if n and u]
        if parts:
            tool_reaper_markers({"action": "structure", "parts": parts, "replace": True})
        return as_json({"a_reaperbe_irva": {"tempo": song.get("tempo"), "utemmutato": song.get("utemmutato"), "szerkezet": parts},
                        "elteresek_voltak": diffs})
    return error("action: check | from_reaper | to_reaper | from_gp | to_gp")


TOOLS.append(("dal_szinkron", tool_dal_szinkron,
              "A dal memóriája (tempó, ütemmutató, tempóváltások, szerkezet), a nyitott Reaper-projekt és a dal Guitar Pro-fájlja (a guitarpro/ mappa legújabbja, vagy gp_file) összevetése: check (mi tér el — a dal megnyitásakor és kézi változtatás után nézd meg, és szólj, ha van); from_reaper / to_reaper; from_gp (a Guitar Pro szerint frissíti a memóriát) / to_gp (a memória szerint írja a Guitar Pro-fájlt: .gp és .gp5; előtte mentés a guitarpro/.elozmenyek/-be). A memória a közös pont: Reaper → memória → Guitar Pro, és vissza.",
              {"action": {"type": "string", "enum": ["check", "from_reaper", "to_reaper", "from_gp", "to_gp"]},
               "title": {"type": "string"}, "band": {"type": "string"}, "gp_file": {"type": "string"}}))

# ----------------------------------------------------------------------------- export és megosztás (#333)

def render_stems(d, name):
    """Minden felvett sáv külön wav-ba (a sáv nevével), a dal elejétől a végéig; az üres és a klikksáv kimarad."""
    lua = ("if reaper.GetProjectLength(0) <= 0 then error('a dal üres, nincs mit exportálni') end\n"
           "for i = 0, reaper.CountTracks(0) - 1 do local tr = reaper.GetTrack(0, i) local _, n = reaper.GetTrackName(tr)\n"
           "  reaper.SetTrackSelected(tr, reaper.CountTrackMediaItems(tr) > 0 and n ~= 'Klikk') end\n"
           "if reaper.CountSelectedTracks(0) == 0 then return 0 end\n"   # üres renderre a Reaper ablakot nyitna
           ""
           f"reaper.RecursiveCreateDirectory({lua_str(d)}, 0)\n"
           f"reaper.GetSetProjectInfo_String(0, 'RENDER_FILE', {lua_str(d)}, true)\n"
           f"reaper.GetSetProjectInfo_String(0, 'RENDER_PATTERN', {lua_str(name + ' - $track')}, true)\n"
           "reaper.GetSetProjectInfo_String(0, 'RENDER_FORMAT', 'ZXZhdxgAAQ==', true)\n"
           "reaper.GetSetProjectInfo(0, 'RENDER_SETTINGS', 3, true)\n"   # a kijelölt sávok külön (a 2 a Reaper 7.82-ben csak a mastert adja)
           "reaper.GetSetProjectInfo(0, 'RENDER_BOUNDSFLAG', 1, true)\n"
           "reaper.GetSetProjectInfo(0, 'RENDER_SRATE', 48000, true)\n"
           "reaper.Main_OnCommand(42230, 0)\n"
           "reaper.GetSetProjectInfo(0, 'RENDER_SETTINGS', 0, true)\n"
           "return reaper.CountSelectedTracks(0)")
    return reaper_call(lua, timeout=600)


def cover_image(path, band_name, title, day):
    """Borítókép a videóhoz: sötét alap, a dal címe sárgán, a zenekar és a dátum alatta (ImageMagick)."""
    cmd = ["convert", "-size", "1280x720", "xc:#141012",
           "-fill", "#e2352b", "-draw", "rectangle 0,600 1280,612",
           "-font", "DejaVu-Sans-Bold", "-fill", "#f5c542", "-pointsize", "84", "-gravity", "center",
           "-annotate", "+0-60", title,
           "-font", "DejaVu-Sans", "-fill", "#f2ece4", "-pointsize", "40", "-annotate", "+0+50", f"{band_name} · {day}",
           path]
    code, _, err = sh(" ".join(shlex.quote(c) for c in cmd), timeout=60)
    return code == 0, err


def tool_dal_export(args):
    """A dal exportja a dal export/ mappájába dátummal: mp3 (meghallgatásra), wav (megőrzésre), kérésre sávonként
    és videóként (borítókép + mp3) a YouTube-hoz; visszaadja a fájlokat és az értesítő szövegét."""
    try:
        bid, band, song = songs.band_and_song(args)
    except ValueError as e:
        return error(str(e))
    if not song:
        return error("Kell a title: melyik dal.")
    if not reaper_running():
        return error("A Reaper nem fut. Nyisd meg a dalt: dal_megnyitas.")
    day = time.strftime("%Y-%m-%d")
    label = (args.get("label") or "").strip()
    folder = day + (" " + label if label else "")
    d = os.path.join(songs.ensure(band, song), "export", folder)
    os.makedirs(d, exist_ok=True)
    shown = mem.display_title(song)                  # kifelé a publikus cím, ha van (#365)
    base = f"{shown} - {folder}"
    fmts = args.get("formats") or ["mp3", "wav"]
    res = {"mappa": d, "fajlok": []}
    r = tool_reaper_render({"path": os.path.join(d, base + (".mp3" if "mp3" in fmts else ".wav"))})
    if r.get("isError"):
        return r
    info = json.loads(r["content"][0]["text"])
    if "mp3" in info:
        res["fajlok"].append({"tipus": "mp3 (meghallgatásra)", "fajl": info["mp3"]})
    if "wav" in fmts:
        res["fajlok"].append({"tipus": "wav 48 kHz/24 bit (megőrzésre)", "fajl": info["wav"]})
    elif os.path.exists(info["wav"]):
        os.remove(info["wav"])
    if args.get("stems"):
        sd = os.path.join(d, "savok")
        st = render_stems(sd, song["cim"])
        if not st.get("ok"):
            return reaper_result(st)
        if not st.get("result"):
            res["savok"] = "nincs felvett sáv (a klikksáv nem számít), ezért sávonként nem lett export"
        res["fajlok"] += [{"tipus": "sáv", "fajl": f} for f in sorted(glob.glob(os.path.join(sd, "*.wav")))]
    if args.get("video"):
        mp3 = info.get("mp3")
        if not mp3:
            return error("A videóhoz mp3 is kell (formats-ban legyen mp3).")
        cover = args.get("cover") or band.get("kep")
        if not cover or not os.path.exists(cover):
            cover = os.path.join(d, "borito.png")
            ok, err = cover_image(cover, band.get("nev", ""), shown, day)
            if not ok:
                return error("A borítókép nem készült el: " + err)
        mp4 = os.path.join(d, base + ".mp4")
        code, _, err = sh(f"ffmpeg -y -loglevel error -loop 1 -i {shlex.quote(cover)} -i {shlex.quote(mp3)} "
                          f"-c:v libx264 -tune stillimage -r 2 -pix_fmt yuv420p -c:a aac -b:a 256k -shortest {shlex.quote(mp4)}",
                          timeout=900)
        if code != 0:
            return error("A videó nem készült el: " + err)
        res["fajlok"].append({"tipus": "videó (YouTube-ra, nem nyilvánosan)", "fajl": mp4, "borito": cover})
    for f in res["fajlok"]:
        f["meret_MB"] = round(os.path.getsize(f["fajl"]) / 1e6, 1)
    tagok = [t for t in band.get("tagok", []) if not t.get("_torles")]
    res["tagok"] = [{k: t.get(k) for k in ("nev", "email", "telefon") if t.get(k)} for t in tagok]
    res["ertesito_vazlat"] = (f"Sziasztok! Itt a {shown} – {folder} felvétele: <LINK>\n"
                              "Hallgassátok meg, és írjátok meg, mi tetszik és mi nem.")
    res["mit_tegyel"] = ("Töltsd fel a zenekar Drive-mappájába (Zenekar/Dal/dátum), csak a tagokkal megosztva, vagy a videót "
                         "a YouTube-ra nem nyilvánosként (unlisted); a linket írd az értesítőbe, és csak jóváhagyás után küldd el. "
                         "A Google-belépést a zenekar végzi.")
    mem.tool_dal({"action": "set", "title": song["cim"], "band": bid,
                  "data": {"jegyzet": f"export: {folder} ({', '.join(f['tipus'].split(' ')[0] for f in res['fajlok'])})"}})
    return as_json(res)


TOOLS.append(("dal_export", tool_dal_export,
              "A nyitott dal exportja a zenekarnak: a dal mappájának export/<dátum> alá mp3 (256k, meghallgatásra) és wav (48 kHz/24 bit, megőrzésre); stems=true: minden sáv külön; video=true: mp4 egy borítóképpel (a zenekar képe, vagy egy elkészített) a YouTube-ra. Visszaadja a fájlokat, a tagokat és az értesítő vázlatát; a feltöltés és a küldés a következő lépés (jóváhagyással).",
              {"title": {"type": "string"}, "band": {"type": "string"},
               "label": {"type": "string", "description": "pl. „próba”, „take 3”; a mappa neve: dátum + ez"},
               "formats": {"type": "array", "items": {"type": "string", "enum": ["mp3", "wav"]}},
               "stems": {"type": "boolean"}, "video": {"type": "boolean"},
               "cover": {"type": "string", "description": "a borítókép fájlja (alap: a zenekar képe)"}}))


# ----------------------------------------------------------------------------- gitárból Guitar Pro (#319)

def tool_gitar_kotta(args):
    """Egy sáv felvételéből .gp5: hangnál hangfelismeréssel (muzikos_tab), MIDI-nél egyenesen a hangjegyekből."""
    try:
        import muzikos_tab as tab
    except ImportError as e:
        return error(f"Hiányzik a kottához kellő csomag ({e}); MuzikOS-en: sudo apt install python3-numpy, és pip PyGuitarPro.")
    if not reaper_running():
        return error("A Reaper nem fut (reaper_start), vagy nincs nyitva a dal (dal_megnyitas).")
    data = reaper_call("return muzikos.take_info(" + json_to_lua({"track": args.get("track", 1), **(
        {"item": int(args["item"])} if args.get("item") else {})}) + ")", timeout=10)
    if not data.get("ok"):
        return reaper_result(data)
    ti = data["result"]
    sav = ti.get("sav") or str(args.get("track"))
    instrument = args.get("instrument") or ("bass" if any(w in norm(sav) for w in ("basszus", "bass")) else "guitar")
    # hangolás: a kérés > a dalnál a tagé > a tag alaphangolása > a zenekaré > szabványos
    spec, honnan = args.get("tuning"), "kérés"
    if not spec:
        try:
            bid = mem.find_band(args.get("band"))
            band = mem.tool_zenekar({"action": "get", "name": bid}) if bid else {}
            tag = next((t for t in band.get("tagok", []) if any(
                w and norm(w) in norm(sav) for w in (t.get("becenev"), t.get("nev")))), {})
            song = {}
            if args.get("title") and bid:
                try:
                    song = mem.tool_dal({"action": "get", "title": args["title"], "band": bid})
                except ValueError:
                    song = {}
            sh_ = song.get("hangolas") or {}
            for k, v in (((tag.get("becenev") or "", "a dalnál"), (tag.get("nev") or "", "a dalnál"))):
                if k and isinstance(sh_, dict) and sh_.get(k):
                    spec, honnan = sh_[k], v
                    break
            if not spec and tag.get("hangolas"):
                spec, honnan = tag["hangolas"], "a tag alaphangolása"
            bh = band.get("hangolas")
            if not spec and bh:
                spec = bh.get("basszusgitár" if instrument == "bass" else "gitár") if isinstance(bh, dict) else bh
                honnan = "a zenekar alaphangolása"
        except Exception:
            spec = None
    try:
        tun = tab.parse_tuning(spec, instrument)
    except ValueError as e:
        return error(str(e))
    if not tun:
        tun, honnan = tab.TUNINGS["bass" if instrument == "bass" else "guitar"], "szabványos (nincs megadva)"
    grid = int(args.get("grid", 16))
    bpm, num, den = float(ti["bpm"]), int(ti["num"]), int(ti["den"])
    per_qn = grid / 4.0
    hints = None
    if args.get("source") in ("dudolas", "beatbox"):
        return mouth_kotta(args, ti, sav, instrument, tun, honnan, grid, bpm, num, den)
    if ti.get("midi") is not None:
        notes = sorted(([int(round(n["s"] * per_qn)), max(1, int(round((n["e"] - n["s"]) * per_qn))), int(n["p"]),
                         min(1.0, n["v"] / 127.0)] for n in ti["midi"]), key=lambda n: n[0])
        q = []
        for n in notes:                                # egyszólamú: egy helyen egy hang (a legmagasabb)
            if q and q[-1][0] == n[0]:
                q[-1] = max(q[-1], n, key=lambda x: x[2])
            else:
                q.append(n)
        for a, b in zip(q, q[1:]):
            a[1] = max(1, min(a[1], b[0] - a[0]))
        if args.get("midi_string_channels"):          # MIDI-hangszedő húronkénti csatornával: 1. csatorna = 1. húr
            by_start = {int(round(n["s"] * per_qn)): n["c"] for n in ti["midi"]}
            hints = [by_start.get(n[0]) if by_start.get(n[0], 99) <= len(tun) else None for n in q]
        forras, nyers = "MIDI", len(ti["midi"])
    else:
        f = ti.get("file") or ""
        if not os.path.exists(f):
            return error(f"Nem találom a felvétel fájlját: {f}")
        qn0, offs, rate = float(ti["qn"]), float(ti["offs"]), float(ti["rate"] or 1.0)
        end_src = offs + float(ti["len"]) * rate

        def qn_of(t):
            return qn0 + (t - offs) / rate * bpm / 60.0

        # több elemre vágott sáv: ha nincs kért item, az ÖSSZES elem kottázódik, nem csak az utolsó (#50)
        elemek = None
        if not args.get("item") and int(ti.get("felvetelek") or 1) > 1:
            lst = reaper_call("return muzikos.audio_items(" + json_to_lua({"track": args.get("track", 1)}) + ")", timeout=10)
            if lst.get("ok") and lst.get("result"):
                elemek = [e for e in lst["result"] if os.path.exists(e.get("file") or "")]
                if len(elemek) < 2:
                    elemek = None
        mode = args.get("mode", "auto")
        poly = None
        if mode in ("auto", "poly"):
            import muzikos_poly
            if muzikos_poly.available():
                poly = muzikos_poly
            elif mode == "poly":
                return error("A többszólamú felismeréshez kell az onnxruntime és a basic-pitch modell (nmp.onnx); "
                             "nincs a gépen. mode=mono az egyszólamúval megy.")
        if poly:
            raw = [n for n in poly.transcribe(f, min_midi=min(tun), max_midi=max(tun) + 24)
                   if offs - 0.05 <= n[0] < end_src]
            q = tab.quantize_poly(raw, qn_of, grid, max_voices=len(tun))
            forras = "hang, többszólamú (basic-pitch)"
        else:
            fmin = 30.0 if instrument == "bass" else 65.0
            bar_s = 240.0 / bpm * num / den                      # egy ütem hossza másodpercben
            min_gap = max(0.0, float(args["min_hangkoz_ms"]) / 1000.0) if args.get("min_hangkoz_ms") else (
                bar_s / 8 * 0.85 if args.get("egyszeru_riff") else 0.0)
            q, raw, rep, tartomany = [], [], {}, []
            for e in (elemek or [{"qn": qn0, "offs": offs, "rate": rate, "len": ti["len"], "file": f}]):
                e_qn0, e_offs, e_rate = float(e["qn"]), float(e["offs"]), float(e.get("rate") or 1.0)
                e_end = e_offs + float(e["len"]) * e_rate
                x, sr = tab.read_audio(e["file"])
                times, f0, db, flux = tab.pitch_track(x, sr, fmin=fmin)
                if args.get("onset") == "flux":
                    part = tab.notes_from_pitch(times, f0, db, flux)
                else:                                       # alap: a burkoló ugrása, a rács egységénél sűrűbb hangot nem enged
                    part = tab.notes_from_envelope(x, sr, times, f0, db, gap=0.85 * 60.0 / bpm * 4.0 / grid)
                part = [n for n in part if e_offs - 0.05 <= n[0] < e_end]
                part, r_ = tab.clean_notes(part, tun, int(args.get("max_fret", 20)), min_gap=min_gap)
                for k_, v_ in r_.items():
                    rep[k_] = rep.get(k_, 0) + v_
                if part:
                    tartomany.append((min(n[0] for n in part), max(n[1] for n in part)))
                raw += part
                q += tab.quantize(part, lambda t, a=e_qn0, b=e_offs, c=e_rate: a + (t - b) / c * bpm / 60.0, grid)
            q.sort(key=lambda n: n[0])
            dd = []
            for n_ in q:                                    # két elem találkozásánál ne kezdődjön két hang egy helyen
                if dd and dd[-1][0] == n_[0]:
                    if n_[1] > dd[-1][1]:
                        dd[-1] = n_
                    continue
                dd.append(n_)
            q = dd
            for a_, b_ in zip(q, q[1:]):
                a_[1] = max(1, min(a_[1], b_[0] - a_[0]))
            forras = "hang, egyszólamú" + (f" ({len(elemek)} elem)" if elemek else "")
            tisztitas = {"hangok_a_felvetelen": sum(rep.values()) + len(raw), **rep,
                         "feldolgozott_idotartomany_mp": [round(min(a for a, _ in tartomany), 1), round(max(b for _, b in tartomany), 1)] if tartomany else None}
        nyers = len(raw)
    if not q:
        return error("Nem találtam hangjegyet a felvételen. Tiszta (effekt nélküli) gitárjel kell, és egyszerre egy hang.")
    if q and isinstance(q[0][2], list):          # többszólamú: akkordonként a fogás
        cf = tab.fret_chords([n[2] for n in q], tun, int(args.get("max_fret", 20)))
        frets = [c[0] if len(c) == 1 else c for c in cf]
    else:
        frets = tab.fret_notes([n[2] for n in q], tun, int(args.get("max_fret", 20)), hints)
    # hova: a dal guitarpro/ mappájába, ha a dal ismert; különben a projekt mellé
    title, folder = args.get("title"), None
    if title:
        try:
            bid, band, song = songs.band_and_song({"title": title, "band": args.get("band")})
            folder = os.path.join(songs.ensure(band, song), "guitarpro")
            title = song["cim"]
        except ValueError:
            folder = None
    if not folder:
        st = reaper_call("return muzikos.status().projekt", timeout=3).get("result") or ""
        folder = os.path.dirname(st) if st and os.path.isabs(st) else os.path.expanduser("~/MuzikOS/Kotta")
        title = title or (os.path.splitext(os.path.basename(st))[0] if st and os.path.isabs(st) else "Kotta")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{title} - {sav} - {time.strftime('%Y-%m-%d %H%M%S')}.gp5")   # másodperccel: két futtatás nem írja felül egymást
    eltolas = None
    if args.get("elso_hangtol") and q and not (q and isinstance(q[0][2], list)):
        bar_units_ = num * grid // den
        eltolas = (q[0][0] // bar_units_) * bar_units_       # az első hang ütemének elejétől induljon a kotta
        for n_ in q:
            n_[0] -= eltolas
    info = tab.write_gp5(path, q, frets, tun, bpm, num, den, grid, title=title, track_name=sav,
                         instrument=33 if instrument == "bass" else 27)
    bar_units = num * grid // den
    def show(n, f):
        sf = [f] if isinstance(f, tuple) else f
        return " + ".join(f"{tab.note_name(tun[s - 1] + fr)} ({s}. húr {fr}. bund)" for s, fr in sf) + \
            f" — {n[0] // bar_units + 1}. ütem"
    elso = [show(n, f) for n, f in zip(q[:12], frets[:12])]
    res = {"fajl": path, "forras": forras, "sav": sav, "hangszer": "basszusgitár" if instrument == "bass" else "gitár",
           "hangolas": " ".join(tab.note_name(m) for m in reversed(tun)), "hangolas_honnan": honnan, "tempo": bpm, "utemmutato": f"{num}/{den}",
           "felismert_hangok": nyers, "kottaban": len(q), **info, "elso_hangok": elso,
           **({"tisztitas": tisztitas} if 'tisztitas' in locals() else {}),
           **({"eltolas_utem": eltolas // (num * grid // den), "eltolas_megjegyzes": "A kotta az első hang ütemétől indul; a Reaperben ennyi ütemmel később kezdődik a játék."} if eltolas else {}),
           "mit_tegyel": "Mondd el röviden, mi lett (hány ütem, hány hang, az eleje), és kérdezd meg, megnyissa-e a "
                         "TuxGuitarban (open: true). Ha sok a hiba: tisztább jel (effekt nélkül, DI), lassabb tempó, "
                         "vagy grid=8 a nyolcadoknál."}
    if args.get("open"):
        binary = shutil.which("tuxguitar") or shutil.which("tuxguitar-gtk")
        if binary:
            env = dict(os.environ)
            env.setdefault("DISPLAY", ":0")
            subprocess.Popen([binary, path], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            res["megnyitva"] = "TuxGuitar"
        else:
            res["megnyitva"] = "nincs TuxGuitar a gépen"
    return as_json(res)


def _kotta_folder(args):
    """Hova menjen a kotta: a dal guitarpro/ mappájába, ha a dal ismert; különben a Reaper-projekt mellé."""
    title, folder = args.get("title"), None
    if title:
        try:
            bid, band, song = songs.band_and_song({"title": title, "band": args.get("band")})
            folder = os.path.join(songs.ensure(band, song), "guitarpro")
            title = song["cim"]
        except ValueError:
            folder = None
    if not folder:
        st = reaper_call("return muzikos.status().projekt", timeout=3).get("result") or ""
        folder = os.path.dirname(st) if st and os.path.isabs(st) else os.path.expanduser("~/MuzikOS/Kotta")
        title = title or (os.path.splitext(os.path.basename(st))[0] if st and os.path.isabs(st) else "Kotta")
    os.makedirs(folder, exist_ok=True)
    return folder, title


def mouth_kotta(args, ti, sav, instrument, tun, honnan, grid, bpm, num, den):
    """Szájjal felvett téma (#375): dúdolásból gitár-/basszussáv, beatboxból dobsáv (.gp5, kérésre a Reaperbe is)."""
    import muzikos_tab as tab
    import muzikos_mouth as mouth
    f = ti.get("file") or ""
    if ti.get("midi") is not None or not os.path.exists(f):
        return error("A dúdoláshoz és a beatboxhoz hangfelvétel kell (mikrofonsáv), nem MIDI-sáv.")
    qn0, offs, rate = float(ti["qn"]), float(ti["offs"]), float(ti["rate"] or 1.0)
    end_src = offs + float(ti["len"]) * rate
    x, sr = tab.read_audio(f)
    per_qn = grid / 4.0
    bar_units = num * grid // den
    state = {"qn0": qn0, "t0": offs, "bpm": bpm}

    def qn_of(t):
        return state["qn0"] + (t - state["t0"]) / rate * state["bpm"] / 60.0

    if args["source"] == "dudolas":
        raw = [n for n in mouth.hum_notes(x, sr) if offs - 0.05 <= n[0] < end_src]
        raw, shift = mouth.fit_range(raw, tun)
        if not raw:
            return error("Nem találtam dallamot: tisztán, egyenletesen dúdolj vagy énekelj, egy hangot egyszerre.")
        q = tab.quantize(raw, qn_of, grid)
        frets = tab.fret_notes([n[2] for n in q], tun, int(args.get("max_fret", 20)))
        folder, title = _kotta_folder(args)
        path = os.path.join(folder, f"{title} - dúdolás ({'basszus' if instrument == 'bass' else 'gitár'}) - "
                                    f"{time.strftime('%Y-%m-%d %H%M')}.gp5")
        info = tab.write_gp5(path, q, frets, tun, bpm, num, den, grid, title=title,
                             track_name="Basszus (dúdolásból)" if instrument == "bass" else "Gitár (dúdolásból)",
                             instrument=33 if instrument == "bass" else 27)
        hint = (f", és hogy {abs(shift) // 12} oktávval {'feljebb' if shift > 0 else 'lejjebb'} tetted a hangszer "
                "fekvésébe") if shift else ""
        res = {"fajl": path, "forras": "dúdolás", "hangszer": "basszusgitár" if instrument == "bass" else "gitár",
               "hangolas": " ".join(tab.note_name(m) for m in reversed(tun)), "hangolas_honnan": honnan, "tempo": bpm,
               "oktav_eltolas": shift // 12, "felismert_hangok": len(raw), "kottaban": len(q), **info,
               "elso_hangok": [f"{tab.note_name(tun[s - 1] + fr)} ({s}. húr {fr}. bund) — {n[0] // bar_units + 1}. ütem"
                               for n, (s, fr) in zip(q[:12], frets[:12])],
               "mit_tegyel": f"Mondd el, mi lett (hány ütem, hány hang, az eleje{hint}), és kérdezd meg, megnyissa-e "
                             "a TuxGuitarban (open: true)."}
    else:
        found = [h for h in mouth.beatbox_hits(x, sr) if offs - 0.05 <= h[0] < end_src]
        if not found:
            return error("Nem találtam ütést a felvételen: hangosabban, a mikrofonhoz közel.")
        fixes = {int(k): str(v).lower() for k, v in (args.get("javitas") or {}).items()}
        hits = []
        for i, (t, m, sure, _) in enumerate(found):
            if (i + 1) in fixes and fixes[i + 1] in mouth.BY_NAME:
                m, sure = mouth.BY_NAME[fixes[i + 1]], 1.0
            hits.append((t, m, sure))
        estimated = None
        if args.get("tempo") == "becsul":
            estimated = mouth.estimate_bpm([t for t, _, _ in hits])
            if estimated:                             # metronóm nélkül: az első ütés az 1. ütem eleje
                bpm = estimated
                state.update(qn0=0.0, t0=offs + (hits[0][0] - offs), bpm=bpm)
        pos = {}
        for t, m, sure in hits:
            pos.setdefault(int(round(qn_of(t) * per_qn)), set()).add(m)
        keys = sorted(pos)
        q = []
        for i, k in enumerate(keys):
            ms = sorted(pos[k])
            ln = (keys[i + 1] - k) if i + 1 < len(keys) else bar_units - k % bar_units   # az utolsó az ütem végéig
            q.append([k, max(1, min(ln, int(per_qn))), ms if len(ms) > 1 else ms[0], 0.8])
        frets = [[(j + 1, m) for j, m in enumerate(n[2])] if isinstance(n[2], list) else (1, n[2]) for n in q]
        folder, title = _kotta_folder(args)
        path = os.path.join(folder, f"{title} - beatbox - {time.strftime('%Y-%m-%d %H%M')}.gp5")
        info = tab.write_gp5(path, q, frets, [0] * 6, bpm, num, den, grid, title=title,
                             track_name="Dob (beatboxból)", drums=True)
        first = info["elso_utem_a_dalban"] - 1
        table = []
        for i, (t, m, sure) in enumerate(hits):
            b, r = divmod(int(round(qn_of(t) * per_qn)) - first * bar_units, bar_units)
            beat, sub = divmod(r * 4, grid)
            table.append({"sorszam": i + 1, "hely": f"{b + 1}. ütem {beat + 1}. ütés" + (f" +{sub}/{grid}" if sub else ""),
                          "dob": mouth.NAMES.get(m, str(m)), "biztos": sure})
        unsure = [r for r in table if r["biztos"] < 0.5]
        ask = (" A bizonytalanokat kérdezd meg a sorszámukkal („a 7. ütés lábdob vagy tam?”), és a válasszal futtasd "
               "újra: javitas = {\"7\": \"tam\"}.") if unsure else ""
        res = {"fajl": path, "forras": "beatbox", "tempo": bpm, **({"tempo_becsult": True} if estimated else {}),
               "utesek": len(hits), "kottaban": len(q), **info, "utesek_tablaja": table[:64],
               "dobok": {mouth.NAMES.get(m, str(m)): sum(1 for _, mm, _ in hits if mm == m) for m in sorted({m for _, m, _ in hits})},
               "mit_tegyel": "Mondd el, mi lett (hány ütem, melyik dobból hány)." + ask +
                             " Kérésre a Reaperbe is (reaper: true), az AVL-dobkészlettel."}
        if unsure:
            res["bizonytalan"] = unsure
        if args.get("reaper"):
            flat = []
            for n in q:
                for m in (n[2] if isinstance(n[2], list) else [n[2]]):
                    flat += [round(n[0] / per_qn, 6), round(0.9 / per_qn, 6), int(m), 100]
            d = reaper_call("return muzikos.import_notes(" + json_to_lua(
                {"name": f"{sav} – dob (beatboxból)", "drums": True, "at_measure": 1,
                 "len_qn": round((q[-1][0] + q[-1][1]) / per_qn, 6), "notes": flat}) + ")", timeout=30)
            res["reaper"] = d.get("result") if d.get("ok") else ("nem sikerült: " + str(d.get("error")))
    if args.get("open"):
        binary = shutil.which("tuxguitar") or shutil.which("tuxguitar-gtk")
        if binary:
            env = dict(os.environ)
            env.setdefault("DISPLAY", ":0")
            subprocess.Popen([binary, res["fajl"]], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            res["megnyitva"] = "TuxGuitar"
    return as_json(res)


TOOLS.append(("gitar_kotta", tool_gitar_kotta,
              "Gitár- vagy basszusfelvételből (vagy source-szal dúdolásból, beatboxból) Guitar Pro-kotta (.gp5, tabbal): egy sáv felvétele (több elemre vágott sávnál az összes elem; item = egy adott sorszám) → hangfelismerés (zajkapu a játék szintjéhez, hangtartomány a hangolásból, oktávkiugrók és szellemhangok tisztítva; a válasz megmondja, mit dobott el) (egyszólamú, tiszta jel, metronómra) vagy MIDI-sávnál egyenesen a hangjegyek → ritmus a dal tempója szerint (grid: 16 = tizenhatod, 8 = nyolcad) → húr és bund a legkisebb kézmozgással. title = a dal: a dal guitarpro/ mappájába ment; open = megnyitja a TuxGuitarban.",
              {"track": {"type": "string", "description": "a sáv neve vagy sorszáma"}, "item": {"type": "integer"},
               "title": {"type": "string"}, "band": {"type": "string"},
               "instrument": {"type": "string", "enum": ["guitar", "bass"]},
               "tuning": {"type": "string", "description": "név (guitar, d, drop d, drop c, bass, bass5, d bass5) vagy hangnevek mélyről felfelé („D G C F A D”); alap: a dalnál a tagé, a tag vagy a zenekar alaphangolása"},
               "grid": {"type": "integer", "enum": [8, 16, 32]}, "max_fret": {"type": "integer"},
               "midi_string_channels": {"type": "boolean", "description": "MIDI-hangszedő húronkénti csatornával"},
               "mode": {"type": "string", "enum": ["auto", "mono", "poly"],
                        "description": "auto: többszólamú (basic-pitch), ha a gépen van, különben egyszólamú; mono: riffhez, tiszta jelre"},
               "source": {"type": "string", "enum": ["hangszer", "dudolas", "beatbox"],
                          "description": "hangszer (alap); dudolas: dúdolt/énekelt dallamból gitár- vagy basszussáv (a hangszer fekvésébe téve); beatbox: szájdobból dobsáv (lábdob, pergő, lábcin)"},
               "javitas": {"type": "object", "description": "beatbox: ütés sorszáma → dob (\"7\": \"tam\"), ha a felismerés tévedett"},
               "tempo": {"type": "string", "enum": ["projekt", "becsul"], "description": "beatbox: becsul = metronóm nélkül vett fel, a tempót a ritmusból becsüli"},
               "reaper": {"type": "boolean", "description": "beatbox: a dobsáv a Reaperbe is, AVL-dobkészlettel"},
               "onset": {"type": "string", "enum": ["burkolo", "flux"], "description": "hangkezdet-felismerés: burkolo (alap: a hangerő ugrása, torzított és lecsengő jelre is jó) vagy flux (spektrális változás)"},
               "egyszeru_riff": {"type": "boolean", "description": "egyszerű riff: két hang közt legalább az ütem nyolcadának 85%-a (szellemhangok ellen)"},
               "min_hangkoz_ms": {"type": "integer", "description": "két hang közti minimális hangköz ms-ban (felülírja az egyszeru_riff-et)"},
               "elso_hangtol": {"type": "boolean", "description": "a kotta az első hang ütemétől induljon (az eltolást megmondja)"},
               "open": {"type": "boolean"}}))



def tool_camera_snapshot(args):
    """Fotó a kamerából: a képet TE nézed meg (pl. a potiállásokhoz), és a fájl is megmarad."""
    try:
        path = rig.camera_snapshot(args)
    except ValueError as e:
        return error(str(e))
    send = path
    if have("convert"):
        small = path[:-4] + "-kicsi.jpg"
        if sh(f"convert {shlex.quote(path)} -resize '1280x1280>' -quality 85 {shlex.quote(small)}")[0] == 0:
            send = small
    with open(send, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"},
                        {"type": "text", "text": f"A fotó: {path}. Potiálláshoz olvasd le a potikat és a kapcsolókat, és mentsd: potiallas action=save, foto={path}."}]}


def tool_foto_megnezes(args):
    """Egy kép megmutatása neked (a fotóládából vagy bárhonnan): a legújabb beérkezett, vagy a megadott fájl."""
    path = args.get("path")
    if not path:
        files = sorted(glob.glob(os.path.join(rig.inbox_dir(), "*")), key=os.path.getmtime, reverse=True)
        if not files:
            return error("Még nem jött kép a fotóládába (fotolada action=open).")
        path = files[0]
    if not os.path.exists(path):
        return error(f"Nincs ilyen kép: {path}")
    small = os.path.join(tempfile.gettempdir(), f"muzikos-foto-{uuid.uuid4().hex}.jpg")
    # a telefon képe nagy (és HEIC lehet): JPEG-re, legfeljebb 1600 px
    if have("convert") and sh(f"convert {shlex.quote(path)}[0] -auto-orient -resize '1600x1600>' -quality 85 {shlex.quote(small)}")[0] == 0:
        send, mime = small, "image/jpeg"
    else:
        send, mime = path, "image/png" if path.lower().endswith(".png") else "image/jpeg"
    with open(send, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    if send == small:
        os.remove(small)
    return {"content": [{"type": "image", "data": data, "mimeType": mime},
                        {"type": "text", "text": f"A kép: {path}. Potiálláshoz: potiallas action=save, foto={path}."}]}


TOOLS.append(("foto_megnezes", tool_foto_megnezes,
              "Egy kép megmutatása neked: path nélkül a fotóládába legutóbb érkezett (pl. egy eszköz előlapja a telefonról), vagy a megadott fájl. Ebből olvasod le a potiállásokat.",
              {"path": {"type": "string"}}))
TOOLS.append(("camera_snapshot", tool_camera_snapshot,
              "Fotó a laptop (vagy egy USB-s) kamerájából — pl. egy eszköz előlapjáról, a potiállások leolvasásához. A kép a válaszban, és fájlban a MuzikOS/Tudas/fotok alatt.",
              {"device": {"type": "string", "description": "alap: /dev/video0"}, "size": {"type": "string", "description": "alap: 1280x720"}}))
TOOLS.append(("dal_megnyitas", tool_dal_megnyitas,
              "Egy dal a memóriából: megnyitja a Reaper-projektjét (vagy létrehozza a zenekar mappájában: Zenekarok/<zenekar>/Dalok/<dal>), új projektnél beállítja a tempót, és ha még nincsenek dalrészek, a memóriában tárolt szerkezetből lerakja őket. Visszaadja, melyik tag melyik sáv/bemenet, és a dal friss jegyzeteit.",
              {"title": {"type": "string"}, "band": {"type": "string"}, "create": {"type": "boolean"},
               "tempo_from_memory": {"type": "boolean"},
               "replace_structure": {"type": "boolean", "description": "a Reaper dalrészeit a memória szerkezetére cseréli (dalírás után)"}}))
TOOL_MAP = {name: fn for name, fn, _, _ in TOOLS}


def tool_list():
    out = []
    for name, _, desc, props in TOOLS:
        required = [k for k in ("command", "code", "x", "y") if k in props and name in ("run_command", "reaper_lua", "mouse")]
        out.append({"name": name, "description": desc,
                    "inputSchema": {"type": "object", "properties": props, **({"required": required} if required else {})}})
    return out


# ----------------------------------------------------------------------------- JSON-RPC

def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return {"protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": "A MuzikOS zenei gép eszközei: hang (audio_devices, input_levels, set_latency, xrun_check), rendszer (system_status, run_command), képernyő (screenshot, mouse, keyboard) és Reaper (reaper_*). A részletes munkarend a muzikos, muzikos-audio és muzikos-reaper skillben."}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        params = msg.get("params") or {}
        fn = TOOL_MAP.get(params.get("name"))
        if not fn:
            return error(f"Ismeretlen eszköz: {params.get('name')}")
        try:
            return fn(params.get("arguments") or {})
        except Exception as e:  # az eszköz hibája ne vigye el a szervert
            return error(f"{type(e).__name__}: {e}")
    if method == "ping":
        return {}
    if mid is not None:
        raise LookupError(method)
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = msg.get("id")
        try:
            result = handle(msg)
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid, "result": result})
        except LookupError:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Ismeretlen metódus: {msg.get('method')}"}})
        except Exception as e:
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    if "--net-jelzo" in sys.argv:                 # a panel jelzője (genmon, #67): nincs net esetén szól, különben üres
        ok = subprocess.run(["nmcli", "-t", "-g", "CONNECTIVITY", "networking", "connectivity"], capture_output=True, text=True).stdout.strip()             in ("full", "limited", "portal") if shutil.which("nmcli") else True
        print("" if ok else "<txt>⚠ nincs net</txt><tool>Net nélkül a Claude nem működik; a felvétel, a Reaper és az oldalak igen. Ha visszajön, a szinkron magától lefut.</tool>")
    elif "--zenekar-jelzo" in sys.argv:             # a panel jelzője (genmon, #63): az aktív zenekar neve
        try:
            bid = mem.active()
            band = mem.tool_zenekar({"action": "get", "name": bid}) if bid else None
            nev = (band or {}).get("nev") or bid
        except Exception:
            nev = None
        click = "python3 " + os.path.abspath(__file__) + " --kezdolap-megnyit"
        print(f"<txt>♪ {nev}</txt><tool>Az aktív zenekar. Kattintásra a kezdőlapja nyílik.</tool><txtclick>{click}</txtclick>" if nev
              else "<txt>♪ nincs zenekar</txt><tool>Nincs aktív zenekar: kérd a Claude-ot, hogy aktiválja a zenekart.</tool>")
    elif "--kezdolap-megnyit" in sys.argv:
        try:
            print(home.open_home())
        except ValueError as e:                   # nincs mostani zenekar: nincs mit megnyitni
            print(e, file=sys.stderr)
    elif "--reaper-mentetlen" in sys.argv:
        print(chr(10).join(reaper_dirty()))
    elif "--hangut-figyelo" in sys.argv:
        hangut_figyelo()
    elif "--hangparancs-figyelo" in sys.argv:
        hang.figyelo()
    elif "--hangut-rendez" in sys.argv:
        print(json.dumps(hangut_rendez(), ensure_ascii=False))
    else:
        main()
