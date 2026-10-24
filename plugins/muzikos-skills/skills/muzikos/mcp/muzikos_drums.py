"""Dob a MuzikOS-en (#334): az akusztikus dob mikrofonterve a meglévő bemenetekhez, és a fázisellenőrzés.

A terv a hangkártya bemeneteinek számához igazodik: kevés bemenetnél a kevés mikrofonos, bevált felállások
(Glyn Johns, „recorderman”), több bemenetnél a közeli mikrofonok is. A terv a Reaper-sávokat és a bekötési
térképet is meg tudja csinálni.
"""

# Felállások bemenetszám szerint: (név, mikrofon, hova és hogyan, javasolt típus, fantomtáp)
PLANS = {
    1: ("egy mikrofon (mono overhead)", [
        ("Overhead", "a dob elé-fölé, kb. 1 m-re a pergő magasságától, a lábdob és a pergő közé célozva", "kondenzátor", True)]),
    2: ("Glyn Johns-féle két mikrofon (lábdob nélkül)", [
        ("Overhead", "a pergő fölött kb. 1 m-re, a pergő és a lábdob közé célozva", "kondenzátor", True),
        ("Oldal", "a padlótam mellett a dobos jobb oldalán, a pergőtől ugyanannyira, mint az overhead (mérőszalaggal!), a pergő felé célozva", "kondenzátor", True)]),
    3: ("lábdob + két overhead (recorderman)", [
        ("Lábdob", "a lábdob előbőrén lévő lyukba vagy elé, a bőrtől 5–10 cm-re, a verő felé", "dinamikus (lábdob-mikrofon)", False),
        ("Overhead B", "a pergő fölött, a dobos válla fölött, a pergő felé célozva", "kondenzátor", True),
        ("Overhead J", "a dobos jobb válla mögött-fölött; a pergőtől és a lábdobtól ugyanakkora távolságra, mint az Overhead B", "kondenzátor", True)]),
    4: ("lábdob + pergő + két overhead", [
        ("Lábdob", "a lábdob előbőrén lévő lyukba vagy elé, a bőrtől 5–10 cm-re, a verő felé", "dinamikus (lábdob-mikrofon)", False),
        ("Pergő", "a pergő peremén belül 3–5 cm-re, a bőr fölött 3–5 cm-re, a közepe felé, a lábcintól elfordítva", "dinamikus (SM57-féle)", False),
        ("Overhead B", "a pergő fölött kb. 1 m-re, bal oldalt", "kondenzátor", True),
        ("Overhead J", "a pergő fölött kb. 1 m-re, jobb oldalt, a pergőtől ugyanakkora távolságra, mint az Overhead B", "kondenzátor", True)]),
    8: ("teljes: lábdob, pergő, lábcin, tamok, overheadek", [
        ("Lábdob", "a lábdob előbőrén lévő lyukba vagy elé, 5–10 cm-re, a verő felé", "dinamikus (lábdob-mikrofon)", False),
        ("Pergő", "a peremén belül, 3–5 cm-re a bőr fölött, a közepe felé", "dinamikus (SM57-féle)", False),
        ("Lábcin", "a felső cintányér fölött 10–15 cm-re, a széle felé, a pergőtől elfordítva", "kondenzátor (kis membrán)", True),
        ("Tam 1", "a perem fölött 3–5 cm-re, a közepe felé", "dinamikus", False),
        ("Tam 2", "a perem fölött 3–5 cm-re, a közepe felé", "dinamikus", False),
        ("Padlótam", "a perem fölött 3–5 cm-re, a közepe felé", "dinamikus", False),
        ("Overhead B", "a pergő fölött kb. 1 m-re, bal oldalt", "kondenzátor", True),
        ("Overhead J", "a pergő fölött kb. 1 m-re, jobb oldalt, a pergőtől ugyanakkora távolságra", "kondenzátor", True)]),
}


def plan_for(inputs):
    keys = sorted(PLANS)
    best = max(k for k in keys if k <= max(1, inputs))
    name, mics = PLANS[best]
    return best, name, mics


def tool_dob_mikrofon_terv(args):
    """A terv a bemenetszámhoz; apply=true: Reaper-sávok + a bekötési térkép."""
    inputs = int(args.get("inputs", 4))
    first = int(args.get("first_input", 1))
    used, name, mics = plan_for(inputs - first + 1)
    plan = []
    for i, (mic, where, typ, phantom) in enumerate(mics):
        plan.append({"mikrofon": mic, "bemenet": first + i, "hova": where, "tipus": typ,
                     "fantomtap_48V": "be" if phantom else "ki (dinamikushoz nem kell)"})
    out = {"felallas": name, "mikrofonok": len(plan), "terv": plan,
           "altalanos": [
               "a gain-t egyenként állítsd: a dobos üssön erősen arra a dobra, a csúcs −12…−6 dBFS legyen (input_levels)",
               "a két overhead a pergőtől egyforma távolságra legyen (mérőszalag), különben a pergő fázisa szétcsúszik",
               "a fázist ellenőrizd a lábdob és az overhead között (dob_fazis), és fordítsd, ha kell",
               "48V csak a kondenzátor-mikrofonnak kell; a UMC404HD-n a 48V mind a négy bemenetre megy egyszerre — dinamikus mikrofonnak nem árt",
               "a bemenetek számánál több mikrofonhoz nagyobb (8 bemenetes vagy ADAT-tal bővíthető) hangkártya kell"]}
    if inputs - first + 1 > used and used < 8:
        out["megjegyzes"] = f"{inputs - first + 1} bemenetre a {used} mikrofonos terv a legjobb; a maradék bemenetre mehet egy tam vagy egy szobamikrofon."
    return out


def phase_check(samples_a, samples_b, rate, max_ms=10.0):
    """Két csatorna kereszt-korrelációja ±max_ms késésen belül: (késés ms-ban, korreláció −1…1)."""
    n = min(len(samples_a), len(samples_b))
    a, b = samples_a[:n], samples_b[:n]
    ea = sum(x * x for x in a) ** 0.5
    eb = sum(x * x for x in b) ** 0.5
    if ea == 0 or eb == 0:
        return None, 0.0
    maxlag = int(rate * max_ms / 1000)
    best_lag, best = 0, 0.0
    step = 1 if n * (2 * maxlag + 1) < 6e7 else 2
    for lag in range(-maxlag, maxlag + 1, step):
        if lag >= 0:
            s = sum(a[i] * b[i + lag] for i in range(0, n - lag, 2))
        else:
            s = sum(a[i - lag] * b[i] for i in range(0, n + lag, 2))
        if abs(s) > abs(best):
            best, best_lag = s, lag
    corr = 2 * best / (ea * eb)
    return round(1000 * best_lag / rate, 2), round(max(-1.0, min(1.0, corr)), 2)
