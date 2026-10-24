#!/usr/bin/env node
/**
 * A Claude-Chrome: egy állandó Chrome-profil a belépős oldalakhoz (csukaj/clauding#357).
 *
 * Ha egy oldalhoz a felhasználónak be kell lépnie (claude.ai, bolti fiók, admin felület), Claude ezt a
 * Chrome-ot nyitja meg, és innen olvas: a felhasználó EGYSZER bejelentkezik benne a Chrome-ba a
 * Google-fiókjával (így a mentett jelszavai és passkeyei is felkínálódnak), és az oldalakra is egyszer
 * lép be; a profil a gépen marad, minden ügyfél pluginja ugyanezt használja.
 *
 * Miért külön profil: a Chrome a saját, megszokott profiljánál a távvezérlést nem engedi
 * (`--remote-debugging-port` a Chrome 136 óta csak nem alapértelmezett `--user-data-dir`-rel indul).
 * A távvezérlés csak a gépen belülről érhető el (127.0.0.1:9223).
 *
 * Titkot ez a szkript nem kezel: jelszót nem ír be, a jelszótárhoz és a sütikhez nem nyúl, csak
 * lapot nyit, szöveget olvas és képet készít.
 *
 * MuzikOS-en (Linux) zenekaronként külön profil van (#106): a mostani zenekar (a tudás mappa `aktiv.json`-ja, vagy a
 * MUZIKOS_CHROME_PROFIL) kapja a `Claude-Chrome-<zenekar>` profilt, hogy a két zenekar belépései ne keveredjenek.
 * Zenekarváltás után a `start` bezárja a másik zenekar Chrome-ját, és a mostanié nyílik.
 *
 *   node claude-chrome.mjs start [url…]        elindítja (ha nem fut), és megnyitja az URL-eket
 *   node claude-chrome.mjs status              fut-e, és be van-e jelentkezve a Chrome a Google-fiókba
 *   node claude-chrome.mjs tabs                a nyitott lapok
 *   node claude-chrome.mjs text <url-részlet>  a lap látható szövege
 *   node claude-chrome.mjs shot <url-részlet> <kép.png> [--full] [--scroll <CSS-szelektor>]
 *   node claude-chrome.mjs eval <url-részlet> <JavaScript-kifejezés>
 *
 * Bonyolultabb kattintgatáshoz a playwright-core is rácsatlakozik:
 * `chromium.connectOverCDP('http://127.0.0.1:9223')`.
 */

import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { homedir } from 'node:os';

const PORT = 9223;
const BASE = `http://127.0.0.1:${PORT}`;
const ROOT = process.platform === 'win32' ? process.env.LOCALAPPDATA ?? join(homedir(), 'AppData', 'Local')
  : process.platform === 'darwin' ? join(homedir(), 'Library', 'Application Support') : join(homedir(), '.config');
/** A mostani MuzikOS-zenekar azonosítója (a tudás mappa aktiv.json-ja); üres, ha nincs (nem MuzikOS, vagy nincs zenekar). */
function band() {
  const env = process.env.MUZIKOS_CHROME_PROFIL;
  if (env !== undefined) return env.replace(/[^\w.-]/g, '');
  const user = process.env.USER || homedir().split('/').pop();
  const dirs = [process.env.MUZIKOS_TUDAS, process.env.MUSICOS_TUDAS,
    ...[`/media/${user}/PenSSD-Adat`, `/run/media/${user}/PenSSD-Adat`].map(b => join(b, 'MuzikOS', 'Tudas')),
    join(homedir(), 'MuzikOS', 'Tudas')].filter(Boolean);
  for (const d of dirs) {
    try { return String(JSON.parse(readFileSync(join(d, 'aktiv.json'), 'utf8')).zenekar ?? '').replace(/[^\w.-]/g, ''); }
    catch { /* nincs ilyen mappa */ }
  }
  return '';
}
const BAND = band();
const PROFILE = join(ROOT, BAND ? `Claude-Chrome-${BAND}` : 'Claude-Chrome');
/** Melyik profillal fut épp a Chrome (a start írja), hogy zenekarváltáskor tudjuk, kell-e cserélni. */
const ACTIVE_FILE = join(ROOT, 'Claude-Chrome-fut.txt');
/** A RendelŐr korábbi profilja (2026-10-22): ha a közös még nincs, ez lesz az, a belépéseivel együtt. */
const LEGACY = join(ROOT, 'RendelOr-Chrome');

function fail(message) {
  console.error(`HIBA: ${message}`);
  process.exit(2);
}

function chromePath() {
  const list = process.platform === 'win32'
    ? [process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA]
      .filter(Boolean).map(d => join(d, 'Google', 'Chrome', 'Application', 'chrome.exe'))
    : process.platform === 'darwin' ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'];
  return list.find(p => existsSync(p)) ?? fail('Nem találom a Google Chrome-ot ezen a gépen.');
}

async function json(path, method = 'GET') {
  const res = await fetch(BASE + path, { method, signal: AbortSignal.timeout(3000) });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function running() {
  try { return await json('/json/version'); } catch { return null; }
}

/** A profil Google-fiókja a Chrome-ban (a Local State-ből); üres, ha a Chrome nincs bejelentkezve. */
function chromeAccount() {
  try {
    const state = JSON.parse(readFileSync(join(PROFILE, 'Local State'), 'utf8'));
    const info = state?.profile?.info_cache?.Default ?? {};
    return info.user_name || '';
  } catch { return ''; }
}

/** A másik profillal futó Chrome szabályos bezárása (zenekarváltás). */
async function closeRunning() {
  const v = await running();
  if (!v) return;
  const page = await connect({ webSocketDebuggerUrl: v.webSocketDebuggerUrl });
  try { await page.send('Browser.close'); } catch { /* a kapcsolat a bezárással megszakad */ }
  for (let i = 0; i < 40 && (await running()); i++) await new Promise(r => setTimeout(r, 250));
  if (await running()) fail('A másik zenekar Chrome-ja nem zárult be: a zenész zárja be az ablakát.');
}

async function start(urls) {
  let was = '';
  try { was = readFileSync(ACTIVE_FILE, 'utf8').trim(); } catch { /* még nem indult */ }
  if (was && was !== PROFILE && (await running())) {
    console.log(`A Chrome másik profillal fut (${was}): bezárom, és a mostanié nyílik.`);
    await closeRunning();
  }
  if (!(await running())) {
    if (!existsSync(PROFILE) && existsSync(LEGACY)) {
      try { renameSync(LEGACY, PROFILE); console.log(`A régi profil átköltözött: ${LEGACY} → ${PROFILE}`); }
      catch (e) { fail(`A régi profilt nem tudtam átnevezni (fut még a régi Chrome-ablak?): ${e.message}`); }
    }
    const child = spawn(chromePath(), [`--user-data-dir=${PROFILE}`, `--remote-debugging-port=${PORT}`,
      '--no-first-run', '--no-default-browser-check', ...(urls.length ? urls : ['about:blank'])],
    { detached: true, stdio: 'ignore' });
    child.unref();
    for (let i = 0; i < 40 && !(await running()); i++) await new Promise(r => setTimeout(r, 250));
    if (!(await running())) fail('A Chrome elindult, de a távvezérlés nem válaszol (127.0.0.1:9223).');
    writeFileSync(ACTIVE_FILE, PROFILE);
    console.log(`Elindult: ${PROFILE}`);
  } else {
    for (const u of urls) await json(`/json/new?${u}`, 'PUT');
    if (urls.length) console.log(`Megnyitva: ${urls.join(', ')}`);
  }
  await status();
}

async function status() {
  const v = await running();
  const account = chromeAccount();
  console.log(v ? `Fut (${v.Browser}), 127.0.0.1:${PORT}` : 'Nem fut.');
  console.log(account
    ? `A Chrome be van jelentkezve: ${account} (a mentett jelszavak és passkeyek felkínálódnak).`
    : 'A Chrome NINCS bejelentkezve a Google-fiókba: a felhasználó a profil ikonjánál (jobb felül) egyszer jelentkezzen be, hogy a mentett jelszavai is meglegyenek.');
}

async function pages() {
  return (await json('/json')).filter(t => t.type === 'page');
}

/** Az első lap, aminek a címében benne van a részlet; ha nincs ilyen lap, egy ilyen keret (a claude.ai-artifact
 *  tartalma egy másik domainről betöltött keretben fut, a szövegét onnan kell olvasni). */
async function pageFor(match) {
  const all = await json('/json');
  return all.find(t => t.type === 'page' && t.url.includes(match))
    ?? all.find(t => t.type === 'iframe' && t.url.includes(match))
    ?? fail(`Nincs olyan lap vagy keret, aminek a címében benne van: ${match}`);
}

/** Egy CDP-munkamenet a laphoz; `send(method, params)` a válasz `result`-ját adja. */
async function connect(target) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = () => bad(new Error('A lap nem fogadta a kapcsolatot.')); });
  let id = 0;
  const waiting = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) {
      const { ok, bad } = waiting.get(m.id);
      waiting.delete(m.id);
      m.error ? bad(new Error(m.error.message)) : ok(m.result);
    }
  };
  const send = (method, params = {}) => new Promise((ok, bad) => {
    const n = ++id;
    waiting.set(n, { ok, bad });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return { send, close: () => ws.close() };
}

async function evaluate(match, expression) {
  const page = await connect(await pageFor(match));
  try {
    const r = await page.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) fail(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  } finally { page.close(); }
}

/** Képernyőkép. A claude.ai-artifact egy belső keretben fut: `--scroll`-lal előbb odagörget, és a `--full`
 *  az egész oldalt veszi (a lap tartalmának teljes méretében). */
async function shot(match, out, full, scrollTo) {
  const target = await pageFor(match);
  const page = await connect(target);
  try {
    await page.send('Page.enable');
    if (scrollTo) {
      await page.send('Runtime.evaluate', { expression: `(() => { const el = document.querySelector(${JSON.stringify(scrollTo)}); if (el) el.scrollIntoView({ block: 'start' }); return !!el; })()`, returnByValue: true });
      await new Promise(r => setTimeout(r, 500));
    }
    const params = { format: 'png' };
    if (full) {
      const m = await page.send('Page.getLayoutMetrics');
      const s = m.cssContentSize ?? m.contentSize;
      params.clip = { x: 0, y: 0, width: s.width, height: s.height, scale: 1 };
      params.captureBeyondViewport = true;
    }
    const r = await page.send('Page.captureScreenshot', params);
    writeFileSync(out, Buffer.from(r.data, 'base64'));
    console.log(`Kép: ${out}`);
  } finally { page.close(); }
}

const [cmd, ...rest] = process.argv.slice(2);
const flags = new Set(rest.filter(a => a.startsWith('--')));
const scrollIdx = rest.indexOf('--scroll');
const scrollTo = scrollIdx >= 0 ? rest[scrollIdx + 1] : null;
const pos = rest.filter((a, i) => !a.startsWith('--') && !(scrollIdx >= 0 && i === scrollIdx + 1));

switch (cmd) {
  case 'start': await start(pos); break;
  case 'status': await status(); break;
  case 'tabs':
    if (!(await running())) fail('A Claude-Chrome nem fut: `start`.');
    for (const t of await pages()) console.log(`${t.title}\n  ${t.url}`);
    break;
  case 'text': {
    const v = await evaluate(pos[0] ?? fail('Melyik lap? (az URL egy részlete)'), 'document.body ? document.body.innerText : ""');
    console.log(v);
    break;
  }
  case 'eval': {
    const v = await evaluate(pos[0] ?? fail('Melyik lap?'), pos[1] ?? fail('Mit értékeljek ki?'));
    console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 2));
    break;
  }
  case 'shot': await shot(pos[0] ?? fail('Melyik lap?'), pos[1] ?? fail('Hova mentsem a képet?'), flags.has('--full'), scrollTo); break;
  default:
    console.log('Használat: start [url…] | status | tabs | text <url-részlet> | shot <url-részlet> <kép.png> [--full] [--scroll <szelektor>] | eval <url-részlet> <kifejezés>');
    process.exit(cmd ? 2 : 0);
}
