---
name: muzikos-memory
description: >-
  A MuzikOS-memória: a zenekarok (tagok, ki milyen hangszeren játszik, melyik bemenetre megy, melyik
  Reaper-sáv az övé), a dalaik (tempó, hangnem, szerkezet, a projekt helye, jegyzetek), a megtanított
  teendők (receptek) és a szokások — fájlban a PenSSD-Adaton, így újraindítás és új munkamenet után is
  megvan. Használd MINDEN munkamenet elején (tudas), zenekarváltáskor, egy dal elővételekor
  (dal_megnyitas), és valahányszor valaki elmagyaráz egy teendőt vagy kijavít. Hívószavak: "most a …-val
  próbálunk", "váltsunk zenekart", "ki van ma itt", "vegyük elő a … dalt", "jegyezd meg", "mindig így
  csináljuk", "legközelebb is így", "az én sávom mindig a 2-es", "mit tudsz a zenekarról", "milyen dalaink vannak".
---

# MuzikOS-memória

A Claude egy munkamenet végén mindent elfelejt; a MuzikOS-memória nem. Fájlokban van (ember által is
olvasható JSON és markdown), a PenSSD-Adat `MuzikOS/Tudas` mappájában (a Windows és a telefon is látja),
ha az nincs, a `~/MuzikOS/Tudas`-ban. Az eszközök a muzikos MCP-szerveréi.

## A munkamenet elején

`tudas` — a mostani zenekar, a tagok (hangszer, bemenet, sáv), a dalok, a receptek, a szokások. Ebből
dolgozz: ha ott áll, hogy „Marci basszusa a 2-esre megy”, ne kérdezd meg újra. Ha nincs mostani zenekar,
kérdezd meg, kik próbálnak, és vedd fel (lent). Ha a zenekarnak van Drive-szinkronja, rögtön utána
`zenekar_szinkron` (lent), hogy a másik gépen végzett munka is itt legyen.

## Egy zenekar = egy mappa, szinkronban a zenekar Drive-jával

A zenekar minden adata egy mappában van: `MuzikOS/Zenekarok/<zenekar>/` — `zenekar.json` (tagok, hangolás,
logó), `memoria/` (a dalok memóriája, setlistek), `felallasok/`, `Dalok/<dal>/` (reaper, guitarpro, export,
kotta…), a dallista és a koncertanyag. A régi szerkezet (Tudas/zenekarok, Projektek) első induláskor magától
átköltözik ide. A gépé marad a `Tudas` (a mostani zenekar, a receptek, a szokások).

Ha a próbateremben és valakinél otthon is van MuzikOS, a zenekar mappája a zenekar Google Drive-mappájával
szinkronizálódik (rclone, kétirányú):
- **Beállítás gépenként egyszer:** `zenekar_szinkron` `{"action": "beallit", "folder_id": "<a zenekar
  Drive-mappájának azonosítója a linkjéből>"}`; a Drive-on egy `MuzikOS` almappa lesz a szinkron helye (a
  zenekar többi Drive-fájlja érintetlen). A böngészőben megnyílik a Google-belépés: **a zenész lép be**, nem te.
  A LEM-é: `0B0oPYUrHtGknVDVpTzBNamRXMms`.
- **Szinkron:** `zenekar_szinkron` — a munkamenet elején, kérésre („szinkronizálj”), és **a próba végén**
  (előtte mentsd a Reaper-projektet). Mondd el röviden, mi jött és mi ment.
- **Ütközés** (ugyanazt a fájlt két gépen módosították): mindkét változat megvan, a másik gépé számozott
  néven. Mondd el, melyik melyik, kérdezd meg, melyik maradjon; kérdés nélkül ne törölj.
- **Nincs net:** a munka megy tovább helyben; szólj, hogy a szinkront később pótolod.

## Zenekarok

- **Felvétel, bővítés:** `zenekar` `action: "set"`, `name: "…"`, `data: {"tagok": [{"nev": "Marci",
  "hangszer": "basszusgitár", "hangszer_tipus": "Cort B5", "effektlanc": "GP-50", "bemenet": 2,
  "sav": "Basszus", "email": "…"}], "kep": "<a zenekar fotója>", "megjegyzes": "…"}` — az e-mail a
  felvételek megosztásához és az értesítőhöz kell (`dal_export`), a kép a videó borítója; a tagok név szerint
  frissülnek (a többi mezőjük megmarad);
  egy tag törlése: `{"nev": "…", "_torles": true}`.
- **Rövid név (`becenev`):** a tagokat a rövid nevükön szólítsd („Csabi”, „Csuka”), arra is ismerj rá
  („Csabi sávja” = Szabó Csaba sávja), és a sávjaikat is így nevezd el („Csabi – gitár”).
- **Váltás:** „most a másikkal próbálunk” → `zenekar` `action: "activate"`, `name`. Utána a sávokat a tagok
  szerint nevezd el (`reaper_add_track` `name` = a tag `sav`-ja vagy „Marci – basszus”), és a bemenetek a
  tagok `bemenet`-je szerint.
- Több zenekar is lehet; `zenekar` `list`.

## Dalok

- **Felvétel:** `dal` `action: "set"`, `title`, `data: {"tempo": 120, "hangnem": "E-moll", "utemmutato": "4/4",
  "szerkezet": [{"nev": "Intro", "utem": 4}, {"nev": "Verze", "utem": 8}, …]}`; egy megjegyzés: `data:
  {"jegyzet": "a második refrén után egy ütem szünet"}` (dátummal hozzáfűzve).
- **Elővétel:** `dal_megnyitas` `title` — megnyitja vagy létrehozza a projektet a zenekar mappájában
  (`MuzikOS/Zenekarok/<zenekar>/Dalok/<dal>/`), új projektnél a tempót beállítja, és ha még nincsenek dalrészek, a
  szerkezetből lerakja őket (a `reaper_part`-tal utána „a második gyors résztől” indítható). Visszaadja, ki
  melyik sáv.
- **Munkacím és publikus cím:** a dal a munkacímével indul (pl. „Leprusz”): ez a `title`, ebből lesz a mappa
  és a fájlnevek, és később sem változik. Ha megvan a végleges cím: `dal` `set` `title: "Leprusz"`, `data:
  {"publikus_cim": "…"}` — a mappa és a projekt marad, de az export, a borító, az értesítő és a dallista már a
  publikus címet mutatja. A dal mindkét címén előveheted; ha szóban a munkacímén emlegetik, azt használd.
- Ha a próbán kiderül a szerkezet (`reaper_markers` lerakta), írd vissza a dalhoz (`dal` `set` `szerkezet`).

## Dalmappák és dallista

Minden dal fájljai egy helyen: `MuzikOS/Zenekarok/<zenekar>/Dalok/<dal>/` — `reaper/` (a projekt és a felvételek),
`guitarpro/`, `export/`, `kotta/`, `egyeb/`, `jegyzet.md`. A `dal_megnyitas` az új projektet már ide teszi.
- `dalmappa` `files` — mi van a dal mappájában; `sort` `path: <fájl vagy mappa>` — a kapott fájlokat (pl. egy
  pendrive-ról, letöltésből, a fotóládából) kiterjesztés szerint a helyükre másolja (`copy: false` áthelyezi).
- `dallista` — a zenekar dalai az állapotukkal (ötlet → próbálva → felvéve → keverve → kész), tempóval,
  hangnemmel, szerkezettel, fájlokkal; `status` (title, status) frissít; `render` `open: true` megnyit egy
  olvasható oldalt a dalokkal és a fájlok linkjeivel.
- `dal_adatlap` `{"title": "<a dal>", "open": true}` — egy dal egy oldalon (a dal mappájában `adatlap.html`):
  állapot, hangolás, tempó, hangnem, ütemmutató, hossz, a szerkezet színes sávként, a mappa fájljai, jegyzetek.

### A zenekar logója

„Legyen fent a logónk” → `zenekar_logo` `{"path": "<a kép>"}`. A képet keresd meg a zenekar mappájában (pl. a
LEM-nél: `02_Brand/Press kit 2026/01_Logo/` — az átlátszó hátterű, egyszínű változat a legjobb), vagy kérd a
fotóládán át. A rendszer levágja a hátteret, fejlécre méretezi; az egyszínű logót az arculat színére festi
(`color`: `narancs`, `vilagos`, vagy `eredeti`), a többszínűt meghagyja (a sötétet világos lapra teszi). Utána
frissítsd és mutasd meg az oldalakat (dallista, adatlap, koncertlista): ott a név helyett a logó áll.
`remove: true` visszaállítja a nevet.

## Szinkron: a memória, a Reaper és a Guitar Pro

A dal tempója, ütemmutatója, tempóváltásai és szerkezete a memóriában a „hiteles” változat; a Reaper és a Guitar
Pro ezt követi, ha a Claude-on át változtatnak. A memória a közös pont: Reaper → memória → Guitar Pro, és vissza.
- A `dal_megnyitas` magától jelzi („FIGYELEM, szinkronizálni való van: …”) — mondd el a zenekarnak.
- `dal_szinkron` `check` — az eltérések a Reaperrel és a dal Guitar Pro-fájljával (a `guitarpro/` mappa
  legújabbja, vagy `gp_file`); kérdezd meg, melyik a jó, aztán:
  - `from_reaper` / `to_reaper` — a Reaper szerint a memóriát, vagy a memória szerint a Reapert;
  - `from_gp` / `to_gp` — a Guitar Pro szerint a memóriát, vagy a memória szerint a Guitar Pro-fájlt (.gp és
    .gp5; a .gpx-et nem: azt mentsék el .gp-ként a Guitar Próban). Írás előtt az eredeti fájl a
    `guitarpro/.elozmenyek/` mappába kerül, időbélyeggel — ha valami nem tetszik, onnan visszahozható.
  - Pl. „a Reaperben gyorsítottunk, vidd át a kottába is” → `from_reaper`, aztán `to_gp`.
- Ha a Claude-on át változtatsz tempót vagy szerkezetet (`reaper_tempo`, `reaper_markers`), írd vissza a memóriába
  is (`dal_szinkron` `from_reaper`), és kérdezd meg, a kottába is menjen-e (`to_gp`).
- A .gp5-be csak az első tempó kerül; a tempóváltásokhoz .gp kell (ezt a válasz jelzi).

## Receptek: amit megtanítottak

Ha valaki elmagyaráz egy teendőt („a próba eleje mindig így megy: …”, „a szólót háromszor vesszük fel, a
legjobbat tartjuk meg”), és jó eséllyel lesz még ilyen: `recept` `action: "set"`, `name`, `triggers`
(a szavak, amikkel kérni fogják), `text` (a lépések, az eszközökkel és a paraméterekkel). Mondd meg, hogy
elmentetted. Legközelebb egy hasonló kérésnél előbb `recept` `list` / `get`, és aszerint csinálj.

## Szokások és javítások

Ha valaki kijavít („az én sávom mindig a 2-es”, „ne legyen metronóm a szólónál”, „a fájlnév legyen dátum +
dal”): `szokas` `action: "add"`, `who`, `text` — és onnantól eszerint. Ami egy tag adata (bemenet, sáv),
az inkább a `zenekar` tagjába kerüljön.

## Amit ne

- Jelszót, belépési adatot ne írj a memóriába.
- Törölni (`delete`) csak kérésre, és az előnézet után (`confirm`).
