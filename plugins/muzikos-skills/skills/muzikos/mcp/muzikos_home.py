"""A zenekar kezdőlapja (#65, #53): egy oldal, ahonnan a zenekar összes infóoldala egy kattintással elérhető.

    MuzikOS/Zenekarok/<zenekar>/kezdolap.html

Bal oldalt az oldalsáv (dallista, koncertek, felállások, dal-adatlapok, logó), jobbra a kiválasztott oldal egy keretben
(az oldalsáv így nem tűnik el). Az oldalsáv egy gombbal elrejthető és visszahozható, és a választás megmarad (#53).
Az asztalon van rá ikon, és belépéskor magától megnyílik (a `--kezdolap-megnyit` mód, lásd server.py).
"""

import datetime
import glob
import html
import os
import subprocess
import urllib.parse

import muzikos_memory as mem
import muzikos_style as style

HOME_CSS = """
html,body{height:100%}body{display:flex;flex-direction:column;min-height:0}
.top{display:flex;align-items:center;gap:12px;padding:8px 14px;border-bottom:1px solid var(--edge);
background:linear-gradient(180deg,var(--p1),var(--p2))}
.top .brand{font-family:var(--head);font-weight:700;font-size:20px;flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.top .brand .logo{font-size:11px;color:var(--or);letter-spacing:2px;margin-right:10px}
.top .sub{color:var(--sub);font-size:12px}
#toggle{font:inherit;font-size:20px;line-height:1;width:44px;height:36px;border-radius:8px;border:1px solid var(--edge);
background:var(--well);color:var(--ink);cursor:pointer}#toggle:hover{border-color:var(--or)}
.wrap{display:flex;flex:1;min-height:0}
nav#side{flex:0 0 270px;overflow:auto;padding:12px;border-right:1px solid var(--edge);background:var(--p2)}
body.side-off nav#side{display:none}
nav#side h2{font-family:var(--head);font-size:11px;letter-spacing:2px;color:var(--sub);margin:14px 4px 6px;text-transform:uppercase}
nav#side h2:first-child{margin-top:2px}
nav#side a{display:block;padding:8px 10px;margin:2px 0;border-radius:8px;color:var(--ink);text-decoration:none;font-size:15px;
border:1px solid transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
nav#side a:hover{background:var(--well);border-color:var(--edge)}
nav#side a.on{background:var(--well);border-color:var(--or);color:var(--or2)}
nav#side .none{color:var(--sub);font-size:13px;padding:4px 10px}
iframe#tartalom{flex:1;min-width:0;border:0;background:var(--bg)}
"""

JS = """
const body = document.body, key = 'muzikosKezdolapOldalsav';
const set = off => { body.classList.toggle('side-off', off); try { localStorage.setItem(key, off ? '1' : '0'); } catch (e) {} };
try { if (localStorage.getItem(key) === '1') body.classList.add('side-off'); } catch (e) {}
document.getElementById('toggle').addEventListener('click', () => set(!body.classList.contains('side-off')));
const links = document.querySelectorAll('nav#side a');
links.forEach(a => a.addEventListener('click', () => { links.forEach(x => x.classList.remove('on')); a.classList.add('on'); }));
const first = document.querySelector('nav#side a'); if (first) first.classList.add('on');
"""


_http = {"on": False}


def file_url(path):
    """Egy fájl linkje: a helyi szerveren át (/_f/…), ha a kezdőlap onnan nyílik (a dallista gombjai csak ott működnek),
    különben file://."""
    p = path.replace(os.sep, "/")
    if _http["on"]:
        return "/_f/" + urllib.parse.quote(p, safe="/:")
    return "file://" + urllib.parse.quote(p, safe="/:")


def page_html(title, sections, sub=""):
    """A kezdőlap HTML-je. sections = [(szakasz címe, [(felirat, link)…])…]; az első link töltődik be először."""
    nav, first = [], None
    for head, items in sections:
        nav.append(f"<h2>{html.escape(head)}</h2>")
        if not items:
            nav.append("<div class=none>még nincs</div>")
        for label, link in items:
            first = first or link
            nav.append(f'<a href="{html.escape(link)}" target="tartalom" title="{html.escape(label)}">{html.escape(label)}</a>')
    return ("<!doctype html><html lang=hu><head><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)} — MuzikOS</title>{style.FONT_LINK}<style>{style.CSS}{HOME_CSS}</style></head><body>"
            f'<div class=top><button id=toggle title="Oldalsáv elrejtése / megjelenítése" aria-label="Oldalsáv">☰</button>'
            f'<div class=brand><span class=logo>MUZIKOS</span>{html.escape(title)}</div><div class=sub>{html.escape(sub)}</div></div>'
            f'<div class=wrap><nav id=side>{"".join(nav)}</nav>'
            f'<iframe id=tartalom name=tartalom src="{html.escape(first or "about:blank")}"></iframe></div>'
            f"<script>{JS}</script></body></html>")


def _find(pattern):
    return sorted(glob.glob(pattern))


def sections_of(band_folder, band_id=None):
    """A zenekar mappájából a szakaszok: dallista, koncertek, felállások, dal-adatlapok, logó."""
    import muzikos_rig as rig
    sec = []
    dl = os.path.join(band_folder, "dallista.html")
    sec.append(("Dallista", [("Dallista", file_url(dl))] if os.path.exists(dl) else []))
    kon = []
    for p in _find(os.path.join(band_folder, "koncert", "*", "lista.html")):
        kon.append((os.path.basename(os.path.dirname(p)), file_url(p)))
    sec.append(("Koncertek", kon))
    fel = []
    for r in rig.rigs(band_id):
        h = os.path.join(rig.rig_dir(r["azonosito"]), r["azonosito"] + ".html")
        if os.path.exists(h):
            fel.append((r.get("nev") or r["azonosito"], file_url(h)))
    sec.append(("Felállások", fel))
    dal = [(os.path.basename(os.path.dirname(p)), file_url(p)) for p in _find(os.path.join(band_folder, "Dalok", "*", "adatlap.html"))]
    sec.append(("Dalok", dal))
    logo = [(os.path.basename(p), file_url(p)) for p in _find(os.path.join(band_folder, "logo", "*"))
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".pdf"))]
    sec.append(("Logó, press kit", logo))
    return sec


def render(band_id=None):
    """A zenekar kezdőlapjának megírása (a hiányzó aloldalakat előbb elkészíti); visszaadja az útvonalat."""
    import muzikos_songs as songs
    bid = mem.find_band(band_id)
    if not bid:
        raise ValueError("Nincs mostani zenekar (zenekar action=activate), vagy nincs ilyen zenekar.")
    import muzikos_rig as rig
    _http["on"] = bool(rig.rig_http())
    band = mem.tool_zenekar({"action": "get", "name": bid})
    folder = songs.band_folder(band)
    os.makedirs(folder, exist_ok=True)
    try:
        songs.tool_dallista({"action": "render", "band": bid})
    except Exception:
        pass                                    # a kezdőlap a meglévő aloldalakkal is megnyílik
    for s in mem.tool_dal({"action": "list", "band": bid}):
        try:
            songs.tool_dal_adatlap({"title": s["munkacim"], "band": bid})
        except Exception:
            pass
    sub = f"frissítve: {datetime.datetime.now():%Y-%m-%d %H:%M}"
    out = os.path.join(folder, "kezdolap.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page_html(band.get("nev") or bid, sections_of(folder, bid), sub))
    return out


def home_url(out):
    """A kezdőlap címe: a helyi szerveren át, hogy a dallista gombjai (Reaper, kotta…) működjenek."""
    import muzikos_rig as rig
    port = rig.rig_http()
    return f"http://127.0.0.1:{port}/_f/" + urllib.parse.quote(out.replace(os.sep, "/"), safe="/:") if port else out


def open_home(band_id=None):
    out = render(band_id)
    subprocess.Popen(["xdg-open", home_url(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return out


def tool_kezdolap(args):
    out = render(args.get("band"))
    res = {"kezdolap": out}
    if args.get("open", True):
        subprocess.Popen(["xdg-open", home_url(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        res["megnyitva"] = True
    return res


TOOLS = [
    ("kezdolap", tool_kezdolap,
     "A zenekar kezdőlapja (Zenekarok/<zenekar>/kezdolap.html): egy oldal, ahonnan az összes aloldal egy kattintással elérhető "
     "(dallista, koncertek, felállások, dalok adatlapja, logó). Újraírja (a hiányzó aloldalakat is elkészíti), és megnyitja "
     "(open=false: csak megírja). Az oldalsáv egy gombbal elrejthető, és a választás megmarad. Az asztalon ikon van rá, "
     "belépéskor magától megnyílik.",
     {"band": {"type": "string"}, "open": {"type": "boolean"}}),
]
