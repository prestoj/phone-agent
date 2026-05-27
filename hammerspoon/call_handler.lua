local M = {}

local BANNER_IDENTIFIER = "FACETIME_NOTIFICATION"
local NC_APP_NAME = "Notification Center"

local function safeAttr(el, name)
  local ok, val = pcall(function() return el:attributeValue(name) end)
  if not ok then return nil end
  return val
end

local function findFirst(el, predicate, depth, seen)
  depth = depth or 0
  seen = seen or {}
  if depth > 25 then return nil end
  if type(el) ~= "userdata" then return nil end
  local key = tostring(el)
  if seen[key] then return nil end
  seen[key] = true

  if predicate(el) then return el end

  local children = safeAttr(el, "AXChildren")
  if type(children) == "table" then
    for _, child in ipairs(children) do
      local r = findFirst(child, predicate, depth + 1, seen)
      if r then return r end
    end
  end
  return nil
end

local function findAll(el, predicate, depth, seen, acc)
  depth = depth or 0
  seen = seen or {}
  acc = acc or {}
  if depth > 25 then return acc end
  if type(el) ~= "userdata" then return acc end
  local key = tostring(el)
  if seen[key] then return acc end
  seen[key] = true

  if predicate(el) then table.insert(acc, el) end

  local children = safeAttr(el, "AXChildren")
  if type(children) == "table" then
    for _, child in ipairs(children) do
      findAll(child, predicate, depth + 1, seen, acc)
    end
  end
  return acc
end

function M.findBanner()
  local nc = hs.application.find(NC_APP_NAME, true, true)
  if not nc then
    return nil, "Notification Center not running"
  end
  local ncAx = hs.axuielement.applicationElement(nc)
  if not ncAx then
    return nil, "no AX element for Notification Center"
  end
  local banner = findFirst(ncAx, function(el)
    return safeAttr(el, "AXIdentifier") == BANNER_IDENTIFIER
  end)
  if not banner then
    return nil, "no FACETIME_NOTIFICATION banner visible"
  end
  return banner, nil
end

function M.getCallerInfo()
  local banner, err = M.findBanner()
  if not banner then return nil, err end
  local info = findFirst(banner, function(el)
    if safeAttr(el, "AXRole") ~= "AXGenericElement" then return false end
    local desc = safeAttr(el, "AXDescription") or ""
    return desc:find("From Your iPhone", 1, true) ~= nil
  end)
  if not info then return nil, "no caller-info element under banner" end
  local desc = safeAttr(info, "AXDescription") or ""
  local caller = desc:gsub("%s*,%s*From Your iPhone%s*$", ""):gsub("^[\226\128\170\226\128\172]+", ""):gsub("[\226\128\170\226\128\172]+$", "")
  return caller, nil
end

local function findButton(buttonDesc)
  local banner, err = M.findBanner()
  if not banner then return nil, err end
  local btn = findFirst(banner, function(el)
    return safeAttr(el, "AXRole") == "AXButton"
        and safeAttr(el, "AXDescription") == buttonDesc
  end)
  if not btn then return nil, "no AXButton[desc=" .. buttonDesc .. "]" end
  return btn, nil
end

local function press(buttonDesc)
  local btn, err = findButton(buttonDesc)
  if not btn then
    hs.alert.show("[" .. buttonDesc .. "] " .. err, 2)
    print("[call_handler] press failed: " .. err)
    return false
  end
  local ok, e = pcall(function() btn:performAction("AXPress") end)
  if ok then
    print("[call_handler] AXPress on " .. buttonDesc .. " succeeded")
    return true
  else
    hs.alert.show("press error: " .. tostring(e), 2)
    print("[call_handler] AXPress failed: " .. tostring(e))
    return false
  end
end

function M.answerCall()
  local caller, _ = M.getCallerInfo()
  print(string.format("[call_handler] Answer pressed (caller=%q)", caller or "?"))
  if press("Answer") then
    hs.alert.show("📞 Answered: " .. (caller or "unknown"), 2)
    return true
  end
  return false
end

function M.tryAnswerQuiet()
  local btn = findButton("Answer")
  if not btn then return false end
  local ok = pcall(function() btn:performAction("AXPress") end)
  if ok then
    local caller = M.getCallerInfo() or "unknown"
    print(string.format("[call_handler] auto-answered caller=%q", caller))
    hs.alert.show("📞 Answered: " .. caller, 2)
    return true
  end
  return false
end

function M.hasAnswerButton()
  return findButton("Answer") ~= nil
end

function M.declineCall()
  local caller, _ = M.getCallerInfo()
  print(string.format("[call_handler] Decline pressed (caller=%q)", caller or "?"))
  if press("Decline") then
    hs.alert.show("✋ Declined: " .. (caller or "unknown"), 2)
    return true
  end
  return false
end

function M.probe()
  local banner, err = M.findBanner()
  if not banner then
    hs.alert.show("probe: " .. err, 2)
    print("[call_handler] probe: " .. err)
    return
  end
  local caller = M.getCallerInfo() or "(unknown)"
  local buttons = findAll(banner, function(el)
    return safeAttr(el, "AXRole") == "AXButton"
  end)
  local descs = {}
  for _, b in ipairs(buttons) do
    table.insert(descs, safeAttr(b, "AXDescription") or "?")
  end
  local msg = string.format("📞 ringing: %s\nbuttons: %s",
    caller, table.concat(descs, ", "))
  hs.alert.show(msg, 3)
  print("[call_handler] probe -> " .. msg:gsub("\n", " | "))
end

return M
