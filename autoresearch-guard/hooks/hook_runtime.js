"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const PROJECT_BOUNDARY_MARKERS = [
  ".git",
  ".arx-boundary",
  "package.json",
  "pyproject.toml",
  "Cargo.toml",
  "go.mod",
  "pom.xml",
  "composer.json",
  "Gemfile",
  "mix.exs",
];

function readStdinSync() {
  if (process.stdin.isTTY) {
    return "";
  }
  try {
    return fs.readFileSync(0, "utf8").trim();
  } catch {
    return "";
  }
}

function readEvent({ cwd = "", command = "" } = {}) {
  let payload = {};
  const text = readStdinSync();
  if (text) {
    try {
      const loaded = JSON.parse(text);
      if (loaded && typeof loaded === "object" && !Array.isArray(loaded)) {
        payload = { ...loaded };
      }
    } catch {
      payload = { command: text, malformed_input: true };
    }
  }
  if (cwd) {
    payload.cwd = cwd;
  }
  if (command) {
    if (!payload.tool_name) {
      payload.tool_name = "Bash";
    }
    payload.tool_input = { command };
  }
  return {
    payload,
    get session_id() {
      return String(payload.session_id || "");
    },
    get turn_id() {
      return String(payload.turn_id || payload.prompt_id || "");
    },
    get cwd() {
      return path.resolve(String(payload.cwd || process.cwd()));
    },
    get stop_hook_active() {
      return payload.stop_hook_active === true;
    },
  };
}

function isProjectBoundary(dir) {
  return PROJECT_BOUNDARY_MARKERS.some((name) => fs.existsSync(path.join(dir, name)));
}

function findResearchRoot(cwd) {
  let current = path.resolve(cwd);
  const { root } = path.parse(current);
  while (true) {
    if (fs.existsSync(path.join(current, ".research", "current"))) {
      return path.join(current, ".research");
    }
    if (isProjectBoundary(current)) {
      return null;
    }
    if (current === root) {
      return null;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

function additionalContext(eventName, message) {
  return {
    hookSpecificOutput: {
      hookEventName: eventName,
      additionalContext: message,
    },
  };
}

function systemWarning(message, { stop = false } = {}) {
  const payload = { systemMessage: message };
  if (stop) {
    payload.continue = false;
    payload.stopReason = message;
  }
  return payload;
}

function dumpJson(value) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "boolean" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(dumpJson).join(", ")}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    const body = keys.map((key) => `${JSON.stringify(key)}: ${dumpJson(value[key])}`).join(", ");
    return `{${body}}`;
  }
  return JSON.stringify(value);
}

function emit(payload) {
  if (payload) {
    process.stdout.write(`${dumpJson(payload)}\n`);
  }
}

function resolvePython() {
  if (process.env.ARX_PYTHON) {
    return [process.env.ARX_PYTHON];
  }
  const candidates =
    process.platform === "win32"
      ? [
          ["py", "-3"],
          ["python3"],
          ["python"],
        ]
      : [
          ["python3"],
          ["python"],
        ];
  for (const cmd of candidates) {
    const result = spawnSync(cmd[0], [...cmd.slice(1), "-c", "import sys; print(sys.executable)"], {
      encoding: "utf8",
      timeout: 8000,
      windowsHide: true,
    });
    if (result.status === 0) {
      const exe = String(result.stdout || "")
        .trim()
        .split(/\r?\n/)[0];
      if (exe) {
        return [exe];
      }
    }
  }
  throw new Error(
    "Python 3 not found for AutoResearch Guard hooks (tried python3/python/py -3). Set ARX_PYTHON to a Python 3 executable."
  );
}

function runBridge(op, { researchRoot, event, allowIncomplete = false, cwdProvided = false } = {}) {
  const bridge = path.join(__dirname, "arx_bridge.py");
  const python = resolvePython();
  const args = [bridge, op, "--research-root", researchRoot];
  if (allowIncomplete) {
    args.push("--allow-incomplete");
  }
  if (cwdProvided) {
    args.push("--cwd-provided");
  }
  const result = spawnSync(python[0], args, {
    input: JSON.stringify(event || {}),
    encoding: "utf8",
    timeout: 15000,
    windowsHide: true,
    env: process.env,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const err = String(result.stderr || result.stdout || "").trim();
    throw new Error(err || `arx_bridge.py ${op} failed with code ${result.status}`);
  }
  const text = String(result.stdout || "").trim();
  if (!text) {
    return { skip: true };
  }
  return JSON.parse(text);
}

module.exports = {
  readEvent,
  findResearchRoot,
  additionalContext,
  systemWarning,
  emit,
  runBridge,
  resolvePython,
};

if (require.main === module) {
  const idx = process.argv.indexOf("--find-root");
  if (idx !== -1) {
    const target = process.argv[idx + 1] || process.cwd();
    const root = findResearchRoot(target);
    process.stdout.write(root || "");
    process.exit(0);
  }
  process.stderr.write("usage: node hook_runtime.js --find-root <cwd>\n");
  process.exit(2);
}
