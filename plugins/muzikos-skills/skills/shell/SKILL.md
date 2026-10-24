---
name: shell
description: >-
  Parancs a felhasználó gépére — az OS-hez illő shellben. Windowson PowerShell 7 (`$env:VAR`,
  `Get-Content`, `;` vagy `&&`, here-string, backtick-sorfolytatás), macOS-en és Linuxon POSIX
  sh/bash/zsh; szerveren (SSH-n át) a szerver shellje, az Linux. Használd MINDEN alkalommal, amikor egy
  parancsot adsz, amit a felhasználónak a saját gépén kell lefuttatnia (terminálba másolandó sor,
  telepítési lépés, környezeti változó beállítása, egy script indítása), amikor magad futtatsz egyet a
  gépen, és amikor egy skillbe vagy dokumentációba parancsot írsz. Hívószavak: "add meg a parancsot",
  "mit írjak be a terminálba", "hogyan futtassam", "állítsd be a változót", "nem fut a parancs",
  "PowerShellben hibát ad", "command not found", "export", "2>/dev/null". Angolul: "give me the command",
  "how do I run this", "set the env var", "this doesn't work in PowerShell".
---

# Parancs a felhasználó gépére — az OS-hez illő shellben

A parancs, amit adsz, **annak a gépnek a shelljében fusson, ahol le fogják futtatni** — nem abban, amit
megszoktál. Windowson a terminál alapból PowerShell, és egy bash-sor ott hibát ad, vagy — ami rosszabb —
csendben mást csinál. A csapat többsége Windowson dolgozik; egy „csak másold be" parancs, amit kézzel kell
átírni, nem kész válasz.

## Előbb: melyik gép, melyik shell?

| Hol fut a parancs | Shell | Honnan tudod |
|---|---|---|
| a felhasználó **Windows** gépén | **PowerShell 7** (`pwsh`) | a környezet `Platform: win32`-t mond, vagy az útvonal `C:\…` |
| a felhasználó **macOS / Linux** gépén | **POSIX sh / bash / zsh** | `darwin` / `linux`, vagy az útvonal `/Users/…`, `/home/…` |
| egy **szerveren**, SSH-n át (`ssh <alias> '…'`) | a szerver shellje (Linux, bash) | az idézőjelen BELÜLI rész — azt a szerver futtatja |
| **te futtatod** egy eszközzel | az eszköz shellje | a Bash eszköz POSIX (Windowson is, Git Bash), a PowerShell eszköz PowerShell — a szintaxis az eszközhöz igazodik, nem a géphez |

Ha nem derül ki, melyik gép, **kérdezd meg egyszer** — vagy adj olyan parancsot, ami mindkét shellben fut
(lent). Ne a bash legyen az alapértelmezett tipp.

## Ami mindkét shellben fut

A legjobb parancs az, amin nincs mit fordítani. Ezek egy az egyben mennek PowerShellben és bash-ben is:

- egyetlen programhívás idézett argumentumokkal: `node scripts/build-plugin.mjs --check`, `git -C <repo> fetch origin`,
  `npm test`, `python script.py --db mailbox.db stats`, `gh pr view 12 --json state`;
- `ssh <alias> '<parancs a szerveren>'` — az egyes idézőjel mindkettőben szó szerinti, a belsejét a szerver
  futtatja;
- több parancs `&&`-sel (PowerShell 7-ben is van);
- **egy sorban** — a sorfolytatás shellenként más (`\` vs. backtick), tehát inkább hosszú egy sor, mint
  törött kettő.

Ha a parancs ennél többet kér (változó, átirányítás, fájlművelet, ciklus), **adj két változatot**, külön
blokkban, megcímkézve: `powershell` és `bash`. Ha tudod, melyik gépen vagy, elég az az egy.

## A fordítótábla

| Mit akarsz | bash / zsh | PowerShell 7 |
|---|---|---|
| környezeti változó erre a munkamenetre | `export FOO=bar` | `$env:FOO = 'bar'` |
| környezeti változó olvasása | `$FOO`, `"$CLAUDE_PLUGIN_ROOT/x"` | `$env:FOO`, `"$env:CLAUDE_PLUGIN_ROOT/x"` |
| változó egy parancs idejére | `FOO=bar cmd` | `$env:FOO = 'bar'; cmd` |
| tartósan (új terminálban is) | sor a `~/.zshrc` / `~/.bashrc` végére | `setx FOO bar` (a MOSTANI ablakban nem látszik) |
| a hibakimenet eldobása | `2>/dev/null` | `2>$null`, vagy `-ErrorAction SilentlyContinue` |
| fájl olvasása, ha van | `cat f 2>/dev/null` | `Get-Content f -ErrorAction SilentlyContinue` |
| fájl írása | `printf '%s\n' x > f` | `Set-Content f 'x'` |
| mappa (szülőkkel) | `mkdir -p d` | `New-Item -ItemType Directory -Force d` |
| törlés | `rm -rf d` | `Remove-Item -Recurse -Force d` |
| parancs kimenete változóba | `SHA=$(cmd)` | `$SHA = cmd` |
| több soros szöveg | `<<'EOF' … EOF` | `@' … '@` (a záró `'@` a sor elején) |
| sorfolytatás | `\` a sor végén | `` ` `` a sor végén — vagy inkább egy sor |
| egymás után, hibától függetlenül | `a; b` | `a; b` |
| hol van egy program | `which x` | `(Get-Command x).Source` |
| a home-mappa | `~`, `$HOME` | `~`, `$HOME` (mindkettő működik) |

Csapdák, amik **nem adnak hibát, csak mást csinálnak** PowerShellben: a `$FOO` egy üres PowerShell-változó,
nem a környezeti (`$env:FOO` kell); a `2>/dev/null` egy `C:\dev\null` fájlba próbál írni; a `curl` régi
PowerShellben az `Invoke-WebRequest` álneve (7-ben már a valódi `curl.exe` — ha kétséges, írd ki:
`curl.exe`). Windowson `rsync` alapból nincs: a mappamásolás ott `scp -r`.

## Amikor skillbe vagy dokumentációba írsz parancsot

- A kódblokk címkéje mondja meg a shellt: `bash`, `powershell` — egy címke nélküli blokk olyan, mintha
  mindkettőre ígérne.
- **Aki a felhasználó gépén fut, az legyen mindkét shellben futtatható, vagy legyen két változata.** A
  szerveren futó rész (az `ssh '…'` belseje, a szerver saját parancsai, `php artisan` a szerveren) maradhat
  bash.
- A fejlesztő gépén futó `git` / `gh` / `node` / `npm` hívás maradjon egy sorban és változó nélkül — akkor
  mindkét shellben fut.
- A `$CLAUDE_PLUGIN_ROOT`-ot a Bash eszköz ismeri; PowerShellben `$env:CLAUDE_PLUGIN_ROOT`. A felhasználó
  saját termináljában egyik sincs beállítva: oda a teljes utat írd ki.
