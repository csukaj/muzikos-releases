---
name: muzikos-rig
description: >-
  A próba felállása a MuzikOS-en: a bekötési térkép (minden eszköz, port és kábel, ki milyen hangszerrel,
  melyik Reaper-sáv honnan jön), a kattintható rajza helyi weboldalként, a próba előtti pipálható
  bekötési útmutató a végén szintméréses ellenőrzéssel, és a potiállások: egy tag lefotózza az eszközt a
  telefonjával (fotóláda QR-kóddal), a Claude leolvassa és névvel menti, és visszaállításkor megmondja, mit
  merre kell csavarni. Használd, valahányszor bekötés, kábel, „mit hova dugjak”, felállás, rajz, poti,
  gain-állás vagy „el van csavarva” kerül szóba. Hívószavak: "mutasd a bekötést", "mit hova kell dugni",
  "ma a basszus a 3-asba megy", "rajzold le a felállást", "mentsd el a potiállásokat", "lefotóztam",
  "el vannak csavarva a potik", "állítsd vissza a múltkori hangzást", "kezdjük a bekötést".
---

# Bekötési térkép és potiállások

A felállás egy fájl a MuzikOS-memória mellett (`MuzikOS/Tudas/felallasok/<felállás>.json`), a rajza
ugyanott `.html`.

## Ha valami hiányzik

A `felallas` `activate` megnézi, hogy a felállás hangkártyája látszik-e (`hianyzik`). Ha nem: szólj, hogy dugják
be, és addig **ne válassz helyette** másik kártyát vagy bemenetet — csak ha a zenész kéri.

## Egy zenekar több felállása

Egy zenekarnak több felállása van (`fajta`), mindegyik másképp van bekötve:
- **szobapróba** — ötletelés, számkialakítás (pl. a LEM-nél Józsinál: Nitro, UMC404HD, GP-50);
- **próbaterem** — gyakorlás koncertre, félig koncert-setup (akusztikus dob, ládák, okos pedálok);
- **koncert** — a rider szerint (a koncertanyag erre épül);
- **otthoni** — egy tag saját setupja (`tag`: kié), pl. Bence a sajátját állítja be.

A próba elején (vagy ha szóba kerül: „most a teremben vagyunk”, „ma szobapróba”, „Bence otthon dolgozik”)
`felallas` `action: "activate"`, `name`: a mondat szavai is jók. A válasz a bekötés, a sávok, a zenészek és a
`teendok`: ebből dolgozz (a Reaper-sávok, a bemenetek, a próba előtti útmutató ehhez a felálláshoz
tartoznak). A teendők közt pontosítandó részek is lehetnek: kérdezd meg őket, és írd be (`felallas_kabel`,
`felallas` `set`). `felallas` `list` a mostani zenekar felállásait adja. Új felállásnál add meg a `fajta`-t
(és otthoninál a `tag`-ot).

## A felállás felvétele

- **Kész fájlból:** `felallas` `action: "import"`, `path` (az első: a PenSSD-Adat `MuzikOS/felallas-otthon.json`).
- **Szóban:** `felallas` `action: "set"`, `name`, `data`:
  - `eszkozok`: `[{"id": "umc", "nev": "Behringer UMC404HD", "tipus": "hangkártya", "portok": ["1. bemenet", …],
    "megjegyzes": "…"}]` — az `id` rövid és állandó (erre hivatkoznak a kábelek és a potiállások); a `tipus`
    dönti el, hova kerül a rajzon: hangszer/mikrofon balra, pedál/effekt/dobmodul/táp utána, hangkártya,
    keverő és számítógép középen, hangszóró/fejhallgató jobbra;
  - `zeneszek`, `reaper_savok` (`{"sav": "Dob", "forras": "UMC 1. bemenet"}`).
- **Egy kábel:** `felallas_kabel` `action: "add"`, `honnan: "gp50: PHONES out"`, `hova: "umc: 3. bemenet"`,
  `fajta: "3,5 mm kábel + átalakító"`, `mire: "a basszus"` — az ugyanabból a portból induló régi kábel
  cserélődik („ma a basszus a 3-asba megy”). Ha a kábel egy Reaper-sáv bemenetét változtatja, a sávot is
  igazítsd hozzá (`reaper_track_set` `input`), és a tag bemenetét a memóriában (`zenekar` `set`).
- A kábel fajtáját írd ki (USB, 6,3 mm jack TS/TRS, 3,5 mm jack, XLR, MIDI, táp): a rajz ebből színez.

## A rajz és a próba előtti útmutató

`felallas_rajz` — megnyitja a böngészőben. Az eszközre vagy kábelre kattintva látszanak a részletek és a
mentett potiállások (számlapként). Jobb oldalt a **pipálható bekötési lista** (a pipák megmaradnak). A
lista végén ellenőrizz: `input_levels`, és kérd meg a zenészeket egyenként, hogy játsszanak — minden
hangszernek ott kell szólnia, ahol a rajz szerint van. Ha nem, mondd meg, melyik kábelt hova tegyék át.

## Potiállások fotóról

1. **Fotó:** a telefonnal (ez az alap) — `fotolada` `action: "open"`: a képernyőn egy QR-kód jelenik meg;
   a tag a telefonnal beolvassa (ugyanazon a wifin), lefotózza az eszköz előlapját, és elküldi. Kérd meg:
   **szemből, jó fénnyel, hogy a potik jelölései látsszanak.** A fotóláda 15 percig él. (A laptop kamerája
   tartalék: `camera_snapshot`.)
2. **Leolvasás:** `foto_megnezes` (a legújabb beérkezett kép) — **te** olvasod le a potikat óraállásban
   („2 óra”; a legtöbb potin 7 óra a minimum, 12 óra a közép, 5 óra a maximum), és a kapcsolókat (be/ki).
   Ha valamit nem látsz biztosan, mondd meg és kérj új fotót; ne találgass.
3. **Mentés:** `potiallas` `action: "save"`, `eszkoz: "umc"`, `allas: "Próba – alap"`,
   `allasok: {"Gain 1": "1 óra", "Gain 2": "3 óra", "48V": "ki", "Hi-Z 2": "be", "Monitor": "12 óra"}`,
   `foto` (a kép útvonala). Egy eszközhöz több állás lehet („Felvétel – ének”, „Marci basszusa”).
4. **Visszaállítás:** „el vannak csavarva” → kérj új fotót, olvasd le, vesd össze a mentettel
   (`potiallas` `get`), és mondd meg potinként: „a 2-es gaint vedd vissza 3 óráról 1 órára”, „a 48V-ot
   kapcsold ki”. Új fotó, amíg minden egyezik. A pontosság fél–egy „óra”: ennél finomabbat ne ígérj.

## Mutasd meg a valódi eszközön

Ha fizikai teendőt kérsz („tekerd fel a basszus gainjét”, „dugd a GP-50 fülhallgató-kimenetét a UMC 2-be”), ne
csak mondd: **mutasd meg az eszköz képén** — `mutasd` `{"eszkoz": "UMC404HD", "jeloles": "gain2", "forgatas":
"jobbra", "szoveg": "GAIN 2 → jobbra, kb. 2 óráig"}`. Az asztalon megnyílik a kép: a többi elsötétítve, a poti
bekarikázva, a forgatás iránya nyíllal, és a felirat. Aljzatnál több jelölés is lehet (`jeloles: ["phones"]`, a
szövegben, hova menjen a kábel). Hogy melyik poti: a felállásból tudod (a basszus a UMC 2-be megy → `gain2`); a
jobbra = óramutató szerint = feljebb.

- **A képtár:** `eszkoz` `list` / `get` — eszközönként előlap, hátlap, közeli kép, és rajtuk a portok, potik,
  kapcsolók jelölései. Most: Behringer UMC404HD (előlap, közeli, hátlap), Valeton GP-50 (felülről, hátlap).
- **Új eszköz:** kép a netről (`eszkoz` `kep`, `url`, `forras`; a gyártó vagy egy bolt termékfotója, szemből)
  vagy fotóról (a fotóládával; `path`). Utána **te** jelölöd be a kép alapján (`jeloles`: id, név, típus, x, y,
  r képpontban), megmutatod az áttekintőt (`attekintes`, `open: true`), és ha a zenész jónak látja: `jovahagy`.
  Amíg nincs jóváhagyva, a `mutasd` szól, hogy kérdezd meg, jó helyen van-e a karika.
