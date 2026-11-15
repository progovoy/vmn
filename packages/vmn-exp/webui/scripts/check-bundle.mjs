// Fails the build when the entry chunk outgrows its budget, so growth is
// noticed (plan 42 E14b). Library code lives in assets/vendor.js.
import { statSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const ENTRY_BUDGET_BYTES = 300_000;

export function checkEntrySize(size, budget) {
  const ok = size <= budget;
  const verdict = ok ? "within" : "over";
  return { ok, message: `assets/index.js is ${size} bytes, ${verdict} the ${budget}-byte budget` };
}

function main() {
  const entry = fileURLToPath(new URL("../../src/vmn_exp/ui/static/assets/index.js", import.meta.url));
  const { ok, message } = checkEntrySize(statSync(entry).size, ENTRY_BUDGET_BYTES);
  console[ok ? "log" : "error"](message);
  process.exitCode = ok ? 0 : 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
