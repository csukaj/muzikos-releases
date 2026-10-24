"""A MuzikOS arculata (#349), Józsi választása (2026-10-23): keverőpultos design.

Sötét, majdnem fekete alap; a modulok rackmodulok (fémes panel, csavarok a sarkokban); a számok és az állapot egy
narancsszínben izzó kijelzőn; a fő kiemelés narancs, a felvétel piros; az állapotokat színes LED-ek jelzik. A színek
jelentést hordoznak, mindenhol ugyanazt: a tagoké (a sávon, a bekötésen, a dalnézetben, a koncertlistán), a
dalrészeké, a dal állapotáé, a kábeleké és a jelzéseké (zöld rendben, borostyán figyelj, piros hiba).
Betűk: Orbitron a címeknek, Saira a szövegnek, Share Tech Mono a kijelzőnek. Minden oldalon rövid súgó van (a jobb
alsó, narancsban izzó „?”), hosszú szöveg nincs.
A saját oldalaink (dallista, bekötési rajz, koncertlista, fotóláda) ebből építkeznek; a Claude is ezt használja,
ha új oldalt vagy ábrát rajzol.
"""
import html

COLORS = {
    "bg": "#0b0c0f", "panel1": "#20232a", "panel2": "#15171c", "edge": "#2a2d35", "well": "#1d2026",
    "ink": "#eef0f3", "sub": "#8a909c",
    "or": "#ff7a1a", "or2": "#ffa04d",                 # a fő kiemelés: narancs (a kijelző is)
    "rec": "#ff3b30", "ok": "#33d17a", "warn": "#ffb020", "cyan": "#33c3ff", "vio": "#b57cff",
}
HEAD_FONT = '"Orbitron","Saira",sans-serif'
BODY_FONT = '"Saira","DejaVu Sans","Segoe UI",Arial,sans-serif'
MONO_FONT = '"Share Tech Mono","DejaVu Sans Mono",monospace'
# a MuzikOS-en telepítve vannak; a hivatkozás azért kell, hogy máshol (Windows, telefon) is így nézzen ki, ha van net
# a betűk a MuzikOS-en helyben telepítve vannak (Orbitron, Saira, Share Tech Mono): net nélkül sem tölt a netről (#67)
FONT_LINK = ""

# a tagok színe (a tagnak saját is lehet: zenekar.json → tagok[].szin), különben a sorszáma szerint
MEMBER_PALETTE = ["#ff9a3d", "#2fd0bd", "#5aa2ff", "#b5e05a", "#ff5fa8", "#e6cfae", "#b57cff", "#4fd1e8"]
INSTRUMENT_COLORS = {"dob": "#ff9a3d", "gitár": "#2fd0bd", "gitár 2": "#5aa2ff", "basszus": "#b5e05a",
                     "ének": "#ff5fa8", "sampler": "#e6cfae", "billentyű": "#b57cff", "klikk": "#8a909c"}

# dalrészek: a név eleje szerint
PART_COLORS = {"intro": "#4b5361", "verze": "#1f6f9a", "refr": "#c4322a", "bridge": "#7b4bc4", "híd": "#7b4bc4",
               "szól": "#d27a12", "outro": "#4b5361", "átvezet": "#2f7a5f"}
PART_DEFAULT = "#3a3e48"

# a dal állapota (ötlet → kész): a LED színe
STATUS_COLORS = {"ötlet": "#5c616c", "próbálva": "#ff7a1a", "felvéve": "#ff3b30", "keverve": "#b57cff", "kész": "#33d17a"}

# kábelek fajtánként (a bekötési rajz)
CABLE_COLORS = {"hang": "#ff7a1a", "jack": "#ff7a1a", "usb": "#33c3ff", "midi": "#b57cff", "xlr": "#ff5fa8",
                "hangszóró": "#33d17a", "táp": "#6b707b", "bluetooth": "#4fd1e8"}

CSS = """
:root{--bg:%(bg)s;--p1:%(panel1)s;--p2:%(panel2)s;--edge:%(edge)s;--well:%(well)s;--ink:%(ink)s;--sub:%(sub)s;
--or:%(or)s;--or2:%(or2)s;--rec:%(rec)s;--ok:%(ok)s;--warn:%(warn)s;--cyan:%(cyan)s;--vio:%(vio)s;
--head:%(head)s;--body:%(body)s;--mono:%(mono)s}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 30%% -10%%,#1d1a1a 0%%,var(--bg) 60%%),var(--bg);color:var(--ink);
font-family:var(--body);font-size:16px;line-height:1.45;min-height:100vh}
header.mz{display:flex;align-items:center;gap:18px;padding:16px 22px;margin:16px 16px 0;border-radius:14px;
background:linear-gradient(180deg,var(--p1),var(--p2));border:1px solid var(--edge);box-shadow:inset 0 1px 0 #ffffff12,0 10px 30px #0009}
header.mz .logo{font-family:var(--head);font-weight:800;letter-spacing:2px;font-size:15px;color:var(--or)}
header.mz h1{margin:0;font-family:var(--head);font-weight:700;font-size:32px;line-height:1.1}
header.mz .sub{color:var(--sub);font-size:14px}
header.mz h1{display:flex;align-items:center;flex-wrap:wrap;gap:4px 14px}
header.mz .bandlogo{height:72px;width:auto;display:block;filter:drop-shadow(0 0 10px #ff7a1a40)}
header.mz .bandlogo.plate{background:#eef0f3;padding:6px 10px;border-radius:10px;filter:none}
header.mz .sep{color:#555b66;font-weight:400}
main.mz{padding:16px}
.card,.panel{background:linear-gradient(180deg,var(--p1),var(--p2));border:1px solid var(--edge);border-radius:14px;padding:16px 18px;
margin:0 0 14px;position:relative;box-shadow:inset 0 1px 0 #ffffff12,inset 0 -1px 0 #0008,0 10px 30px #0009}
.card::before,.card::after,.panel::before,.panel::after{content:"";position:absolute;width:7px;height:7px;border-radius:50%%;top:9px;
background:radial-gradient(circle at 35%% 35%%,#6b707b,#2a2d33)}
.card::before,.panel::before{left:9px}.card::after,.panel::after{right:9px}
.lab{font-family:var(--head);font-weight:700;font-size:12px;letter-spacing:2px;color:var(--sub);text-transform:uppercase;margin:0 0 10px}
.lcd{background:linear-gradient(180deg,#120a03,#1b0f05);border:1px solid #3a2410;border-radius:10px;padding:10px 14px;
box-shadow:inset 0 0 26px #ff7a1a22,inset 0 2px 8px #000;display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end}
.lcd .v{font-family:var(--mono);color:var(--or2);text-shadow:0 0 12px #ff7a1a99;font-size:30px;line-height:1;white-space:nowrap}
.lcd .k{font-size:11px;color:#a8743f;letter-spacing:2px;text-transform:uppercase;margin-bottom:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%%,280px),1fr));gap:14px}
.row{display:flex;align-items:center;gap:10px}
table.mz{border-collapse:collapse;width:100%%}
table.mz th{color:var(--sub);text-align:left;font-family:var(--head);font-weight:700;font-size:11px;letter-spacing:2px;
text-transform:uppercase;padding:10px 12px;border-bottom:1px solid var(--edge)}
table.mz td{padding:11px 12px;border-bottom:1px solid #22252c;vertical-align:middle}
table.mz tr:last-child td{border-bottom:0} table.mz tr:hover td{background:#ffffff06}
.num{font-family:var(--mono);color:var(--or2)}
a{color:var(--or2)} .k{color:var(--sub);font-size:14px}
.led{display:inline-block;width:9px;height:9px;border-radius:50%%;background:#3a3d44;flex:none}
.chip{display:inline-flex;align-items:center;gap:7px;height:26px;padding:0 12px;border-radius:999px;font-size:14px;
font-weight:600;line-height:1;white-space:nowrap;vertical-align:middle;background:var(--well);border:1px solid #333742;color:var(--ink)}
.part{display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:7px;font-size:13px;font-weight:600;color:#fff;
margin:0 4px 4px 0;box-shadow:inset 0 1px 0 #ffffff30,inset 0 -2px 0 #0004}
.btn{font:inherit;font-size:15px;padding:8px 14px;border-radius:10px;border:1px solid #3a3e48;color:var(--ink);cursor:pointer;
background:linear-gradient(180deg,#2b2e36,#191b20);box-shadow:inset 0 1px 0 #ffffff1a,0 4px 10px #0009}
.btn:hover{border-color:var(--or)} .btn.main{border-color:#7a1f1a;box-shadow:inset 0 0 18px #ff3b3055,0 0 18px #ff3b3055}
.sig-ok{color:var(--ok)} .sig-warn{color:var(--warn)} .sig-err{color:var(--rec)}
#mz-help-btn{position:fixed;right:22px;bottom:22px;width:56px;height:56px;border-radius:50%%;border:0;display:flex;align-items:center;
justify-content:center;background:radial-gradient(circle at 35%% 30%%,#ffb067,#ff7a1a 55%%,#c4520a);color:#1a0c02;
font-family:var(--head);font-weight:800;font-size:28px;cursor:pointer;box-shadow:0 0 26px #ff7a1a99,0 8px 18px #000a;z-index:50}
#mz-help{position:fixed;right:90px;bottom:24px;max-width:min(380px,calc(100vw - 120px));background:#1b1d23f2;
border:1px solid #5a3a1a;border-radius:12px;padding:12px 16px;display:none;z-index:50;box-shadow:0 10px 30px #000a}
#mz-help.on{display:block} #mz-help b{color:var(--or2);font-family:var(--head);letter-spacing:1px}
#mz-help ul{margin:6px 0 0;padding-left:18px}
@media (max-width:640px){header.mz .bandlogo{height:48px} header.mz h1{font-size:24px} main.mz{padding:10px} header.mz{margin:10px 10px 0}}
""" % {**COLORS, "head": HEAD_FONT, "body": BODY_FONT, "mono": MONO_FONT}


def led(color, glow=True):
    sh = f";box-shadow:0 0 8px {color}" if glow else ""
    return f'<span class=led style="background:{color}{sh}"></span>'


def status_chip(status):
    """Állapotcímke: sötét kapszula, benne a színes LED (ötlet → próbálva → felvéve → keverve → kész)."""
    c = STATUS_COLORS.get(status, STATUS_COLORS["ötlet"])
    return f'<span class=chip>{led(c, status != "ötlet")}{html.escape(status)}</span>'


def part_color(name):
    n = (name or "").lower()
    for k, c in PART_COLORS.items():
        if n.startswith(k):
            return c
    return PART_DEFAULT


def part_chip(name):
    return f'<span class=part style="background:{part_color(name)}">{html.escape(name)}</span>'


def member_color(member, index=0):
    """A tag színe: a sajátja (szin), különben a sorszáma szerint."""
    if member.get("szin"):
        return member["szin"]
    return MEMBER_PALETTE[index % len(MEMBER_PALETTE)]


def cable_color(kind):
    k = (kind or "").lower()
    for word, c in CABLE_COLORS.items():
        if word in k:
            return c
    return CABLE_COLORS["hang"]


def lcd(items):
    """Izzó kijelző: [(felirat, érték, alsó felirat)…]."""
    cells = "".join(f'<div><div class=k>{html.escape(k)}</div><div class=v>{html.escape(str(v))}</div>'
                    + (f'<div class=k style="margin:4px 0 0">{html.escape(s)}</div>' if s else "") + "</div>"
                    for k, v, s in items)
    return f"<div class=lcd>{cells}</div>"


def help_html(lines):
    """A súgó: legfeljebb néhány rövid sor; hosszú szöveg nem kell."""
    items = "".join(f"<li>{x}</li>" for x in lines)
    return ('<button id="mz-help-btn" title="súgó" onclick="document.getElementById(\'mz-help\').classList.toggle(\'on\')">?</button>'
            f'<div id="mz-help"><b>SÚGÓ</b><ul>{items}</ul></div>')


def page(title, body, sub="", help_lines=None, extra_css="", head_extra="", kind="MUZIKOS", brand=None):
    """Egy teljes oldal a MuzikOS arculatával: fejléc (MuzikOS · cím · alcím), tartalom, súgógomb.
    brand = a zenekar: a cím elé a logója (#373), ha van, különben a neve."""
    hl = help_lines or ["Kérdezd a Claude-ot: ő kezeli ezt az oldalt is."]
    h1, tab_title = html.escape(title), title
    if brand:
        import muzikos_logo
        name = brand.get("nev") or ""
        mark = muzikos_logo.header_html(brand) or f"<span class=bandname>{html.escape(name)}</span>"
        h1 = f"{mark}<span class=sep>—</span>{html.escape(title)}" if title else mark
        tab_title = f"{name} — {title}" if title else name
    return ("<!doctype html><html lang=hu><head><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(tab_title)} — MuzikOS</title>{FONT_LINK}<style>{CSS}{extra_css}</style>{head_extra}</head><body>"
            f'<header class=mz><div><div class=logo>{html.escape(kind)}</div><h1>{h1}</h1>'
            f'<div class=sub>{html.escape(sub)}</div></div></header><main class=mz>{body}</main>'
            f"{help_html(hl)}</body></html>")
