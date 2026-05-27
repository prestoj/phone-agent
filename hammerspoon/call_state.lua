local M = {}

local STATE_FILE = "/tmp/phone-agent-call.json"

local function jsonEscape(s)
  if not s then return "" end
  return tostring(s):gsub("\\", "\\\\"):gsub("\"", "\\\""):gsub("\n", "\\n")
end

function M.markActive(caller)
  local fh = io.open(STATE_FILE, "w")
  if not fh then
    print("[call_state] failed to open " .. STATE_FILE)
    return false
  end
  caller = caller or "unknown"
  fh:write(string.format(
    '{"caller":"%s","started_at":"%s"}\n',
    jsonEscape(caller), os.date("%Y-%m-%dT%H:%M:%S")
  ))
  fh:close()
  print(string.format("[call_state] active: caller=%q", caller))
  return true
end

function M.markInactive()
  local ok, err = os.remove(STATE_FILE)
  if ok then
    print("[call_state] inactive")
  else
    -- not an error if file already gone
    print("[call_state] (no state file to clear)")
  end
end

function M.isActive()
  local fh = io.open(STATE_FILE, "r")
  if not fh then return false end
  fh:close()
  return true
end

return M
