"""A zenekar mappájának szinkronja a zenekar Google Drive-mappájával (#351), rclone bisync-kel.

Minden MuzikOS-gépen ugyanaz a zenekar: a próbatermi és az otthoni gépen elmentett változás (új take, új dal, új
szerkezet) szinkron után a másikon is megvan.
    beállítás: zenekaronként egy rclone-kapcsolat (muzikos-<zenekar>) a zenekar Drive-mappájára — a mappa
               azonosítójával, így a velünk megosztott mappa is megy; a Google-belépést a zenész végzi a böngészőben.
               A Drive-on a zenekar mappájában egy almappa (alapból „MuzikOS”) a szinkron helye.
    szinkron:  kétirányú (bisync); ütközésnél egyik változat se vész el: a vesztes számozott néven megmarad, és a
               Claude szól róla. A változatlan nagy hangfájlok nem mennek újra. Nincs net: a munka megy tovább, a
               szinkron később pótolja.
Mi nem megy fel: a Reaper biztonsági mentései (.rpp-bak, Backups/), a csúcsfájlok (.reapeaks), az ideiglenes fájlok.
A gépé (nem a zenekaré): a kapcsolat (~/.config/rclone/rclone.conf) és a bisync állapota (~/.cache/rclone/bisync).
"""
import datetime
import glob
import os
import re
import shutil
import subprocess
import time

import muzikos_memory as mem

EXCLUDE = ["*.rpp-bak", "**/Backups/**", "*.reapeaks", "*.tmp", "*.RPP-UNDO", ".~lock*", "**/.Trash*/**",
           "**/__pycache__/**"]
CONFLICT_RE = re.compile(r"\.(ütközés|conflict)\d+|\.\.path[12]$|\(ütközés \d")
OFFLINE = ("no such host", "dial tcp", "network is unreachable", "temporary failure in name resolution",
           "i/o timeout", "connection refused", "couldn't find root directory id")


def rclone():
    return shutil.which("rclone")


def version():
    try:
        out = subprocess.run([rclone(), "version"], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"v(\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    except (OSError, subprocess.SubprocessError):
        return (0, 0)


def remote_name(bid):
    return "muzikos-" + mem.slug(bid)


def remotes():
    r = subprocess.run([rclone(), "listremotes"], capture_output=True, text=True, timeout=20)
    return [x.strip().rstrip(":") for x in r.stdout.splitlines() if x.strip()]


def target(bid, band):
    s = band.get("szinkron") or {}
    if s.get("cel"):                     # más cél (helyi mappa, hálózati meghajtó, más rclone-kapcsolat): ahogy van
        return s["cel"]
    return f"{s.get('remote') or remote_name(bid)}:{s.get('almappa', 'MuzikOS')}"


def state_file(bid):
    return os.path.join(mem.root(), "szinkron", mem.slug(bid) + ".json")      # a gépé: mikor, mi lett


def filters_file():
    p = os.path.join(mem.root(), "szinkron", "kihagy.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(f"- {x}\n" for x in EXCLUDE))
    return p


def conflicts(folder):
    return sorted(os.path.relpath(p, folder) for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
                  if CONFLICT_RE.search(os.path.basename(p)))


def run(cmd, timeout=6 * 3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def pull_first(local, remote, stub):
    """Az első szinkron előtt: ami a Drive-on van és itt nincs, lejön (új gép); a csonk zenekar.json helyére a
    Drive-on lévő valódi kerül. Így a --resync egyesítésében az új gép üres adatai nem írnak felül semmit.
    Visszaad: (rc, napló, a csonk lecserélődött-e / nem kellett)."""
    run([rclone(), "mkdir", remote])                   # az első gépnél a Drive-on még nincs meg a mappa
    code, out = run([rclone(), "copy", remote, local, "--ignore-existing", "--filter-from", filters_file()])
    if not stub:
        return code, out, True
    remote_json = remote.rstrip("/") + "/zenekar.json"
    c2, o2 = run([rclone(), "lsf", remote_json])
    if c2 != 0 or not o2.strip():
        return code, out + o2, True                    # a Drive-on még nincs zenekar.json: ez a gép az első
    c3, o3 = run([rclone(), "copyto", remote_json, os.path.join(local, "zenekar.json")])
    return (code or c3), out + o3, c3 == 0


def tidy_conflicts(local):
    """Az rclone 1.60 ütközésnél mindkét változatot átnevezi (X..path1 = ez a gép, X..path2 = a másik): a saját
    változat visszakapja az eredeti nevét (a Reaper-projekt ott marad, ahol a memória tudja), a másik gépé mellé kerül
    „X (ütközés <idő>).ext” néven, hogy meg is lehessen nyitni. Visszaad: [(megmaradt, a másiké)]."""
    out = []
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
    for p1 in glob.glob(os.path.join(local, "**", "*..path1"), recursive=True):
        orig = p1[:-len("..path1")]
        p2 = orig + "..path2"
        if os.path.exists(orig):
            continue
        os.replace(p1, orig)
        if os.path.exists(p2):
            stem, ext = os.path.splitext(orig)
            other = f"{stem} (ütközés {stamp}){ext}"
            os.replace(p2, other)
            out.append((os.path.relpath(orig, local), os.path.relpath(other, local)))
    for p2 in glob.glob(os.path.join(local, "**", "*..path2"), recursive=True):   # csak a másik oldalon változott
        orig = p2[:-len("..path2")]
        if not os.path.exists(orig):
            os.replace(p2, orig)
    return out


def run_bisync(local, remote, first, dry=False):
    v = version()
    cmd = [rclone(), "bisync", local, remote, "--filters-file", filters_file(), "--max-delete", "50", "-v"]
    if v >= (1, 64):
        cmd.append("--create-empty-src-dirs")          # a Debian 13 rclone-ja (1.60) ezt még nem tudja
    if first:
        cmd.append("--resync")                         # az első: a két oldal uniója, semmi nem törlődik
        if v >= (1, 64):
            cmd += ["--resync-mode", "newer"]          # ami mindkét oldalon van: az újabb marad
    if v >= (1, 66):                                   # az újabb nyer, a régebbi „.ütközés1” néven megmarad
        cmd += ["--conflict-resolve", "newer", "--conflict-loser", "num", "--conflict-suffix", "ütközés",
                "--resilient", "--recover", "--max-lock", "5m", "--compare", "size,modtime"]
    if dry:
        cmd.append("--dry-run")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600)
    return r.returncode, (r.stdout + r.stderr), round(time.time() - t0, 1)


def tool_zenekar_szinkron(args):
    if not rclone():
        raise ValueError("Nincs rclone a gépen (a MuzikOS-képben benne van; máshol: sudo apt install rclone).")
    act = args.get("action", "szinkron")
    bid = mem.find_band(args.get("band"))
    if not bid and act == "beallit" and args.get("band"):
        # új gép: a zenekar még nincs itt — egy csonk, amit az első szinkron a Drive-on lévővel cserél le
        mem.tool_zenekar({"action": "set", "name": args["band"], "data": {"_csonk": True}})
        bid = mem.find_band(args["band"])
    if not bid:
        raise ValueError("Nincs mostani zenekar: add meg a band-et (új gépen a zenekar nevét is).")
    band = mem.tool_zenekar({"action": "get", "name": bid})
    local = mem.band_dir(bid)
    st = mem.read_json(state_file(bid), {})

    if act == "beallit":
        rn = remote_name(bid)
        data = {"remote": rn, "almappa": args.get("almappa") or "MuzikOS"}
        if args.get("folder_id"):
            data["drive_mappa"] = args["folder_id"]
        mem.tool_zenekar({"action": "set", "name": band.get("nev") or bid, "data": {"szinkron": data}})
        if rn in remotes() and not args.get("ujra"):
            return {"kapcsolat": rn, "megvan": True, "cel": f"{rn}:{data['almappa']}",
                    "mit_tegyel": "A kapcsolat megvan: zenekar_szinkron (action: szinkron)."}
        cmd = [rclone(), "config", "create", rn, "drive", "scope=drive"]
        fid = args.get("folder_id") or (band.get("szinkron") or {}).get("drive_mappa")
        if fid:
            cmd.append(f"root_folder_id={fid}")
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        log = os.path.join(mem.root(), "szinkron", rn + "-belepes.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as fh:                    # a belépés a böngészőben megy; ez megvárja a végét
            subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        return {"kapcsolat": rn, "belepes": "elindult", "naplo": log,
                "mit_tegyel": "Szólj a zenésznek: a böngészőben megnyílt a Google-belépés — lépjen be a zenekar "
                              "Drive-ját látó fiókkal, és engedélyezze az rclone-t (a jelszót ő írja be, nem te). "
                              "Utána: zenekar_szinkron action=allapot, majd action=szinkron."}

    if act == "allapot":
        sz = band.get("szinkron") or {}
        rn = sz.get("remote")
        return {"beallitva": bool(rn or sz.get("cel")), "kapcsolat_megvan": bool(sz.get("cel")) or (bool(rn) and rn in remotes()),
                "cel": target(bid, band) if (rn or sz.get("cel")) else None,
                "helyi_mappa": local, "utolso": st.get("utolso"), "eredmeny": st.get("eredmeny"),
                "utkozesek": conflicts(local)}

    if act != "szinkron":
        raise ValueError("action: beallit | szinkron | allapot")
    s = band.get("szinkron") or {}
    if not s.get("cel") and (not s.get("remote") or s["remote"] not in remotes()):
        raise ValueError("Még nincs beállítva a zenekar Drive-szinkronja: zenekar_szinkron action=beallit "
                         "(folder_id: a zenekar Drive-mappájának azonosítója a linkjéből).")
    first = not st.get("elso_kesz")
    res = {"helyi": local, "cel": target(bid, band)}
    if first and not args.get("proba"):
        pcode, pout, replaced = pull_first(local, target(bid, band), bool(band.get("_csonk")))
        if pcode != 0 and any(w in pout.lower() for w in OFFLINE):
            return {**res, "eredmeny": "nincs net", "mit_tegyel": "Nincs kapcsolat a Drive-val: a munka megy tovább "
                                                                  "helyben, a szinkront később pótold."}
        if pcode != 0 or not replaced:                 # az első egyesítés csak tiszta letöltés után: semmi ne íródjon felül
            return {**res, "eredmeny": "hiba", "hiba": "\n".join(pout.strip().splitlines()[-8:]),
                    "mit_tegyel": "A Drive-ról nem sikerült lehozni a zenekar adatait; a szinkron nem indult el, hogy a "
                                  "Drive-on lévő ne íródjon felül. Mondd el a hibát."}
        band = mem.tool_zenekar({"action": "get", "name": bid})
        if band.get("_csonk"):                         # a Drive-on még nincs ilyen zenekar: ez a gép az első
            mem.tool_zenekar({"action": "set", "name": band.get("nev") or bid, "data": {"_csonk": None}})
    code, out, secs = run_bisync(local, target(bid, band), first, bool(args.get("proba")))
    low = out.lower()
    res["ido_mp"] = secs
    if code != 0 and any(w in low for w in OFFLINE):
        res.update(eredmeny="nincs net", mit_tegyel="Nincs kapcsolat a Drive-val: a munka megy tovább helyben, a "
                                                    "szinkront később pótold (zenekar_szinkron).")
    elif code != 0 and "--resync" in low and not first:
        # a bisync elvesztette az állapotát (pl. megszakadt): újra az unióval — törlés így sem lesz
        code, out, secs = run_bisync(local, target(bid, band), True, bool(args.get("proba")))
        res["ujrakezdve"] = True
    if code == 0:
        res["eredmeny"] = "kész"
        fixed = tidy_conflicts(local)
        if fixed:                                       # a rendbe tett nevek a Drive-ra is, rögtön
            run_bisync(local, target(bid, band), False)
            res["utkozes_rendezve"] = [{"ez_a_gepe": a, "a_masik_gepe": b} for a, b in fixed]
        if not args.get("proba"):
            st["elso_kesz"] = True
        moved = [ln.split("INFO  :", 1)[-1].strip() for ln in out.splitlines()
                 if re.search(r"(Copied|Deleted|Moved|Renamed)", ln)][:40]
        res["valtozasok"] = moved
    elif "eredmeny" not in res:
        res["eredmeny"] = "hiba"
        res["hiba"] = "\n".join(out.strip().splitlines()[-12:])
    c = conflicts(local)
    if c:
        res["utkozesek"] = c
        res["mit_tegyel"] = ("Ütközés: ugyanazt a fájlt két gépen is módosították. Mindkét változat megvan: az "
                             "eredeti nevű az, amelyiket ezen a gépen mentették (ahol az ütközés kiderült), az „(ütközés …)” "
                             "nevű a másik gépé (utkozes_rendezve mondja meg). Mondd el, melyik melyik, kérdezd meg, "
                             "melyik maradjon; a másikat kérdés nélkül ne töröld.")
    if not args.get("proba"):
        st.update(utolso=datetime.datetime.now().isoformat(timespec="seconds"), eredmeny=res["eredmeny"])
        mem.write_json(state_file(bid), st)
    return res


TOOLS = [
    ("zenekar_szinkron", tool_zenekar_szinkron,
     "A zenekar mappájának (Zenekarok/<zenekar>: memória, dalok, felállások, projektek) szinkronja a zenekar "
     "Google Drive-mappájával, kétirányúan: action=beallit (egyszer gépenként: folder_id = a zenekar Drive-mappájának "
     "azonosítója, almappa alapból „MuzikOS”; a Google-belépést a zenész végzi a böngészőben), action=szinkron "
     "(induláskor, kérésre, a próba végén; proba=true csak megmutatja), action=allapot. Ütközésnél mindkét változat "
     "megmarad; nincs net: később pótolja.",
     {"action": {"type": "string", "enum": ["beallit", "szinkron", "allapot"]}, "band": {"type": "string"},
      "folder_id": {"type": "string"}, "almappa": {"type": "string"}, "ujra": {"type": "boolean"},
      "proba": {"type": "boolean"}}),
]
