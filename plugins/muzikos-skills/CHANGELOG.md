# A muzikos-skills plugin változásai (korábban: musicos-skills)

## 0.31.17 — 2026-10-25

- **Hangparancsok a felvételhez, kéz nélkül.** Gitárral a kézben: „felvétel”, „stop”, „vissza az elejére”, „újra az utolsó
  ütemtől”, „ez jó volt” (jelölőt tesz a Reaperbe). A beszédfelismerés helyben fut, net nélkül is (faster-whisper, magyarul);
  csak a rövid, egy fix parancsra hasonlító mondat számít parancsnak, a beszélgetés és a játék nem. Bizonytalan felismerésnél
  rákérdez („felvétel? Mondd: igen”), a lefutott parancsot hangjelzés és értesítés követi. Belépéskor magától indul; a
  `hangparancs` eszközzel kikapcsolható, a mikrofon megadható (`forras`), és szövegre kipróbálható (`proba`). A lemezkép
  építése letölti a „small” felismerő modellt (kb. 480 MB). ([#255](https://github.com/csukaj/muzikos/issues/255))

## 0.31.16 — 2026-10-25

- **Folyamatos fejlesztési napló (`fejlesztesi_naplo`).** A MuzikOS kérés nélkül rögzíti, ami a fejlesztéshez hasznos: az
  eszközhibákat, amit kézzel kellett megkerülni, amit a zenész kijavított vagy elvetett, és a zenész észrevételeit szó szerint;
  a gép-pillanatkép (kép- és pluginverzió, hangeszközök) és a háttérnapló hibái magától bekerülnek. A napló naponta egy
  csomagban elmegy a MuzikOS saját szerverére (net nélkül sorba áll, később egyszer megy el). Hangfelvétel, dal, kotta, jelszó
  és e-mail nem kerül bele; a zenész bármikor megnézheti (`mit_kuldenel`) és kikapcsolhatja. Józsi gépén alapból be van
  kapcsolva, a többieknél az első indításkor a Claude megkérdezi, és igen nélkül nem küld. ([#69](https://github.com/csukaj/muzikos/issues/69))

## 0.31.15 — 2026-10-25

- **A Claude alapból a zenész belépett Chrome-jával dolgozik** a belépős oldalakon (RouteNote, Drive, YouTube…). A `chrome`
  böngészőeszköz a Claude-Chrome-hoz kapcsolódik; a zenész egyszer belép benne a Google-fiókjával, és a belépései megmaradnak.
  Zenekaronként külön Chrome-profil van, zenekarváltás után a mostani zenekaré nyílik, a belépések nem keverednek. Jelszót a
  Claude nem ír be, és küldés, közzététel, fizetés vagy feltöltés véglegesítése előtt mindig rákérdez. ([#106](https://github.com/csukaj/muzikos/issues/106))

## 0.31.14 — 2026-10-25

- **Problémabejelentés (`bejelentes`).** Amit a MuzikOS nem tud, vagy ami visszatérően elromlik, a Claude helyben feljegyzi
  (gyakorisággal); ugyanaz harmadszor: magától felajánlja a beküldést. A zenész a küldés előtt látja a pontos szöveget, és
  csak a jóváhagyása után megy el; hangfelvétel, jelszó, e-mail és mások adata nem kerül bele. Net nélkül sorba áll, és a
  net megjöttével egyszer ér célba. A cél a MuzikOS saját szervere (muzikos-mcp, #44) — amíg az nincs bekötve, a bejelentések
  a sorban várnak. ([#3](https://github.com/csukaj/muzikos/issues/3))

## 0.31.13 — 2026-10-24

- **Net nélkül is használható.** Az oldalak (kezdőlap, dallista, felállás…) nem töltenek betűtípust a netről (a MuzikOS helyben telepített betűit használják); a panelen „⚠ nincs net” jelzés, ha nincs hálózat. ([#67](https://github.com/csukaj/muzikos/issues/67))

## 0.31.12 — 2026-10-24

- **A bekarikázott eszközkép a Claude válaszában jelenik meg** (`mutasd`, az áttekintő kép), nem külön böngészőablakban; ahol a
  kép nem fér be a beszélgetésbe, a Claude ezt mondja, és ablakban nyitja meg (`ablak: true` is kérhető). ([#2](https://github.com/csukaj/muzikos/issues/2))
- **A felállás-rajzon az eszközök valódi képe látszik** (a képtárból) a dobozban, kattintásra nagyban a mentett potiállásokkal; a
  kép nélküli eszközöket a `felallas_rajz` felsorolja, és a Claude felajánlja a kép beszerzését. ([#1](https://github.com/csukaj/muzikos/issues/1))

## 0.31.11 — 2026-10-24

- **A dallistán a dalok megnyithatók.** A dal címére kattintva az adatlapja nyílik; a sorban gombok nyitják a helyi fájlokat: a
  Reaper-projektet (a Reaperben), a Guitar Pro-kottát (TuxGuitarban), a jegyzetet, a legutóbbi felvételt és a dal mappáját. A lista
  oszlopaiban tempó, hangnem és állapot látszik. A dallista és a kezdőlap a helyi szerveren (127.0.0.1) nyílik, a gombok csak a
  MuzikOS-mappán belüli fájlt nyitják. ([#64](https://github.com/csukaj/muzikos/issues/64))

## 0.31.10 — 2026-10-24

- **Az aktív zenekar neve mindig látszik a panelen** (♪ LEM), 5 másodpercenként frissül, zenekarváltás után az újat mutatja;
  kattintásra a zenekar kezdőlapja nyílik. (`--zenekar-jelzo`) ([#63](https://github.com/csukaj/muzikos/issues/63))

## 0.31.9 — 2026-10-24

- **A felállás-rajzon az eszközök egérrel áthúzhatók**, a kábelek követik, és az új elrendezés magától mentődik (a felállás
  eszközönkénti `x`/`y`-jába), Mentés gomb nélkül; újranyitáskor és a Drive-szinkronnal a másik gépen is így látszik. A Claude által
  hozzáadott új eszköz szabad helyre kerül, a kézzel elrendezetteket nem mozgatja. A rajz a helyi szerveren (127.0.0.1) nyílik
  (`felallas_rajz`). ([#62](https://github.com/csukaj/muzikos/issues/62))

## 0.31.8 — 2026-10-24

- **Képernyőkép egy gombnyomással.** PrtSc (egész), Alt+PrtSc (ablak), Shift+PrtSc (kijelölt terület) és asztali ikonok: a kép a
  `~/MuzikOS/Kepernyokepek` mappába kerül (a `legutobbi.png` mindig a legfrissebb), a vágólapra is; a Claude a „nézd meg a
  képernyőképet” kérésre a legutóbbit megnyitja. ([#58](https://github.com/csukaj/muzikos/issues/58))

## 0.31.7 — 2026-10-24

- **Zenekari kezdőlap.** Új `kezdolap` eszköz: egy oldal (`Zenekarok/<zenekar>/kezdolap.html`), ahonnan a dallista, a koncertek,
  a felállások, a dalok adatlapjai és a logó egy kattintással elérhető. Az oldalsáv egy gombbal elrejthető és visszahozható,
  és újranyitáskor úgy marad. Az asztalon ikon van rá, belépéskor magától megnyílik. ([#65](https://github.com/csukaj/muzikos/issues/65),
  [#53](https://github.com/csukaj/muzikos/issues/53))

## 0.31.6 — 2026-10-24

- **A felállás-oldalon a bekötési rajz teljes szélességben** (a kijelzőhöz igazodva, görgetés nélkül, 1366×768-on
  lemérve), alatta a részletek, a próba előtti lista és a jelmagyarázat. ([#53](https://github.com/csukaj/muzikos/issues/53))

## 0.31.5 — 2026-10-24

- **Kikapcsolás és újraindítás egy ikonnal az asztalon.** Két ikon (Kikapcsolás, Újraindítás), egy megerősítéssel; ha a
  Reaperben mentetlen dal van, előbb szól. A szerver `--reaper-mentetlen` módja adja a mentetlen dalok listáját.
  ([#52](https://github.com/csukaj/muzikos/issues/52))

## 0.31.4 — 2026-10-24

- **Pontosabb Guitar Pro-kotta a felvételből (`gitar_kotta`).** Zajkapu a játék szintjéhez (a csend és a zúgás nem lesz
  hang); a hangolás tartománya alatti/feletti hang (kitalált C1) eldobva; az oktáv-kiugró hang a szomszédaihoz közeli
  oktávra kerül; az azonos hangmagasságú, rövid szünettel szétvált hangok egybeolvadnak; `egyszeru_riff` / `min_hangkoz_ms`
  a szellemhangok ellen. A válasz megmondja, milyen időtartományból dolgozott, és mit dobott el. Több elemre vágott
  sávnál az összes elemet kottázza (nem csak az utolsót), a fájlnévben másodperc van (két futtatás nem írja felül egymást),
  `elso_hangtol`: a kotta az első hang ütemétől indul. ([#50](https://github.com/csukaj/muzikos/issues/50))

## 0.31.3 — 2026-10-24

- **Jobb ütésfelismerő a ritmusigazításhoz.** A `javitas_hang` simított burkolóra és az ütem nyolcadának megfelelő
  minimális hangközre épül (az erősebb ugrás nyer, nem a korábbi), így a torzított, lecsengő basszus hullámzását nem
  veszi ütésnek (eddig 55 ms-onként „talált”). A válasz megmondja az ütések számát ütemenként; gyanúsan sok ütésnél
  (ütemenként 12 fölött) figyelmeztet, és az `apply`-t nem engedi (`force` felülírja). ([#49](https://github.com/csukaj/muzikos/issues/49))

## 0.31.2 — 2026-10-24

- **Kotta behozása a Reaperbe.** A hangok az eredeti hosszuk 55%-áig szólnak (`hossz`), így az ismételt hang
  (B♭ B♭ B♭ B♭) újra megszólal; a basszus sáv basszusos hangszínt kap (azonnali kezdet, rövid kioldás); az új sáv neve
  „Kotta: <név>”, nem ütközik a felvétel sávjával. ([#48](https://github.com/csukaj/muzikos/issues/48))

## 0.31.1 — 2026-10-24

- **Reaper-apróságok a próbáról.** Az `input_levels` egy hívásban az összes bemenetet megméri (ha a kártya több egységre
  bomlik, mindet egyszerre), és csatornánként megmondja a gain-teendőt (cél: -18…-6 dBFS). A `reaper_click` alapból a dal
  hosszáig szól, legalább 64 ütemig (eddig 16). A `reaper_metronome` szól, hogy a beépített metronóm a UMC főkimenetén
  nem hallatszik, a hallható klikk a Klikk-sáv. ([#47](https://github.com/csukaj/muzikos/issues/47))

## 0.31.0 — 2026-10-24

- **Hangútvonalak a hangkártya kihúzása után.** Új háttérfigyelő (belépéskor indul): a hangkártya ki-be dugása után
  magától visszakötődik a Reaper (a kártya bemenetei sorban a Reaper bemeneteire, a kimenetek az A párra), az asztal
  hangja az A párra áll, a beépített mikrofon és hangszóró kötései lekerülnek; a laptop mikrofonjának szintje
  induláskor 25%. A `reaper_reconnect` új `input` + `reaper_in` paramétere egy kötést tesz meg („a UMC 2-es bemenete
  menjen a Reaper 1-esére”), a `belso: "marad"` megtartja a beépített hangot. ([#51](https://github.com/csukaj/muzikos/issues/51))

## 0.30.3 — 2026-10-24

- **Reaper-apróságok:** a `.rpp` dupla kattintásra a Reaperben nyílik (MIME-típus, alapértelmezett megnyitó), és a
  Reaper nem kérdez frissítésről (`verchk=0`), a `reaper_start` a már meglévő beállításban is kikapcsolja.
  ([#6](https://github.com/csukaj/muzikos/issues/6))

## 0.30.2 — 2026-10-24

- **Zúgás, brummogás:** a Claude lépésenként végigvezet a hibakeresésen („zúg a hangszóró”: töltő, a dob USB-je,
  földhurok-leválasztó, közös konnektor), és megjegyzi a felállásban, mi segített. A `KELLEKEK.md` felsorolja az
  USB-leválasztót és a földhurok-leválasztót. ([#43](https://github.com/csukaj/muzikos/issues/43))

## 0.30.1 — 2026-10-23

- **Drive-szinkron az első gépen:** ha a Drive-on még nincs meg a zenekar szinkronmappája, létrehozza (eddig a
  biztonsági megállás hibát jelzett). A MuzikOS-kép VM-es próbája találta meg. ([#351](https://github.com/csukaj/clauding/issues/351))

## 0.30.0 — 2026-10-23

- **A hangrendszer egészsége** (Bence mUSBic-tapasztalatai alapján). Új `hangrendszer` (`muzikos_rendszer`):
  `allapot` (mintavétel, puffer, kimaradások, wifi, Guitarix neurális modell, a kártya profilja — érvénybe is lép);
  `wifi` ki/be; `mintavetel`; `hangolas` (terhelés alatt végigpróbálja a puffereket, a legkisebb kimaradás nélküli +
  egy fokozat tartalék lesz a kártya profilja, a kártya neve szerint); `korbeli` (oda-vissza késés hurokkábellel,
  jack_iodelay). A felvétel indítása előbb szól, ha a wifi be van kapcsolva hálózat nélkül, vagy a Guitarix neurális
  modellel 48 kHz-en fut; a leállítás megmondja a felvétel alatti hangkimaradásokat, és a `take_lista` take-enként
  mutatja (és a pontszámban is számít). ([#381](https://github.com/csukaj/clauding/issues/381),
  [#383](https://github.com/csukaj/clauding/issues/383), [#384](https://github.com/csukaj/clauding/issues/384),
  [#385](https://github.com/csukaj/clauding/issues/385))

## 0.29.0 — 2026-10-23

- **Hiányzó bemenetnél nincs csendes csere.** A `reaper_add_track` hibát ad, ha a kért bemenetbe nincs hangkártya
  bekötve (és megmondja, melyekbe van; `force` csak kérésre); a `reaper_reconnect` eszköznév nélkül a felállás
  hangkártyájára köt, és ha az nincs bedugva, nem köt helyette másikra; a `felallas` `activate` jelzi, ha a felállás
  hangkártyája hiányzik. Szabály a skillekben is. Bence (mUSBic) ötlete. ([#386](https://github.com/csukaj/clauding/issues/386))

## 0.28.0 — 2026-10-23

- **Távpróba egy irányban.** Új `tavproba` (`muzikos_tavproba`): a két gép Tailscale-en (privát hálózat, a belépés a
  zenészé), a hang JackTrip-pel, fix pufferrel; az otthoni gép a hangszert és a saját klikkjét küldi, a terem két
  monitorozott sávon hallja és felveszi. Az összerakás a hangból méri a késést és a két hangkártya órájának
  csúszását (GCC-PHAT a dal elején és végén, ellenőrzés középen), az otthoni felvételt új sávra teszi a csúszásnak
  megfelelő sebességgel, a hálózati sávokat elnémítja, a terem sávjait a rácsra tolja. A képbe: `jacktrip`,
  `tailscale`. ([#352](https://github.com/csukaj/clauding/issues/352))

## 0.27.0 — 2026-10-23

- **Fizikai teendők a valódi eszköz képén.** Új `muzikos_eszkoz`: eszközönként képtár (előlap, hátlap, közeli; a
  netről vagy fotóról, a forrással), rajtuk a portok, potik, kapcsolók jelölései (a Claude rakja fel, egy ember
  jóváhagyja az áttekintőn); `mutasd` kiemelt képet nyit az asztalon: a többi elsötétítve, a poti bekarikázva,
  forgatás-nyíl, felirat. ([#335](https://github.com/csukaj/clauding/issues/335))

## 0.26.0 — 2026-10-23

- **Egy zenekar = egy mappa, Drive-szinkronnal.** A zenekar minden adata a `MuzikOS/Zenekarok/<zenekar>/` mappában:
  `zenekar.json`, `memoria/` (dalok, setlistek), `felallasok/`, `Dalok/<dal>/`, dallista, koncertanyag, logó. A
  régi szerkezet (Tudas/zenekarok, Tudas/felallasok, Projektek) első induláskor átköltözik, az útvonalak a
  memóriában, a Reaper-projektekben és az oldalakon átíródnak. Új `zenekar_szinkron` (`muzikos_sync`): a zenekar
  mappája kétirányúan szinkronizálódik a zenekar Google Drive-mappájával (rclone bisync; a megosztott mappa is,
  azonosítóval), ütközésnél mindkét változat megmarad, net nélkül később pótol. A képbe: `rclone`.
  ([#351](https://github.com/csukaj/clauding/issues/351))

## 0.25.0 — 2026-10-23

- **Zenekari logó és dal-adatlap.** Új `zenekar_logo`: a logó a zenekar mappájába kerül, háttér nélkül, fejlécre
  méretezve; az egyszínűt az arculat színére festi (narancs / világos / eredeti), a többszínűt meghagyja, a sötétet
  világos lapra teszi (Pillow, tartaléknak ImageMagick; új `muzikos_logo`). A dallista, a koncertlista és az új
  `dal_adatlap` (a dal egy oldalon: kijelző, színes szerkezet, mappacsempék, jegyzetek) fejlécében a név helyett a
  logó áll (`style.page(brand=…)`). ([#373](https://github.com/csukaj/clauding/issues/373))

## 0.24.0 — 2026-10-23

- **Dúdolásból és beatboxból Guitar Pro-kotta.** A `gitar_kotta` új `source`-a: `dudolas` — a dúdolt vagy énekelt
  dallamból (vibrato simítva, csúszás és ismételt hang kezelve) gitár- vagy basszussáv, a hangszer fekvésébe téve;
  `beatbox` — a szájdob ütéseiből (2 ms-os felismerés, a hangszín szerint lábdob, pergő, lábcin) GP-dobsáv, a
  bizonytalanok jelölve, szóban javítható (`javitas`), kérésre a Reaperbe is (AVL), metronóm nélkül becsült tempóval.
  Új `muzikos_mouth`; a `write_gp5` dobsávot is ír. ([#375](https://github.com/csukaj/clauding/issues/375))

## 0.23.0 — 2026-10-23

- **Felvétel javítása.** Új `muzikos_fix`: `javitas_midi` a MIDI-sávot (dob: csak a kért dobok is) ritmusra igazítja
  erősséggel és a dinamikát kiegyenlíti, egy „javított” take-re (az „eredeti” visszaállítható); `javitas_hang` a
  hangsáv elcsúszott ütéseit (2 ms-os hangkezdet-felismerés) Reaper-nyújtásjelölőkkel húzza a rácsra, vágás
  nélkül; `utem_csere` egy rossz ütemet egy másik take ugyanazon ütemére cserél a „Végleges” rétegen, áttűnéssel.
  Mindegyik előbb csak megmutatja, mit változtatna. ([#326](https://github.com/csukaj/clauding/issues/326))

## 0.22.0 — 2026-10-23

- **Guitar Pro-sávok és Hydrogen-dob a Reaperbe.** Új `muzikos_import` és `import_reaperbe`: a .gp (GP7/8) és
  .gp5 kotta kiválasztott sávjai, illetve egy Hydrogen-dal (.h2song) dobja sávonként egy új Reaper-sávra kerül,
  hangjegyenként (a hídon: `muzikos.import_notes`) — a dob AVL Drumkits-szel a 10. csatornán, a gitár és a
  basszus ReaSynth-szel; a kotta tempója és ütemmutatói a projektbe. A dalmappában új `hydrogen/` almappa.
  ([#327](https://github.com/csukaj/clauding/issues/327))

## 0.21.0 — 2026-10-23

- **Take-ek és a végleges felvétel.** Új `muzikos_takes`: a sáv rögzített rétegekbe tehető (Reaper 7 fixed lanes,
  minden felvétel egy take), `take_lista` dalrészenként méri a take-eket (időzítés a 16-od rácshoz, csúcs,
  hangerő, túlvezérlés, csend) és javasolja a legjobbat okkal; `take_jegyzet` a zenészek értékelését a dal
  take-naplójába írja (újraindítás után is megvan); `take_comp` jóváhagyás után összevágja egy „Végleges” rétegre
  áttűnésekkel (az eredeti take-ek maradnak); `take_play` egy take-et vagy a véglegeset szólaltatja meg.
  ([#332](https://github.com/csukaj/clauding/issues/332))

## 0.20.0 — 2026-10-23

- **Guitar Pro-szinkron** (a dalmappák második része). Új `muzikos_gp`: a dal Guitar Pro-fájljából (.gp GP7/8,
  .gp5/.gp4/.gp3) kiolvassa a tempót, a tempóváltásokat, az ütemmutatót és a dalrészeket, és visszaírja beléjük a
  memória szerint (írás előtt mentés a `guitarpro/.elozmenyek/`-be). A `dal_szinkron` `check` a Guitar Pro-fájllal
  is összevet (a Reaper nélkül is), és új `from_gp` / `to_gp`: Reaper → memória → Guitar Pro, és vissza.
  ([#346](https://github.com/csukaj/clauding/issues/346))

## 0.19.0 — 2026-10-23

- **Keverőpultos design** (Józsi választása az első változat helyett): rackmodulok fémes panellel és csavarokkal,
  narancsban izzó kijelző a számoknak, színes LED-ek az állapotoknak, narancs fő kiemelés (a citromsárga helyett),
  piros felvétel; betűk: Orbitron (cím), Saira (szöveg), Share Tech Mono (kijelző). A `muzikos_style` új elemei:
  `lcd()`, `led()`, `part_chip()`; a dallista, a koncertlista (kijelzővel: számok, hossz, klikk és sampler oldala),
  a bekötési rajz (a kábelek a saját színükben izzanak), a fotóláda és a Reaper dalnézete (kijelzősáv, a mostani
  ütem nagy narancs számokkal) ebben a stílusban. ([#349](https://github.com/csukaj/clauding/issues/349))

## 0.18.0 — 2026-10-23

- **Saját arculat** (Józsi választása: „A — Színpad”): sötét, meleg alap, piros és sárga kiemelés, címek Archivo
  Blackkel, szöveg IBM Plex Sansszal, nagyobb betűk. A színek jelentést hordoznak: a tagoké, a dalrészeké, a dal
  állapotáé, a kábeleké és a jelzéseké mindenhol ugyanaz. Új `muzikos_style` (színek, oldalváz, állapotcímke,
  rövid súgó a jobb alsó „?” gombon); ezzel készül a dallista (állapotcímkék középre igazítva, a dalrészek
  színesen), a koncertlista, a bekötési rajz (sötét, a kábelek az új színekkel), a fotóláda oldala és a Reaper
  dalnézete (a dalrész színe, a mostani rész sárga keretben). A muzikos skill leírja, hogy a Claude új oldalt
  és ábrát is így rajzoljon. ([#349](https://github.com/csukaj/clauding/issues/349))

## 0.17.0 — 2026-10-23

- **Az új neve MuzikOS** (eddig MusicOS): a plugin `muzikos-skills`, az eszközszerver `muzikos`, a skillek
  `muzikos`, `muzikos-audio`, `muzikos-reaper`, `muzikos-memory`, `muzikos-rig`, `muzikos-drums`. A régi
  adatok megmaradnak: a PenSSD-Adat `MusicOS` mappája első indításkor `MuzikOS`-ra költözik (memória, projektek,
  felállások), a `MUSICOS_TUDAS` is működik még, és a Reaper indítószkriptjéből kikerül a régi híd sora.
  ([#361](https://github.com/csukaj/clauding/issues/361))

## 0.16.0 — 2026-10-23

- **Sampler, setlist és koncertanyag.** Új `sampler` (a számok előtt/után bejátszott hangok a dal `sampler/`
  mappájában és memóriájában; a próbán le is játssza), `setlist` (a zenekar setlistjei, a dalok munka- vagy
  publikus címén), és `koncert_anyag`: egy setlistből számonként sztereó wav, az egyik oldalon a klikk a dobos
  fülébe (tempó, ütemmutató, tempóváltások, szerkezet, előszámolás), a másikon a samplerhangok a közönségnek;
  kérésre egyben is, mellé áttekintő oldal és a bekötés javaslata. ([#362](https://github.com/csukaj/clauding/issues/362))

## 0.15.0 — 2026-10-23

- **Több felállás egy zenekaron belül.** A felállásnak fajtája van (szobapróba, próbaterem, koncert, otthoni — kié),
  és a zenekarhoz tartozik; a `felallas` `list` a mostani zenekaréit adja, az `activate` a mondat szavaiból is
  választ („most a teremben vagyunk”, „Bence otthon dolgozik”), és visszaadja a bekötést, a sávokat, a
  zenészeket és a teendőket. A rajz fejlécében a fajta és a gazdája. ([#363](https://github.com/csukaj/clauding/issues/363))

## 0.14.0 — 2026-10-23

- **Munkacím és publikus cím.** A dal a munkacímével indul (pl. Leprusz): ebből a mappa és a fájlnevek, és nem
  változik. A végleges címet a `publikus_cim` adja; a dal mindkét címén előjön, az export, a borító, az
  értesítő, a dallista és a dal megnyitása már a publikus címet mutatja.
  ([#365](https://github.com/csukaj/clauding/issues/365))

## 0.13.0 — 2026-10-23

- **Gitárból Guitar Pro-kotta.** Új `gitar_kotta`: egy gitár- vagy basszussáv felvételéből .gp5 tabbal — a
  hangfelismerés egyszólamú, tiszta (effekt nélküli) jelre és metronómra készült: hangmagasság (YIN),
  hangkezdetek (újrapengetés is), ritmus a dal tempója szerint (tizenhatod vagy nyolcad), húr és bund a
  legkisebb kézmozgással. Akkordot és akkordbontást a Spotify basic-pitch modelljével (ONNX, ha a gépen van):
  az egyszerre szóló hangok egy ütésbe, külön húrra kerülnek. Hangolás a kérésből, a dalnál a tagéból, a tag
  vagy a zenekar alaphangolásából (pl. D G C F A D, A D G C F). MIDI-sávból (MIDI-hangszedő) a hangjegyek egyenesen jönnek, húronkénti csatornával a
  húr is. A fájl a dal `guitarpro/` mappájába megy, és kérésre a TuxGuitarban nyílik meg. A tagok rövid nevén
  (`becenev`) is szólít és keres a Claude. ([#319](https://github.com/csukaj/clauding/issues/319))

## 0.12.0 — 2026-10-23

- **Export és megosztás a zenekarral.** Új `dal_export`: a dal mappájának `export/<dátum> <címke>/` alá mp3
  (256k, meghallgatásra) és wav (48 kHz/24 bit, megőrzésre); kérésre minden felvett sáv külön, és egy videó
  borítóképpel (a zenekar képe, vagy egy elkészített: a dal címe, a zenekar, a dátum) a YouTube-hoz. Visszaadja a
  fájlokat, a tagokat és az értesítő vázlatát; a musicos-reaper skill leírja a feltöltést (Drive: csak a tagokkal
  megosztva; YouTube: nem nyilvánosan) és az értesítést (csak jóváhagyás után). A zenekar tagjaihoz e-mail, a
  zenekarhoz kép is írható. Javítás: az ékezetes fájlnév (pl. „próba”) nem rontja el az mp3-átalakítást.
  ([#333](https://github.com/csukaj/clauding/issues/333))

## 0.11.0 — 2026-10-23

- **Belépős oldalakhoz egy saját, megmaradó Chrome: a Claude-Chrome.** Ha egy oldalhoz be kell lépni (claude.ai-artifact, bolti fiók, ügyfélkapu, admin felület), és Claude-nak kell olvasnia vagy lefényképeznie, egy állandó Chrome-profilt nyit (`%LOCALAPPDATA%\Claude-Chrome`), nem a beépített böngészőt, ami a mentett jelszavakat nem látja. A felhasználó egyszer bejelentkezik benne a Chrome-ba a Google-fiókjával: onnan a Google Jelszókezelő jelszavai és passkeyei felkínálódnak, a belépései megmaradnak a Chrome bezárása után is, és minden ügyfél pluginja ugyanezt a profilt használja. Claude a `browser-testing` skill új szkriptjével (`scripts/claude-chrome.mjs`: `start`, `status`, `text`, `shot`, `eval`) indítja és olvassa, csak a gépen belülről (127.0.0.1:9223); jelszót nem ír be, a jelszótárhoz és a sütikhez nem nyúl.
  ([csukaj/clauding#357](https://github.com/csukaj/clauding/issues/357))

## 0.10.0 — 2026-10-23

- **Elektromos dob felvétele: MIDI és hang egyszerre.** Új `reaper_midi_inputs` (mit lát a Reaper a MIDI-eszközökből,
  mi van bekapcsolva; bekapcsolás név szerint — egy frissen bedugott MIDI-eszköz a Reaperben alapból ki van
  kapcsolva, ezért nem jött belőle semmi) és `dob_midi_sav` (a dobmodul MIDI-bemenete bekapcsolva, MIDI-sáv a 10.
  csatornán AVL-dobkészlettel — Black Pearl, Red Zeppelin, Blonde Bop, HotRod —, és kérésre a modul saját hangja
  egy hangsávon, monitorozás nélkül). A `reaper_add_track` egy MIDI-eszközre is szűkíthető. A felvétel
  leállításakor a Reaper már nem nyit „mentsem-e a fájlokat?” ablakot, ami megakasztotta a Claude-ot.
  ([#328](https://github.com/csukaj/clauding/issues/328))

## 0.9.0 — 2026-10-23

- **Dalmappák, dallista és szinkronfigyelés (első rész).** Új `dalmappa` (a dal mappája `reaper/`,
  `guitarpro/`, `export/`, `kotta/`, `egyeb/` almappákkal és jegyzettel; fájlok besorolása kiterjesztés szerint),
  `dallista` (a zenekar dalai állapottal, tempóval, hangnemmel, szerkezettel, fájlokkal; olvasható oldal), és
  `dal_szinkron` (a memória és a Reaper összevetése; `from_reaper` / `to_reaper`). A `dal_megnyitas` az új
  projektet a dal `reaper/` mappájába teszi, és jelzi, ha a Reaperben kézzel változott valami. A Guitar Pro a
  következő részben. ([#346](https://github.com/csukaj/clauding/issues/346))

## 0.8.0 — 2026-10-23

- **Metronóm és tempótérkép.** Új `reaper_tempo` (tempó és ütemmutató egy ütemtől, fokozatos gyorsítás/lassítás,
  lista, törlés), `reaper_metronome` (a Reaper metronómja be/ki), `reaper_click` (saját klikksáv: követi a
  tempótérképet, kiemelt első ütés, nyolcadok/triolák, három hangszín, hangerő, kihagyott dalrészek, kérésre csak
  a fejhallgatóban), és `reaper_transport` `count_in` (előszámolás felvétel előtt).
  ([#344](https://github.com/csukaj/clauding/issues/344))

## 0.7.0 — 2026-10-23

- **Az akusztikus dob felvétele.** Új skill (`musicos-drums`) és eszközök: `dob_mikrofon_terv` (a meglévő
  bemenetekhez a legjobb felállás 1–8 mikrofonra: hely, mód, típus, 48V; `apply`: a Reaper-sávok és a bekötési
  térkép), `dob_fazis` (két mikrofon fázisa és késése egy ütésen), és `reaper_track_set` `phase_invert`.
  A bekötési térképen egy bemenetbe már csak egy dugó mehet (az ütköző régi kábel cserélődik, és a válasz
  megmondja, melyik). ([#334](https://github.com/csukaj/clauding/issues/334))

## 0.6.0 — 2026-10-23

- **Dalszerkezet élőben.** A dalírás közben elhangzó szerkezet (A, A', B ×2, C…) a dal memóriájába kerül, a
  korábbi változatok megmaradnak, és a Reaperbe is cserélhető (`dal_megnyitas` `replace_structure`). Új
  `reaper_song_view`: egy Reaper-ablak nagy betűvel mutatja a mostani részt, az ütemet benne, a következő részt
  és a váltás előtti visszaszámlálást, alul a dal sávjával. ([#341](https://github.com/csukaj/clauding/issues/341))

## 0.5.0 — 2026-10-23

- **Bekötési térkép, próba előtti útmutató és potiállások telefonos fotóról.** Új skill (`musicos-rig`) és
  eszközök: `felallas` (eszközök, portok, kábelek, zenészek, sávok; import egy kész fájlból), `felallas_kabel`
  („ma a basszus a 3-asba megy”: a régi kábel cserélődik), `felallas_rajz` (kattintható helyi weboldal, a
  kábelek fajtánként színezve, a potiállások számlapként, pipálható bekötési lista), `fotolada` (a telefonok a
  helyi hálózaton, QR-kóddal küldenek képet; egyszer használatos cím, csak képek, 15 perc), `foto_megnezes`,
  `potiallas` (mentés, lekérés; a Claude olvassa le a fotóról), `camera_snapshot` (tartalék: a laptop kamerája).
  ([#323](https://github.com/csukaj/clauding/issues/323))

## 0.4.0 — 2026-10-23

- **MusicOS-memória: a Claude megjegyzi a zenekarokat, a dalokat és amit megtanítottak.** Új skill
  (`musicos-memory`) és eszközök: `tudas` (minden egy pillantásra, vagy keresés), `zenekar` (tagok hangszerrel,
  bemenettel, sávval; váltás), `dal` (tempó, hangnem, szerkezet, projekt, jegyzetek), `recept` (megtanított
  teendők hívószavakkal), `szokas` (ki mit szeret, mit javított ki), és `dal_megnyitas` (a dal projektje
  megnyitva vagy létrehozva, a tempó és a dalrészek a memóriából). Fájlban a PenSSD-Adat `MusicOS/Tudas`
  mappájában. ([#325](https://github.com/csukaj/clauding/issues/325))

## 0.3.0 — 2026-10-23

- **Rájátszás és visszahallgatás késés nélkül.** Új `reaper_overdub` (mit vegyen fel és mit halljanak a
  zenészek: a felvett sávok szoftveres visszahangja ki, mert a zenész a hangkártyán közvetlenül hallja magát;
  a nem kért sávok némítva), `reaper_track_set` (élesítés, monitorozás, némítás, szóló, hangerő, panoráma,
  bemenet, név vagy sorszám szerint) és `reaper_cue_mix` (külön fejhallgató-keverés egy kimenetpárra,
  pre-fader). A musicos-reaper skillben a menet, és hogy mit csináljon a zenész a hangkártyán.
  ([#331](https://github.com/csukaj/clauding/issues/331))

## 0.2.0 — 2026-10-23

- **Dalszerkezet: a Claude leteszi a dal részeit, és „a második gyors résztől” indít.** Új `reaper_markers`
  (jelölők és dalrészek: a szerkezet egyben, menet közben szóban a mostani helyre ütemre kerekítve, átnevezés,
  mozgatás, törlés) és `reaper_part` (egy rész a zenész szavaival — sorszámmal, toldalékkal —: oda, onnan
  előszámolással, ismétlés, felvétel csak arra a részre). ([#336](https://github.com/csukaj/clauding/issues/336))

## 0.1.0 — 2026-10-23

- **Az első kiadás: a Claude kezeli a MusicOS zenei gépet.** A plugin egy helyi MCP-szervert hoz magával
  (Python, telepítés nélkül fut): hangkártyák és MIDI-eszközök, szintmérés bemenetenként, a PipeWire
  pufferének állítása, kattogás keresése, parancsfuttatás rendszergazdaként, képernyőkép, egér és
  billentyűzet, és a Reaper vezérlése egy Lua-hídon át (sáv, bemenet, élesítés, effekt, felvétel, tempó,
  metronóm, tetszőleges ReaScript). Három skill: `musicos` (a gép), `musicos-audio` (hang és késés),
  `musicos-reaper` (felvétel). ([#318](https://github.com/csukaj/clauding/issues/318))
- **Az első valódi próba (2026-10-23) javításai:** a Claude Desktopból indított eszközszerver maga pótolja
  a munkamenet környezetét (`XDG_RUNTIME_DIR`, `DISPLAY`, D-Bus), különben sem a hangrendszert, sem a
  Reapert nem érte el; új `reaper_reconnect` (a Reaper visszakötése a hangkártyára kihúzás–visszadugás
  után) és `audio_default` (az asztal hangja ne menjen egy frissen bedugott pedálba); a Reaper bezárása
  minden fület ellenőriz, mentetlen dalnál nem zár be; a skillekben a mentés helyes módja, a lemért
  eszközök (UMC404HD, GP-50 hangkártyaként, Nitro MIDI), és a Reaper megakadásának gyakori oka.
