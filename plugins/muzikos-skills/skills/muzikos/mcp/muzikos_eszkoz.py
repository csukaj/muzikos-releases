"""Fizikai teendők a valódi eszköz képén (#335): melyik potit csavard, hova dugd.

Eszközönként képek (előlap, hátlap, közeli; a netről vagy fotóról, a forrással és a dátummal) és rajtuk a portok,
potik, kapcsolók helye (jelölések, képpontban). A jelöléseket a Claude rakja fel a kép alapján, egy ember egyszer
jóváhagyja (áttekintő kép); utána a Claude egy kiemelt képpel mutatja a teendőt: a többi elsötétítve, a poti
bekarikázva, a forgatás iránya nyíllal, és a felirat („GAIN 2 → jobbra, kb. 2 óráig”).
    <tudás>/eszkozok/<eszköz>/eszkoz.json   név, képek, jelölések
    <tudás>/eszkozok/<eszköz>/<nézet>.jpg   a képek
    <tudás>/eszkozok/<eszköz>/mutatas/     a kiemelt képek
"""
import datetime
import glob
import math
import os
import shutil
import subprocess
import urllib.request

import muzikos_memory as mem
import muzikos_style as style

OR = (255, 122, 26)
INK = (238, 240, 243)


def base():
    return os.path.join(mem.root(), "eszkozok")


def find(name):
    """Eszköz az azonosítója, a neve vagy a névrésze szerint („umc”, „UMC404HD”, „Valeton GP-50”)."""
    want = mem.slug(name or "")
    if not want:
        return None
    all_ = sorted(glob.glob(os.path.join(base(), "*", "eszkoz.json")))
    for p in all_:
        d = mem.read_json(p, {})
        if os.path.basename(os.path.dirname(p)) == want or mem.slug(d.get("nev", "")) == want:
            return os.path.basename(os.path.dirname(p))
    for p in all_:
        d = mem.read_json(p, {})
        keys = [os.path.basename(os.path.dirname(p)), mem.slug(d.get("nev", ""))] + [mem.slug(a) for a in d.get("mas_nevek", [])]
        if any(want in k or (k and k in want) for k in keys):
            return os.path.basename(os.path.dirname(p))
    return None


def path(eid):
    return os.path.join(base(), eid, "eszkoz.json")


def load(eid):
    return mem.read_json(path(eid), {})


def font(size, bold=True):
    from PIL import ImageFont
    names = (["Saira-Bold.ttf", "Saira[wdth,wght].ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"] if bold
             else ["Saira[wdth,wght].ttf", "DejaVuSans.ttf", "arial.ttf"])
    for n in names:
        for d in ("/usr/share/fonts/truetype/muzikos", "/usr/share/fonts/truetype/dejavu", "/usr/local/share/fonts",
                  "C:/Windows/Fonts", os.path.expanduser("~/.local/share/fonts")):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def label(draw, xy, text, size, anchor_left=True, img_w=None):
    f = font(size)
    x, y = xy
    b = draw.textbbox((0, 0), text, font=f)
    w, h = b[2] - b[0], b[3] - b[1]
    pad = max(4, size // 3)
    if img_w and x + w + 2 * pad > img_w:
        x = img_w - w - 2 * pad - 2
    x = max(2, x)
    draw.rounded_rectangle([x, y, x + w + 2 * pad, y + h + 2 * pad], radius=pad, fill=(20, 12, 4, 235), outline=OR, width=2)
    draw.text((x + pad - b[0], y + pad - b[1]), text, font=f, fill=INK)
    return y + h + 2 * pad


def arrow_arc(draw, cx, cy, r, clockwise, width):
    """Forgatás-nyíl a poti körül: ív és nyílhegy (óramutató szerint = jobbra = feljebb)."""
    start, end = (-140, -20) if clockwise else (-40, -160)
    a0, a1 = (start, end) if clockwise else (end, start)
    draw.arc([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=OR, width=width)
    t = math.radians(end)
    hx, hy = cx + r * math.cos(t), cy + r * math.sin(t)
    tang = t + (math.pi / 2 if clockwise else -math.pi / 2)        # a mozgás iránya a végpontban
    s = width * 3.2
    p1 = (hx + s * math.cos(tang), hy + s * math.sin(tang))
    p2 = (hx + s * 0.9 * math.cos(tang + 2.5), hy + s * 0.9 * math.sin(tang + 2.5))
    p3 = (hx + s * 0.9 * math.cos(tang - 2.5), hy + s * 0.9 * math.sin(tang - 2.5))
    draw.polygon([p1, p2, p3], fill=OR)


def render(eid, view, marks, text=None, turn=None, overview=False):
    """Kiemelt kép: a jelölések bekarikázva (a többi elsötétítve), forgatás-nyíl, felirat."""
    from PIL import Image, ImageDraw
    d = load(eid)
    src = os.path.join(base(), eid, d["kepek"][view]["fajl"])
    im = Image.open(src).convert("RGBA")
    # a termékfotók egyszínű (fehér) margója le: az eszköz legyen nagy; a jelölések eltolva
    bg = im.getpixel((0, 0))
    diff = Image.eval(im.convert("L"), lambda v, b=sum(bg[:3]) // 3: 255 if abs(v - b) > 18 else 0)
    box = diff.getbbox()
    if box:
        pad = int(max(im.size) * 0.04)
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.size[0], box[2] + pad), min(im.size[1], box[3] + pad))
        im = im.crop(box)
        marks = [{**m, "x": m["x"] - box[0], "y": m["y"] - box[1]} for m in marks]
    scale = max(1.0, 1100 / max(im.size))                       # kis képet felnagyít, hogy a felirat olvasható legyen
    if scale > 1:
        im = im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.LANCZOS)
    W, H = im.size
    shade = Image.new("RGBA", im.size, (0, 0, 0, 0 if overview else 150))
    sd = ImageDraw.Draw(shade)
    for m in marks:
        x, y, r = m["x"] * scale, m["y"] * scale, m.get("r", 12) * scale * 1.35
        sd.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 0))
    im = Image.alpha_composite(im, shade)
    dr = ImageDraw.Draw(im)
    lw = max(3, int(W / 300))
    for m in marks:
        x, y, r = m["x"] * scale, m["y"] * scale, m.get("r", 12) * scale * 1.35
        dr.ellipse([x - r, y - r, x + r, y + r], outline=OR, width=lw)
        if overview:
            label(dr, (x - r, y + r + 2), m.get("nev", m["id"]), max(11, int(W / 75)), img_w=W)
        elif turn in ("jobbra", "balra") and m.get("tipus") == "poti":
            arrow_arc(dr, x, y, r * 1.55, turn == "jobbra", lw + 1)
    if text and not overview:
        m = marks[0]
        x, y, r = m["x"] * scale, m["y"] * scale, m.get("r", 12) * scale * 1.35
        ty = y - r * 1.9 - W / 22 if y > H * 0.35 else y + r * 1.9
        label(dr, (x - W / 10, max(4, ty)), text, max(16, int(W / 40)), img_w=W)
    return im.convert("RGB")


def _open(p):
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        subprocess.Popen(["xdg-open", p], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def tool_eszkoz(args):
    """Eszközök képtára: list, get, kep (kép felvétele netről vagy fájlból), jeloles (jelölések), attekintes, jovahagy."""
    act = args.get("action", "list")
    if act == "list":
        out = []
        for p in sorted(glob.glob(os.path.join(base(), "*", "eszkoz.json"))):
            d = mem.read_json(p, {})
            out.append({"azonosito": os.path.basename(os.path.dirname(p)), "nev": d.get("nev"),
                        "kepek": {k: v.get("forras") for k, v in d.get("kepek", {}).items()},
                        "jelolesek": {k: len(v) for k, v in d.get("jelolesek", {}).items()},
                        "jovahagyva": d.get("jovahagyva", {})})
        return {"helye": base(), "eszkozok": out}
    name = args.get("eszkoz")
    eid = find(name) or (mem.slug(name) if act == "kep" and name else None)
    if not eid:
        raise ValueError(f"Nincs ilyen eszköz a képtárban: {name}. eszkoz action=list")
    d = load(eid) or {"nev": args.get("nev") or name, "kepek": {}, "jelolesek": {}}
    if args.get("nev"):
        d["nev"] = args["nev"]
    if args.get("mas_nevek"):
        d["mas_nevek"] = args["mas_nevek"]
    folder = os.path.join(base(), eid)
    if act == "get":
        return {"azonosito": eid, **d}
    if act == "kep":
        view = mem.slug(args.get("nezet") or "elolap")
        src = args.get("path") or args.get("url")
        if not src:
            raise ValueError("Kell a path (fájl, pl. a fotóládából) vagy az url (a gyártó vagy a bolt képe).")
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(src.split("?")[0])[1].lower() or ".jpg"
        dst = os.path.join(folder, view + ext)
        if args.get("url"):
            req = urllib.request.Request(args["url"], headers={"User-Agent": "Mozilla/5.0 MuzikOS"})
            with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
                f.write(r.read())
        else:
            shutil.copy2(src, dst)
        d["kepek"][view] = {"fajl": os.path.basename(dst), "forras": args.get("forras") or src,
                            "mikor": datetime.date.today().isoformat()}
        d.setdefault("jovahagyva", {})[view] = False
        mem.write_json(path(eid), d)
        return {"eszkoz": eid, "nezet": view, "fajl": dst,
                "mit_tegyel": "Nézd meg a képet, és rakd fel a portok, potik, kapcsolók helyét (eszkoz action=jeloles), "
                              "utána mutasd meg az áttekintőt jóváhagyásra (action=attekintes)."}
    if act == "jeloles":
        view = mem.slug(args.get("nezet") or "elolap")
        if view not in d["kepek"]:
            raise ValueError(f"Nincs {view} képe: eszkoz action=kep.")
        cur = {m["id"]: m for m in d["jelolesek"].get(view, [])}
        for m in args.get("jelolesek") or []:
            if m.get("_torles"):
                cur.pop(m.get("id"), None)
            else:
                cur[m["id"]] = {**cur.get(m["id"], {}), **m}
        d["jelolesek"][view] = list(cur.values())
        d.setdefault("jovahagyva", {})[view] = False
        mem.write_json(path(eid), d)
        return {"eszkoz": eid, "nezet": view, "jelolesek": len(cur)}
    if act == "attekintes":
        view = mem.slug(args.get("nezet") or "elolap")
        marks = d["jelolesek"].get(view) or []
        if not marks:
            raise ValueError(f"A(z) {view} képen még nincs jelölés.")
        out = os.path.join(folder, f"attekintes-{view}.png")
        render(eid, view, marks, overview=True).save(out)
        opened = _open(out) if args.get("open") else False
        return {"kep": out, "megnyitva": opened,
                "mit_tegyel": "Mutasd meg a zenésznek: jó helyen vannak-e a jelölések? Ha igen: action=jovahagy; "
                              "ha valamelyik rossz, javítsd (action=jeloles) és mutasd újra."}
    if act == "jovahagy":
        view = mem.slug(args.get("nezet") or "elolap")
        d.setdefault("jovahagyva", {})[view] = True
        mem.write_json(path(eid), d)
        return {"eszkoz": eid, "nezet": view, "jovahagyva": True}
    raise ValueError("action: list | get | kep | jeloles | attekintes | jovahagy")


def tool_mutasd(args):
    """Egy fizikai teendő a valódi eszköz képén: melyik poti, merre, mennyit; melyik aljzat."""
    eid = find(args.get("eszkoz"))
    if not eid:
        raise ValueError(f"Nincs ilyen eszköz a képtárban: {args.get('eszkoz')}. eszkoz action=list")
    d = load(eid)
    want = [mem.slug(x) for x in (args.get("jeloles") if isinstance(args.get("jeloles"), list) else [args.get("jeloles")]) if x]
    if not want:
        raise ValueError("Kell a jeloles (a poti vagy aljzat azonosítója, pl. „gain2”, „phones”).")
    views = [args["nezet"]] if args.get("nezet") else sorted(d["kepek"], key=lambda v: (v != "kozeli", v != "elolap"))
    for view in views:                                 # a legközelebbi nézet, amin mind rajta van
        ms = {mem.slug(m["id"]): m for m in d["jelolesek"].get(view, [])}
        ms.update({mem.slug(m.get("nev", "")): m for m in d["jelolesek"].get(view, [])})
        hit = [ms[w] for w in want if w in ms]
        if len(hit) == len(want):
            break
    else:
        raise ValueError(f"Nincs ilyen jelölés a(z) {d.get('nev')} képein: {', '.join(want)}. eszkoz action=get")
    text = args.get("szoveg") or " · ".join(m.get("nev", m["id"]) for m in hit)
    out_dir = os.path.join(base(), eid, "mutatas")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{want[0]}.png")
    render(eid, view, hit, text, args.get("forgatas")).save(out)
    opened = _open(out) if (args.get("ablak") or args.get("open")) else False    # alapból a válaszban jelenik meg (#2)
    res = {"kep": out, "nezet": view, "megnyitva": opened, "jeloles": [m.get("nev", m["id"]) for m in hit]}
    if not d.get("jovahagyva", {}).get(view):
        res["figyelem"] = "Ezen a képen a jelöléseket még senki nem hagyta jóvá: kérdezd meg, jó helyen van-e a karika."
    return res


TOOLS = [
    ("eszkoz", tool_eszkoz,
     "A fizikai eszközök képtára (hangkártya, effektpedál, dobmodul…): list; get (eszkoz); kep (eszkoz, nezet: elolap / "
     "hatlap / kozeli / oldal, url VAGY path, forras; nev, mas_nevek — a felállás eszköznevei, hogy ráismerjen); jeloles "
     "(eszkoz, nezet, jelolesek: [{id, nev, tipus: poti|aljzat|gomb|kapcsolo|kijelzo, x, y, r}] képpontban — a kép alapján "
     "te rakod fel); attekintes (az összes jelölés egy képen, jóváhagyásra; open); jovahagy.",
     {"action": {"type": "string", "enum": ["list", "get", "kep", "jeloles", "attekintes", "jovahagy"]},
      "eszkoz": {"type": "string"}, "nezet": {"type": "string"}, "url": {"type": "string"}, "path": {"type": "string"},
      "forras": {"type": "string"}, "nev": {"type": "string"}, "mas_nevek": {"type": "array", "items": {"type": "string"}},
      "jelolesek": {"type": "array", "items": {"type": "object"}}, "open": {"type": "boolean"}}),
    ("mutasd", tool_mutasd,
     "Fizikai teendő a valódi eszköz képén, egy ablakban az asztalon: eszkoz (pl. „UMC404HD”), jeloles (id vagy név, "
     "pl. „gain2”, vagy lista: hova dugd), forgatas: jobbra (óramutató szerint, feljebb) | balra; szoveg: a felirat, "
     "röviden („GAIN 2 → jobbra, kb. 2 óráig”). A felállásból tudd, melyik bemenet kié (a basszus = UMC 2). A bejelölt kép a "
     "válaszban jelenik meg (ablak nem nyílik); ablak=true külön ablakban is megnyitja (ha a kép nem fér a beszélgetésbe).",
     {"eszkoz": {"type": "string"}, "jeloles": {"type": ["string", "array"]}, "forgatas": {"type": "string", "enum": ["jobbra", "balra"]},
      "szoveg": {"type": "string"}, "nezet": {"type": "string"}, "ablak": {"type": "boolean"}, "open": {"type": "boolean"}}),
]
