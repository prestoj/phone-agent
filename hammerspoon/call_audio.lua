local M = {}

local CALL_INPUT  = "BlackHole 2ch"   -- system default input during a call (capture-side; mainly for completeness)
local CALL_OUTPUT = "BlackHole 16ch"  -- system default output during a call (caller voice → Python)
local PHONE_MIC   = "BlackHole 2ch"   -- Phone.app's selected mic (injection side, Python → caller)

local savedInput  = nil
local savedOutput = nil

local function findInput(name)
  for _, d in ipairs(hs.audiodevice.allInputDevices()) do
    if d:name() == name then return d end
  end
  return nil
end

local function findOutput(name)
  for _, d in ipairs(hs.audiodevice.allOutputDevices()) do
    if d:name() == name then return d end
  end
  return nil
end

local function selectPhoneMic(name)
  local phone = hs.application.find("Phone", true, true)
  if not phone then
    print("[call_audio] Phone.app not running; cannot select mic")
    return false
  end
  local ok = phone:selectMenuItem({"Video", name})
  if ok then
    print("[call_audio] Phone.app mic → " .. name)
    return true
  else
    print("[call_audio] could not click {Video, " .. name .. "} in Phone.app menu")
    return false
  end
end

function M.engage()
  if savedInput or savedOutput then
    print("[call_audio] already engaged; skipping")
    return
  end
  savedInput  = hs.audiodevice.defaultInputDevice()
  savedOutput = hs.audiodevice.defaultOutputDevice()
  print(string.format("[call_audio] snapshot: in=%q out=%q",
    savedInput  and savedInput:name()  or "?",
    savedOutput and savedOutput:name() or "?"))

  local newIn  = findInput(CALL_INPUT)
  local newOut = findOutput(CALL_OUTPUT)
  if newIn  then newIn:setDefaultInputDevice();   print("[call_audio] system input → "  .. CALL_INPUT)
  else           print("[call_audio] missing input device: "  .. CALL_INPUT) end
  if newOut then newOut:setDefaultOutputDevice(); print("[call_audio] system output → " .. CALL_OUTPUT)
  else           print("[call_audio] missing output device: " .. CALL_OUTPUT) end

  -- Phone.app's Video menu isn't populated until the call is active.
  -- Retry a few times so we land it even if menu setup is briefly behind.
  local attempts = 0
  local function tryClick()
    attempts = attempts + 1
    if selectPhoneMic(PHONE_MIC) then return end
    if attempts < 6 then
      hs.timer.doAfter(0.4, tryClick)
    else
      print("[call_audio] giving up on Phone.app mic select after 6 tries")
    end
  end
  hs.timer.doAfter(0.4, tryClick)
end

function M.disengage()
  if not (savedInput or savedOutput) then return end
  if savedInput  then savedInput:setDefaultInputDevice();   print("[call_audio] restored input → "  .. savedInput:name())  end
  if savedOutput then savedOutput:setDefaultOutputDevice(); print("[call_audio] restored output → " .. savedOutput:name()) end
  savedInput  = nil
  savedOutput = nil
end

function M.status()
  local di = hs.audiodevice.defaultInputDevice()
  local do_ = hs.audiodevice.defaultOutputDevice()
  local msg = string.format(
    "[call_audio] now: in=%q out=%q  saved=%s",
    di and di:name() or "?", do_ and do_:name() or "?",
    (savedInput or savedOutput) and "yes" or "no")
  print(msg)
  hs.alert.show(msg, 2)
end

return M
