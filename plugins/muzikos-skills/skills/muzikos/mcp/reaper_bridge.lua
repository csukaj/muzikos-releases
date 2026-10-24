-- MuzikOS-híd: a Claude (a muzikos MCP-szerver) ezen át vezérli a Reapert.
-- A Reaper indulásakor a Scripts/__startup.lua tölti be (a szerver telepíti oda).
-- Működés: a szerver Lua-kódot ír a <XDG_RUNTIME_DIR>/muzikos-reaper/request.lua fájlba; a híd
-- lefuttatja, és az eredményt JSON-ban a response.json-ba írja. Hálózat nincs, csak helyi fájl.

local dir = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/muzikos-reaper"
os.execute('mkdir -p "' .. dir .. '"')
local req_path = dir .. "/request.lua"
local resp_path = dir .. "/response.json"

-- ------------------------------------------------------------------ JSON
local function esc(s)
  return (s:gsub('[%c"\\]', function(c)
    local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
    return map[c] or string.format("\\u%04x", c:byte())
  end))
end

local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" then return false end
    n = n + 1
  end
  return n == #t
end

local function encode(v, depth)
  depth = depth or 0
  if depth > 20 then return '"…"' end
  local t = type(v)
  if v == nil then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if math.type and math.type(v) == "integer" then return tostring(v) end
    return string.format("%.10g", v)
  elseif t == "string" then return '"' .. esc(v) .. '"'
  elseif t == "table" then
    local parts = {}
    if next(v) == nil then return "[]" end
    if is_array(v) then
      for _, x in ipairs(v) do parts[#parts + 1] = encode(x, depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for k, x in pairs(v) do parts[#parts + 1] = '"' .. esc(tostring(k)) .. '":' .. encode(x, depth + 1) end
    return "{" .. table.concat(parts, ",") .. "}"
  else
    return '"' .. esc(tostring(v)) .. '"'
  end
end

-- ------------------------------------------------------------------ segédfüggvények a kéréseknek
muzikos = muzikos or {}
local logbuf = {}
function log(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[#parts + 1] = tostring(select(i, ...)) end
  logbuf[#logbuf + 1] = table.concat(parts, " ")
end

local function track_info(tr, idx)
  local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
  local recin = math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT"))
  local input
  if recin < 0 then input = "nincs"
  elseif recin & 4096 ~= 0 then
    local ch = recin & 31
    input = "MIDI" .. (ch == 0 and " (minden csatorna)" or (" " .. ch .. ". csatorna"))
  else
    local start = (recin & 1023) + 1
    if recin & 1024 ~= 0 then input = "sztereó " .. start .. "/" .. (start + 1)
    else input = "mono " .. start end
  end
  local fx = {}
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, fxname = reaper.TrackFX_GetFXName(tr, i, "")
    fx[#fx + 1] = fxname
  end
  return {
    sorszam = idx + 1, nev = name, bemenet = input,
    elesitve = reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") == 1,
    monitor = math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_RECMON")),
    hangero_dB = math.floor(20 * math.log(math.max(reaper.GetMediaTrackInfo_Value(tr, "D_VOL"), 1e-9), 10) * 10 + 0.5) / 10,
    nema = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1,
    effektek = fx,
  }
end

function muzikos.transport()
  local st = reaper.GetPlayState()
  local state = "áll"
  if st & 4 ~= 0 then state = "felvétel" elseif st & 2 ~= 0 then state = "szünet" elseif st & 1 ~= 0 then state = "lejátszás" end
  return {
    allapot = state,
    pozicio_mp = (st & 1 ~= 0) and reaper.GetPlayPosition() or reaper.GetCursorPosition(),
    tempo = reaper.Master_GetTempo(),
    metronom = reaper.GetToggleCommandState(40364) == 1,
  }
end

-- Mentés másként: a Main_SaveProjectEx csak egy másolatot ír (a fül nem kapcsolódik a fájlhoz),
-- ezért utána ugyanazon a fülön megnyitjuk a frissen mentett fájlt — így semmi nem vész el.
-- A mappát előbb létrehozzuk: nem létező mappába mentve a Reaper hibaablakot dobna.
function muzikos.save_as(path)
  local dir = path:match("^(.*)/[^/]+$")
  if dir then reaper.RecursiveCreateDirectory(dir, 0) end
  reaper.Main_SaveProjectEx(0, path, 0)
  reaper.Main_openProject("noprompt:" .. path)
  local _, now = reaper.EnumProjects(-1, "")
  if now ~= path then error("a mentés nem sikerült: " .. path) end
  return now
end

-- A nyitott dalok (projekt-fülek); az aktív a „most” jelzésű.
function muzikos.projects()
  local cur = reaper.EnumProjects(-1, "")
  local list = {}
  for i = 0, 99 do
    local p, f = reaper.EnumProjects(i, "")
    if not p then break end
    local _, name = reaper.GetSetProjectInfo_String(p, "PROJECT_NAME", "", false)
    list[#list + 1] = {
      ful = i + 1, nev = (name ~= "" and name) or "(mentetlen)", fajl = f,
      most = (p == cur), mentetlen = reaper.IsProjectDirty(p) ~= 0, savok = reaper.CountTracks(p),
    }
  end
  return list
end

function muzikos.status()
  local _, projfile = reaper.EnumProjects(-1, "")
  local tracks = {}
  for i = 0, reaper.CountTracks(0) - 1 do tracks[#tracks + 1] = track_info(reaper.GetTrack(0, i), i) end
  local inputs = {}
  for i = 0, reaper.GetNumAudioInputs() - 1 do inputs[#inputs + 1] = reaper.GetInputChannelName(i) end
  local _, mode = reaper.GetAudioDeviceInfo("MODE")
  local _, srate = reaper.GetAudioDeviceInfo("SRATE")
  local _, bsize = reaper.GetAudioDeviceInfo("BSIZE")
  return {
    projekt = projfile ~= "" and projfile or "(mentetlen)",
    felvetel_mappa = reaper.GetProjectPath(""),
    hang = { mod = mode, mintavetel = srate, puffer = bsize, bemenetek = inputs },
    transport = muzikos.transport(),
    savok = tracks,
  }
end

-- ------------------------------------------------------------------ dalszerkezet (#336)
-- Ütem ↔ idő: az ütemek 1-től számozva, ahogy a zenész mondja.
function muzikos.bar_time(m) return reaper.TimeMap2_beatsToTime(0, 0, m - 1) end

-- Hányadik ütemben van t, és hol kezdődik az az ütem; snap: a legközelebbi ütemhatárra kerekít.
function muzikos.bar_of(t, snap)
  local _, measures = reaper.TimeMap2_timeToBeats(0, t)
  local start = reaper.TimeMap2_beatsToTime(0, 0, measures)
  if snap then
    local nxt = reaper.TimeMap2_beatsToTime(0, 0, measures + 1)
    if nxt - t < t - start then return measures + 2, nxt end
  end
  return measures + 1, start
end

-- A jelölők és a dalrészek (régiók), időrendben, ütemszámmal.
function muzikos.markers()
  local out, i = {}, 0
  while true do
    local ret, isrgn, pos, rgnend, name, idx = reaper.EnumProjectMarkers3(0, i)
    if ret == 0 then break end
    local e = { tipus = isrgn and "resz" or "jelolo", nev = name, azonosito = idx,
                kezd_mp = pos, kezd_utem = (muzikos.bar_of(pos)) }
    if isrgn then e.veg_mp = rgnend; e.veg_utem = (muzikos.bar_of(rgnend)) end
    out[#out + 1] = e
    i = i + 1
  end
  return out
end

-- A mostani pozíció: lejátszás/felvétel közben a lejátszófej, különben a kurzor.
function muzikos.now()
  if reaper.GetPlayState() & 1 ~= 0 then return reaper.GetPlayPosition() end
  return reaper.GetCursorPosition()
end

-- ------------------------------------------------------------------ visszahallgatás, rájátszás (#331)
-- Sáv keresése: sorszám (1-től) vagy a név része (ékezet és kisbetű nem számít).
local function plain(s)
  s = tostring(s):lower()
  local map = { ["á"]="a", ["é"]="e", ["í"]="i", ["ó"]="o", ["ö"]="o", ["ő"]="o", ["ú"]="u", ["ü"]="u", ["ű"]="u" }
  return (s:gsub("[\195\197][\128-\191]", function(c) return map[c] or c end))
end

function muzikos.find_tracks(spec)
  local out = {}
  if type(spec) ~= "table" then spec = { spec } end
  for _, want in ipairs(spec) do
    local n = tonumber(want)
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
      if (n and i + 1 == n) or (not n and plain(name):find(plain(want), 1, true)) then out[#out + 1] = { tr = tr, i = i } end
    end
  end
  return out
end

-- Egy sáv felvétele a kottához (#319): hangfájlnál a fájl és az elhelyezése, MIDI-nél a hangjegyek
-- negyedekben a dal elejétől; mellé a tempó és az ütemmutató a felvétel helyén.
function muzikos.take_info(o)
  local ts = muzikos.find_tracks(o.track)
  if #ts == 0 then error("nincs ilyen sáv: " .. tostring(o.track)) end
  local tr = ts[1].tr
  local n = reaper.CountTrackMediaItems(tr)
  if n == 0 then error("a sávon nincs felvétel") end
  local it = reaper.GetTrackMediaItem(tr, o.item and math.min(o.item, n) - 1 or n - 1)
  local tk = reaper.GetActiveTake(it)
  if not tk then error("a felvételnek nincs aktív take-je") end
  local pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local num, den, bpm = reaper.TimeMap_GetTimeSigAtTime(0, pos)
  local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
  local r = { sav = name, pos = pos, len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH"),
              offs = reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS"),
              rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE"),
              qn = reaper.TimeMap2_timeToQN(0, pos), bpm = bpm, num = num, den = den, felvetelek = n }
  if reaper.TakeIsMIDI(tk) then
    local notes = {}
    local _, cnt = reaper.MIDI_CountEvts(tk)
    for i = 0, cnt - 1 do
      local _, _, muted, sp, ep, chan, pitch, vel = reaper.MIDI_GetNote(tk, i)
      if not muted then
        notes[#notes + 1] = { s = reaper.MIDI_GetProjQNFromPPQPos(tk, sp), e = reaper.MIDI_GetProjQNFromPPQPos(tk, ep),
                              p = pitch, v = vel, c = chan + 1 }
      end
    end
    r.midi = notes
  else
    r.file = reaper.GetMediaSourceFileName(reaper.GetMediaItemTake_Source(tk), "")
  end
  return r
end

-- ------------------------------------------------------------------ take-ek és összevágás (#332)
-- A take-ek a sáv rögzített rétegein (Reaper 7: fixed lanes): minden felvétel egy réteg. A végleges változat egy
-- külön rétegre kerül („Végleges”), a választott részekből összevágva; az eredeti rétegek nem változnak.
local COMP_NAME = "Végleges"

local function lane_count(tr) return math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_NUMFIXEDLANES")) end

function muzikos.take_lanes(o)
  local ts = muzikos.find_tracks(o.track)
  if #ts == 0 then error("nincs ilyen sáv: " .. tostring(o.track)) end
  local tr = ts[1].tr
  if o.prepare and reaper.GetMediaTrackInfo_Value(tr, "I_FREEMODE") ~= 2 then
    reaper.SetMediaTrackInfo_Value(tr, "I_FREEMODE", 2)        -- rögzített rétegek: az új felvétel új rétegre megy
  end
  local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
  local lanes = {}
  for l = 0, lane_count(tr) - 1 do
    local _, ln = reaper.GetSetMediaTrackInfo_String(tr, "P_LANENAME:" .. l, "", false)
    lanes[#lanes + 1] = { reteg = l, nev = ln, szol = reaper.GetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. l) > 0 }
  end
  local items = {}
  for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    local tk = reaper.GetActiveTake(it)
    if tk and not reaper.TakeIsMIDI(tk) then
      items[#items + 1] = { reteg = math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")),
        pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION"), len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH"),
        offs = reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS"), rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE"),
        file = reaper.GetMediaSourceFileName(reaper.GetMediaItemTake_Source(tk), "") }
    end
  end
  return { sav = name, retegek_modja = reaper.GetMediaTrackInfo_Value(tr, "I_FREEMODE") == 2, retegek = lanes, felvetelek = items }
end

-- Összevágás: parts = {{t0, t1, lane}}: minden rész a választott réteg felvételéből, áttűnéssel (fade mp) a
-- vágásoknál; a „Végleges” rétegre kerül, és csak az szól. Az előző „Végleges” összevágás helyére jön.
function muzikos.take_comp(o)
  local ts = muzikos.find_tracks(o.track)
  if #ts == 0 then error("nincs ilyen sáv: " .. tostring(o.track)) end
  local tr = ts[1].tr
  if reaper.GetMediaTrackInfo_Value(tr, "I_FREEMODE") ~= 2 then error("a sáv nincs rétegekben (take_lista prepare)") end
  local fade = o.fade or 0.015
  reaper.Undo_BeginBlock()
  -- a végleges réteg: a meglévő, vagy egy új a végén
  local comp
  for l = 0, lane_count(tr) - 1 do
    local _, ln = reaper.GetSetMediaTrackInfo_String(tr, "P_LANENAME:" .. l, "", false)
    if ln == COMP_NAME then comp = l end
  end
  if comp then                                   -- a korábbi összevágás törlése (az eredeti rétegek maradnak)
    for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do
      local it = reaper.GetTrackMediaItem(tr, i)
      if math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")) == comp then reaper.DeleteTrackMediaItem(tr, it) end
    end
  else
    comp = lane_count(tr)
    reaper.SetMediaTrackInfo_Value(tr, "I_NUMFIXEDLANES", comp + 1)
  end
  local made = {}
  for _, p in ipairs(o.parts) do
    -- a választott réteg felvétele, ami a részt (legjobban) lefedi
    local best, cover = nil, 0
    for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
      local it = reaper.GetTrackMediaItem(tr, i)
      if math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")) == p.lane then
        local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
        local b = a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
        local c = math.min(b, p.t1) - math.max(a, p.t0)
        if c > cover then best, cover = it, c end
      end
    end
    if not best then error(string.format("a(z) %d. rétegen nincs felvétel %.1f–%.1f mp között", p.lane + 1, p.t0, p.t1)) end
    local a = reaper.GetMediaItemInfo_Value(best, "D_POSITION")
    local b = a + reaper.GetMediaItemInfo_Value(best, "D_LENGTH")
    local s, e = math.max(a, p.t0 - fade / 2), math.min(b, p.t1 + fade / 2)
    local _, chunk = reaper.GetItemStateChunk(best, "", false)
    chunk = chunk:gsub("\n%s*I?GUID [^\n]*", "")                  -- új azonosítót kap
    local it = reaper.AddMediaItemToTrack(tr)
    reaper.SetItemStateChunk(it, chunk, false)
    local tk = reaper.GetActiveTake(it)
    local rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE")
    reaper.SetMediaItemTakeInfo_Value(tk, "D_STARTOFFS", reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS") + (s - a) * rate)
    reaper.SetMediaItemInfo_Value(it, "D_POSITION", s)
    reaper.SetMediaItemInfo_Value(it, "D_LENGTH", e - s)
    reaper.SetMediaItemInfo_Value(it, "D_FADEINLEN", fade)
    reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", fade)
    reaper.SetMediaItemInfo_Value(it, "I_FIXEDLANE", comp)
    made[#made + 1] = { resz = p.name, reteg = p.lane, kezd_mp = s, veg_mp = e }
  end
  reaper.GetSetMediaTrackInfo_String(tr, "P_LANENAME:" .. comp, COMP_NAME, true)
  for l = 0, lane_count(tr) - 1 do reaper.SetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. l, l == comp and 1 or 0) end
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("MuzikOS: végleges összevágás", -1)
  return { reteg = comp, darabok = made }
end

-- ------------------------------------------------------------------ felvétel javítása (#326)
local function track_of(spec)
  local ts = muzikos.find_tracks(spec)
  if #ts == 0 then error("nincs ilyen sáv: " .. tostring(spec)) end
  return ts[1].tr
end

-- Ami most szól a sávon: rétegeknél a szóló réteg elemei, különben minden elem.
local function playing_items(tr, midi)
  local lanes = reaper.GetMediaTrackInfo_Value(tr, "I_FREEMODE") == 2
  local out = {}
  for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    local tk = reaper.GetActiveTake(it)
    local lane = math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE"))
    if tk and (reaper.TakeIsMIDI(tk) == midi)
       and (not lanes or reaper.GetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. lane) > 0) then
      out[#out + 1] = it
    end
  end
  return out
end

local function take_named(it, name)
  for k = 0, reaper.CountTakes(it) - 1 do
    local tk = reaper.GetTake(it, k)
    local _, n = reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", "", false)
    if n == name then return tk, k end
  end
end

-- MIDI ritmusra igazítása. o = {track, t0, t1 (mp), grid (negyedben, pl. 0.25), strength (0–1),
-- pitches = {…} vagy nil, vel = 0–1 (a dinamika kiegyenlítése az átlag felé), apply}. Az eredeti take
-- „eredeti” néven megmarad az elemen; a javítás egy „javított” másolaton megy (restore visszaváltja).
function muzikos.midi_fix(o)
  local tr = track_of(o.track)
  local want = {}
  for _, p in ipairs(o.pitches or {}) do want[p] = true end
  local filter = next(want) ~= nil
  local g, st = o.grid or 0.25, o.strength or 1
  local items = playing_items(tr, true)
  if #items == 0 then error("a sávon nincs MIDI-elem") end
  if o.restore then
    local n = 0
    for _, it in ipairs(items) do
      local _, k = take_named(it, "eredeti")
      if k then reaper.SetMediaItemInfo_Value(it, "I_CURTAKE", k); n = n + 1 end
    end
    reaper.UpdateArrange()
    return { visszaallitva = n }
  end
  local stat = { hangok = 0, elotte_ms = 0, utana_ms = 0, max_ms = 0, ero_elotte = {}, ero_utana = {} }
  if o.apply then reaper.Undo_BeginBlock() end
  for _, it in ipairs(items) do
    local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local b = a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
    if b > o.t0 and a < o.t1 then
      local tk = reaper.GetActiveTake(it)
      if o.apply then
        local _, cur = reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", "", false)
        if cur ~= "javított" then
          reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", "eredeti", true)
          local old = take_named(it, "javított")
          if old then                                     -- a korábbi javítás helyett újat az eredetiből
            reaper.SetActiveTake(old)
            reaper.SelectAllMediaItems(0, false); reaper.SetMediaItemSelected(it, true)
            reaper.Main_OnCommand(40129, 0)               -- Take: Delete active take from items
            local _, k = take_named(it, "eredeti"); reaper.SetMediaItemInfo_Value(it, "I_CURTAKE", k)
          end
          reaper.SelectAllMediaItems(0, false); reaper.SetMediaItemSelected(it, true)
          reaper.Main_OnCommand(40639, 0)                 -- Take: Duplicate active take
          tk = reaper.GetActiveTake(it)
          reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", "javított", true)
        end
      end
      local _, cnt = reaper.MIDI_CountEvts(tk)
      local sel, sum = {}, 0
      for k = 0, cnt - 1 do
        local _, s_, m_, sp, ep, ch, p, v = reaper.MIDI_GetNote(tk, k)
        local t = reaper.MIDI_GetProjTimeFromPPQPos(tk, sp)
        if t >= o.t0 - 0.02 and t < o.t1 - 0.02 and (not filter or want[p]) then
          sel[#sel + 1] = { k = k, sp = sp, ep = ep, v = v, s = s_, m = m_, ch = ch, p = p }
          sum = sum + v
        end
      end
      local mean = #sel > 0 and sum / #sel or 0
      for _, n in ipairs(sel) do
        local qn = reaper.MIDI_GetProjQNFromPPQPos(tk, n.sp)
        local target = math.floor(qn / g + 0.5) * g
        local nq = qn + (target - qn) * st
        local t, tt, tn = reaper.TimeMap2_QNToTime(0, qn), reaper.TimeMap2_QNToTime(0, target), reaper.TimeMap2_QNToTime(0, nq)
        local before, after = math.abs(tt - t) * 1000, math.abs(tt - tn) * 1000
        stat.hangok = stat.hangok + 1
        stat.elotte_ms = stat.elotte_ms + before
        stat.utana_ms = stat.utana_ms + after
        stat.max_ms = math.max(stat.max_ms, before)
        local nv = math.floor(n.v + (mean - n.v) * (o.vel or 0) + 0.5)
        stat.ero_elotte[#stat.ero_elotte + 1] = n.v
        stat.ero_utana[#stat.ero_utana + 1] = nv
        if o.apply then
          local nsp = reaper.MIDI_GetPPQPosFromProjQN(tk, nq)
          reaper.MIDI_SetNote(tk, n.k, n.s, n.m, nsp, n.ep + (nsp - n.sp), n.ch, n.p, nv, true)
        end
      end
      if o.apply then reaper.MIDI_Sort(tk) end
    end
  end
  if o.apply then
    reaper.UpdateArrange()
    reaper.Undo_EndBlock("MuzikOS: MIDI ritmusra igazítása", -1)
  end
  local function spread(t)
    if #t == 0 then return 0 end
    local s, m = 0, 0
    for _, v in ipairs(t) do s = s + v end
    m = s / #t; s = 0
    for _, v in ipairs(t) do s = s + (v - m) ^ 2 end
    return math.floor(math.sqrt(s / #t) * 10 + 0.5) / 10
  end
  local n = math.max(stat.hangok, 1)
  return { hangok = stat.hangok, atlag_elteres_ms = math.floor(stat.elotte_ms / n * 10 + 0.5) / 10,
           utana_ms = math.floor(stat.utana_ms / n * 10 + 0.5) / 10, legnagyobb_ms = math.floor(stat.max_ms + 0.5),
           ero_szoras = spread(stat.ero_elotte), ero_szoras_utana = spread(stat.ero_utana), atirva = o.apply and true or false }
end

-- A szóló hangelemek adatai (a hangkezdetek kereséséhez): pozíció, hossz, forrásfájl, eltolás, sebesség.
function muzikos.audio_items(o)
  local tr = track_of(o.track)
  local out = {}
  for _, it in ipairs(playing_items(tr, false)) do
    local tk = reaper.GetActiveTake(it)
    local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local l = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
    if a + l > (o.t0 or 0) and a < (o.t1 or math.huge) then
      out[#out + 1] = { pos = a, len = l, qn = reaper.TimeMap2_timeToQN(0, a), offs = reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS"),
        rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE"), stretch = reaper.GetTakeNumStretchMarkers(tk),
        file = reaper.GetMediaSourceFileName(reaper.GetMediaItemTake_Source(tk), "") }
    end
  end
  return out
end

-- Hangsáv ütései a rácsra, nyújtásjelölőkkel (a hangfájl nem változik, nincs vágás). o = {track, t0, t1,
-- onsets = {projektidő mp…} (a hangkezdetek), grid (negyed), strength, min_ms (csak ennél nagyobb eltérés),
-- apply, restore}. A visszaállítás a tartomány nyújtásjelölőit törli.
function muzikos.audio_fix(o)
  local tr = track_of(o.track)
  local g, st, min_s = o.grid or 0.25, o.strength or 1, (o.min_ms or 10) / 1000
  local items = playing_items(tr, false)
  if #items == 0 then error("a sávon nincs hangelem") end
  if o.apply or o.restore then reaper.Undo_BeginBlock() end
  local moved, kept, n_rm = {}, 0, 0
  for _, it in ipairs(items) do
    local tk = reaper.GetActiveTake(it)
    local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local b = a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
    local rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE")
    if b > o.t0 and a < o.t1 then
      -- a tartomány korábbi jelölői
      for k = reaper.GetTakeNumStretchMarkers(tk) - 1, 0, -1 do
        local _, pos = reaper.GetTakeStretchMarker(tk, k)
        local t = a + pos / rate
        if t >= o.t0 - 0.05 and t < o.t1 + 0.05 and (o.apply or o.restore) then
          reaper.DeleteTakeStretchMarkers(tk, k); n_rm = n_rm + 1
        end
      end
      if not o.restore then
        local offs = reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS")
        local marks = {}
        for _, t in ipairs(o.onsets or {}) do
          if t > a + 0.03 and t < b - 0.03 and t >= o.t0 and t < o.t1 then
            local qn = reaper.TimeMap2_timeToQN(0, t)
            local tt = reaper.TimeMap2_QNToTime(0, math.floor(qn / g + 0.5) * g)
            local d = tt - t
            local nt = (math.abs(d) >= min_s) and (t + d * st) or t
            -- elteres_ms: + késik, − siet
            if nt ~= t then moved[#moved + 1] = { mp = t, elteres_ms = math.floor(-d * 1000 + 0.5), uj_mp = nt } else kept = kept + 1 end
            marks[#marks + 1] = { pos = (nt - a) * rate, src = offs + (t - a) * rate }
          end
        end
        if o.apply and #marks > 0 then
          -- horgony a tartomány két szélén, hogy azon kívül semmi ne mozduljon
          local e0, e1 = math.max(a, o.t0 - 0.02), math.min(b, o.t1)
          reaper.SetTakeStretchMarker(tk, -1, (e0 - a) * rate, offs + (e0 - a) * rate)
          for _, m in ipairs(marks) do reaper.SetTakeStretchMarker(tk, -1, m.pos, m.src) end
          reaper.SetTakeStretchMarker(tk, -1, (e1 - a) * rate, offs + (e1 - a) * rate)
        end
      end
    end
  end
  if o.apply or o.restore then
    reaper.UpdateArrange()
    reaper.Undo_EndBlock(o.restore and "MuzikOS: hangsáv igazítás visszavonása" or "MuzikOS: hangsáv ütései a rácsra", -1)
  end
  return { mozdul = moved, helyen = kept, torolt_jelolok = n_rm, atirva = (o.apply or o.restore) and true or false }
end

-- Egy darab másolata a forráselemből a célrétegre, [s, e] között, áttűnéssel.
local function copy_piece(tr, src, s, e, lane, fade)
  local a = reaper.GetMediaItemInfo_Value(src, "D_POSITION")
  local _, chunk = reaper.GetItemStateChunk(src, "", false)
  chunk = chunk:gsub("\n%s*I?GUID [^\n]*", "")
  local it = reaper.AddMediaItemToTrack(tr)
  reaper.SetItemStateChunk(it, chunk, false)
  local tk = reaper.GetActiveTake(it)
  local rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE")
  reaper.SetMediaItemTakeInfo_Value(tk, "D_STARTOFFS", reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS") + (s - a) * rate)
  reaper.SetMediaItemInfo_Value(it, "D_POSITION", s)
  reaper.SetMediaItemInfo_Value(it, "D_LENGTH", e - s)
  reaper.SetMediaItemInfo_Value(it, "D_FADEINLEN", fade)
  reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", fade)
  reaper.SetMediaItemInfo_Value(it, "I_FIXEDLANE", lane)
  return it
end

-- Ütem(ek) cseréje egy másik take ugyanazon részére. o = {track, t0, t1, lane (a forrás réteg), fade}.
-- A csere a „Végleges” rétegen megy; ha még nincs, a most szóló rétegből lesz (az eredeti rétegek maradnak).
function muzikos.bar_replace(o)
  local tr = track_of(o.track)
  if reaper.GetMediaTrackInfo_Value(tr, "I_FREEMODE") ~= 2 then error("a sáv nincs rétegekben: nincs másik take") end
  local fade = o.fade or 0.015
  local h = fade / 2
  local comp, playing
  for l = 0, lane_count(tr) - 1 do
    local _, ln = reaper.GetSetMediaTrackInfo_String(tr, "P_LANENAME:" .. l, "", false)
    if ln == COMP_NAME then comp = l end
    if reaper.GetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. l) > 0 and not playing then playing = l end
  end
  if o.lane == comp then error("a forrás nem lehet a „Végleges” réteg") end
  reaper.Undo_BeginBlock()
  if not comp then
    comp = lane_count(tr)
    reaper.SetMediaTrackInfo_Value(tr, "I_NUMFIXEDLANES", comp + 1)
    local src = {}
    for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
      local it = reaper.GetTrackMediaItem(tr, i)
      if math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")) == (playing or 0) then src[#src + 1] = it end
    end
    for _, it in ipairs(src) do
      local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
      copy_piece(tr, it, a, a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH"), comp, 0)
    end
  end
  -- a végleges rétegből kivágjuk a részt (a szélein áttűnésnyi átfedéssel)
  local cut = {}
  for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    if math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")) == comp then cut[#cut + 1] = it end
  end
  for _, it in ipairs(cut) do
    local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local b = a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
    if b > o.t0 and a < o.t1 then
      local mid = it
      if a < o.t0 + h then
        mid = reaper.SplitMediaItem(it, o.t0 + h)
        reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", fade)
      end
      if mid and b > o.t1 - h then
        local right = reaper.SplitMediaItem(mid, o.t1 - h)
        if right then reaper.SetMediaItemInfo_Value(right, "D_FADEINLEN", fade) end
      end
      if mid then reaper.DeleteTrackMediaItem(tr, mid) end
    end
  end
  -- a forrás take ugyanazon része
  local best, cover = nil, 0
  for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    if math.floor(reaper.GetMediaItemInfo_Value(it, "I_FIXEDLANE")) == o.lane then
      local a = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
      local c = math.min(a + reaper.GetMediaItemInfo_Value(it, "D_LENGTH"), o.t1) - math.max(a, o.t0)
      if c > cover then best, cover = it, c end
    end
  end
  if not best then
    reaper.Undo_EndBlock("MuzikOS: ütemcsere", -1)
    error(string.format("a(z) %d. take-ben nincs felvétel %.1f–%.1f mp között", o.lane + 1, o.t0, o.t1))
  end
  local a = reaper.GetMediaItemInfo_Value(best, "D_POSITION")
  local b = a + reaper.GetMediaItemInfo_Value(best, "D_LENGTH")
  copy_piece(tr, best, math.max(a, o.t0 - h), math.min(b, o.t1 + h), comp, fade)
  reaper.GetSetMediaTrackInfo_String(tr, "P_LANENAME:" .. comp, COMP_NAME, true)   -- a végén: az üres réteg nevét elhagyná
  for l = 0, lane_count(tr) - 1 do reaper.SetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. l, l == comp and 1 or 0) end
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("MuzikOS: ütemcsere", -1)
  return { reteg = comp, forras_take = o.lane + 1, kezd_mp = o.t0, veg_mp = o.t1 }
end

-- Melyik réteg szóljon: egy take meghallgatásához, vagy vissza a véglegeshez.
function muzikos.take_play(o)
  local ts = muzikos.find_tracks(o.track)
  if #ts == 0 then error("nincs ilyen sáv: " .. tostring(o.track)) end
  local tr = ts[1].tr
  for l = 0, lane_count(tr) - 1 do reaper.SetMediaTrackInfo_Value(tr, "C_LANEPLAYS:" .. l, l == o.lane and 1 or 0) end
  reaper.UpdateArrange()
  return { szol = o.lane }
end

-- Kit hall a zenész: a „hear” sávok szólnak a Reaperből, a többi némítva; a „record” sávok élesítve.
-- direct = a zenész a saját hangszerét a hangkártya közvetlen monitorozásán hallja → a felvett sáv
-- szoftveres monitorozása KI (különben kétszer, késve szólna).
function muzikos.overdub(o)
  local hear, rec, info = {}, {}, {}
  for _, t in ipairs(muzikos.find_tracks(o.hear or {})) do hear[t.i] = true end
  for _, t in ipairs(muzikos.find_tracks(o.record or {})) do rec[t.i] = true end
  -- előbb ellenőrzés, csak utána állítás: egy elírt sávnév ne állítsa át a többit
  if #(o.record or {}) > 0 and next(rec) == nil then error("nincs ilyen felveendő sáv: " .. table.concat(o.record, ", ")) end
  if #(o.hear or {}) > 0 and next(hear) == nil then error("nincs ilyen hallgatandó sáv: " .. table.concat(o.hear, ", ")) end
  reaper.Undo_BeginBlock()
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if rec[i] then
      reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
      reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", o.direct == false and 1 or 0)
      reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
    else
      reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
      if o.mute_others ~= false then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", hear[i] and 0 or 1) end
    end
    reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", 0)
  end
  reaper.Undo_EndBlock("MuzikOS: rájátszás beállítása", -1)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    info[#info + 1] = { sorszam = i + 1, nev = name,
      szerep = rec[i] and "felvesz" or (reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1 and "némítva" or "szól"),
      monitor = math.floor(reaper.GetMediaTrackInfo_Value(tr, "I_RECMON")) }
  end
  return info
end

-- Fejhallgató-keverés: a megadott sávokból küldés a hangkártya egy kimenetpárjára (pre-fader: a fő keverés
-- hangerejétől független). out = az első kimenet sorszáma 1-től (3 = 3/4); levels = {sávnév = dB}.
function muzikos.cue_mix(o)
  local made = {}
  local dst = math.max((o.out or 3) - 1, 0)
  for spec, db in pairs(o.levels or {}) do
    for _, t in ipairs(muzikos.find_tracks(spec)) do
      -- a meglévő küldés ugyanerre a kimenetre: újrahasznosítjuk
      local idx = -1
      for k = 0, reaper.GetTrackNumSends(t.tr, 1) - 1 do
        if math.floor(reaper.GetTrackSendInfo_Value(t.tr, 1, k, "I_DSTCHAN")) == dst then idx = k end
      end
      if idx < 0 then idx = reaper.CreateTrackSend(t.tr, nil) end
      reaper.SetTrackSendInfo_Value(t.tr, 1, idx, "I_DSTCHAN", dst)
      reaper.SetTrackSendInfo_Value(t.tr, 1, idx, "I_SENDMODE", 3)                 -- pre-fader (post-FX)
      reaper.SetTrackSendInfo_Value(t.tr, 1, idx, "D_VOL", 10 ^ ((tonumber(db) or 0) / 20))
      local _, name = reaper.GetSetMediaTrackInfo_String(t.tr, "P_NAME", "", false)
      made[#made + 1] = { sav = name, kimenet = (dst + 1) .. "/" .. (dst + 2), dB = tonumber(db) or 0 }
    end
  end
  return made
end

-- Effekt hozzáadása több lehetséges néven (LV2/VST/JS alatt más a neve).
local FX_ALIASES = {
  ["neural amp modeler"] = { "Neural Amp Modeler", "LV2: Neural Amp Modeler", "NAM" },
  ["guitarix"] = { "Guitarix", "LV2: GxAmplifier-X", "GxAmplifier", "gx_amp" },
  ["reaeq"] = { "ReaEQ" }, ["reacomp"] = { "ReaComp" }, ["reaverb"] = { "ReaVerbate" },
  -- AVL Drumkits (avldrums.lv2): a Reaperben a készletek neve látszik, nem a csomagé. GM-kiosztás, 10. csatorna.
  ["avl drumkits"] = { "Black Pearl Drumkit (Robin Gareus)" }, ["avldrums"] = { "Black Pearl Drumkit (Robin Gareus)" },
  ["avl"] = { "Black Pearl Drumkit (Robin Gareus)" },
  ["black pearl"] = { "Black Pearl Drumkit (Robin Gareus)" }, ["red zeppelin"] = { "Red Zeppelin Drumkit (Robin Gareus)" },
  ["blonde bop"] = { "Blonde Bop Drumkit (Robin Gareus)" }, ["blonde bop hotrod"] = { "Blonde Bop HotRod Drumkit (Robin Gareus)" },
  ["drumgizmo"] = { "DrumGizmo" },
}

local function add_fx(tr, want)
  local names = FX_ALIASES[want:lower()] or { want }
  for _, n in ipairs(names) do
    local idx = reaper.TrackFX_AddByName(tr, n, false, -1)
    if idx >= 0 then
      local _, real = reaper.TrackFX_GetFXName(tr, idx, "")
      return real
    end
  end
  return nil
end

function muzikos.add_track(o)
  reaper.Undo_BeginBlock()
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, true)
  local tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", o.name or "Sáv", true)
  local recin
  if o.kind == "midi" then
    recin = 4096 + ((o.midi_device or 63) << 5) + (o.midi_channel or 0)   -- 63 = minden MIDI-bemenet
  else
    local start = math.max((o.input or 1) - 1, 0)
    recin = start + (o.stereo and 1024 or 0)
    if not o.stereo then reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2) end
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", recin)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 0)       -- a bemenetet veszi fel
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", o.arm == false and 0 or 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", o.monitor == false and 0 or 1)
  local added, missing = {}, {}
  for _, f in ipairs(o.fx or {}) do
    local real = add_fx(tr, f)
    if real then added[#added + 1] = real else missing[#missing + 1] = f end
  end
  reaper.TrackList_AdjustWindows(false)
  reaper.Undo_EndBlock("MuzikOS: új sáv (" .. (o.name or "") .. ")", -1)
  local info = track_info(tr, idx)
  info.hozzaadott_effektek = added
  if #missing > 0 then info.nem_talalt_effektek = missing end
  return info
end

-- Hangjegyek új sávra (#327: Guitar Pro, Hydrogen). o = {name, drums, at_measure, len_qn, fx,
-- notes = {pos, hossz, hang, erő, pos, …} negyedekben a fájl elejétől}. A dob a 10. csatornán, AVL-készlettel.
function muzikos.import_notes(o)
  reaper.Undo_BeginBlock()
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, true)
  local tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", o.name or "Átvitt sáv", true)
  local fx = add_fx(tr, o.fx or (o.drums and "avl" or "ReaSynth"))
  -- basszusos hangszín a ReaSynthen (#48): azonnali kezdet, rövid kioldás, fűrész + háromszög hullám
  if fx and o.synth == "basszus" and fx:find("ReaSynth") then
    local fi = reaper.TrackFX_GetCount(tr) - 1
    for pi = 0, reaper.TrackFX_GetNumParams(tr, fi) - 1 do
      local _, pn = reaper.TrackFX_GetParamName(tr, fi, pi, "")
      pn = pn:lower()
      if pn:find("attack") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0)
      elseif pn:find("decay") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0.35)
      elseif pn:find("sustain") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0.4)
      elseif pn:find("release") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0.05)
      elseif pn:find("saw") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0.6)
      elseif pn:find("triangle") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0.5)
      elseif pn:find("square") then reaper.TrackFX_SetParamNormalized(tr, fi, pi, 0)
      end
    end
  end
  local q0 = reaper.TimeMap_timeToQN(muzikos.bar_time(o.at_measure or 1))
  local item = reaper.CreateNewMIDIItemInProj(tr, q0, q0 + math.max(o.len_qn or 4, 1), true)
  local take = reaper.GetActiveTake(item)
  local chan, n = o.drums and 9 or 0, o.notes or {}
  for i = 1, #n - 3, 4 do
    local s = reaper.MIDI_GetPPQPosFromProjQN(take, q0 + n[i])
    local e = reaper.MIDI_GetPPQPosFromProjQN(take, q0 + n[i] + n[i + 1])
    reaper.MIDI_InsertNote(take, false, false, s, math.max(e, s + 1), chan, n[i + 2], n[i + 3], true)
  end
  reaper.MIDI_Sort(take)
  reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", o.name or "", true)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("MuzikOS: átvitel (" .. (o.name or "") .. ")", -1)
  local info = track_info(tr, idx)
  info.hangjegyek = math.floor(#n / 4)
  info.hangszer = fx
  info.kezdet_utem = o.at_measure or 1
  return info
end

-- ------------------------------------------------------------------ távpróba (#352)
-- Az összes hangelem: sáv, pozíció, hossz, forrásfájl (az összerakáshoz).
function muzikos.tav_items()
  local out = {}
  for t = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, t)
    local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
      local it = reaper.GetTrackMediaItem(tr, i)
      local tk = reaper.GetActiveTake(it)
      if tk and not reaper.TakeIsMIDI(tk) then
        out[#out + 1] = { sav = name, sav_sorszam = t + 1, pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION"),
          len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH"), offs = reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS"),
          rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE"),
          file = reaper.GetMediaSourceFileName(reaper.GetMediaItemTake_Source(tk), "") }
      end
    end
  end
  return out
end

-- Hálózati sáv: a bemenete a REAPER „in” portja (in_ch: 0-tól), monitorozva (a terem hallja); vagy egy sáv
-- küldése a REAPER egy kimeneti portjára (send_from: a sáv neve, out_ch: 0-tól) — onnan megy a JackTrip-be.
function muzikos.tav_route(o)
  reaper.Undo_BeginBlock()
  local res = {}
  for _, r in ipairs(o.inputs or {}) do
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, true)
    local tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", r.name, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", r.in_ch)          -- mono bemenet
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
    res[#res + 1] = { sav = r.name, bemenet = r.in_ch + 1 }
  end
  for _, s in ipairs(o.sends or {}) do
    local ts = muzikos.find_tracks(s.track)
    if #ts == 0 then error("nincs ilyen sáv: " .. tostring(s.track)) end
    local tr = ts[1].tr
    local k = reaper.CreateTrackSend(tr, nil)                          -- hardverkimenet
    reaper.SetTrackSendInfo_Value(tr, 1, k, "I_SRCCHAN", 0 | (1 << 10)) -- a sáv 1. csatornája, monóban
    reaper.SetTrackSendInfo_Value(tr, 1, k, "I_DSTCHAN", s.out_ch | 1024)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    res[#res + 1] = { sav = nm, kimenet = s.out_ch + 1 }
  end
  reaper.TrackList_AdjustWindows(false)
  reaper.Undo_EndBlock("MuzikOS: távpróba bekötése", -1)
  return res
end

-- Összerakás: minden meglévő elem shift mp-cel odébb (ami 0 elé kerülne, az eleje levágva), és egy új sávra a
-- fájl (pos, rate: lejátszási sebesség az órák eltérésére, hangmagasság-tartással). A hálózati sávok némítva.
function muzikos.tav_place(o)
  reaper.Undo_BeginBlock()
  local shift = o.shift or 0
  for t = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, t)
    for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do
      local it = reaper.GetTrackMediaItem(tr, i)
      local p = reaper.GetMediaItemInfo_Value(it, "D_POSITION") + shift
      local l = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
      if p < 0 then
        if l + p <= 0 then reaper.DeleteTrackMediaItem(tr, it)
        else
          local tk = reaper.GetActiveTake(it)
          if tk and not reaper.TakeIsMIDI(tk) then
            local rate = reaper.GetMediaItemTakeInfo_Value(tk, "D_PLAYRATE")
            reaper.SetMediaItemTakeInfo_Value(tk, "D_STARTOFFS", reaper.GetMediaItemTakeInfo_Value(tk, "D_STARTOFFS") - p * rate)
          end
          reaper.SetMediaItemInfo_Value(it, "D_LENGTH", l + p)
          reaper.SetMediaItemInfo_Value(it, "D_POSITION", 0)
        end
      else
        reaper.SetMediaItemInfo_Value(it, "D_POSITION", p)
      end
    end
  end
  for _, n in ipairs(o.mute or {}) do
    for _, x in ipairs(muzikos.find_tracks(n)) do reaper.SetMediaTrackInfo_Value(x.tr, "B_MUTE", 1) end
  end
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, true)
  local tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", o.name or "Otthonról", true)
  local src = reaper.PCM_Source_CreateFromFile(o.file)
  if not src then error("nem tudom megnyitni: " .. tostring(o.file)) end
  local it = reaper.AddMediaItemToTrack(tr)
  local tk = reaper.AddTakeToMediaItem(it)
  reaper.SetMediaItemTake_Source(tk, src)
  local rate = o.rate or 1
  local srclen = reaper.GetMediaSourceLength(src)
  reaper.SetMediaItemTakeInfo_Value(tk, "D_PLAYRATE", rate)
  reaper.SetMediaItemTakeInfo_Value(tk, "B_PPITCH", 1)
  local p = (o.pos or 0) + shift
  local cut = 0
  if p < 0 then cut = -p; p = 0 end
  reaper.SetMediaItemTakeInfo_Value(tk, "D_STARTOFFS", cut * rate)
  reaper.SetMediaItemInfo_Value(it, "D_POSITION", p)
  reaper.SetMediaItemInfo_Value(it, "D_LENGTH", srclen / rate - cut)
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("MuzikOS: távpróba összerakása", -1)
  return { sav = o.name, pos = p, hossz = srclen / rate - cut, rate = rate, eltolas = shift }
end

-- ------------------------------------------------------------------ tempó, ütemmutató, klikk (#344)
function muzikos.tempo_list()
  local out = {}
  for i = 0, reaper.CountTempoTimeSigMarkers(0) - 1 do
    local _, t, mpos, bpos, bpm, num, den, lin = reaper.GetTempoTimeSigMarker(0, i)
    out[#out + 1] = { utem = math.floor(mpos + 0.5) + 1, mp = t, bpm = bpm,
                      utemmutato = (num > 0) and (num .. "/" .. den) or nil, atmenet = lin }
  end
  local _, _, bpm0 = reaper.GetProjectTimeSignature2(0)
  return { alap = { bpm = reaper.Master_GetTempo() }, jelolok = out }
end

-- Egy jelölő az ütem elején: tempó (bpm), ütemmutató (num/den), átmenet a következő jelölőig (lin).
-- A meglévő jelölőt ugyanazon az ütemen felülírja.
function muzikos.tempo_set(o)
  local m = o.measure - 1
  local t0 = muzikos.bar_time(o.measure)
  local idx = -1
  for i = 0, reaper.CountTempoTimeSigMarkers(0) - 1 do
    local _, t = reaper.GetTempoTimeSigMarker(0, i)
    if math.abs(t - t0) < 1e-6 then idx = i end
  end
  -- a tempó negyedekben (a TimeMap_GetDividedBpmAtTime /8-os ütemben a kétszeresét adná)
  local _, _, raw = reaper.TimeMap_GetTimeSigAtTime(0, t0)
  local bpm = o.bpm or raw
  local num, den = o.num or 0, o.den or 0
  if num == 0 and idx >= 0 then local _, _, _, _, _, n, d = reaper.GetTempoTimeSigMarker(0, idx); num, den = n, d end
  reaper.SetTempoTimeSigMarker(0, idx, -1, m, 0, bpm, num, den, o.linear and true or false)
  reaper.UpdateTimeline()
  return muzikos.tempo_list()
end

function muzikos.tempo_clear(from)
  for i = reaper.CountTempoTimeSigMarkers(0) - 1, 0, -1 do
    local _, _, mpos = reaper.GetTempoTimeSigMarker(0, i)
    if mpos + 1 >= (from or 1) then reaper.DeleteTempoTimeSigMarker(0, i) end
  end
  reaper.UpdateTimeline()
  return muzikos.tempo_list()
end

-- A klikksáv: MIDI-hangok minden ütésre (a tempótérkép szerint), ReaSynth rövid hanggal.
-- o = {from, to (ütemek), sound = "magas"|"mely"|"fa", volume_db, sub = 1|2|3, accent, headphones_only, out, skip = {részek}}
local SOUNDS = { magas = { 96, 84 }, mely = { 60, 48 }, fa = { 79, 72 } }

function muzikos.click(o)
  reaper.Undo_BeginBlock()
  local tr
  for _, t in ipairs(muzikos.find_tracks({ "Klikk" })) do tr = t.tr end
  if not tr then
    reaper.InsertTrackAtIndex(reaper.CountTracks(0), true)
    tr = reaper.GetTrack(0, reaper.CountTracks(0) - 1)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "Klikk", true)
  end
  -- a régi klikk-elemek ki
  for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do reaper.DeleteTrackMediaItem(tr, reaper.GetTrackMediaItem(tr, i)) end
  -- hangszer: ReaSynth, rövid, pattogó hanggal
  local fx = reaper.TrackFX_AddByName(tr, "ReaSynth", false, 1)
  if fx >= 0 then
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
      pn = pn:lower()
      if pn:find("attack") then reaper.TrackFX_SetParamNormalized(tr, fx, p, 0) end
      if pn:find("decay") then reaper.TrackFX_SetParamNormalized(tr, fx, p, 0.03) end
      if pn:find("sustain") then reaper.TrackFX_SetParamNormalized(tr, fx, p, 0) end
      if pn:find("release") then reaper.TrackFX_SetParamNormalized(tr, fx, p, 0.02) end
      if pn:find("square") then reaper.TrackFX_SetParamNormalized(tr, fx, p, o.sound == "fa" and 0.6 or 0) end
    end
  end
  local from = o.from or 1
  local to = o.to
  if not to then to = math.max((muzikos.bar_of(reaper.GetProjectLength(0))) + 1, from + 64) end   -- a dal hosszáig, legalább 64 ütem (#47)
  local t0, t1 = muzikos.bar_time(from), muzikos.bar_time(to)
  local item = reaper.CreateNewMIDIItemInProj(tr, t0, t1, false)
  local take = reaper.GetActiveTake(item)
  reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", "klikk", true)
  local hi, lo = table.unpack(SOUNDS[o.sound or "magas"] or SOUNDS.magas)
  local skip = {}
  for _, m in ipairs(muzikos.markers()) do
    if m.tipus == "resz" then
      for _, want in ipairs(o.skip or {}) do if plain(m.nev):find(plain(want), 1, true) then skip[#skip + 1] = { m.kezd_mp, m.veg_mp } end end
    end
  end
  local function skipped(t) for _, r in ipairs(skip) do if t >= r[1] - 1e-6 and t < r[2] - 1e-6 then return true end end return false end
  local n = 0
  for meas = from - 1, to - 2 do
    local _, qn0, qn1, num, den = reaper.TimeMap_GetMeasureInfo(0, meas)
    local beat = 4 / den
    for b = 0, num - 1 do
      for s = 0, (o.sub or 1) - 1 do
        local qn = qn0 + b * beat + s * beat / (o.sub or 1)
        if qn < qn1 - 1e-9 then
          local t = reaper.TimeMap2_QNToTime(0, qn)
          if not skipped(t) then
            local ppq = reaper.MIDI_GetPPQPosFromProjTime(take, t)
            local first = (b == 0 and s == 0)
            local pitch = (first and o.accent ~= false) and hi or lo
            local vel = (s == 0) and ((first and o.accent ~= false) and 127 or 96) or 60
            reaper.MIDI_InsertNote(take, false, false, ppq, ppq + 60, 0, pitch, vel, true)
            n = n + 1
          end
        end
      end
    end
  end
  reaper.MIDI_Sort(take)
  reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 10 ^ ((o.volume_db or -6) / 20))
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
  -- csak a fejhallgatóban: a fő keverésbe (és így az exportba) nem megy, egy kimenetpárra küldve
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", o.headphones_only and 0 or 1)
  if o.headphones_only then
    local dst = math.max((o.out or 1) - 1, 0)
    local idx = -1
    for k = 0, reaper.GetTrackNumSends(tr, 1) - 1 do
      if math.floor(reaper.GetTrackSendInfo_Value(tr, 1, k, "I_DSTCHAN")) == dst then idx = k end
    end
    if idx < 0 then idx = reaper.CreateTrackSend(tr, nil) end
    reaper.SetTrackSendInfo_Value(tr, 1, idx, "I_DSTCHAN", dst)
  end
  reaper.Undo_EndBlock("MuzikOS: klikk", -1)
  reaper.UpdateArrange()
  return { utesek = n, utemek = from .. "–" .. (to - 1), hang = o.sound or "magas", dB = o.volume_db or -6,
           csak_fejhallgato = o.headphones_only and true or false, kihagyva = #skip }
end

-- ------------------------------------------------------------------ „hol tartunk” kijelző (#341)
-- Egy saját ablak a Reaperben: nagy betűvel a mostani dalrész, a következő, az ütem a részen belül, és a
-- váltás előtt visszaszámlálás; alul a dal összes része egy sávban, a lejátszófejjel.
muzikos.view = muzikos.view or { on = false }

function muzikos.view_open(w, h)
  gfx.init("MuzikOS — hol tartunk", w or 1000, h or 420)
  muzikos.view.on = true
  return { nyitva = true }
end

function muzikos.view_close()
  if muzikos.view.on then gfx.quit() end
  muzikos.view.on = false
  return { nyitva = false }
end

local function parts_now(pos)
  local regs = {}
  for _, m in ipairs(muzikos.markers()) do if m.tipus == "resz" then regs[#regs + 1] = m end end
  table.sort(regs, function(a, b) return a.kezd_mp < b.kezd_mp end)
  local cur, nxt
  for i, r in ipairs(regs) do
    if pos >= r.kezd_mp - 1e-6 and pos < r.veg_mp then cur = i end
    if not nxt and r.kezd_mp > pos + 1e-6 then nxt = i end
  end
  return regs, cur, nxt
end

function muzikos.view_state()
  local pos = muzikos.now()
  local regs, cur, nxt = parts_now(pos)
  local st = { pozicio_mp = pos, utem = (muzikos.bar_of(pos)), reszek = #regs }
  if cur then
    local r = regs[cur]
    st.most = r.nev
    st.utem_a_reszben = st.utem - r.kezd_utem + 1
    st.resz_hossza = r.veg_utem - r.kezd_utem
    st.hatra = st.resz_hossza - st.utem_a_reszben + 1
  end
  if nxt then st.kovetkezo = regs[nxt].nev end
  return st
end

-- a MuzikOS arculata (#349): sötét alap, piros és sárga kiemelés, a dalrészek színe a név szerint
local function hex(h) return tonumber(h:sub(2, 3), 16) / 255, tonumber(h:sub(4, 5), 16) / 255, tonumber(h:sub(6, 7), 16) / 255 end
local PART_COLORS = { { "intro", "#4b5361" }, { "verze", "#1f6f9a" }, { "refr", "#c4322a" }, { "bridge", "#7b4bc4" },
                      { "híd", "#7b4bc4" }, { "szól", "#d27a12" }, { "outro", "#4b5361" }, { "átvezet", "#2f7a5f" } }
local function part_color(name)
  local n = plain(name or "")
  for _, pc in ipairs(PART_COLORS) do if n:sub(1, #plain(pc[1])) == plain(pc[1]) then return hex(pc[2]) end end
  return hex("#3a3e48")
end
local HEAD_FONT, BODY_FONT, MONO_FONT = "Orbitron", "Saira", "Share Tech Mono"

local function txt(s, x, y, size, r, g, b, center, w, head)
  if head == "mono" then gfx.setfont(1, MONO_FONT, size)
  elseif head then gfx.setfont(1, HEAD_FONT, size, string.byte("b"))
  else gfx.setfont(1, BODY_FONT, size, string.byte("b")) end
  gfx.set(r, g, b, 1)
  local tw = gfx.measurestr(s)
  gfx.x = center and (x + (w - tw) / 2) or x
  gfx.y = y
  gfx.drawstr(s)
end

local function view_draw()
  if gfx.getchar() < 0 then muzikos.view.on = false return end   -- az ablakot bezárták
  local W, H = gfx.w, gfx.h
  gfx.set(hex("#0b0c0f")); gfx.rect(0, 0, W, H, 1)
  gfx.set(hex("#170d04")); gfx.rect(0, 0, W, 54, 1)              -- a kijelzősáv: narancsban izzik
  gfx.set(hex("#3a2410")); gfx.rect(0, 54, W, 2, 1)
  local pos = muzikos.now()
  local regs, cur, nxt = parts_now(pos)
  local playing = reaper.GetPlayState()
  local state = (playing & 4 ~= 0) and "● FELVÉTEL" or ((playing & 1 ~= 0) and "▶ lejátszás" or "■ áll")
  local sr, sg, sb = hex((playing & 4 ~= 0) and "#ff3b30" or ((playing & 1 ~= 0) and "#33d17a" or "#8a909c"))
  txt(state, 20, 14, 24, sr, sg, sb, nil, nil, "mono")
  local bar = (muzikos.bar_of(pos))
  local yr, yg, yb = hex("#ffa04d")
  txt(string.format("%d. ütem   %.0f BPM", bar, reaper.Master_GetTempo()), W - 340, 14, 26, yr, yg, yb, nil, nil, "mono")
  if #regs == 0 then
    txt("Nincsenek dalrészek — kérd a Claude-ot, hogy rakja le a szerkezetet.", 20, H / 2 - 20, 26, 0.95, 0.93, 0.89)
    gfx.update() return
  end
  if cur then
    local r = regs[cur]
    local inbar = bar - r.kezd_utem + 1
    local len = r.veg_utem - r.kezd_utem
    local left = len - inbar + 1
    local pr, pg, pb = part_color(r.nev)
    txt(r.nev, 0, 70, math.min(140, H * 0.32), pr + (1 - pr) * 0.35, pg + (1 - pg) * 0.35, pb + (1 - pb) * 0.35, true, W, true)
    txt(string.format("%d / %d", inbar, len), 0, 70 + math.min(140, H * 0.32) + 14, 44, yr, yg, yb, true, W, "mono")
    if nxt and left <= 4 then
      txt(string.format("%s jön %d ütem múlva", regs[nxt].nev, left), 0, H - 150, 40, yr, yg, yb, true, W, true)
    elseif nxt then
      txt("utána: " .. regs[nxt].nev, 0, H - 140, 28, 0.54, 0.56, 0.61, true, W)
    else
      txt("ez az utolsó rész", 0, H - 140, 28, 0.54, 0.56, 0.61, true, W)
    end
  else
    txt(nxt and ("következik: " .. regs[nxt].nev) or "a dal vége", 0, H / 2 - 40, 56, 0.95, 0.93, 0.89, true, W, true)
  end
  -- a dal sávja
  local t0, t1 = regs[1].kezd_mp, regs[#regs].veg_mp
  local x0, y0, bw, bh = 20, H - 70, W - 40, 46
  for i, r in ipairs(regs) do
    local xa = x0 + (r.kezd_mp - t0) / (t1 - t0) * bw
    local xb = x0 + (r.veg_mp - t0) / (t1 - t0) * bw
    gfx.set(part_color(r.nev))
    gfx.rect(xa + 1, y0, math.max(2, xb - xa - 2), bh, 1)
    if i == cur then                                  -- a mostani rész sárga keretet kap
      gfx.set(yr, yg, yb, 1)
      gfx.rect(xa - 1, y0 - 2, math.max(2, xb - xa + 2), bh + 4, 0); gfx.rect(xa, y0 - 1, math.max(2, xb - xa), bh + 2, 0)
    end
    gfx.setfont(1, BODY_FONT, 16)
    gfx.set(0.95, 0.93, 0.89, 1)
    local tw = gfx.measurestr(r.nev)
    if tw < xb - xa - 6 then gfx.x = xa + (xb - xa - tw) / 2; gfx.y = y0 + 14; gfx.drawstr(r.nev) end
  end
  if pos >= t0 and pos <= t1 then
    local xp = x0 + (pos - t0) / (t1 - t0) * bw
    gfx.set(0.95, 0.93, 0.89, 1); gfx.rect(xp - 1, y0 - 6, 3, bh + 12, 1)
  end
  gfx.update()
end

-- ------------------------------------------------------------------ a kérésfigyelő
local last_check = 0
local function write_response(id, ok, result, err)
  local body = '{"id":' .. encode(id) .. ',"ok":' .. (ok and "true" or "false")
  if ok then body = body .. ',"result":' .. encode(result) else body = body .. ',"error":' .. encode(err) end
  body = body .. ',"log":' .. encode(logbuf) .. "}"
  local tmp = resp_path .. ".tmp"
  local f = io.open(tmp, "w")
  if f then f:write(body); f:close(); os.rename(tmp, resp_path) end
end

local function poll()
  local now = reaper.time_precise()
  if now - last_check >= 0.05 then
    last_check = now
    local f = io.open(req_path, "r")
    if f then
      local src = f:read("*a")
      f:close()
      os.remove(req_path)
      local id = src:match("^%-%- id:(%w+)") or ""
      logbuf = {}
      local chunk, cerr = load(src, "=muzikos", "t")
      if not chunk then
        write_response(id, false, nil, "Lua-szintaxishiba: " .. tostring(cerr))
      else
        local ok, fn = pcall(chunk)
        if not ok or type(fn) ~= "function" then
          write_response(id, false, nil, tostring(fn))
        else
          local ok2, res = pcall(fn)
          if ok2 then write_response(id, true, res) else write_response(id, false, nil, tostring(res)) end
        end
      end
    end
  end
  if muzikos.view.on then
    local ok, err = pcall(view_draw)
    if not ok then muzikos.view.on = false; reaper.ShowConsoleMsg("MuzikOS-kijelző: " .. tostring(err) .. "\n") end
  end
  reaper.defer(poll)
end

if not muzikos.bridge_running then
  muzikos.bridge_running = true
  poll()
end
