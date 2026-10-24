"""Távpróba egy irányban (#352): aki otthon játszik, a saját MuzikOS-én klikkre és kísérőre játszik (a dal
Reaper-projektje: a korábbi felvételek, vagy a Guitar Próból behozott sávok), a terem élő hangját nem hallja; a terem
őt hallja, fix késéssel, és hozzá igazodik. A felvétel után a Claude összerakja: az otthoni, teljes minőségű felvétel a
helyére kerül, a terem sávjai a klikk rácsára tolódnak.

    hálózat: Tailscale (a két gép egy privát hálózaton, routerbe nyúlás nélkül; a belépés a zenészé), a hang JackTrip-
             pel (tömörítetlen, fix pufferrel: a késés nem ugrál). Az otthoni gép két csatornát küld: a hangszert és a
             saját klikkjét — így a terem pontosan azt hallja, amihez az otthoni játszik.
    otthon:  a hangszer és a klikk sávja egy-egy Reaper-kimenetre küld, onnan a JackTrip-be; a felvétel helyben, a
             projekt elejétől.
    terem:   a JackTrip két csatornája két új, monitorozott Reaper-sávra („<név> (hálózat)”, „Klikk (hálózat)”):
             ezt hallják, és ezt is felveszik — az összerakás ebből méri a késést.
    összerakás: az otthoni felvétel és a hálózati másolat összevetése (keresztkorreláció) a dal elején és végén: a
             késés ezredmásodpercre, és a két hangkártya órájának eltérése is; az otthoni felvétel új sávra, a
             hálózati sávok némítva, és minden úgy tolódik, hogy az otthoni felvétel ott legyen, ahol otthon felvették
             (a klikk rácsán).
"""
import json
import os
import re
import shutil
import subprocess
import time

import muzikos_memory as mem

reaper_call = None          # a szerver adja (ugyanaz a híd és zár)
json_to_lua = None
CLIENT = "muzikos-tav"      # a JackTrip JACK-neve: muzikos-tav:send_1, receive_1 …
STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "muzikos-tavproba.json")


def _call(lua, timeout=30):
    d = reaper_call(lua, timeout=timeout)
    if not d.get("ok"):
        raise ValueError(d.get("error") or "A Reaper nem válaszol.")
    return d.get("result")


def sh(cmd, timeout=30):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


# ----------------------------------------------------------------------------- hálózat: Tailscale

def ts_status():
    if not shutil.which("tailscale"):
        raise ValueError("Nincs Tailscale a gépen (a MuzikOS-képben benne van; máshol: tailscale.com/download).")
    code, out, err = sh(["tailscale", "status", "--json"])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"BackendState": "NoState", "hiba": (err or out).strip()[:300]}


def peers(st):
    out = []
    for p in (st.get("Peer") or {}).values():
        out.append({"nev": p.get("HostName"), "ip": (p.get("TailscaleIPs") or [None])[0], "online": bool(p.get("Online")),
                    "rendszer": p.get("OS")})
    return sorted(out, key=lambda p: (not p["online"], p["nev"] or ""))


def login():
    """Belépés: a tailscale up kiírja a belépési címet; a böngészőben a zenész lép be (a Claude nem)."""
    user = os.environ.get("USER") or "zenesz"
    host = "muzikos-" + mem.slug(os.uname().nodename if hasattr(os, "uname") else "gep")
    p = subprocess.Popen(["sudo", "-n", "tailscale", "up", f"--operator={user}", f"--hostname={host}"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    url, t0 = None, time.time()
    while time.time() - t0 < 25:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        m = re.search(r"https://login\.tailscale\.com/\S+", line)
        if m:
            url = m.group(0)
            break
    if url:
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        subprocess.Popen(["xdg-open", url], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return url


# ----------------------------------------------------------------------------- hálózat: JackTrip és a portok

def pw(direction):
    code, out, _ = sh(f"pw-link -{direction}")
    return [x.strip() for x in out.splitlines() if x.strip()]


def linked():
    """A már összekötött portok (pw-link -l)."""
    code, out, _ = sh("pw-link -l")
    used = set()
    for ln in out.splitlines():
        s = ln.strip().lstrip("|<->").strip()
        if s:
            used.add(s)
    return used


def port_no(p):
    m = re.search(r"(\d+)$", p)
    return int(m.group(1)) if m else 0


def free_reaper(kind, n=2):
    """A REAPER legmagasabb sorszámú, szabad (be nem kötött) in/out portjai: a hangkártya az alsókat használja."""
    ports = [p for p in (pw("i") if kind == "in" else pw("o")) if p.startswith(f"REAPER:{kind}")]
    used = linked()
    free = sorted([p for p in ports if p not in used], key=port_no)
    if len(free) < n:
        raise ValueError(f"Nincs elég szabad Reaper-{'bemenet' if kind == 'in' else 'kimenet'} a hálózati hangnak "
                         f"({len(free)} szabad, {n} kell). A Reaper hangbeállításában több JACK-csatorna kell.")
    return free[-n:]


def wait_ports(pattern, kind, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        ps = sorted([p for p in pw(kind) if p.startswith(f"{CLIENT}:{pattern}")], key=port_no)
        if len(ps) >= 2:
            return ps
        time.sleep(1)
    return []


def jacktrip_running():
    st = mem.read_json(STATE, {})
    pid = st.get("pid")
    if pid and os.path.exists(f"/proc/{pid}"):
        return st
    return None


def start_jacktrip(role, peer_ip, queue):
    if not shutil.which("jacktrip"):
        raise ValueError("Nincs JackTrip a gépen (a MuzikOS-képben benne van; máshol: sudo apt install jacktrip).")
    if jacktrip_running():
        return mem.read_json(STATE, {})
    base = ["pw-jack"] if shutil.which("pw-jack") else []
    cmd = base + ["jacktrip", "-s" if role == "terem" else "-c", *([] if role == "terem" else [peer_ip]),
                  "-n", "2", "-q", str(queue), "-J", CLIENT, "-z"]
    log = STATE[:-5] + ".log"
    with open(log, "w") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    st = {"pid": p.pid, "szerep": role, "tars": peer_ip, "puffer": queue, "parancs": " ".join(cmd), "naplo": log,
          "indult": mem.now()}
    mem.write_json(STATE, st)
    return st


def quantum():
    code, out, _ = sh("pw-metadata -n settings 0 clock.force-quantum; pw-metadata -n settings 0 clock.quantum")
    q = [int(x) for x in re.findall(r"value:'(\d+)'", out) if int(x) > 0]
    code, out2, _ = sh("pw-metadata -n settings 0 clock.rate")
    r = [int(x) for x in re.findall(r"value:'(\d+)'", out2) if int(x) > 0]
    return (q[0] if q else 256), (r[0] if r else 48000)


def tool_tavproba(args):
    act = args.get("action", "halozat")
    if act in ("halozat", "belepes"):
        st = ts_status()
        if st.get("BackendState") != "Running":
            if act != "belepes":
                return {"bejelentkezve": False, "allapot": st.get("BackendState"),
                        "mit_tegyel": "A gép még nincs a Tailscale-hálózaton: tavproba action=belepes (a böngészőben a "
                                      "zenész lép be; mindkét gépen ugyanazzal a fiókkal, vagy a fiók meghívja a másikat)."}
            url = login()
            return {"belepes": url or "nem jött belépési cím", "mit_tegyel":
                    "Szólj: a böngészőben megnyílt a Tailscale-belépés, lépjen be (a jelszót ő írja be, nem te). Utána "
                    "tavproba action=halozat."}
        me = st.get("Self") or {}
        return {"bejelentkezve": True, "ez_a_gep": me.get("HostName"), "ip": (me.get("TailscaleIPs") or [None])[0],
                "gepek": peers(st), "jacktrip": bool(jacktrip_running())}

    if act == "inditas":
        role = args.get("szerep")
        if role not in ("terem", "otthon"):
            raise ValueError("Kell a szerep: terem (őt hallják) vagy otthon (aki otthon játszik).")
        ip = None
        if role == "otthon":
            want = mem.slug(args.get("gep") or "")
            st = ts_status()
            cands = [p for p in peers(st) if p["online"] and (not want or want in mem.slug(p["nev"] or "") or p["ip"] == args.get("gep"))]
            if not cands:
                raise ValueError("Nem látom a termi gépet a Tailscale-hálózaton (online). tavproba action=halozat")
            ip = cands[0]["ip"]
        jt = start_jacktrip(role, ip, int(args.get("puffer") or 16))
        res = {"jacktrip": jt}
        # bekötés: a terem a fogadott két csatornát két új, monitorozott sávra; az otthoni a hangszert és a klikket küldi
        if role == "terem":
            rec = wait_ports("receive_", "o", int(args.get("varakozas") or 60))
            if not rec:
                res["mit_tegyel"] = ("A termi gép vár az otthonira: indítsd el ott is (szerep: otthon), aztán "
                                     "tavproba action=bekotes szerep=terem.")
                return res
        res["bekotes"] = tool_tavproba({**args, "action": "bekotes"})
        return res

    if act == "bekotes":
        role = args.get("szerep") or (mem.read_json(STATE, {}).get("szerep"))
        name = args.get("nev") or "Otthonról"
        if role == "terem":
            rec = wait_ports("receive_", "o", 10)
            if not rec:
                raise ValueError("Még nincs kapcsolat: a JackTrip nem fogad hangot (fut az otthoni gépen is?).")
            ins = free_reaper("in")
            for src, dst in zip(rec[:2], ins):
                sh(f"pw-link '{src}' '{dst}'")
            made = _call("return muzikos.tav_route(" + json_to_lua({"inputs": [
                {"name": f"{name} (hálózat)", "in_ch": port_no(ins[0]) - 1},
                {"name": "Klikk (hálózat)", "in_ch": port_no(ins[1]) - 1}]}) + ")")
            return {"szerep": "terem", "sajat_savok": made, "kotesek": [f"{a} → {b}" for a, b in zip(rec[:2], ins)],
                    "mit_tegyel": "A terem a hálózati sávokat hallja (monitorozva). Felvételkor ezek is felvétel alatt "
                                  "vannak: az összerakáshoz kellenek."}
        if role == "otthon":
            snd = wait_ports("send_", "i", 30)
            if not snd:
                raise ValueError("A JackTrip küldő portjai nincsenek meg (fut a JackTrip?).")
            track = args.get("sav")
            if not track:
                raise ValueError("Kell a sav: az otthoni hangszer sávja (pl. „Bálint”).")
            outs = free_reaper("out")
            made = _call("return muzikos.tav_route(" + json_to_lua({"sends": [
                {"track": track, "out_ch": port_no(outs[0]) - 1},
                {"track": args.get("klikk_sav") or "Klikk", "out_ch": port_no(outs[1]) - 1}]}) + ")")
            for src, dst in zip(outs, snd[:2]):
                sh(f"pw-link '{src}' '{dst}'")
            return {"szerep": "otthon", "kuldes": made, "kotesek": [f"{a} → {b}" for a, b in zip(outs, snd[:2])],
                    "mit_tegyel": "Az otthoni a saját hangszerét, a klikket és a kísérőt hallja; a felvétel a projekt "
                                  "elejéről induljon (az összerakás ehhez igazít)."}
        raise ValueError("Kell a szerep: terem vagy otthon.")

    if act == "keses":
        jt = jacktrip_running() or {}
        q, rate = quantum()
        buf_ms = (jt.get("puffer") or 16) * q / rate * 1000
        ping = None
        if jt.get("tars"):
            code, out, _ = sh(["tailscale", "ping", "-c", "3", jt["tars"]], timeout=20)
            ms = [float(x) for x in re.findall(r"in (\d+(?:\.\d+)?)ms", out)]
            ping = min(ms) if ms else None
        return {"puffer_ms": round(buf_ms, 1), "halozat_oda_ms": round(ping / 2, 1) if ping else None,
                "becsult_keses_ms": round(buf_ms + (ping / 2 if ping else 0) + 2 * q / rate * 1000, 1),
                "mit_tegyel": "Ennyivel később hallja a terem az otthonit; a felvétel összerakásakor a pontos értéket a "
                              "Claude a hangból méri ki."}

    if act == "allapot":
        jt = jacktrip_running()
        return {"jacktrip": jt, "portok": [p for p in pw("o") + pw("i") if p.startswith(CLIENT + ":")]}

    if act == "leallitas":
        jt = jacktrip_running()
        if jt:
            try:
                os.killpg(jt["pid"], 15)
            except OSError:
                pass
        if os.path.exists(STATE):
            os.remove(STATE)
        return {"leallitva": bool(jt)}

    if act == "osszerakas":
        return assemble(args)
    raise ValueError("action: halozat | belepes | inditas | bekotes | keses | allapot | leallitas | osszerakas")


# ----------------------------------------------------------------------------- összerakás

SR = 8000


def load(path, start=0.0, dur=None):
    import numpy as np
    import muzikos_tab as tab
    x, sr = tab.read_audio(path)
    x = np.asarray(x, dtype=float)
    if x.ndim > 1:
        x = x.mean(axis=1)
    k = max(1, int(sr // 4000))                        # egyszerű aluláteresztő a lebutítás előtt
    if k > 1:
        x = np.convolve(x, np.ones(k) / k, mode="same")
    t = np.arange(int(len(x) * SR / sr)) / SR
    y = np.interp(t, np.arange(len(x)) / sr, x)
    return y


def xcorr_lag(a, b):
    """Mennyivel van b később, mint a (mp): GCC-PHAT, alminta-pontossággal."""
    import numpy as np
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    A, B = np.fft.rfft(a, n), np.fft.rfft(b, n)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-12
    c = np.fft.irfft(R, n)
    i = int(np.argmax(c))
    y0, y1, y2 = c[i - 1], c[i], c[(i + 1) % n]
    d = (y0 - y2) / (2 * (y0 - 2 * y1 + y2)) if (y0 - 2 * y1 + y2) != 0 else 0.0
    lag = i + d
    if lag > n / 2:
        lag -= n
    peak = float(y1 / (np.sqrt(np.mean(c ** 2)) + 1e-12))
    return lag / SR, peak


def offset_at(home, net, t, coarse, win=8.0, search=0.4):
    """A hálózati másolatban hol van az otthoni felvétel t mp-nél kezdődő ablaka (net idő), a durva becslés körül."""
    import numpy as np
    a = home[int(t * SR):int((t + win) * SR)]
    s0 = max(0, int((t + coarse - search) * SR))
    b = net[s0:s0 + int((win + 2 * search) * SR)]
    if len(a) < SR or len(b) < len(a):
        return None, 0
    lag, peak = xcorr_lag(a, b)
    return s0 / SR + lag, peak


def loudest_from(x, start, end, win=8.0):
    """A [start, end] tartomány legerősebb ablakának eleje (csendes részen a korreláció bizonytalan)."""
    import numpy as np
    best, bt = -1, start
    t = start
    while t + win <= end:
        e = float(np.mean(x[int(t * SR):int((t + win) * SR)] ** 2))
        if e > best:
            best, bt = e, t
        t += 1.0
    return bt


def assemble(args):
    import numpy as np
    items = _call("return muzikos.tav_items()")
    netname = mem.slug(args.get("halozati_sav") or "halozat")
    nets = [i for i in items if netname in mem.slug(i["sav"]) and "klikk" not in mem.slug(i["sav"])]
    if not nets:
        raise ValueError("Nincs a projektben felvett hálózati sáv („… (hálózat)”): a teremben azt is fel kell venni.")
    net = max(nets, key=lambda i: i["len"])
    home_path = args.get("path")
    if not home_path or not os.path.exists(home_path):
        raise ValueError("Kell a path: az otthoni gép felvétele (a zenekar mappájában, szinkron után; vagy pendrive-ról).")
    home = load(home_path)
    netx = load(net["file"])
    # a hálózati elem a projektben: net_file_time = offs + (room_time - pos)
    T = len(home) / SR
    if T < 20:
        raise ValueError("Az otthoni felvétel túl rövid az összerakáshoz (legalább 20 mp kell).")
    # durva: az otthoni első fél perce a hálózati első másfél percében
    lag0, peak0 = xcorr_lag(home[:int(min(T, 30) * SR)], netx[:int(min(len(netx) / SR, 90) * SR)])
    if peak0 < 8:
        raise ValueError("Nem találom az otthoni felvételt a hálózati sávban (más felvétel, vagy túl halk?).")
    t1 = loudest_from(home, 1.0, min(T / 2, 40.0))
    t2 = loudest_from(home, max(T / 2, T - 40.0), T - 1.0)
    n1, p1 = offset_at(home, netx, t1, lag0)
    n2, p2 = offset_at(home, netx, t2, lag0 + (t2 - t1) * 0.0)
    if n1 is None or n2 is None:
        raise ValueError("Az otthoni felvétel és a hálózati sáv nem fedi egymást eléggé.")
    b = (n2 - n1) / (t2 - t1)                       # a hálózati (termi) óra az otthonihoz képest
    a = n1 - b * t1                                  # net_file_time = a + b * home_time
    tm = (t1 + t2) / 2                               # ellenőrzés középen
    nm, pm = offset_at(home, netx, tm, a + (b - 1) * tm)
    resid = None if nm is None else round((nm - (a + b * tm)) * 1000, 2)
    pos_room = net["pos"] + (a - net["offs"])        # az otthoni felvétel 0. másodperce a termi idővonalon
    home_start = float(args.get("otthoni_kezdet") or 0.0)   # otthon a projekt melyik pontjáról vették fel
    shift = home_start - pos_room
    placed = _call("return muzikos.tav_place(" + json_to_lua({
        "name": args.get("nev") or os.path.splitext(os.path.basename(home_path))[0] + " (otthonról)",
        "file": home_path, "pos": float(pos_room), "rate": float(1.0 / b), "shift": float(shift),
        "mute": [n["sav"] for n in items if netname in mem.slug(n["sav"])] or []}) + ")", timeout=60)
    return {"keses_ms": round((pos_room - net["pos"] + net["offs"]) * 1000, 1),
            "ora_elteres_ppm": round((b - 1) * 1e6, 1),
            "csuszas_a_dal_vegen_ms": round((b - 1) * T * 1000, 1),
            "ellenorzes_kozepen_ms": resid, "biztonsag": round(min(p1, p2), 1),
            "termi_savok_eltolva_ms": round(shift * 1000, 1), "otthoni_sav": placed,
            "mit_tegyel": "Mondd el: mekkora volt a késés, mennyit csúszott a két óra, és hogy a hálózati sávokat "
                          "elnémítottad (a minőségi otthoni felvétel szól helyettük). Hallgassátok meg együtt."}


TOOLS = [
    ("tavproba", tool_tavproba,
     "Távpróba egy irányban: aki otthon van, klikkre és kísérőre játszik (a dal projektje: a korábbi felvételek vagy a "
     "Guitar Próból behozott sávok), a terem őt hallja fix késéssel. action: halozat (Tailscale: be van-e lépve, mely "
     "gépek látszanak), belepes (a böngészőben a zenész lép be), inditas (szerep: terem | otthon; otthon: gep = a termi "
     "gép neve, sav = az otthoni hangszer sávja, nev = kié; puffer: a JackTrip sora, alap 16), bekotes, keses (becslés), "
     "allapot, leallitas, osszerakas (a teremben a felvétel után: path = az otthoni felvétel fájlja; a késést és a két "
     "óra csúszását a hangból méri, az otthoni felvételt új sávra teszi, a terem sávjait a rácsra tolja; "
     "otthoni_kezdet = otthon a projekt hányadik mp-étől vettek fel, alap 0).",
     {"action": {"type": "string", "enum": ["halozat", "belepes", "inditas", "bekotes", "keses", "allapot", "leallitas", "osszerakas"]},
      "szerep": {"type": "string", "enum": ["terem", "otthon"]}, "gep": {"type": "string"}, "sav": {"type": "string"},
      "klikk_sav": {"type": "string"}, "nev": {"type": "string"}, "puffer": {"type": "integer"},
      "varakozas": {"type": "integer"}, "path": {"type": "string"}, "halozati_sav": {"type": "string"},
      "otthoni_kezdet": {"type": "number"}}),
]
