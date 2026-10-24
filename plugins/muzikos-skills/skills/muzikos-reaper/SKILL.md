---
name: muzikos-reaper
description: >-
  A Reaper vezérlése a MuzikOS-en a zenészek helyett: sáv a bedugott hangszernek a jó bemenettel
  (a szintmérésből kiderül, hol szól), élesítés, monitorozás, erősítő-szimulátor (Neural Amp Modeler,
  Guitarix), MIDI-sáv elektromos dobnak, tempó, metronóm, felvétel indítása és leállítása, mentés,
  gyakorló- és zenekari projekt összerakása, és bármi más a teljes ReaScript API-val (reaper_lua). A
  muzikos MCP-szerver egy Lua-hídon át beszél a Reaperrel. Használd, valahányszor a Reaper, egy sáv, egy
  felvétel vagy egy projekt kerül szóba. Hívószavak: "bedugtam a gitárt, vegyél fel neki sávot", "vegyük
  fel", "indítsd a felvételt", "állj", "legyen 120 a tempó", "kapcsold be a metronómot", "rakj rá
  erősítőt", "csinálj egy zenekari projektet", "rakd be a dobot a Guitar Próból", "hozd át a Hydrogen-dobot", "a pergő siet, igazítsd", "bedúdolom a riffet", "beatboxolom a dobot",
  "cseréld ki a 17. ütemet", "kapcsold be a távpróbát", "rakd össze a távpróbát",
  "mentsd el", "nem indul a Reaper".
---

# Felvétel a Reaperben

A Reapert a **muzikos MCP-szerver** vezérli egy Lua-hídon át (`reaper_bridge.lua`). A hidat a
`reaper_start` telepíti a Reaper `Scripts` mappájába, és a `__startup.lua` minden induláskor
elindítja. A híd a Reaper teljes ReaScript API-ját eléri: amit a kényelmi eszközök nem tudnak, azt a
`reaper_lua` igen.

## Indulás

1. `reaper_start` — elindítja a Reapert (ha nem fut), megvárja a hidat, és megmondja a hangeszközét.
2. **Ha a `hang.mod` nem JACK**, vagy nincs bemenet (`bemenetek: []`): `reaper_audio_system`
   (`system: "jack"`). Ez bezárja a Reapert (mentetlen projektnél nem!), átírja a beállítását, és
   addig próbálja, amíg a Reaper JACK-en nem szól. A megtalált `linux_audio_mode` értéket írd fel a
   válaszodba (legközelebb `mode`-dal egyből megy).
3. Ha a Reaper elindult, de a híd nem válaszol: `screenshot` — egy ablak vár, és amíg nyitva van, a
   híd áll. Gyakori okok: első indítás, licenc-emlékeztető, vagy **a Reaper újranyitná a legutóbbi
   dalokat, de a fájljuk nem érhető el** (pl. a PenSSD-Adat nincs csatolva: `udisksctl mount -b
   /dev/disk/by-label/PenSSD-Adat`). Kattints rá (`mouse`), aztán újra `reaper_status`.
4. **Ha a `reaper_status` bemenetei „not connected”-et mutatnak** (a hangkártyát kihúzták és
   visszadugták, vagy a Reaper előbb indult, mint hogy a kártyát bedugták): `reaper_reconnect` — a
   Reaper JACK-portjait visszaköti a hangkártyára (a bemeneteket sorban, a kimenet 1–2-t a kártya első két
   kimenetére). A Reaper ezt magától nem teszi meg.

A MuzikOS-en a Reaper JACK-módja `linux_audio_mode=0` (lemérve). Egy mentetlen dal mellett a Reaper nem
zárható be a hídon át (`reaper_audio_system` ezt jelzi): előbb mentés, vagy rákérdezés, eldobható-e.

## „Bedugtam a gitárt, vegyél fel neki sávot”

**Csatornát csendben ne cserélj.** Ha a felállás vagy a memória szerinti bemenet (vagy hangkártya) nincs meg —
kihúzták, más kártya van bedugva, a csatornán nincs jel —, mondd meg, mi hiányzik, és kérdezd meg, mi legyen;
magadtól ne válassz helyette másik bemenetet vagy kártyát: egy rossz csatorna csendben tönkreteszi a felvételt.
A `reaper_add_track` és a `reaper_reconnect` ilyenkor hibát ad (a `force`/`device` csak a zenész kérésére).

1. `audio_devices` → látszik-e a hangkártya (ha nem: muzikos-audio).
2. `input_levels` — **kérd meg, hogy játsszon közben**; a `jel: van` csatorna a bemenete. Ha több is
   szól, kérdezz rá, melyik a gitár. Ha túlvezérel vagy túl halk, szólj (gain).
3. `reaper_add_track`:
   ```json
   {"name": "Gitár", "input": 1, "fx": ["Neural Amp Modeler"]}
   ```
   - gitár, basszus: mono, `fx`: `Neural Amp Modeler` (ha nincs hozzá profil betöltve, a `Guitarix`
     is jó kezdésnek);
   - ének: mono, effekt nélkül (vagy `ReaEQ`, `ReaComp`);
   - sztereó forrás (billentyű, keverő): `stereo: true`, az `input` az első csatorna;
   - elektromos dob: `dob_midi_sav` (muzikos-drums skill, „Elektromos dob”);
   - MIDI-billentyű, MIDI-pedál: előbb `reaper_midi_inputs` `enable` (egy frissen bedugott MIDI-eszköz a
     Reaperben alapból ki van kapcsolva, és a sáv élesítve is üres marad), aztán `kind: "midi"`.
4. Mondd meg, mi lett: a sáv neve, melyik bemeneten, élesítve, monitorozva, milyen effekttel — és hogy
   a `nem_talalt_effektek` közt van-e valami (akkor ajánlj másikat).

**Tiszta jel a felvételen:** a Reaper a bemenetet veszi fel, effekt nélkül (`I_RECMODE` = bemenet); az
erősítő-szimulátor csak a hallgatáshoz és a lejátszáshoz szól. Így később másik hangzás is ráadható, és
a kottafelismerés (gitárból Guitar Pro-fájl) is ebből a tiszta jelből dolgozik.

## Felvétel

- `reaper_transport` `tempo: 120, metronome: true` → a dal tempója és a metronóm.
- `reaper_transport` `action: "record"` → felvétel; `action: "stop"` → leállítás (a Reaper megtartja a
  felvett részt); `action: "start"` → az elejére; `action: "save"` → mentés.
- Felvétel előtt: van-e hely (`system_status`), és hova ment a projekt (`reaper_status`:
  `felvetel_mappa`). Ha még mentetlen, mentsd el a felvételek helyére (a muzikos skill *Mi hol van*
  táblája) a `reaper_project` `save_as`-szal, pl. `path: ".../MuzikOS/Projektek/2026-10-23 próba/próba.rpp"`.
  **Ne** a `reaper.Main_SaveProjectEx`-szel: az csak egy másolatot ír, a projekt mentetlen marad, és a
  felvétel a `~/Documents/REAPER Media` alá menne (lemérve a MuzikOS-en, 2026-10-23).

## Dalok: új, megnyitás, váltás

Egy dal = egy Reaper-projekt (`.rpp`), mindegyik a saját **fülén** — így több dal is nyitva lehet,
és köztük váltani egy kattintás (`reaper_project`):

- `action: "list"` — a nyitott dalok: fül, név, fájl, mentetlen-e, hány sáv, melyik a mostani;
- `action: "new", path: ".../Projektek/<dal>/<dal>.rpp"` — új dal új fülön, rögtön a helyére mentve;
- `action: "open", path: ...` — megnyitás (ha már nyitva van, csak odavált; ha a mostani fül nem üres,
  új fülön nyit, így semmi nem vész el);
- `action: "switch", path: "<a dal nevének része>"` vagy `tab: 2` — váltás;
- `action: "save_as", path: ...` — mentés másként (pl. egy változat: „… – B verzió.rpp”).

A dal mappája a felvételek helye is (a Reaper a projekt mellé, a `Media` alá veszi fel). Hogy egy
zenekar dalai hol vannak, azt a felvételek helye mondja meg (muzikos skill, *Mi hol van*).

## Visszahallgatás, tekerés, ismétlés

`reaper_transport` — egyszerre több is mehet:

- **beletekerés:** `measure: 17` (a 17. ütemre) vagy `position: 42.5` (másodpercre), és `action: "play"`;
- **egy rész ismétlése:** `loop: {"from_measure": 9, "to_measure": 17}` (a 9. ütem elejétől a 17. elejéig),
  vagy `loop: {"from": 30, "to": 45}`, és `action: "play"` — addig szól körbe, amíg `action: "stop"`;
  ismétlés ki: `loop: false`;
- a zenész ütemben gondolkodik („a refrén”, „a szóló”): ha nem tudod, hányadik ütem, nézd meg a
  projekt markereit/régióit (`reaper_lua`: `reaper.EnumProjectMarkers`), vagy kérdezz rá.

## Rájátszás és visszahallgatás, késés nélkül

A szabály: **a zenész a saját élő hangszerét a hangkártya közvetlen monitorozásán hallja** (késés nélkül), **a
Reaperből csak a már felvett sávok jönnek.** A felvett sávok lejátszása nem késik, és a Reaper az új felvételt
a lejátszáshoz igazítja (a hangkártya mért késésével), tehát a rájátszás időben a helyére kerül.

- **„Vegyük fel a két gitárt a dobra”:** `reaper_overdub` `record: ["Gitár 1", "Gitár 2"]`, `hear: ["Dob"]`.
  A gitársávok élesítve, a szoftveres monitorozásuk **ki** (különben a zenész kétszer hallaná magát, másodszor
  késve); a dob szól, a többi némítva. Utána `reaper_part` `record` vagy `reaper_transport` `record`.
- **Mondd meg a zenésznek, mit csináljon fizikailag:** a UMC404HD elején a **MONITOR (input/playback)** gomb
  állítja, mennyit hall az élő bemenetekből és mennyit a gépből — középállás a jó kezdés; a bemenetek melletti
  gombok (1–4: mono/sztereó) szerint az élő hang középen vagy oldalt szól. A GP-50 fejhallgató-kimenetén is a
  pedál élő hangja jön, késés nélkül.
- **Ha valaki az erősítő-szimulátort akarja hallani** (NAM a sávon): annak a sávnak a monitorozása kell (`direct_monitor:
  false`, vagy `reaper_track_set` `monitor: "on"`), kis pufferrel (`set_latency` 64–128). Ekkor a hangkártya közvetlen
  monitorozását arra a bemenetre le kell venni, különben duplán szól.
- **„Csak a dobot és az én gitáromat akarom hallani”:** `reaper_overdub` `hear: ["Dob", "Gitár 1"]` (vagy
  `reaper_track_set` `mute`/`solo`).
- **Külön fejhallgató-keverés zenészenként:** a hangkártya további kimenetei (UMC404HD: 3/4) → fejhallgató-erősítő;
  `reaper_cue_mix` `out: 3`, `levels: {"Dob": 0, "Gitár 1": -3, "Gitár 2": -9}`. A fő keverés (1/2) ettől nem
  változik. Ehhez fejhallgató-erősítő és kábel kell: írd fel a bekötési térképre (#323).
- A felvétel után: `reaper_track_set` `track: [...]`, `arm: false`, és a némítások vissza (`mute: false`), hogy
  a visszahallgatásnál minden szóljon.

## Metronóm, tempó, ütemmutató

- **Tempó és ütemmutató egy ütemtől:** `reaper_tempo` `action: "set"`, `measure: 17`, `bpm: 90`,
  `time_signature: "6/8"` („a 17. ütemtől 6/8, 90”). A dal eleje: `measure: 1`.
- **Fokozatos gyorsítás/lassítás:** `action: "ramp"`, `measure: 25`, `to_measure: 27`, `to_bpm: 140` („a 25–26.
  ütem alatt gyorsuljon 140-re”) — a 25. ütemtől a 27. elejéig egyenletesen. `list` a térkép, `clear` egy
  ütemtől töröl. A tempó a Reaperben **negyedekben** értendő (6/8-ban is); ha a zenész nyolcadokban vagy
  pontozott negyedekben számol, váltsd át, és mondd ki, mire állítottad.
- **A Reaper metronómja:** `reaper_metronome` `on: true/false`.
  **Figyelem:** a beépített metronóm a UMC főkimenetén nem hallatszik (nincs a fő keverésben). A hallható klikk a **Klikk-sáv** (`reaper_click`): alapból a dal hosszáig szól (legalább 64 ütemig), és a fő keverésen át a UMC főkimenetén is hallatszik. Mondd el a zenésznek, melyiket használod.
- **Testre szabott klikk** (`reaper_click`): egy „Klikk” sáv, ami a tempótérképet és az ütemmutatót követi;
  `sound: "magas" | "mely" | "fa"`, `volume_db`, `accent` (az első ütés más hang és erősebb), `subdivision:
  "8" | "triola" | "16"`, `skip_parts: ["Szóló"]` („a szólónál ne legyen klikk”), és **`headphones_only: true`,
  `out: 3`** — csak a fejhallgatóba (a 3/4-es kimenetre) megy, a fő keverésbe és az exportba nem. A tempó vagy
  a szerkezet változása után hívd újra (újraírja).
- **Előszámolás felvételhez:** `reaper_transport` `action: "record"`, `count_in: 2` (a lejátszás két ütemmel
  korábban indul, a felvétel a mostani helytől), vagy `reaper_part` `count_in`.
- Ha valaki kéri („én nem kérek klikket a szólónál”), írd fel a szokásai közé (`szokas`).

## Dalszerkezet: jelölők és dalrészek

A zenészek részekben gondolkodnak („a második gyors rész”, „a refrén”, „Marci szólója”). Ezeket a Reaperben
**dalrészek** (régiók, elejük és végük van) és **jelölők** (egy pont) tartják — `reaper_markers`:

- **A dal szerkezete egyben**, ha elmondják: `action: "structure"`, `parts: [{"name": "Intro", "bars": 4},
  {"name": "Verze", "bars": 8}, {"name": "Gyors rész", "bars": 8}, …]` (egymás után, a `start_measure`-től;
  `replace: true` a régieket előbb törli). A tempót előbb állítsd be (`reaper_transport` `tempo`), mert az
  ütem → másodperc ebből jön.
- **Menet közben, szóban:** „itt kezdődik a refrén” → `action: "add"`, `name: "Refrén"` — a mostani
  pozícióra (lejátszás közben a lejátszófej), **a legközelebbi ütemre kerekítve** (`snap: false` nélkül);
  egy ütemre: `measure: 17`; egy részt: `measure` + `to_measure`.
- Átnevezés, mozgatás, törlés a zenész szavaival: `action: "rename" | "move" | "delete"`, `name: "második gyors rész"`.
- `action: "list"` — mind, ütemszámmal; ezt olvasd fel, ha kérdezik, mi hol van.

**Használat — `reaper_part`:** `part` a zenész szavaival (sorszámmal is: „második”, „2.”, „utolsó”;
toldalékkal is: „résztől”, „refrénre”):
- `action: "goto"` — oda; `"play"` — onnan, egy ütem előszámolással (`count_in`);
- `action: "loop"` — a rész ismétlése (leállítás: `reaper_transport` `action: "stop"`, `loop: false`);
- `action: "record"` — **felvétel csak arra a részre** (auto-punch), egy ütem előszámolással: a rész előtt is
  szól a lejátszás, de csak a rész kerül a felvételre. A rész végén `reaper_transport` `stop`.
- Ha több ilyen nevű rész van, a válasz felsorolja őket ütemszámmal: mondd meg, melyiket vetted.
- Ha nincs ilyen rész, a válasz felsorolja a dal részeit: kérdezz rá, vagy tedd le (`reaper_markers`).

A zenekar dalainak szerkezete (hány ütem a verze, a refrén) a MuzikOS-memóriában is megvan (#325); ha ott
van, onnan rakd le a részeket.

### Dalírás közben: kövesd a szerkezetet

Ha a zenekar beszélget a dalról („legyen egy A, aztán A', aztán két B, aztán C”), **jegyezd folyamatosan**:
`dal` `set` `data: {"szerkezet": [{"nev": "A", "utem": 4}, {"nev": "A'", "utem": 4}, {"nev": "B", "utem": 8},
{"nev": "B", "utem": 8}, {"nev": "C", "utem": 4}], "temak": {"A": "riff E-ben", "A'": "ugyanaz, a végén váltás"}}`.
Minden módosításnál (`szerkezet` új listával) a régi változat megmarad (`korabbi_szerkezetek`; a
`valtozat_neve` nevet ad neki). Ha nem hangzik el, hány ütem egy rész, kérdezz rá, vagy hagyd 8-on és mondd
meg. Kérdezz vissza, ha kétértelmű („a második B ugyanaz, mint az első?”). A Reaperbe:
`dal_megnyitas` `replace_structure: true` (a dalrészeket a memória szerint cseréli).

### A „hol tartunk” kijelző

`reaper_song_view` `open` — egy Reaper-ablak, nagy betűvel: a mostani rész, hányadik ütem benne, a következő
rész, és a váltás előtt 4 ütemmel visszaszámlálás („C jön 2 ütem múlva”); alul a dal sávja a lejátszófejjel;
felvételkor piros „● FELVÉTEL”. Tedd egy külső monitorra, vagy húzd nagyra, hogy mindenki lássa.
`state` — mit mutat most (ha a zenész kérdezi, hol tartunk).

## Export

`reaper_render` — a teljes keverés (master) fájlba:

- `path: ".../Exportok/<dal> 2026-10-23.mp3"` — mp3 (WAV-ból ffmpeg-gel; a WAV is megmarad);
- `.wav` útvonal — csak WAV (48 kHz, 24 bit);
- csak egy rész: `from_measure`/`to_measure` vagy `from`/`to` (másodperc).

Utána mondd meg, hova ment és mekkora; visszahallgatni a `reaper_transport`-tal (a projektben) vagy
egy lejátszóval lehet (`run_command`: `xdg-open <fájl>`).


### „Töltsd fel a mai próbát a zenekarnak”

1. `dal_export` `title`, `label` („próba”, „take 3”) — a dal mappájába, `export/<dátum> <label>/`: mp3 (256k,
   meghallgatásra) és wav (48 kHz/24 bit, megőrzésre). `stems: true` — minden sáv külön wav (a további
   munkához); `video: true` — mp4 a YouTube-hoz egy borítóképpel (a zenekar `kep`-e, vagy egy elkészített: a dal
   címe, a zenekar, a dátum).
2. **Feltöltés** a Claude Google-eszközeivel, ha vannak (a zenekar saját Google-fiókja; a belépést ők végzik):
   - Drive: a zenekar mappájába, `<Zenekar>/<Dal>/<dátum>` alá (nagy fájlnál a feltöltő munkamenettel), és
     megosztás CSAK a tagokkal (a `dal_export` válaszában a tagok e-mail-címe; ha nincs, kérdezd meg, és írd a
     `zenekar` tagjához);
   - YouTube: a videó **nem nyilvánosan** (unlisted, vagy csak meghívottaknak); címe „<Dal> – <dátum> <label>”,
     leírásában a zenekar, a dal, a take.
   Ha nincs Google-eszközöd, mondd meg, hogy a fájlok hol vannak, és a PenSSD-n a Windows vagy a telefon is
   látja őket.
3. **Értesítő:** a `ertesito_vazlat` a linkkel, a zenekar csatornáján (e-mail, Messenger, WhatsApp). Mutasd meg
   a szöveget és a címzetteket, és csak kimondott igen után küldd el; csatorna nélkül add kimásolhatóan.

## Gitárból Guitar Pro-kotta

„Csináld meg ebből a riffből a Guitar Pro-t” → `gitar_kotta`:

1. **Felvétel hozzá:** tiszta jel (DI, a hangkártya bemenete effekt nélkül — a `reaper_add_track` így is
   veszi fel, a fejhallgatóban közben szólhat az erősítő-szimulátor), **metronómra** (`reaper_metronome` vagy
   `reaper_click`). Előszámolással (`count_in`), hogy az első hang is ütemre jöjjön. Akkordot, akkordbontást
   a többszólamú felismerés (basic-pitch, `mode: "auto"`, ha a gépen van) is lekottáz; egyhangos riffnél a
   `mode: "mono"` lehet pontosabb.
   **Kottázás előtt kérdezd meg a zenésztől** (egy kérdés): milyen hangokat játszott (a kiinduló hang, a lépések,
   pl. „B♭ ismétlések, aztán kvint”), és egy húron volt-e. Ha tudod, a felismerés eredményét ehhez mérd.
2. `gitar_kotta` `{"track": "Csabi", "title": "<a dal>"}` — a sáv felvételéből (több elemre vágott sávnál az összes
   elemből; `item` egy adott elem), a dal
   tempója szerint; a basszust a sáv nevéből felismeri (vagy `instrument: "bass"`). A hangolás a dalnál a
   tagé, a tag vagy a zenekar alaphangolása (a memóriában `hangolas`, pl. „D G C F A D”); ha egy dalban
   áthangolnak, írd a dalhoz: `dal` `set` `data: {"hangolas": {"Csabi": "C G C F A D"}}`, vagy add meg
   `tuning`-gal. A fájl a dal `guitarpro/` mappájába megy. `open: true` megnyitja a TuxGuitarban.
3. Mondd el röviden: hány ütem, hány hang, az eleje (`elso_hangok`), a `tisztitas` mezőből, milyen időtartományból
   dolgozott, és mit dobott el (hangtartományon kívüli, összeolvasztott töredék, oktáv-javítás), és hogy a fogást (húr, bund) a legkisebb
   kézmozgásra számolta — a gitáros lehet, hogy máshol fogja, azt a TuxGuitarban vagy a Guitar Próban
   átírhatja.
4. Ha sok a hiba: tisztább jel (effekt nélkül), lassabb tempó, pontosabb játék a metronómra; nyolcados
   témánál `grid: 8` (kevesebb téves tizenhatod); szellemhangoknál `egyszeru_riff: true` (két hang közt legalább az
   ütem nyolcada); `elso_hangtol: true`, ha a felvétel elején hosszú csend van (a kotta az első hang ütemétől
   indul, az eltolást megmondja). A hangkezdet alapból a hangerő ugrásából jön (`onset: "burkolo"`), ami a
   torzított, lecsengő jelre is jó; a spektrális változás: `onset: "flux"`.

### Szájjal: dúdolásból és beatboxból kotta

Ha nincs kéznél hangszer: a mikrofonba dúdolt vagy énekelt témából gitár- (vagy basszus-) sáv, a szájdobból
(beatbox) dobsáv. Felvétel egy mikrofonsávra, lehetőleg metronómra, aztán ugyanaz a `gitar_kotta`:

- **Dúdolás:** `{"track": "Márk", "source": "dudolas", "title": "<a dal>"}` (basszusra `instrument: "bass"`). A
  dallamot oktávval a hangszer fekvésébe teszi (mondd meg, ha eltolta), a hangolás a szokásos (a dalé, a tagé, a
  zenekaré). Egyenletes, tiszta dúdolás kell, egyszerre egy hang; az ismételt hangok közt kicsit álljon meg a hang.
- **Beatbox:** `{"track": "Márk", "source": "beatbox", "title": "<a dal>"}` — mély „b/pumm” = lábdob, „k/pf/csa” =
  pergő, „ts” = lábcin. Ütésenként megmondja, melyik dob lett és mennyire biztos; a bizonytalanokat kérdezd meg a
  sorszámukkal („a 7. ütés lábdob vagy tam?”), és a válasszal futtasd újra: `javitas: {"7": "tam"}`. `reaper: true`
  a dobsávot a Reaperbe is beteszi (AVL-dobkészlet). Metronóm nélkül vett fel: `tempo: "becsul"` (az első ütés lesz
  az 1. ütem eleje).

MIDI-sávból (MIDI-hangszedő, pl. Fishman TriplePlay) a hangfelismerés kimarad: a hangjegyek egyenesen
jönnek; ha a hangszedő húronként külön csatornán küld, `midi_string_channels: true` a húrt is átveszi.

## Guitar Pro-sávok és Hydrogen-dob a Reaperbe

„Rakd be a dobot és a basszust a Guitar Próból, arra gyakorolunk” → `import_reaperbe`:

1. Melyik fájl: `path`, vagy `title` (a dal) — ekkor a dal `guitarpro/` mappájának legújabb kottája, illetve
   `forras: "hydrogen"`-nel a `hydrogen/` mappa legújabb Hydrogen-dala (.h2song). Előbb `list: true`: milyen
   sávok vannak benne (név, dob-e, hány hang) — a LEM-kottákban a sávok a tagok nevei (Bálint, Csuka…).
2. `import_reaperbe` `{"title": "<a dal>", "tracks": ["Bálint", "Csuka"]}` — sávonként egy új Reaper-sáv,
   hangjegyenként (MIDI): a dob az AVL Drumkits-szel (GM-kiosztás, 10. csatorna), a gitár és a basszus egy
   egyszerű szintetizátorral (ReaSynth; `fx`-szel más). Alapból a kotta tempója és ütemmutatói is a projektbe
   kerülnek (a projekt eddigi tempójelölői helyett); `tempo: "marad"` a projekt tempóját hagyja, `at_measure`
   egy későbbi ütemtől teszi be (ilyenkor alapból marad a tempó).
3. A Hydrogen-dalnál a dob a Hydrogen-készlet GM-hangjegyeiről jön (a GM-készleteknél pontos, más készletnél a
   hangszer nevéből: kick, snare, hat, tom…); a minták a dal sorrendjében, a tempóváltásokkal.
4. Mondd el röviden: melyik sáv jött át, hány hanggal, milyen hangszerrel, és hogy mi lett a tempó. Ha a
   hangszer hiányzik (pl. nincs AVL), a sáv néma: `fx`-szel adj neki mást.

A .gpx (Guitar Pro 6) nem megy: mentsék el .gp-ként. Az ellenkező irány (felvételből kotta) a `gitar_kotta`.

## Take-ek és a végleges felvétel

Ha egy részt vagy dalt többször vesztek fel, a Claude vezeti, melyik take hol a legjobb, és a végén összevágja.

1. **Felvétel előtt:** `take_lista` `{"track": "Csabi", "prepare": true}` — a sáv rögzített rétegekbe kerül:
   minden új felvétel új réteg (take) lesz, a régiek megmaradnak.
2. **Felvétel közben/után a zenészek véleménye** a take-naplóba: „a 3. take verzéje jó, a refrén vége elcsúszott”
   → `take_jegyzet` `{"title": "<a dal>", "track": "Csabi – gitár", "take": 3, "part": "Verze", "jegy": 5,
   "megjegyzes": "…"}` (jegy 1–5). A napló a dal memóriájában van, a következő próbán is megvan.
3. **Elemzés és javaslat:** `take_lista` `{"track": "Csabi", "title": "<a dal>"}` — dalrészenként (a Reaper
   dalrészei szerint) minden take: időzítés a 16-od rácshoz (ms), csúcs, hangerő, túlvezérlés, csend, a napló; és
   részenként a javasolt take az okával. Mondd el röviden, kérdezd meg, jó-e. Meghallgatni egy take-et:
   `take_play` `{"track": "Csabi", "take": 2}`.
4. **Összevágás, csak jóváhagyás után:** `take_comp` `{"track": "Csabi", "title": "<a dal>", "use_suggestion": true}`
   vagy `choice: {"Verze": 3, "Refrén": 1}` — egy „Végleges” rétegre, áttűnéssel a vágásoknál (`fade_ms`, alap
   15), és csak az szól. Az eredeti take-ek nem változnak; újra összevágható más választással, és a Reaperben a
   Ctrl+Z is visszavonja. A végleges után: `take_play` take nélkül.

## Felvétel javítása: elcsúszott és rossz hangok

„A refrénben a pergő siet”, „a 17. ütem rossz, cseréld a 2. take-ére” — mindig két lépés: **előbb megmutatod**, mit
változtatnál (apply nélkül), és **csak jóváhagyás után** írod át (`apply: true`). Az eredeti mindig megmarad.

A rész: `part` (a dalrész neve, ahogy a Reaper jelölői mutatják), vagy `from_measure`–`to_measure`; a rács `grid`
(16 = tizenhatod, 8 = nyolcad, 12 = triola-nyolcad); az erősség `strength` 0–100 (alap 70: közelebb a rácshoz, de
élő marad; 100 = pontosan a rácsra).

- **MIDI (dob, MIDI-gitár, billentyű):** `javitas_midi` `{"track": "Bálint", "part": "Refrén", "drums": ["pergő"]}`
  → hány hang, átlagosan és legfeljebb hány ms-ot csúszik, mennyi marad az igazítás után; `velocity` (0–100) a
  dinamikát egyenlíti az átlag felé (a szórást is mutatja). Átírás: ugyanez `apply: true`-val — egy „javított”
  take-re, az „eredeti” megmarad az elemen; `restore: true` visszaváltja.
- **Hangsáv (gitár, basszus, ének):** `javitas_hang` `{"track": "Csabi", "from_measure": 17, "to_measure": 17}` →
  az ütések, és amelyek `min_ms`-nál (alap 10) jobban csúsznak, ütem.ütéssel (+ késik, − siet). Átírás `apply:
  true`: Reaper-nyújtásjelölőkkel húzza a rácsra — a hangfájl nem változik, nincs vágás, nem pattog; `restore:
  true` a rész jelölőit törli. Hosszan kitartott, lassan induló hangoknál (vonós, pad) a felismerés bizonytalan:
  ott inkább ütemcsere.
- **Rossz ütem cseréje egy másik take-ből:** `utem_csere` `{"track": "Csabi", "from_measure": 17, "take": 2}` — a
  „Végleges” rétegen cserél (ha még nincs, a most szóló take-ből lesz), áttűnéssel a vágásoknál (`fade_ms`, alap
  15); az eredeti take-ek maradnak. Hozzá a sávnak rétegekben kell lennie (lásd: Take-ek).

Mondd el röviden, és mindig tedd hozzá: a Reaperben a Ctrl+Z is visszavonja. Ének hangmagasság-javításhoz
(ReaTune) még nincs eszköz: azt a `reaper_lua`-val, a ReaTune effekttel lehet.

## Távpróba: valaki otthonról játszik

Egy irányban: aki otthon van (pl. Bálint a dobbal), klikkre és kísérőre játszik, a termet nem hallja; a terem őt
hallja, fix késéssel, és hozzá igazodik. Utána a Claude összerakja: az otthoni, teljes minőségű felvétel a helyére
kerül.

1. **Hálózat (gépenként egyszer):** `tavproba` `halozat` — ha nincs belépve: `belepes`, és a böngészőben **a zenész
   lép be** a Tailscale-be (mindkét gépen ugyanazzal a fiókkal, vagy a fiók meghívja a másikat). Utána a `halozat`
   mutatja a másik gépet.
2. **Otthon, a dal projektjében** (a zenekar mappájából, Drive-szinkron után ugyanaz, mint a teremben): a kísérő a
   korábbi felvételek, vagy ha még nincs, a Guitar Próból behozott sávok (`import_reaperbe`); klikk be
   (`reaper_click`); a saját sávja élesítve. Aztán `tavproba` `{"action": "inditas", "szerep": "otthon", "gep":
   "<a termi gép neve>", "sav": "Bálint", "nev": "Bálint"}`: a hangszer és a klikk megy a terembe.
3. **A teremben:** `tavproba` `{"action": "inditas", "szerep": "terem", "nev": "Bálint"}` — két új, monitorozott sáv
   („Bálint (hálózat)”, „Klikk (hálózat)”): ezt hallják. A `keses` megmondja, nagyjából mennyivel később.
4. **Felvétel:** otthon **a projekt elejéről** indul (count-in-nel); a teremben a hálózati sávok is felvétel
   alatt vannak (az összerakáshoz kellenek). A végén mindkét helyen mentés, és **szinkron** (`zenekar_szinkron`),
   hogy az otthoni felvétel átjöjjön.
5. **Összerakás a teremben:** `tavproba` `{"action": "osszerakas", "path": "<az otthoni felvétel>", "nev":
   "Bálint (otthonról)"}` — a hangból méri a késést és a két gép órájának csúszását, az otthoni felvétel új sávra
   kerül, a hálózati sávok elnémulnak, a terem sávjai a klikk rácsára tolódnak. Mondd el a késést, a csúszást és a
   középen mért maradék hibát.
6. **Vége:** `tavproba` `leallitas` mindkét gépen.

## Sampler és koncertanyag

A **sampler** a számok előtt (vagy után) bejátszott hang — fájlokból, játékokból, saját felolvasás; a LEM-nél
Bálint indítja egy iPadről. Próbán is kell, nem csak koncerten.

- **Felvétel:** `sampler` `action: "add"`, `title` (a dal), `path` (a hangfájl: fotóládából, pendrive-ról,
  letöltésből), `name`, `mikor: "előtte"` (vagy „utána”), `gap` (szünet utána, mp) — a dal `sampler/`
  mappájába kerül, és a dal memóriájába.
- **Próbán:** „játszd be a Leprusz elejét” → `sampler` `action: "play"`, `title` (és `name`, ha több van).
- **Setlist:** `setlist` `set` `name: "Szombat, Dürer"`, `data: {"dalok": ["Leprusz", "Ötölős", …], "datum": …,
  "helyszin": …}` — a dalok a munka- vagy a publikus címükön.
- **Koncertanyag:** `koncert_anyag` `setlist` — számonként egy sztereó wav: az egyik oldalon (alap: bal) a klikk
  a dobos fülébe, a dal tempója, ütemmutatója, tempóváltásai (`tempovaltasok`) és szerkezete szerint, egy ütem
  előszámolással (`count_in`); a másikon a samplerhangok a közönségnek. `together: true` egyben is. A klikkhez
  a dal memóriájában kell a tempó és a szerkezet (vagy `utemek`): ha hiányzik, a `hibak` megmondja —
  pótold (`dal_szinkron` `from_reaper` a Reaper-projektből, vagy kérdezd meg).
- Utána mondd el a bekötést (a válasz `bekotes`-e: a lejátszó sztereó kimenete Y-kábellel kettéválasztva, a
  klikk a dobos fülesébe, a sampler a PA felé), és egészítsd ki vele a koncert felállását
  (`felallas` `activate` „koncert”, `set` / `felallas_kabel`).

## Gyakorló és zenekari projekt

- **Gyakorlás (egy zenész):** egy sáv a hangszerének (erősítővel), metronóm, a dal tempója; ha van
  alap (backing track), azt egy külön sávra húzd be (`reaper.InsertMedia(path, 1)`).
- **Zenekari felvétel:** minden bemenetnek egy sáv, a bemenet sorrendjében és nevén (az `input_levels`
  egyenkénti végighallgatásával derül ki, mi hol szól), mind élesítve; a dobnak, ha akusztikus és
  több mikrofonnal megy, mikrofononként egy sáv („Lábdob”, „Pergő”, „Overhead B/J”). Utána
  `reaper_status`, és olvasd fel a listát, hogy mindenki lássa, ő melyik sáv.

## Bármi más: reaper_lua

A `code` egy függvény törzse; amit `return`-nel visszaadsz, az jön vissza JSON-ként, a `log(...)` a
naplóba ír. A segédek: `muzikos.status()`, `muzikos.transport()`, `muzikos.add_track{...}`. Példák:

```lua
-- az 1. sáv hangereje −6 dB-re
local tr = reaper.GetTrack(0, 0)
reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 10 ^ (-6 / 20))
return muzikos.status().savok[1]
```

```lua
-- az utolsó felvett elem fájlja (pl. a kottafelismeréshez)
local item = reaper.GetMediaItem(0, reaper.CountMediaItems(0) - 1)
local src = reaper.GetMediaItemTake_Source(reaper.GetActiveTake(item))
return reaper.GetMediaSourceFileName(src, "")
```

Egy akció futtatása az azonosítójával: `reaper.Main_OnCommand(<id>, 0)` (pl. 40026 = mentés, 40364 =
metronóm ki/be, 1013 = felvétel). Mielőtt egy sávot vagy elemet törölsz, kérdezz rá.
