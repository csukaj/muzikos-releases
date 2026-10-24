"""Zenekari logó (#373): a zenekar neve helyett a logója a MuzikOS oldalainak fejlécében.

A logó a zenekar mappájába kerül (Zenekarok/<zenekar>/logo/: az eredeti és a fejlécre készített változat), a memóriába
a zenekar.logo. Feldolgozás: háttér le (ha nem átlátszó: a sarok színe átlátszó lesz), körbevágás, fejlécmagasságra
kicsinyítés; az egyszínű logó (pl. fekete grafika) az arculat színére festve (narancs vagy világos), a többszínű a saját
színeivel marad, és ha a sötét alapon nem látszana (sötét logó), világos lapot kap maga alá.
Pillow-val (python3-pil); ha nincs, ImageMagick-kel (convert).
"""
import base64
import html
import os
import shutil
import subprocess

import muzikos_style as style

HEIGHT = 240                      # a fejlécben 72 px magas; nagy felbontású kijelzőre ~3×
COLORS = {"narancs": style.COLORS["or"], "vilagos": style.COLORS["ink"], "világos": style.COLORS["ink"]}


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _pil(src, out, color):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    px = im.load()
    w, h = im.size
    alpha = im.getchannel("A")
    if alpha.getextrema()[0] == 255:                  # nincs átlátszóság: a sarkok színe a háttér
        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        bg = tuple(sorted(c[i] for c in corners)[2] for i in range(3))
        data = []
        for r, g, b, a in im.getdata():
            d = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            data.append((r, g, b, 0 if d < 30 else min(255, int((d - 30) * 255 / 60))))  # puha szél, nem fűrészes
        im.putdata(data)
    box = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if not box:
        raise ValueError("A képen nem találok logót (üres, vagy egyszínű kép).")
    im = im.crop(box)
    scale = HEIGHT / im.size[1]
    im = im.resize((max(1, min(int(im.size[0] * scale), HEIGHT * 5)), HEIGHT), Image.LANCZOS)
    # egyszínű-e: a fedett pontok telítettsége és világossága
    sats, lums = [], []
    for r, g, b, a in im.getdata():
        if a > 160:
            mx, mn = max(r, g, b), min(r, g, b)
            sats.append(0 if mx == 0 else (mx - mn) / mx)
            lums.append((0.299 * r + 0.587 * g + 0.114 * b) / 255)
    if not lums:
        raise ValueError("A logó túl halvány: nincs rajta fedett rész.")
    sats.sort()
    lums.sort()
    p90 = sats[int(len(sats) * 0.9)]
    spread = lums[int(len(lums) * 0.9)] - lums[int(len(lums) * 0.1)]
    mono = p90 < 0.2 and spread < 0.35
    mean_l = sum(lums) / len(lums)
    if mono and color != "eredeti":
        rgb = _hex(COLORS.get(color, color if str(color).startswith("#") else COLORS["narancs"]))
        im = Image.merge("RGBA", (*Image.new("RGB", im.size, rgb).split(), im.getchannel("A")))
    im.save(out)
    return {"egyszinu": mono, "sotet": mean_l < 0.3, "meret": list(im.size)}


def _magick(src, out, color):
    """Tartalék Pillow nélkül: ImageMagick. Az egyszínűséget a telítettség átlagából becsli."""
    def run(*a):
        return subprocess.run(list(a), capture_output=True, text=True)
    corner = run("convert", src, "-format", "%[pixel:p{0,0}]", "info:").stdout.strip() or "white"
    opaque = run("convert", src, "-format", "%[opaque]", "info:").stdout.strip().lower() == "true"
    cmd = ["convert", src, "-auto-orient", "-alpha", "set"]
    if opaque:
        cmd += ["-fuzz", "12%", "-transparent", corner]
    cmd += ["-trim", "+repage", "-resize", f"x{HEIGHT}", out]
    r = run(*cmd)
    if r.returncode != 0:
        raise ValueError("A logót nem tudtam feldolgozni: " + r.stderr.strip()[:200])
    sat = float(run("convert", out, "-background", "gray", "-alpha", "remove", "-colorspace", "HSL", "-channel", "G",
                    "-separate", "-format", "%[fx:mean]", "info:").stdout.strip() or 0)
    lum = float(run("convert", out, "-alpha", "off", "-colorspace", "gray", "-format", "%[fx:mean]", "info:").stdout.strip() or 0)
    mono = sat < 0.12
    if mono and color != "eredeti":
        fill = COLORS.get(color, color if str(color).startswith("#") else COLORS["narancs"])
        run("convert", out, "-fill", fill, "-colorize", "100", out)
    size = run("convert", out, "-format", "%w %h", "info:").stdout.split()
    return {"egyszinu": mono, "sotet": lum < 0.3, "meret": [int(x) for x in size] if len(size) == 2 else None}


def prepare(src, band_dir, color="narancs"):
    """A logó a zenekar mappájába: az eredeti másolata és a fejléc-változat (logo/fejlec.png)."""
    if not os.path.exists(src):
        raise ValueError(f"Nincs ilyen fájl: {src}")
    d = os.path.join(band_dir, "logo")
    os.makedirs(d, exist_ok=True)
    orig = os.path.join(d, "eredeti" + os.path.splitext(src)[1].lower())
    if os.path.abspath(src) != os.path.abspath(orig):
        shutil.copy2(src, orig)
    out = os.path.join(d, "fejlec.png")
    try:
        import PIL  # noqa: F401
        info = _pil(orig, out, color)
    except ImportError:
        if not shutil.which("convert"):
            raise ValueError("A logó feldolgozásához kell a Pillow (python3-pil) vagy az ImageMagick.")
        info = _magick(orig, out, color)
    return {"eredeti": orig, "fejlec": out, "szin": color, **info}


def header_html(band):
    """A zenekar a fejlécben: a logója (beágyazva, hogy a fájl magában is megálljon), különben a neve."""
    lg = (band or {}).get("logo") or {}
    f = lg.get("fejlec")
    if f and os.path.exists(f):
        with open(f, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        recolored = lg.get("egyszinu") and lg.get("szin") != "eredeti"
        plate = " plate" if lg.get("sotet") and not recolored else ""     # sötét logó a sötét alapon: világos lap alá
        name = html.escape((band or {}).get("nev") or "", quote=True)
        return f'<img class="bandlogo{plate}" alt="{name}" src="data:image/png;base64,{b64}">'
    return None
