local callHandler = require("call_handler")
local callAudio = require("call_audio")
local callState = require("call_state")

local M = {}

local POLL_INTERVAL = 0.3

M.enabled = true

local pollTimer = nil
local bannerPresentSince = nil
local pressedThisBanner = false

local function tick()
  if not M.enabled then return end

  local banner, err = callHandler.findBanner()
  if not banner then
    if bannerPresentSince then
      print("[auto_answer] banner cleared")
      bannerPresentSince = nil
      pressedThisBanner = false
      callState.markInactive()
      callAudio.disengage()
    end
    return
  end

  -- banner is present
  if not bannerPresentSince then
    bannerPresentSince = hs.timer.secondsSinceEpoch()
    pressedThisBanner = false
    local caller = callHandler.getCallerInfo() or "unknown"
    print(string.format("[auto_answer] banner appeared, caller=%q", caller))
    hs.alert.show("📞 incoming: " .. caller, 2)
  end

  -- Try to press Answer until we get one successful press. Once pressed we
  -- stop trying, even if the AX tree briefly still shows the Answer button
  -- during the ringing→in-call animation. The banner stays visible in in-call
  -- state — we just leave it alone until it disappears.
  if not pressedThisBanner then
    if callHandler.tryAnswerQuiet() then
      pressedThisBanner = true
      local caller = callHandler.getCallerInfo() or "unknown"
      callState.markActive(caller)
      callAudio.engage()
    end
  end
end

function M.start()
  if pollTimer then return end
  pollTimer = hs.timer.doEvery(POLL_INTERVAL, tick)
  print(string.format("[auto_answer] poll started (interval=%.2fs)", POLL_INTERVAL))
end

function M.stop()
  if pollTimer then
    pollTimer:stop()
    pollTimer = nil
    print("[auto_answer] poll stopped")
  end
end

function M.toggle()
  M.enabled = not M.enabled
  hs.alert.show("Auto-answer: " .. (M.enabled and "ON ✅" or "OFF ⛔"), 1.5)
  print("[auto_answer] toggled -> " .. tostring(M.enabled))
end

function M.status()
  local s = string.format("[auto_answer] enabled=%s poll=%s bannerPresent=%s",
    tostring(M.enabled),
    pollTimer and "RUNNING" or "STOPPED",
    bannerPresentSince and "yes" or "no")
  print(s)
  hs.alert.show(s, 2)
end

return M
