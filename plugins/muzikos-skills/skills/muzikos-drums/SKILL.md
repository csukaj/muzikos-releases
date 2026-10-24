---
name: muzikos-drums
description: >-
  A dob felvétele a MuzikOS-en: az akusztikus dob bemikrofonozása a meglévő bemenetekhez igazítva (melyik
  mikrofon hova, hogyan, kell-e 48V; a Reaper-sávok és a bekötési térkép egy mozdulattal), a gain beállítása
  szintméréssel, a mikrofonok fázisának ellenőrzése és javítása, és amit a dobosnak fizikailag kell csinálnia.
  Használd, valahányszor dob, mikrofonozás, overhead, lábdob, pergő, fázis vagy „dobfelvétel” kerül szóba.
  Hívószavak: "vegyük fel az igazi dobot", "mikrofonozzuk be a dobot", "hova tegyem a mikrofont", "hány
  mikrofon kell a dobhoz", "tompa a lábdob", "furcsán szól a dob a felvételen", "nézd meg a fázist".
---

# Dob

## Akusztikus dob: a mikrofonterv

1. **Hány bemenet van?** `audio_devices` (a UMC404HD-n 4). Ha más hangszer is szól közben, annak a bemenetét
   hagyd ki (`first_input`).
2. `dob_mikrofon_terv` `inputs: 4` — a terv: mikrofononként a hely és a mód, a javasolt típus, a 48V.
   - 1 bemenet: egy overhead; 2: Glyn Johns (overhead + oldalmikrofon, egyforma távolságra a pergőtől);
     3: lábdob + két overhead; 4: lábdob + pergő + két overhead; 8: a teljes közeli mikrofonozás is.
   - Mondd el a dobosnak lépésenként, mit hova tegyen, és várd meg, amíg kész. A két overhead a **pergőtől
     egyforma távolságra** legyen (mérőszalag vagy egy zsinór) — ez a legfontosabb.
   - 48V: a kondenzátor-mikrofonnak kell; a UMC404HD-n egy gomb mind a négy bemenetre adja, a dinamikus
     mikrofonnak nem árt.
3. `dob_mikrofon_terv` `apply: true` — a Reaperben mikrofononként egy élesített sáv („Dob – Lábdob”…), és a
   bekötési térképen a mikrofonok és az XLR-kábelek (`felallas_rajz`).

## A gain

Mikrofononként: a dobos üssön **erősen** arra a dobra (a pergőre, a lábdobra; az overheadhez a cintányérra
is), `input_levels` — a csúcs −12 és −6 dBFS között legyen (a dob csúcsos: hagyj tartalékot). Ha túl
hangos, a gain gombot (`muzikos-rig`: a potiállás menthető is) vissza, ha túl halk, fel. A tamokat és a
lábcint a közös gain miatt ne hajtsd túl.

## A fázis

Ha a lábdob vagy a pergő „tompa”, „üres”, vagy furcsán szól a felvételen, és több mikrofon is hallja:
`dob_fazis` `a: 1`, `b: 3` (pl. lábdob és overhead) — a dobos üssön erősen egyet arra a dobra.
- `korrelacio` > 0,3: rendben;
- < −0,3: **fordított fázis** → `reaper_track_set` `track: "Dob – Overhead B"`, `phase_invert: true`, aztán mérd újra;
- a `kesés_ms` a hang útja (≈3 ms/méter); a két overheadnél egyforma legyen a pergőhöz.

## Elektromos dob

Az Alesis Nitro és a többi USB-MIDI-s modul kétféleképpen kerül a felvételre, és mindkettő kell:

- **MIDI-sáv** (a 10. csatorna) egy dobkészlettel: a hangjegyek utólag javíthatók, a készlet cserélhető;
- **hangsáv** a modul saját hangjával (a jack-kimenete a hangkártya egy bemenetén): ez szól úgy, ahogy a dobos
  hallotta.

`dob_midi_sav` `{"device": "Nitro", "kit": "black pearl", "audio_input": 1}` — bekapcsolja a modul MIDI-bemenetét a
Reaperben (ehhez a Reaper újraindul; mentetlen dalnál előbb ments), felteszi a MIDI-sávot a készlettel, és az
`audio_input` bemenetről a hangsávot. A hangsáv monitorozása ki van kapcsolva: a dobos a modul fejhallgatóján
hallja magát, késés nélkül. Készletek (AVL Drumkits, GM-kiosztás): `black pearl` (rock, alap), `red zeppelin`
(nagy, nyitott), `blonde bop` (jazz), `hotrod` (feszes).

Utána kérd meg a dobost, hogy üssön meg minden dobot és cintányért, és nézd meg, mi jön (`reaper_lua`
`reaper.MIDI_GetRecentInputEvent`). A Nitro GM-kiosztással küld (36 lábdob, 38 pergő, 48/45/43 tamok,
42/46 lábcin zárva/nyitva, 49 crash, 51 ride); az első próbán a 38, 43, 45, 46, 48, 49 és 51 jött meg. A modul
MIDI Clockot is küld; az nem baj.

Ha nem jön semmi: `reaper_midi_inputs` `list` — látja-e a Reaper a modult, és be van-e kapcsolva; ha a modult
menet közben dugták be, `enable` újra (a Reaper újraindul, és megtalálja).
