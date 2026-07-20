"use strict";

const {
  emit,
  findResearchRoot,
  readEvent,
  runBridge,
  systemWarning,
} = require("./hook_runtime");

function parseArgs(argv) {
  let cwd = "";
  let allowIncomplete = false;
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--cwd") {
      i += 1;
      cwd = argv[i] || "";
    } else if (arg === "--allow-incomplete") {
      allowIncomplete = true;
    }
  }
  return { cwd, allowIncomplete, cwdProvided: Boolean(cwd) };
}

function main() {
  const args = parseArgs(process.argv);
  const event = readEvent({ cwd: args.cwd });
  const researchRoot = findResearchRoot(event.cwd);
  if (!researchRoot || args.allowIncomplete) {
    return 0;
  }

  try {
    const result = runBridge("stop", {
      researchRoot,
      event: event.payload,
      allowIncomplete: args.allowIncomplete,
      cwdProvided: args.cwdProvided,
    });
    if (result.skip) {
      return 0;
    }

    const action = result.action;
    if (action === "continue") {
      emit({
        decision: "block",
        reason: String(result.reason || "AutoResearch Guard closure is incomplete"),
      });
    } else if (action === "halt") {
      emit(systemWarning(String(result.reason || "AutoResearch Guard paused the loop"), { stop: true }));
    } else if (action === "allow") {
      const readiness = result.readiness || {};
      if (readiness.outcome === "blocked_requires_human" || readiness.outcome === "aborted") {
        emit(systemWarning(String(result.reason || readiness.outcome)));
      }
    }
  } catch (exc) {
    emit(
      systemWarning(
        `AutoResearch Guard Stop check failed; the loop was stopped safely: ${
          exc && exc.message ? exc.message : exc
        }`,
        { stop: true }
      )
    );
  }
  return 0;
}

process.exit(main());
