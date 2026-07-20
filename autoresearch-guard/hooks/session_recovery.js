"use strict";

const {
  additionalContext,
  emit,
  findResearchRoot,
  readEvent,
  runBridge,
  systemWarning,
} = require("./hook_runtime");

function main() {
  const event = readEvent();
  const researchRoot = findResearchRoot(event.cwd);
  if (!researchRoot) {
    return 0;
  }
  try {
    const result = runBridge("session-start", {
      researchRoot,
      event: event.payload,
    });
    if (!result.skip && result.message) {
      emit(additionalContext("SessionStart", result.message));
    }
  } catch (exc) {
    emit(
      systemWarning(
        `AutoResearch Guard recovery context could not be loaded: ${exc && exc.message ? exc.message : exc}`
      )
    );
  }
  return 0;
}

process.exit(main());
