local M = {}

local LOG_PATH = os.getenv("HOME") .. "/projects/phone-agent/logs/ax-dump.log"

local TARGET_PROCESSES = {
  "Phone",
  "FaceTime",
  "NotificationCenter",
  "Notification Center",
  "ControlCenter",
  "Control Center",
  "SystemUIServer",
  "WindowManager",
}

local INTERESTING_ATTRS = {
  "AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue",
  "AXIdentifier", "AXHelp", "AXLabel", "AXPlaceholderValue",
  "AXEnabled", "AXFocused", "AXPosition", "AXSize",
}

local function safeAttr(el, name)
  local ok, val = pcall(function() return el:attributeValue(name) end)
  if not ok or val == nil then return nil end
  if type(val) == "table" and val.x ~= nil then
    return string.format("{%g,%g}", val.x, val.y)
  elseif type(val) == "table" and val.w ~= nil then
    return string.format("{%gx%g}", val.w, val.h)
  end
  return tostring(val)
end

local function walk(el, depth, fh, seen)
  if depth > 25 then return end
  if type(el) ~= "userdata" then return end
  local key = tostring(el)
  if seen[key] then return end
  seen[key] = true

  local indent = string.rep("  ", depth)
  local parts = {}
  for _, attr in ipairs(INTERESTING_ATTRS) do
    local v = safeAttr(el, attr)
    if v ~= nil and v ~= "" then
      table.insert(parts, string.format("%s=%q", attr:gsub("^AX", ""), v))
    end
  end
  fh:write(indent .. table.concat(parts, " ") .. "\n")

  local ok, children = pcall(function() return el:attributeValue("AXChildren") end)
  if ok and type(children) == "table" then
    for _, child in ipairs(children) do
      walk(child, depth + 1, fh, seen)
    end
  end
end

local function dumpProcess(name, fh)
  local app = hs.application.find(name, true, true)
  if not app then
    fh:write(string.format("\n=== %s :: NOT RUNNING ===\n", name))
    return
  end
  fh:write(string.format("\n=== %s :: pid=%d bundleID=%s ===\n",
    name, app:pid(), app:bundleID() or "?"))
  local ax = hs.axuielement.applicationElement(app)
  if not ax then
    fh:write("(no application AX element)\n")
    return
  end
  walk(ax, 0, fh, {})
end

local function dumpAllVisibleWindows(fh)
  fh:write("\n=== ALL VISIBLE WINDOWS (any app) ===\n")
  for _, win in ipairs(hs.window.allWindows()) do
    local app = win:application()
    local appName = app and app:name() or "?"
    fh:write(string.format("  win: app=%q title=%q frame=%s role=%q subrole=%q\n",
      appName, win:title() or "", tostring(win:frame()),
      win:role() or "", win:subrole() or ""))
  end
end

function M.dumpNow(label)
  os.execute("mkdir -p " .. os.getenv("HOME") .. "/projects/phone-agent/logs")
  local fh = io.open(LOG_PATH, "a")
  if not fh then
    hs.alert.show("AX Inspector: failed to open log")
    return
  end
  fh:write(string.format("\n\n##### DUMP %s [%s] #####\n",
    os.date("%Y-%m-%dT%H:%M:%S"), label or "manual"))
  dumpAllVisibleWindows(fh)
  for _, name in ipairs(TARGET_PROCESSES) do
    dumpProcess(name, fh)
  end
  fh:close()
  hs.alert.show("AX dumped → logs/ax-dump.log", 1.5)
  print("[ax_inspector] dump written to " .. LOG_PATH)
end

function M.listRunning()
  hs.alert.show("Logging running candidates to Hammerspoon console")
  print("[ax_inspector] candidate processes running right now:")
  for _, name in ipairs(TARGET_PROCESSES) do
    local app = hs.application.find(name, true, true)
    print(string.format("  %-22s %s", name, app and ("pid=" .. app:pid()) or "(not running)"))
  end
end

return M
