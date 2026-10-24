---
name: browser-testing
description: >-
  Weboldal kipróbálása, ellenőrzése és lefényképezése engedélykérés nélkül: elsőként a plugin playwright
  MCP-szerverével (browser_navigate, browser_snapshot, browser_click, browser_fill_form,
  browser_take_screenshot), tartaléknak playwright-core szkripttel; belépős oldalhoz (claude.ai-artifact, bolti
  fiók, admin) a Claude-Chrome-mal, egy állandó Chrome-profillal a felhasználó belépéseivel és mentett
  jelszavaival (scripts/claude-chrome.mjs). NEM a beépített böngészővel (Claude_Browser), mert az a
  cégoldalakon minden lépésre engedélyt kér, és a mentett jelszavakat sem látja. Élesben előbb a beküldést fogd
  meg (minden nem-GET kérés elakad); a képernyőképet SendUserFile mutatja meg. Ha curl vagy REST is elég, az még
  jobb. Használd, valahányszor egy oldalt, űrlapot, mobilnézetet, képernyőképet vagy PDF-et kell megnézni,
  vagy egy belépős oldalt olvasni. Hívószavak: "nézd meg az oldalon", "próbáld ki az űrlapot", "csinálj
  képernyőképet", "működik-e élesben", "nyisd meg, belépek". Angolul: "take a screenshot".
---

# Weboldal kipróbálása — háttérböngészővel, kérdezgetés nélkül

Egy oldalt kipróbálni (űrlap, görgetés, képernyőkép, mobilnézet, PDF) a **gépen futó, ablak nélküli
(headless) böngészővel** kell. Ez semmit nem kérdez. Két útja van: a plugin **playwright MCP-szervere**
(elsőként), és egy **playwright-core szkript** (tartaléknak).

**A beépített böngészőt (Claude_Browser / „Browser pane”) erre NE használd.** A cégoldalakon minden egyes
lépésre — `find`, `read_page`, kattintás, gépelés, JavaScript — engedélyt kér, és a felhasználó ettől
nagyon ideges lesz (2026-10-15-én és 16-án is szólt miatta). Az ok az app oldalán van, nem nálunk: az
Anthropic oldal-ellenőrzése egyes domaineket kockázatosnak sorol be (a wuuff.taxi „category3”), és ezeken
az app csak lépésenkénti „Allow once”-t kínál, amit sem a Bypass mód, sem az engedélyezett oldalak listája
nem old fel (#225). Csak akkor nyisd meg, ha a felhasználó **kifejezetten azt kéri, hogy ő is lássa ott**
az oldalt.

> **Általános elv:** ha egy eszköz engedélyt kérne, és van másik út ugyanarra, ami nem kér, azt válaszd.
> A kérdés a felhasználó ideje; csak ott kérdezz, ahol a döntés tényleg az övé (küldés, fizetés, élő adat
> módosítása).

## Melyik út?

| Mit kell megtudni | Eszköz |
|---|---|
| él-e az oldal, mi a státuszkód, átirányít-e, mi van a HTML-ben, válaszol-e egy API | **curl** vagy egy REST-végpont (a connector eszközei, pl. a WordPress `wp_*`) — böngésző sem kell |
| hogyan néz ki, működik-e a JavaScript, az űrlap-validáció, a görgetés, a mobilnézet, képernyőkép, PDF | a **playwright MCP** (lent); ha az nem indul, a **szkript** |
| sok lépés egyben, ismételhetően (pl. ugyanaz az űrlap öt adatsorral) | a **szkript** — egy futás, egy eredmény |
| **belépés kell** hozzá (claude.ai-artifact, bolti fiók, admin), és Claude-nak kell olvasnia vagy lefényképeznie | a **Claude-Chrome** (lent): állandó profil a felhasználó belépéseivel és mentett jelszavaival |
| a felhasználó **maga akarja látni** és kattintgatni | a beépített böngésző — csak ekkor; ha belépés kell hozzá, a Claude-Chrome |

## Elsőként: a playwright MCP

A plugin hoz egy helyi MCP-szervert `playwright` néven (`@playwright/mcp`, a gépen `npx`-szel indul, a
Windows Edge-ét vezérli ablak nélkül, minden indulásnál tiszta profillal). Az eszközei a teljes nevükön
`mcp__…playwright__browser_*` alakúak; ha a listádon csak a nevük látszik, töltsd be őket a ToolSearch-csel
(`+playwright browser`). A fontosak:

| eszköz | mire |
|---|---|
| `browser_navigate` | oldal megnyitása (URL) |
| `browser_snapshot` | az oldal szerkezete hivatkozásokkal (`ref`) — ebből kattintasz és töltesz ki |
| `browser_click`, `browser_type`, `browser_fill_form`, `browser_select_option`, `browser_press_key` | kattintás, gépelés, űrlap |
| `browser_take_screenshot` | képernyőkép (`fullPage: true`) — **fájlnév NÉLKÜL**: így a temp alá kerül (`%TEMP%\playwright-mcp\page-….png`), és a válasz megadja a teljes útját. Fájlnévvel a projektmappába írna, a scratchpadba pedig nem enged |
| `browser_resize` | mobilnézet: 390×844 |
| `browser_pdf_save` | PDF-nyomat — ugyanígy, fájlnév nélkül |
| `browser_console_messages`, `browser_network_requests` | konzolhibák, kérések |
| `browser_run_code_unsafe` | Playwright-kód a lapon — itt fogod meg a beküldést (lent) |

**Élesben az első hívás a beküldés megfogása**, még a navigálás előtt:

```
browser_run_code_unsafe(code = "async (page) => { await page.context().route('**/*', r => r.request().method() === 'GET' ? r.continue() : r.abort()); return 'nem-GET kérések elfogva'; }")
```

Ettől kezdve minden POST/PUT/DELETE elakad (lemérve: egy `fetch` POST „Failed to fetch”-csel áll meg). A
szerver a böngészőt egy óra tétlenség után bezárja, és a profil nem marad meg: egy új munkamenetben vagy
`browser_close` után a fogást újra be kell állítani.

Domainkorlát nincs a szerveren (az `--allowed-origins` a külső szolgáltatásokat — reCAPTCHA, süti-sáv,
betűtípus — is letiltaná, és a súgója szerint nem is biztonsági határ). Ezért a szabály a tiéd: **csak a
saját oldalainkat** és a fejlesztői gépeket (localhost) nyisd meg vele, idegen oldalt nem.

Ha a `playwright` eszközök nincsenek a listádon (nincs Node a gépen, vagy a szerver nem indult), menj a
szkriptes útra.

## Tartaléknak: a headless böngésző szkriptből

A `playwright-core` csak a vezérlő, böngészőt nem tölt le — a gépen már van:

1. **A Playwright saját Chromiuma**, ha valaha letöltődött (Windowson
   `%LOCALAPPDATA%\ms-playwright\chromium-<szám>\chrome-win\chrome.exe`, Macen
   `~/Library/Caches/ms-playwright/…`, Linuxon `~/.cache/ms-playwright/…`) — `executablePath`-szal.
2. Ha az nincs: **a Windows Edge-e** — `channel: 'msedge'`, ez minden Windowson ott van. Macen a
   telepített Chrome: `channel: 'chrome'`.
3. Ha egyik sincs: `npx playwright install chromium` a scratchpadban (~150 MB, egyszer).

Telepítés a munkamenet **scratchpadjába** (nem a projektbe — ott nincs keresnivalója):

```bash
npm i --prefix <scratchpad> playwright-core
```

A szkript is a scratchpadba kerül (pl. `check.mjs`), és onnan fut: `node check.mjs <url>`. A
`playwright-core` friss verziója a korábban letöltött Chromiummal is elindul (1.64 a `chromium-1194`-gyel
lemérve); ha mégsem, az Edge-csatorna mindig jó.

## A minta-szkript

```js
import { chromium } from 'playwright-core';
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

// A gépen már letöltött Playwright-Chromium; ha nincs, az Edge (Windows) vagy a Chrome.
function chromiumPath() {
  const root = process.platform === 'win32' ? join(process.env.LOCALAPPDATA ?? '', 'ms-playwright')
    : process.platform === 'darwin' ? join(homedir(), 'Library/Caches/ms-playwright')
    : join(homedir(), '.cache/ms-playwright');
  const exe = process.platform === 'win32' ? ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe']
    : process.platform === 'darwin' ? ['chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium']
    : ['chrome-linux64/chrome', 'chrome-linux/chrome'];
  const dirs = existsSync(root) ? readdirSync(root).filter(d => /^chromium-\d+$/.test(d)).sort().reverse() : [];
  for (const d of dirs) for (const e of exe) if (existsSync(join(root, d, e))) return join(root, d, e);
  return undefined;
}

const path = chromiumPath();
const browser = await chromium.launch(path ? { executablePath: path }
  : { channel: process.platform === 'win32' ? 'msedge' : 'chrome' });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } }); // mobil: 390×844

// ÉLESBEN semmi nem mehet ki: minden nem-GET kérés elakad, mielőtt a szerverhez érne.
const blocked = [];
await page.route('**/*', r => {
  const q = r.request();
  if (q.method() === 'GET') return r.continue();
  blocked.push(`${q.method()} ${q.url()}`);
  return r.abort();
});

// A 'networkidle' élesben kifuthat (reCAPTCHA, analitika folyton kér): 'load', és egy célzott várakozás.
await page.goto(process.argv[2], { waitUntil: 'load' });
// … a próba: page.waitForSelector('form'), page.fill(), page.click(), page.mouse.wheel(0, 800), page.locator('…').textContent() …
await page.screenshot({ path: 'shot.png', fullPage: true });   // PDF: await page.pdf({ path: 'oldal.pdf' })
console.log('elfogott kérések:', blocked);
await browser.close();
```

## Belépős oldal: a Claude-Chrome (#357)

**Ha az oldalhoz a felhasználónak be kell lépnie** (claude.ai-artifact, bolti fiók, ügyfélkapu, admin felület), és
Claude-nak kell olvasnia vagy lefényképeznie, a **Claude-Chrome-ot** nyisd. Ne a beépített böngészőt (nem látja a
mentett jelszavakat, lásd lent), és ne a playwrightot (minden indulásnál tiszta profil, nincs belépés). A
Claude-Chrome a gépen egy állandó Chrome-profil (`%LOCALAPPDATA%\Claude-Chrome`). Minden ügyfél pluginja ugyanazt
használja, tehát ügyfélváltáskor is megmarad, amibe a felhasználó belépett.

- **MuzikOS-en zenekaronként külön profil** van (`Claude-Chrome-<zenekar>`, a mostani zenekar a tudás mappa `aktiv.json`-jából, vagy a `MUZIKOS_CHROME_PROFIL` változóból): a `start` zenekarváltás után bezárja a másik zenekar Chrome-ját, és a mostanié nyílik. A plugin `chrome` MCP-eszközei (`@playwright/mcp --cdp-endpoint`) ugyanehhez a Chrome-hoz kapcsolódnak, tehát a `start` után a `browser_*` eszközökkel is lehet kattintgatni a belépett profilban.
- A felhasználó **egyszer bejelentkezik benne a Chrome-ba** a Google-fiókjával (jobb felül a profil ikon), szinkronnal.
  Így a Google Jelszókezelőben tartott jelszavai és passkeyei felkínálódnak, és a profil megjegyzi a belépéseit a
  Chrome bezárása után is. A munkamenet-sütis oldalak (egyes webshopok) ettől még kiléptethetnek.
- **A szkript** (`scripts/claude-chrome.mjs`, Node 22+):

  ```bash
  node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" start <url>   # indít (ha nem fut) és megnyit
  node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" status        # fut-e, be van-e jelentkezve a Chrome
  node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" text <url-részlet>
  node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" shot <url-részlet> <scratchpad>/kep.png [--full]
  node "$CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" eval <url-részlet> "<JS-kifejezés>"
  ```

  ```powershell
  node "$env:CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" start <url>
  node "$env:CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" status
  node "$env:CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" text <url-részlet>
  node "$env:CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" shot <url-részlet> <scratchpad>/kep.png --full
  node "$env:CLAUDE_PLUGIN_ROOT/skills/browser-testing/scripts/claude-chrome.mjs" eval <url-részlet> "<JS-kifejezés>"
  ```

  A claude.ai-artifact tartalma egy másik domainről betöltött keretben fut:
  a szövegét a keret címével olvasd (a `tabs` mellett a keretek címét a `eval <lap> "[...document.querySelectorAll('iframe')].map(f => f.src)"`
  adja), a képet a lapéval (`shot claude.ai/artifact`). Kattintgatáshoz a playwright-core is rácsatlakozik:
  `chromium.connectOverCDP('http://127.0.0.1:9223')`.
- **Előbb nézd meg, be van-e már lépve** (`text`, `shot`): gyakran igen. Ha a lap a belépőre visz, kérd meg a
  felhasználót, hogy lépjen be **abban a Chrome-ablakban**, és várj a szavára. Ha a `status` szerint a Chrome nincs
  bejelentkezve, előbb azt kérd, különben a mentett jelszavak nem jönnek fel.
- **Titok:** jelszót, kódot Claude nem ír be és nem kér a chatbe, a profil jelszótárához és sütijeihez nem nyúl (nem
  olvassa, nem másolja). A jelszavak a Google Jelszókezelőben vannak, a Chrome titkosítva tárolja őket; aki még
  jobban akarja, a Jelszókezelőben bekapcsolhatja az eszközön történő titkosítást. A távvezérlés csak a gépen
  belülről érhető el (127.0.0.1:9223), de amíg a Claude-Chrome fut, a gépen futó bármely program vezérelheti: ha
  nincs rá szükség, zárd be, és idegen szoftvert ne futtass mellette.
- **Miért nem a megszokott Chrome:** a Chrome a saját alapprofiljánál a távvezérlést nem engedi (a Chrome 136 óta a
  `--remote-debugging-port` csak külön `--user-data-dir`-rel indul). Ha a felhasználónak csak **látnia** kell egy
  belépős oldalt, és Claude-nak nem kell olvasnia, a megszokott Chrome-ja is jó (`Start-Process chrome '<url>'`).

## Belépés a beépített böngészőben — mit tud, és mit nem

Lemérve 2026-10-21-én (Claude asztali app 3.1623.0, Chromium 152, Windows 11; csukaj/clauding#302):

- **Jelszókezelő nincs benne.** A panel nem a felhasználó Chrome-ja: nem látja a Chrome (Google Password
  Manager) mentett jelszavait, és maga sem ment, nem tölt ki semmit.
- **A passkey nem működik.** Az oldal azt látja, hogy van passkey-támogatás (`PublicKeyCredential`, Windows
  Hello, telefonos QR: mind „igen”), de a kérés egy másodpercen belül `NotAllowedError`-ral elhasal, és a
  Windows WebAuthn-naplójában (`Microsoft-Windows-WebAuthN/Operational`) nyoma sincs: az app nem adja tovább a
  Windowsnak. Ez az app oldalán dől el, nem nálunk.
- **A belépés megmarad.** A panel profilja tartós: ahova egyszer belépett a felhasználó (pl. a claude.ai), ott
  a panel bezárása és újranyitása után is be van lépve. Egy oldalra tehát egyszer kell belépni, nem minden
  alkalommal. (Az app újraindítása után még nincs lemérve.)

Ebből a menet:

1. **Ha csak a felhasználónak kell látnia egy belépős oldalt** (egy claude.ai artifactot, egy admin felületet),
   nyisd meg a **saját Chrome-jában**: ott be van lépve, és a jelszókezelő meg a passkey is működik. Windowson
   `Start-Process chrome '<url>'` (ha nincs Chrome: `Start-Process '<url>'`, az alapértelmezett böngésző).
   Az Artifact eszköz `open`-je a panelt nyitja, ilyenkor ez kell helyette.
2. **Ha Claude-nak kell olvasnia vagy lefényképeznie egy belépős oldalt**, a Claude-Chrome-ot használd (fent), ne a
   panelt.
3. Jelszót a chatbe ne kérj, és ne kérd, hogy a felhasználó bemásolja neked.

## Szabályok

- **Élesben megfogod a beküldést** — az MCP-n a `browser_run_code_unsafe`-fel, a szkriptben a fenti
  `page.route(… r.abort())`-tal. Mindkettő minden POST/PUT/DELETE kérést elvág: valódi űrlap, ajánlatkérés, foglalás, levél nem megy ki, és mellékesen az analitika és a
  Sentry sem kap hamis látogatást. A „sikeres beküldés” így nem látszik — azt dev oldalon próbáld, vagy a
  felhasználó döntése. Ha az oldal egy POST-tal **olvas** (pl. WordPress `admin-ajax.php` kereső), azt az
  egy URL-t engedd át név szerint, ne az egészet.
- **A képernyőkép a projekten kívülre kerül** (az MCP-n a temp alá, a válaszban álló úttal; a szkriptben a
  scratchpadba, a `path`-szal), és a **SendUserFile** mutatja meg a felhasználónak
  (`display: 'render'`). Egy kép többet mond egy bekezdésnél; görgetett vagy mobilnézetnél külön kép kell.
- **Mit mértél, azt mondd ki:** a státuszkódot, a validációs üzenetet szó szerint, az elfogott kérések
  listáját — ne csak azt, hogy „működik”.
- **Belépést igénylő oldalnál** (admin, ügyfélfiók) ne gépelj be jelszót: kérdezd meg a felhasználót, vagy
  használd a szerveroldali eszközt (connector, REST), ami a saját hitelesítésével megy. Ha a felhasználónak
  kell belépnie, az a Claude-Chrome-ban történik (*Belépős oldal* szakasz).
- A szkript dobható: a scratchpadban marad, a projekt repójába nem kerül, hacsak a feladat nem épp egy
  tartós teszt.
