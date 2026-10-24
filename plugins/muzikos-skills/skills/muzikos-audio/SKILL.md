---
name: muzikos-audio
description: >-
  Hangkártya és kis késés a MuzikOS-en: a bedugott külső hangkártya felismerése (PipeWire, ALSA),
  a Pro Audio profil, melyik bemeneten jön jel és mekkora (szintmérés csatornánként, túlvezérlés), a
  puffer és a mintavétel állítása a lehető legkisebb késésre, a kattogás (xrun) okának keresése, és a
  valódi oda-vissza késés lemérése. Használd, valahányszor hangkártya, bemenet, szint, késés, kattogás,
  recsegés vagy „nincs hang” kerül szóba a MuzikOS-en. Hívószavak: "bedugtam a hangkártyát", "melyik
  bemeneten van a gitár", "túl halk / túl hangos", "kattog", "recseg", "késik a hang", "zúg a hangszóró", "brummog", "mekkora a
  késés", "állítsd kisebbre a puffert", "nem látszik a hangkártya".
---

# Hangkártya és kis késés

A MuzikOS hangrendszere a **PipeWire**: a Reaper és az Ardour JACK-programként, a többi program
PulseAudio- vagy ALSA-programként szól rajta át. Az alap: **48 kHz, 128 mintás puffer** (≈2,7 ms
egy puffer). A program kérhet kisebbet is, 32-ig.

## A bedugott hangkártya

1. `audio_devices` — látszik-e a kártya (a `hangkartyak` és a `pipewire_eszkozok` között), hány
   be- és kimenete van, melyik profilon áll.
2. **Többsávos felvételhez a Pro Audio profil kell**: abban minden bemenet külön csatorna, a
   PipeWire nem kever össze semmit, és nem tesz rá saját átalakítást.
   ```bash
   pactl list cards short                       # a kártya neve
   pactl set-card-profile <kártya> pro-audio
   ```
   (vagy `wpctl status`, aztán `wpctl set-profile <id> <profil>`.) Utána újra `audio_devices`.
3. **Melyik bemeneten mi szól:** `input_levels` (alap 3 másodperc). Kérd meg a zenészt, hogy
   **játsszon közben**, aztán olvasd ki, hol `jel: van`. Több hangszer azonosításakor egyenként:
   „most csak a gitár szóljon”.
   - jó szint: csúcs **−18 és −6 dBFS között**;
   - 0 dBFS közelében túlvezérel (`tulvezerles: true`): a kártyán a gain gombot lejjebb;
   - −40 alatt túl halk: gain fel, vagy a Hi-Z/Inst kapcsoló (gitárnál, basszusnál) legyen bekapcsolva.

### Amit a próbán lemértünk (2026-10-23)

- **A UMC404HD** a HiFi profilon áll; a PipeWire a négy bemenetét négy külön mono forrásra bontja
  (`…HiFi__Mic1__source` … `Mic4`), a Reaper JACK-en a `alsa_input.hw_U192k_0:capture_AUX0…3` portokat
  látja. Pro Audio profil ehhez nem kell.
- **Egy új USB-hangeszköz elviheti az asztal hangját**: a GP-50 bedugásakor a WirePlumber azt tette
  alapértelmezetté, és a böngésző hangja a pedálba ment. Javítás: `audio_default` `device: "UMC404HD"`.
  (A MuzikOS lemezképében egy WirePlumber-szabály a felvevő hangkártyáknak elsőbbséget ad.)
- **Kihúzás–visszadugás után** a rendszer hangja magától visszaáll, **a Reaper portjai nem**:
  `reaper_reconnect` (muzikos-reaper).
- **A Valeton GP-50** Linuxon USB-s hangkártya is (USB Audio Class 1, 2 be / 2 ki, 16 bit, **csak
  44,1 kHz** — a PipeWire 48 kHz-re mintavételez): a basszus USB-n kb. 10 dB-lel erősebben jött, mint a
  fejhallgató-kimenetén át a UMC-be. A MIDI-je `GP-50 MIDI 1`.
- **Az Alesis Nitro** USB-MIDI (10. csatorna), MIDI Clockot is küld; hangot csak a jack-kimenetén ad.

- **A hangkártya kihúzása és visszadugása után** a háttérfigyelő (`muzikos-hangut`, belépéskor indul) 3 másodperc
  nyugalom után magától rendbe teszi: a kártya bemenetei sorban a Reaper bemeneteire, a Reaper kimenetei a kártya
  **A párjára** (1/2), az asztal hangja és a felvétel alapja is a kártyára (nem a B párra), a TuxGuitar és a többi
  program ezért az A páron szól; a laptop beépített mikrofonjának kötései lekerülnek a Reaperről, a szintje
  induláskor 25%-ra áll (100%-on torzít). Kézzel: `reaper_reconnect` (egy kötés: `input` + `reaper_in`, „a UMC
  2-es bemenete menjen a Reaper 1-esére”; `belso: "marad"` megtartja a beépített hangot).

**Class compliant** (külön meghajtó nélkül működő) USB-kártya kell — a legtöbb ilyen (Behringer UMC,
Focusrite Scarlett, MOTU M2/M4, Audient, Steinberg UR, Zoom, Tascam). Ha a kártya nem látszik:
`lsusb`, `dmesg | tail -n 30`, `cat /proc/asound/cards`. A Thunderboltos és a saját meghajtót kérő
profi kártyák (UAD Apollo, Antelope) Linuxon nem vagy csak részben mennek — ezt mondd meg egyenesen.

## A késés

- **Futás közben:** `set_latency` (`quantum`: 32, 64, 128, 256, 512; `0` = vissza az alapra). A
  Reaper és az Ardour induláskor a `PIPEWIRE_QUANTUM` szerint kér pufferet (a `reaper_start` 128-at ad).
- **Ökölszabály:** 64–128 gitárszimulátorral is jól játszható; ha kattog, 256. Felvételkor, ha a
  zenész a kártya közvetlen monitorozásán hallja magát (a kártya „direct monitor” gombja), a puffer
  lehet nagyobb is — ott a késés nem számít.
- **A teljes kép:** `muzikos-info` (kernel, puffer, jogok, processzor, USB-alvás, rtirq).
- **A munkamenet elején:** `hangrendszer` `allapot` — mintavétel, puffer, a hangkimaradások eddig, wifi, a
  Guitarix neurális modellje, és ha a bedugott kártyának van elmentett profilja, az **érvénybe lép**.

### Késleltetés-hangolás a kártyához (egyszer kártyánként)

„Hangold be a hangkártyát” → előbb kérd meg, hogy **a Reaper játsszon egy valódi, effektes projektet** (2–3
erősítő-szimulátor, dob, klikk — ez a terhelés), aztán `hangrendszer` `{"action": "hangolas"}`: a puffereket
(64 → 512) sorra kipróbálja, 15 mp bemelegítés után próbánként 60 mp-ig (`mp`; alaposan: 180) számolja a
kimaradásokat, és a legkisebb kimaradás nélküli + egy fokozat tartalék lesz a kártya profilja (a kártya neve szerint,
nem a sorszáma szerint). Utána a kártya bedugásakor ez áll be. Mondd el: hányas puffernél volt még hibátlan, és hogy
ez a **pufferhossz**, nem az oda-vissza késés. A valódit hurokkábellel: `hangrendszer` `korbeli` (a kártya 1.
kimenete egy kábellel a `bemenet`-re); az eredmény a profilba kerül.

### Zúgás, brummogás (földhurok, USB-zaj) — „zúg a hangszóró”

Ez más, mint a kattogás: egyenletes zúgás vagy berregés, ami a gép terhelésével, a billentyűzet nyomkodásával vagy a
töltővel együtt változik. Ritkán beállítás a hibás, jellemzően a **föld** (USB-föld a laptop és a hangkártya/hangszóró
földje között). A LEM-próbán (2026-10-23, Alesis Nitro USB-n) ez volt: a **dob USB-jét kihúzva megszűnt**, a töltő nem
volt a ludas. Vezesd végig a zenészt **egyesével, egyszerre egy dolgot változtatva**, és minden lépés után kérdezd meg,
változott-e a zúgás:

1. **Hol zúg?** Csak a hangszóróban, vagy a felvételen is? `input_levels`: látszik-e a zaj a bemeneteken a hangszer
   nélkül is (a hangszereket húzza ki a kártyából)? Ha a felvételen is ott van, nem csak a hangszórón.
2. **Töltő:** húzza ki a laptop töltőjét, és menjen akkuról. Megszűnt → a töltő (másik töltő, vagy földelt hosszabbító).
3. **A dob (vagy más USB-s hangszer) USB-je:** húzza ki az USB-kábelt (a dob jack-kimenete a hangkártyán marad).
   Megszűnt → USB-föld a ludas. Ilyenkor a hanghoz nem kell az USB, de a **MIDI-hez igen**: ide **USB-leválasztó** (lásd
   `KELLEKEK.md`) kell a dob és a laptop közé, vagy **másik USB-port**, vagy a dob a tápos USB-elosztón át.
4. **A hangkártya kimenete a hangszóróhoz:** szimmetrikus (TRS vagy XLR) kábel, és ha a hangszórón csak jack van, egy
   **földhurok-leválasztó** (vagy DI-doboz földleválasztással) a kártya és a hangszóró közé.
5. **Egyetlen konnektor:** a laptop, a hangszóró, a pedál és a dobmodul egy elosztóból menjen (ne két külön fali dugaljból).
6. **Az energiagazdálkodás és a teljesítmény-üzemmód:** `muzikos-info` (USB-alvás), `system_status` — a performance
   üzemmód csökkenti a terheléssel változó zajt. Ez ritkán a fő ok, a föld előbb jön.

Ami segített, azt **írd be a felállásba** (`felallas` `set`, az adott eszköz `megjegyzes`-e: „zúgott, USB-leválasztóval
megszűnt”), hogy a következő próbán a Claude már tudja, és a felállás képén **mutasd meg**, melyik kábelre kell a
leválasztó (`felallas_rajz`). Ha hardver kell, mondd meg a zenésznek, mit vegyen (`KELLEKEK.md`).

### „Hol szól a basszus?” — minden bemenet egy hívásban

`input_levels` (device nélkül): a kártya **mind a négy** (vagy ahány) bemenetét egyszerre megméri, és megmondja, melyiken van jel (`osszefoglalo`), mekkora a csúcs, és csatornánként a `gain` mezőben a teendőt: cél a -18…-6 dBFS közti csúcs; túlvezérlésnél mennyit vegyen vissza, halknál mennyit tekerjen fel. Nem kell bemenetenként külön hívni. A gombot mutasd meg a kártya képén (`felallas_rajz`).

### Kattogás, recsegés (xrun)

1. `xrun_check` — a `pw-top` ERR oszlopa nő-e, és mi van a naplóban. **Felvételenként** a `reaper_transport`
   `stop` megmondja, volt-e kimaradás a felvétel alatt (`kimaradas_a_felvetel_alatt`), és a `take_lista` is
   mutatja take-enként (`rendszer_kimaradas`): ha volt, a recsegés a gépé, nem a zenészé — mondd meg így.
2. Gyakori okok, ebben a sorrendben:
   - túl kicsi a puffer a gépnek (`set_latency` 256);
   - a laptop akkuról megy (a processzor lelassul) — töltőre;
   - a Wi-Fi: **ha be van kapcsolva, de nincs hálózaton**, a háttérkeresése kimaradásokat okoz (Bence mérése: 0
     helyett 305 JACK-hiba) — a felvétel indítása ilyenkor szól; `hangrendszer` `{"action": "wifi", "kapcsolo":
     "ki"}`, a végén `be`; a Bluetooth: `rfkill block bluetooth`;
   - Guitarix **neurális (RTNeural) modellel 48 kHz-en**: ezek a modellek 44,1 kHz-esek, és 48 kHz-en kimaradás
     nélkül is recseghetnek (Bence megtalálta a Guitarix-hibát) — `hangrendszer` `{"action": "mintavetel", "rate":
     44100}` (a NAM-ot ez nem érinti);
   - a processzor nem performance üzemmódban (`system_status`);
   - a hangkártya egy USB-elosztón vagy ugyanazon a vezérlőn, mint a külső SSD: közvetlenül a gépbe,
     másik porton;
   - egy pluginnehéz projekt: a Reaperben a nehéz effektek „Freeze”-e, vagy nagyobb puffer.

### Valódi késés mérése (oda-vissza)

Egy kábel a hangkártya egyik kimenetéről az egyik bemenetére, aztán:
```bash
jack_iodelay &            # kiírja a mért késést mintában és ms-ban
qpwgraph &                # kösd össze: jack_iodelay:out → a kártya kimenete, a kártya bemenete → jack_iodelay:in
```
Ugyanazzal a pufferrel, mint a Windowson (ASIO), hogy a kettő összevethető legyen. Az eredményt
mondd ki ms-ban, és hogy melyik pufferrel mérted.
