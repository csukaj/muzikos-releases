---
name: muzikos
description: >-
  A MuzikOS zenei gép (hordozható Debian 13 live, valós idejű kernellel, PenSSD-ről vagy pendrive-ról
  indítva) teljes kezelése a Claude-ból: mi fut rajta, mi hol van, mik a szabályai (TPM, Secure Boot,
  tartós fájl, tiszta indítás), és hogyan oldj meg rajta BÁRMILYEN problémát teljes hozzáféréssel —
  parancsokkal (sudo jelszó nélkül), a muzikos MCP-szerver eszközeivel, és ha egy programot másképp nem
  lehet, a képernyőn kattintva. Használd a MuzikOS-en minden kérésnél elsőként, és mindig, ha valami nem
  működik: nincs hang, nincs net, nem indul egy program, betelt a lemez, lassú a gép, frissíteni kell.
  Hívószavak: "nem szól semmi", "nézd meg, mi a baj", "nem indul a Reaper", "nincs internet", "mennyi
  hely van még", "frissítsd a gépet", "telepítsd fel", "mi ez a gép". A hangkártya és a késés részletei a
  muzikos-audio, a felvétel a muzikos-reaper skillben.
---

# A MuzikOS gép

A MuzikOS egy hordozható zenei felvevőrendszer: **Debian 13 (trixie) élő rendszer**, valós idejű
(PREEMPT_RT) kernellel, XFCE asztallal, magyarul. Egy külső SSD-ről vagy pendrive-ról indul (Ventoy),
a gép belső lemezéhez nem nyúl. Egy zenekar használja: gitár, basszus, dob, ének — gyakorlásra és
zenekari felvételre.

**Te ezen a gépen teljes hozzáféréssel dolgozol.** Ez egy külön zenei gép, nincs rajta személyes adat;
a gazdája (Józsi) azt kérte, hogy mindent a Claude-ból lehessen csinálni. Tehát: ne kérdezz rá arra,
amit egy rendszergazda magától megcsinálna (csomag telepítése, szolgáltatás újraindítása, beállítás
átírása) — csináld meg, és mondd el, mit csináltál. **Kivétel, amire mindig rákérdezel:** a zenészek
munkájának eldobása (mentetlen Reaper-projekt bezárása, felvétel törlése), lemez formázása, és a
belső lemez (a gépen lévő Windows) bármilyen módosítása.

**Minden munkamenet elején: `tudas`** (a muzikos-memory skill) — ki próbál, melyik zenekar, ki melyik
bemenet és sáv, milyen dalok vannak, mit tanítottak meg korábban. Amit ott találsz, azt ne kérdezd meg újra.

## Az eszközeid (muzikos MCP-szerver)

| Eszköz | Mire |
|---|---|
| `system_status` | egy pillantás: valós idejű-e a kernel, processzor-üzemmód, jogosultságok, lemezek, háló, tartós fájl |
| `run_command` | bármilyen parancs; `sudo: true` = rendszergazdaként (jelszó nélkül) |
| `audio_devices`, `input_levels`, `set_latency`, `xrun_check` | hang — a muzikos-audio skill |
| `reaper_*` | a Reaper — a muzikos-reaper skill |
| `screenshot`, `mouse`, `keyboard` | a képernyő: ha egy programot nem lehet parancsból kezelni |

Ha a Claude Code-ban vagy, a saját shelled is jó a parancsokhoz; a `run_command` a Claude Desktop
chatjéből is elér mindent. **Ahol van parancs vagy API, azt használd, ne a kattintást**: gyorsabb, és
nem téved. A képernyő a végső eszköz (egy párbeszédablak, egy program, aminek nincs más felülete).
Kattintás előtt mindig friss `screenshot`, utána újabb, hogy lásd, mi lett.

## Mi hol van

| Mi | Hol |
|---|---|
| a felhasználó | `zenesz` (jelszó: `live`), automatikus belépés, `sudo` jelszó nélkül |
| Reaper | `/opt/REAPER`, beállítások: `~/.config/REAPER` |
| ingyenes zenei programok | Ardour, Audacity, Guitarix, Neural Amp Modeler (LV2, `/usr/lib/lv2`), Hydrogen, DrumGizmo, TuxGuitar, MuseScore 3, qpwgraph (hang-útválasztás), pavucontrol |
| hangrendszer | PipeWire (JACK és ALSA is rajta át): `/etc/pipewire/pipewire.conf.d/90-muzikos-lowlatency.conf` — 48 kHz, 128-as alappuffer |
| valós idejű jogok | `/etc/security/limits.d/95-muzikos-audio.conf` (`audio` csoport: rtprio 95, memlock) |
| teljesítmény | `muzikos-performance.service` (processzor: performance), `rtirq` (a hangkártya megszakításai előre) |
| állapotjelentés | `muzikos-info` parancs |
| a PenSSD adatrésze | `PenSSD-Adat` (exFAT; a Windows és a telefon is látja): bejelentkezéskor csatolódik a `/media/zenesz/PenSSD-Adat` alá; ha mégsem: `udisksctl mount -b /dev/disk/by-label/PenSSD-Adat` |
| böngésző | Google Chrome az alapértelmezett (a zenész a saját Google-fiókjával lép be, akkor a jelszavai is ott vannak — a belépés az övé); Firefox is van |
| kijelző, touchpad | a nagyítás bejelentkezéskor a kijelzőhöz igazodik (`muzikos-display-scale`); a touchpad Windows-szerű: `/etc/X11/xorg.conf.d/40-muzikos-touchpad.conf` |

**Felvételek helye:** ha a `PenSSD-Adat` csatolva van, a zenekar dalai a `…/PenSSD-Adat/MuzikOS/Zenekarok/<zenekar>/Dalok`
alá kerülnek (`dal_megnyitas`), a zenekarhoz nem tartozó felvételek a `…/MuzikOS/Projektek` alá (a Windows is
látja, és nem fogy tőle a tartós fájl); különben `~/MuzikOS`.

## Belépős oldalak (RouteNote, Drive, YouTube…): a zenész Chrome-ja

Ha egy oldalhoz a zenésznek be kell lépnie, a **Claude-Chrome-ot** használd, beállítás nélkül: a `browser-testing` skill
szkriptje indítja (`node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" start <url>`), és a plugin
`chrome` böngészőeszköze (`browser_navigate`, `browser_snapshot`, `browser_click`…) ahhoz kapcsolódik. Előbb mindig a `start`,
aztán az eszközök. A profil **zenekaronként külön** (`Claude-Chrome-<zenekar>`): zenekarváltás (`zenekar` activate) után a `start`
a mostani zenekaré nyitja, a másiké bezárul. A zenész egyszer belép benne a Chrome-ba és az oldalakra (a `status` megmondja, be
van-e lépve), és a belépések megmaradnak. Helyi oldalakhoz (127.0.0.1, a MuzikOS saját oldalai) nem kell a Chrome.

- **Jelszót, kódot, „nem vagyok robot” ellenőrzést a zenész intézi**, vagy a Chrome jelszókezelője tölti ki; te nem írsz be ilyet.
- **Küldés, közzététel, fizetés, feltöltés véglegesítése előtt mindig kérdezz** (mutasd meg, mi megy el), és csak kimondott igenre nyomd meg.
- Olvasni, megnyitni, képernyőképet készíteni kérdés nélkül lehet.

## A rendszer természete: élő rendszer, tartós fájllal

- A rendszer egy lemezképből indul (`MuzikOS.iso` a Ventoyon). **Minden változás** (telepített csomag,
  beállítás, a home mappa) a **tartós fájlba** kerül (`MuzikOS.dat`, 20 GB, ext4); a
  `system_status` megmutatja, használja-e (`/run/live/persistence`).
- **„Tiszta indítás”** a menüben (`nopersistence`): a tartós fájl nélkül, a lemezkép eredeti
  állapotában indul. **Ez a biztonsági háló**: ha valamit elrontottál, és a gép nem indul rendesen,
  így elindul, és a tartós fájlból javítható vagy visszaállítható.
- A tartós fájl betelhet: nézd a `df`-et. Ha kevés a hely, a felvételeket a `PenSSD-Adat`-ra kell
  tenni, a csomag-gyorsítótárat üríteni (`sudo apt clean`).
- A kernelt **ne** frissítsd a tartós fájlba (az élő rendszer a lemezkép kerneljével indul; a
  frissítés csak egy új lemezképpel jön). Programot nyugodtan telepíts aptból.

## Arculat: amikor oldalt, ábrát vagy rajzot készítesz

A MuzikOS-nek saját arculata van (Józsi választása): **keverőpultos design** — majdnem fekete alap, rackmodulok
(fémes panel, csavarok a sarkokban), a számok és az állapot egy narancsban izzó kijelzőn, a fő kiemelés narancs, a
felvétel piros, az állapotokat színes LED-ek jelzik. Betűk: Orbitron a címeknek, Saira a szövegnek, Share Tech Mono
a kijelzőnek. A színek jelentést hordoznak, és mindenhol ugyanazt: a tagoké (a sávon, a bekötésen, a dalnézetben, a
koncertlistán), a dalrészeké (intro, verze, refrén, bridge, szóló), a dal állapotáé (ötlet → próbálva → felvéve →
keverve → kész), a kábeleké (hang, USB, MIDI, XLR, hangszóró, táp) és a jelzéseké (zöld rendben, borostyán figyelj,
piros hiba). A pontos színek és a kész elemek a `mcp/muzikos_style.py`-ban vannak (`page()`, `lcd()`, `led()`,
`status_chip()`, `part_chip()`, `member_color()`, `cable_color()`): ha egy új oldalt vagy ábrát rajzolsz
(`run_command`-dal egy HTML-t vagy SVG-t), ezeket használd. Kevés szöveg: ikonok, színek, LED-ek, kijelzők mondják el
a lényeget, és legyen rövid súgó (a jobb alsó narancs „?”: egy-két sor, nem hosszú leírás).

## Szabályok, amik a gazda gépét védik

- **TPM:** a rendszer nem írhat a gép TPM-chipjébe, különben a gépen lévő Windows új PIN-t kér. Ezért a
  systemd TPM-szolgáltatásai le vannak tiltva (`systemd-tpm2-*`, `systemd-pcr*`, a kernel parancssorán
  is). Ezeket **soha** ne kapcsold vissza.
- **Óra:** a gép órája helyi időben jár (`/etc/adjtime`: LOCAL), hogy a Windows órája ne csússzon el.
  Ne állítsd UTC-re.
- **Secure Boot:** Józsi ThinkPadján ki van kapcsolva, és maradjon is (minden átváltás új Windows-PIN-t
  kér). Más gépen a MuzikOS Secure Boottal is indul.
- **A belső lemezhez** (a Windows partíciói) ne nyúlj, ne csatold írhatóan.

## Hibakeresés: a menet

1. **Mondd ki, mit látsz**: `system_status`, és a tünethez illő eszköz (hangnál `audio_devices`,
   `xrun_check`; programnál a napló).
2. **Nézd a naplót**: `journalctl -b -p warning --no-pager | tail -n 80`, a felhasználói szolgáltatásoké
   `journalctl --user -b --no-pager | tail -n 80`, egy programé az indítása terminálból.
3. **Javíts, és ellenőrizd vissza** — ugyanazzal a méréssel, amivel a hibát láttad.
4. **Mondd el a zenésznek egyszerűen**, mi volt a baj és mit csináltál; a technikai részlet csak
   kérésre.

Gyakori esetek:

| Tünet | Első lépés |
|---|---|
| nincs hang | muzikos-audio: `audio_devices` (látszik-e a kártya), `systemctl --user status pipewire wireplumber`, `wpctl status`; újraindítás: `systemctl --user restart pipewire wireplumber` |
| a Reaper nem szól / nem vesz fel a hangkártya visszadugása után | a háttérfigyelő magától visszaköti (3 mp nyugalom után: a kártya 1. bemenete → Reaper 1, a kimenetek az A párra, az asztal hangja is az A párra megy, a beépített mikrofon és hangszóró kötései lekerülnek); ha mégsem: `reaper_reconnect`, egy kötésre `input` + `reaper_in` („a UMC 2-es bemenete menjen a Reaper 1-esére”) |
| a böngésző vagy a lejátszó hangja rossz eszközre megy (pl. egy pedálba) | `audio_default` `device: "UMC404HD"` |
| egy eszköz nem látszik | `dmesg | tail -n 30` (lekapcsolódott? — a Nitro egyszer magától lekapcsolódott, újradugva ment), `lsusb` |
| „nézd meg a képernyőképet” | a legutóbbi: `~/MuzikOS/Kepernyokepek/legutobbi.png` (PrtSc = egész képernyő, Alt+PrtSc = ablak, Shift+PrtSc = kijelölt terület; a vágólapra is kerül) — nyisd meg képként (Read), és írd le, mit látsz |
| kattog, recseg | muzikos-audio: `xrun_check`, nagyobb puffer (`set_latency`), töltő a laptopon, Wi-Fi ki |
| zúg a hangszóró (egyenletes zúgás, a gép terhelésével vagy a billentyűzettel változik) | muzikos-audio „Zúgás, brummogás”: töltő ki, a dob USB-je ki, földhurok-leválasztó; lépésenként, egyszerre egy dolgot |
| nem indul a Reaper | muzikos-reaper: `reaper_start`; ha nem válaszol, `screenshot` (párbeszédablak vár?) |
| nincs internet | `nmcli device`, `nmcli device wifi list`, `nmcli device wifi connect <név> password <jelszó>` (a jelszót a zenész mondja meg) |
| betelt a hely | `df -h`, `du -sh ~/* | sort -h`; felvételek át a `PenSSD-Adat`-ra |
| lassú a gép | `top -b -n 1 | head -20`; a processzor üzemmódja (`system_status`) |
| program kell | `sudo apt update && sudo apt install -y <csomag>` (a tartós fájlba kerül) |

## Amit soha

- A zenészek felvételeit, projektjeit kérdés nélkül ne töröld, ne írd felül.
- Jelszót, belépési adatot ne találj ki és ne írj be helyettük: kérdezd meg, és ők írják be.
- A TPM-, óra- és Secure Boot-szabályt ne írd felül (fent).

## Problémabejelentés a fejlesztőknek

Ha valami **visszatérően** elromlik, vagy a zenész olyat kér, amit a MuzikOS nem tud („kéne X"), jegyezd fel a `bejelentes`
eszközzel (`action: "jegyez"`, rövid állandó `kulcs`, `cim`, `leiras`, `lepes`). Ha a válaszban `felajanlas` áll (ugyanaz
harmadszor), ajánld fel a zenésznek a beküldést. Menete: `piszkozat` → **mutasd meg neki a pontos szöveget** → csak a
kifejezett igen után `kuldes` az `ujjlenyomat`-tal. Nem megy bele hangfelvétel, jelszó, mások adata. Net nélkül sorba áll,
és magától elmegy. Ne küldj be semmit a zenész jóváhagyása nélkül.

## Fejlesztési napló (magától)

A `fejlesztesi_naplo` eszközzel **kérés nélkül** jegyezd fel, ami a fejlesztéshez hasznos: ami elromlott (`hiba`), amit kézzel
kellett megkerülni (`kezi_megoldas`, pl. pw-link), amit a zenész kijavított vagy elvetett (`elutasitas`), és amit a zenész
mond, ha azt kéri, „ezt jegyezd fel” (`eszrevetel`, **szó szerint**). A munkamenet végén és egy hiba után egy-két sor:
mi történt → mi kellene; `eszkoz`: a hangkártya, dob, pedál. A gép-pillanatkép és a háttérnapló hibái magától bekerülnek,
a napló naponta magától elmegy a fejlesztőknek. Hangfelvétel, dal, kotta, jelszó, e-mail nem kerül bele.
Az első indításkor (`action: "allapot"` → `beallitas: "kerdezni"`) kérdezd meg a zenészt, küldhetjük-e; a válasza szerint
`beallit` be vagy ki, és igen nélkül semmi nem megy el. „Mit küldenél el?” → `mit_kuldenel` pontos szövege. Józsi gépén alapból be van kapcsolva.
Nálunk a beérkezettekből (a muzikos-mcp `idea_list`-je, forrás: `muzikos-naplo`) összesítés készül gépenként és eszközönként,
gyakorisággal, és feladatjavaslat, jóváhagyással.

## Hangparancsok (kéz nélkül)

Belépéskor magától indul egy helyi figyelő (net nélkül is megy), ami a mikrofonon rövid, fix parancsokat ismer fel:
„felvétel”, „stop”, „vissza az elejére” (felvétel közben nem fut), „újra az utolsó ütemtől”, „ez jó volt” (jelölő a Reaperben).
Bizonytalan felismerésnél rákérdez, és „igen”-t vár. A `hangparancs` eszközzel: `allapot` (be van-e, megvan-e a modell),
`be` / `ki`, `forras` (a mikrofon eszköznévrésze: ha a parancs hangja a felvételbe kerül, adj meg fejhallgatós mikrofont),
`proba` (egy szövegről megmondja, melyik parancs lenne). Ha nem működik, nézd a `naplo.log` `[hangparancs]` sorait. Hang
nem mentődik és nem megy sehova.

## Napló a hibakereséshez

A háttérfigyelők (ablakhelyek, Claude-oldalsáv, hangútvonalak) a `~/.local/state/muzikos/naplo.log` fájlba írnak. Ha a zenész azt
mondja, hogy valami nem megy (ablak, hangkötés, oldalsáv), **olvasd el a napló végét** (`tail -n 60`), és abból javíts.
