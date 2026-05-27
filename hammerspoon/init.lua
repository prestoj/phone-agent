package.path = package.path .. ";" .. hs.configdir .. "/?.lua"

local inspector = require("ax_inspector")
local callHandler = require("call_handler")
local autoAnswer = require("auto_answer")
local callAudio = require("call_audio")
local callState = require("call_state")

hs.hotkey.bind({"cmd", "alt", "ctrl"}, "A", function()
  inspector.dumpNow("hotkey")
end)

hs.hotkey.bind({"cmd", "alt", "ctrl"}, "L", function()
  inspector.listRunning()
end)

hs.hotkey.bind({"cmd", "alt", "ctrl"}, "P", callHandler.probe)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "Return", callHandler.answerCall)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "D", callHandler.declineCall)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "T", autoAnswer.toggle)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "S", autoAnswer.status)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "E", callAudio.engage)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "R", callAudio.disengage)

hs.hotkey.bind({"cmd", "alt", "ctrl"}, "I", function()
  local logPath = os.getenv("HOME") .. "/projects/phone-agent/logs/audio-devices.log"
  local fh = io.open(logPath, "w")
  local function emit(s)
    print(s)
    if fh then fh:write(s .. "\n"); fh:flush() end
  end
  emit("timestamp: " .. os.date("%Y-%m-%dT%H:%M:%S"))
  emit("hs version: " .. tostring(hs.processInfo.version or "?"))

  local function probe(label, fn)
    local ok, result = pcall(fn)
    if not ok then
      emit(string.format("[%s] ERROR: %s", label, tostring(result)))
      return
    end
    local n = result and #result or -1
    emit(string.format("[%s] count=%d", label, n))
    if result then
      for i, d in ipairs(result) do
        local nameOk, name = pcall(function() return d:name() end)
        local uidOk, uid = pcall(function() return d:uid() end)
        local inOk, ic = pcall(function() return d:inputChannels() end)
        local outOk, oc = pcall(function() return d:outputChannels() end)
        emit(string.format("  %s [%d] name=%q uid=%q in=%s out=%s",
          label, i,
          nameOk and tostring(name) or ("ERR:"..tostring(name)),
          uidOk and tostring(uid) or ("ERR:"..tostring(uid)),
          inOk and tostring(ic) or ("ERR:"..tostring(ic)),
          outOk and tostring(oc) or ("ERR:"..tostring(oc))))
      end
    end
  end

  probe("allDevices",       function() return hs.audiodevice.allDevices() end)
  probe("allInputDevices",  function() return hs.audiodevice.allInputDevices() end)
  probe("allOutputDevices", function() return hs.audiodevice.allOutputDevices() end)

  local diOk, di = pcall(hs.audiodevice.defaultInputDevice)
  local doOk, do_ = pcall(hs.audiodevice.defaultOutputDevice)
  emit("default input:  " .. (diOk and di and di:name() or tostring(di)))
  emit("default output: " .. (doOk and do_ and do_:name() or tostring(do_)))

  if fh then fh:close() end
  hs.alert.show("audio devices logged → logs/audio-devices.log", 2)
end)

autoAnswer.start()

local watchedAppNames = {
  ["Phone"] = true,
  ["FaceTime"] = true,
  ["NotificationCenter"] = true,
  ["Control Center"] = true,
}

local appWatcher = hs.application.watcher.new(function(name, eventType, appObject)
  if not watchedAppNames[name] then return end
  if eventType == hs.application.watcher.launched
      or eventType == hs.application.watcher.activated then
    print(string.format("[phone-agent] %s event=%d — auto-dumping in 500ms", name, eventType))
    hs.timer.doAfter(0.5, function() inspector.dumpNow("auto:" .. name) end)
  end
end)
appWatcher:start()

local windowFilter = hs.window.filter.new(function(win)
  local app = win:application()
  if not app then return false end
  return watchedAppNames[app:name()] == true
end)
windowFilter:subscribe(hs.window.filter.windowCreated, function(win, appName)
  print(string.format("[phone-agent] new window in %s: %q", appName, win:title() or ""))
  hs.timer.doAfter(0.3, function() inspector.dumpNow("window:" .. appName) end)
end)

hs.alert.show(
  "phone-agent loaded · AUTO-ANSWER ON ✅\n"
  .. "⌥⌃⌘+T: toggle auto-answer\n"
  .. "⌥⌃⌘+↩: manual answer · ⌥⌃⌘+D: decline · ⌥⌃⌘+P: probe\n"
  .. "⌥⌃⌘+A: AX dump · ⌥⌃⌘+L: list procs",
  5)
print("[phone-agent] init complete, log = " .. os.getenv("HOME") .. "/projects/phone-agent/logs/ax-dump.log")
