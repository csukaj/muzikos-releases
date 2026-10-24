"""Take-ek és összevágás (#332): a sáv rögzített rétegein (Reaper 7 fixed lanes) minden felvétel egy take; a Claude
dalrészenként méri (időzítés a rácshoz, túlvezérlés, csend), a zenészek szóbeli értékelését a take-naplóba írja (a
dal memóriája: take_naplo), javasolja a legjobbat, és jóváhagyás után összevágja egy „Végleges” rétegre,
áttűnésekkel. Az eredeti take-ek megmaradnak; az összevágás visszavonható (a Reaperben is, és újra összevágható).
"""
import math

import muzikos_memory as mem


# a szerver adja (server.py: takes.reaper_call = reaper_call …), hogy ugyanazon a hídon és zárral menjen
reaper_call = None
json_to_lua = None


def _call(lua, timeout=15):
    return reaper_call(lua, timeout=timeout)


def _lua_args(o):
    return json_to_lua(o)


def parts_now():
    """A dal részei a Reaper jelölőiből: [(név, kezdet mp, vég mp)]; ha nincs, az egész egy rész."""
    d = _call("return muzikos.markers()")
    regs = [r for r in (d.get("result") or []) if r.get("tipus") == "resz"] if d.get("ok") else []
    regs.sort(key=lambda r: r["kezd_mp"])
    # az azonos nevű részek (pl. két refrén) sorszámot kapnak, hogy külön választhatók legyenek
    seen, out = {}, []
    for r in regs:
        n = r["nev"]
        seen[n] = seen.get(n, 0) + 1
        out.append((n if seen[n] == 1 else f"{n} {seen[n]}", r["kezd_mp"], r["veg_mp"]))
    return out


def tempo_now():
    d = _call("return muzikos.tempo_list()")
    try:
        return float(d["result"]["alap"]["bpm"])
    except (KeyError, TypeError):
        return 120.0


def measure(seg, sr, t_proj0, bpm):
    """Egy take egy részének mérése: csúcs, átlagos hangerő, időzítés (a hangkezdetek eltérése a 16-od rácstól, ms)."""
    import numpy as np
    import muzikos_tab as tab
    if len(seg) < sr * 0.2:
        return {"csend": True}
    peak = float(20 * np.log10(np.max(np.abs(seg)) + 1e-9))
    rms = float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))
    out = {"csucs_dB": round(peak, 1), "hangero_dB": round(rms, 1), "tulvezerel": peak > -0.3, "csend": rms < -50}
    if not out["csend"]:
        times, f0, db, flux = tab.pitch_track(seg, sr, fmin=40.0)
        gate = max(-30 + float(np.max(db)), -60.0)
        ons = tab.onsets_from_flux(flux, db, gate)
        step = 60.0 / bpm / 4                                # tizenhatod, mp
        lag = 0.085 / 2 - 0.01 / 2   # a flux a hangot akkor látja, amikor az ablakba lép: az ablak közepe ennyivel korábbi
        devs = [abs(((t_proj0 + times[i] + lag) / step) - round((t_proj0 + times[i] + lag) / step)) * step * 1000 for i in ons]
        if devs:
            out["idozites_ms"] = round(float(np.median(devs)), 1)
            out["hangkezdetek"] = len(devs)
    return out


def score(m, note):
    """Pontszám: a zenészek jegye a legerősebb, utána az időzítés, a túlvezérlés, és ha a gép recsegett (#384)."""
    return _score(m, note) - (15 if m.get("rendszer_kimaradas") else 0)


def _score(m, note):
    """Pontszám a javaslathoz: a zenészek értékelése (1–5) a legerősebb, utána az időzítés, a túlvezérlés, a csend."""
    if m.get("csend"):
        return -1000.0
    s = 0.0
    if note and note.get("jegy"):
        s += (float(note["jegy"]) - 3) * 20
    s -= float(m.get("idozites_ms", 30)) * 0.6
    if m.get("tulvezerel"):
        s -= 25
    return s


def song_of(args):
    bid = mem.find_band(args.get("band"))
    if not bid or not args.get("title"):
        raise ValueError("Kell a title (a dal) és a mostani zenekar.")
    return bid, mem.tool_dal({"action": "get", "title": args["title"], "band": bid})


def tool_take_lista(args):
    """A sáv take-jei (rétegei) dalrészenként, méréssel és a naplóval, és a javaslat részenként."""
    import muzikos_tab as tab
    d = _call("return muzikos.take_lanes(" + _lua_args({"track": args.get("track", 1), "prepare": bool(args.get("prepare"))}) + ")")
    if not d.get("ok"):
        raise ValueError(d.get("error") or "A Reaper nem válaszol.")
    info = d["result"]
    if args.get("prepare"):
        info["elokeszitve"] = ("A sáv rétegekben van: minden új felvétel új rétegre (take-re) kerül. "
                               "Felvétel előtt menj a dal elejére (vagy a rész elejére).")
    takes = sorted({it["reteg"] for it in info.get("felvetelek", [])})
    names = {l["reteg"]: l.get("nev") for l in info.get("retegek", [])}
    takes = [t for t in takes if names.get(t) != "Végleges"]
    if not takes or args.get("analyze") is False:
        return info
    parts = parts_now() or [("egész", min(i["pos"] for i in info["felvetelek"]),
                             max(i["pos"] + i["len"] for i in info["felvetelek"]))]
    bpm = tempo_now()
    log = {}
    if args.get("title"):
        try:
            _, song = song_of(args)
            log = (song.get("take_naplo") or {}).get(info["sav"], {})
        except ValueError:
            log = {}
    audio = {}
    table, best = [], {}
    for name, t0, t1 in parts:
        row = {"resz": name, "kezd_mp": round(t0, 2), "veg_mp": round(t1, 2), "take": {}}
        for lane in takes:
            items = [i for i in info["felvetelek"] if i["reteg"] == lane and i["pos"] < t1 and i["pos"] + i["len"] > t0]
            note = (log.get(str(lane + 1)) or {}).get(name)
            if not items:
                row["take"][lane + 1] = {"nincs": True}
                continue
            it = max(items, key=lambda i: min(i["pos"] + i["len"], t1) - max(i["pos"], t0))
            if it["file"] not in audio:
                audio[it["file"]] = tab.read_audio(it["file"])
            x, sr = audio[it["file"]]
            a, b = max(it["pos"], t0), min(it["pos"] + it["len"], t1)
            s0 = int((it["offs"] + (a - it["pos"]) * it["rate"]) * sr)
            s1 = int((it["offs"] + (b - it["pos"]) * it["rate"]) * sr)
            m = measure(x[max(0, s0):max(0, s1)], sr, a, bpm)
            import muzikos_rendszer as hr
            xr = hr.xruns_for_file(it["file"])
            if xr is not None:
                m["rendszer_kimaradas"] = xr                 # a felvétel alatt a gép recsegett-e (#384)
            if note:
                m["naplo"] = note
            m["pont"] = round(score(m, note), 1)
            row["take"][lane + 1] = m
        cand = {k: v for k, v in row["take"].items() if "pont" in v}
        if cand:
            k = max(cand, key=lambda t: cand[t]["pont"])
            why = []
            if cand[k].get("naplo", {}).get("jegy"):
                why.append(f"a zenészek {cand[k]['naplo']['jegy']}-esre értékelték")
            if "idozites_ms" in cand[k]:
                why.append(f"az időzítése {cand[k]['idozites_ms']} ms-on belül")
            if not cand[k].get("tulvezerel"):
                why.append("nem vezérel túl")
            best[name] = {"take": k, "miert": ", ".join(why)}
        table.append(row)
    info["reszek"] = table
    info["javaslat"] = best
    info["mit_tegyel"] = ("Mondd el részenként a javaslatot és az okát, kérdezd meg, jó-e; a zenészek véleményét írd a "
                          "naplóba (take_jegyzet). Jóváhagyás után: take_comp. Egy take meghallgatása: take_play.")
    return info


def tool_take_jegyzet(args):
    """A zenészek értékelése egy take egy részéről a dal take-naplójába (újraindítás után is megmarad)."""
    bid, song = song_of(args)
    sav, take, part = args.get("track_name") or args.get("track"), args.get("take"), args.get("part")
    if not sav or not take or not part:
        raise ValueError("Kell a track (a sáv neve), a take (sorszám, 1-től) és a part (a dalrész neve).")
    naplo = song.get("take_naplo") or {}
    e = naplo.setdefault(str(sav), {}).setdefault(str(int(take)), {}).setdefault(part, {})
    if args.get("jegy") is not None:
        e["jegy"] = int(args["jegy"])
    if args.get("megjegyzes"):
        e["megjegyzes"] = args["megjegyzes"]
    e["mikor"] = mem.now()
    mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"take_naplo": naplo}})
    return {"dal": mem.display_title(song), "sav": sav, "take": int(take), "resz": part, "bejegyzes": e}


def tool_take_comp(args):
    """Összevágás a választás szerint ({rész: take}) vagy a javaslat szerint; a „Végleges” rétegre, áttűnéssel."""
    choice = args.get("choice") or {}
    parts = parts_now()
    if not parts:
        raise ValueError("Nincsenek dalrészek a Reaperben (reaper_markers structure): részenként kell választani.")
    if args.get("use_suggestion") or not choice:
        lst = tool_take_lista({"track": args.get("track"), "title": args.get("title"), "band": args.get("band")})
        choice = {**{k: v["take"] for k, v in (lst.get("javaslat") or {}).items()}, **choice}
    missing = [n for n, _, _ in parts if n not in choice]
    if missing:
        raise ValueError("Ezekhez a részekhez nincs választott take: " + ", ".join(missing))
    plan = [{"t0": t0, "t1": t1, "lane": int(choice[n]) - 1, "name": n} for n, t0, t1 in parts]
    d = _call("return muzikos.take_comp(" + _lua_args({"track": args.get("track", 1), "parts": plan,
                                                        "fade": float(args.get("fade_ms", 15)) / 1000}) + ")", timeout=30)
    if not d.get("ok"):
        raise ValueError(d.get("error") or "Az összevágás nem sikerült.")
    if args.get("title"):
        try:
            bid, song = song_of(args)
            v = song.get("vegleges") or {}
            v[str(args.get("track"))] = {"valasztas": choice, "mikor": mem.now()}
            mem.tool_dal({"action": "set", "title": song["cim"], "band": bid, "data": {"vegleges": v}})
        except ValueError:
            pass
    return {"osszevagva": choice, **d["result"],
            "mit_tegyel": "Hallgassátok meg (reaper_part / reaper_transport play). Ha egy rész nem jó: take_comp újra "
                          "más választással; egy take meghallgatása: take_play; a Reaperben Ctrl+Z is visszavonja."}


def tool_take_play(args):
    """Melyik take szóljon (meghallgatáshoz), vagy a végleges."""
    lane = args.get("take")
    if lane in (None, "", "vegleges", "végleges"):
        d = _call("return muzikos.take_lanes(" + _lua_args({"track": args.get("track", 1)}) + ")")
        comp = [l["reteg"] for l in (d.get("result") or {}).get("retegek", []) if l.get("nev") == "Végleges"]
        if not comp:
            raise ValueError("Még nincs végleges összevágás (take_comp).")
        lane = comp[0] + 1
    d = _call("return muzikos.take_play(" + _lua_args({"track": args.get("track", 1), "lane": int(lane) - 1}) + ")")
    if not d.get("ok"):
        raise ValueError(d.get("error") or "A Reaper nem válaszol.")
    return {"szol": int(lane)}


TOOLS = [
    ("take_lista", tool_take_lista,
     "Egy sáv take-jei (a Reaper rögzített rétegei): prepare=true rétegekbe teszi a sávot (felvétel előtt: minden új felvétel új take lesz). Felvétel után dalrészenként (a Reaper dalrészei szerint) méri minden take-et (időzítés a 16-od rácshoz ms-ban, csúcs, hangerő, túlvezérlés, csend), hozzáveszi a take-naplót (title = a dal), és javasolja részenként a legjobbat, okkal.",
     {"track": {"type": "string"}, "title": {"type": "string"}, "band": {"type": "string"},
      "prepare": {"type": "boolean"}, "analyze": {"type": "boolean"}}),
    ("take_jegyzet", tool_take_jegyzet,
     "A zenészek értékelése a take-naplóba: title (a dal), track (a sáv neve), take (sorszám 1-től), part (a dalrész neve, ahogy a take_lista mutatja), jegy (1–5), megjegyzes („a vége elcsúszott”). Újraindítás után is megmarad.",
     {"title": {"type": "string"}, "band": {"type": "string"}, "track": {"type": "string"}, "take": {"type": "integer"},
      "part": {"type": "string"}, "jegy": {"type": "integer"}, "megjegyzes": {"type": "string"}}),
    ("take_comp", tool_take_comp,
     "A végleges felvétel összevágása a take-ekből: choice = {\"Verze\": 2, \"Refrén\": 3, …} (a dalrészek neve, ahogy a take_lista mutatja), vagy use_suggestion=true (a javaslat; a choice felülírja). Egy új „Végleges” rétegre kerül, fade_ms áttűnéssel a vágásoknál, és csak az szól; az eredeti take-ek nem változnak. Csak jóváhagyás után.",
     {"track": {"type": "string"}, "title": {"type": "string"}, "band": {"type": "string"}, "choice": {"type": "object"},
      "use_suggestion": {"type": "boolean"}, "fade_ms": {"type": "number"}}),
    ("take_play", tool_take_play,
     "Melyik take szóljon a sávon (meghallgatáshoz: take = sorszám), vagy a végleges (take nélkül).",
     {"track": {"type": "string"}, "take": {"type": "integer"}}),
]
