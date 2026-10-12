/** "Copy as CLI" (plan 19 §1.4): the command that prints what the page
 *  shows. Runs are named by verstr (it survives prune); a store workspace
 *  adds `--store` to `vmn-exp` commands. Pages with no CLI twin get none. */
import type { CliCommand, CrumbInput } from "./contracts";
import { compareRefs, diffRefs, runOf } from "./crumbs";

const SAFE = /^[A-Za-z0-9@._+:/=-]+$/;

/** *arg* as one POSIX shell word. */
export function shellQuote(arg: string): string {
  return SAFE.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`;
}

const join = (args: string[]) => args.map(shellQuote).join(" ");

function vmnExpArgs(input: CrumbInput): string[][] {
  const { routeId, app = "", search, params } = input;
  switch (routeId) {
    case "experiments": {
      const q = search.get("q");
      return [[
        "list", app, ...(q ? ["--query", q] : []), ...(search.get("archived") === "1" ? ["--archived"] : []),
      ]];
    }
    case "run": {
      const v = runOf(input).verstr;
      return ["show", "restore", "rerun"].map((cmd) => [cmd, app, "-v", v]);
    }
    case "code-diff": {
      const [v, to] = diffRefs(search);
      return [["diff", app, "-v", v, "-v", to]];
    }
    case "compare-runs": {
      const refs = compareRefs(search);
      return refs.length ? [["compare", app, ...refs.flatMap((r) => ["-v", r])]] : [];
    }
    case "models": return [["model", "list"]];
    case "model": return [["model", "show", params.modelName ?? ""]];
    default: return [];
  }
}

function vmnArgs({ routeId, app = "", search }: CrumbInput, verstr: string): string[][] {
  if (routeId === "run") return [["goto", "-v", verstr, app]];
  if (routeId !== "tree") return [];
  const v = search.get("v");
  return [v ? ["goto", "-v", v, app] : ["show", app]];
}

export function cliFor(input: CrumbInput): CliCommand[] {
  const store = input.storeUri ? ["--store", input.storeUri] : [];
  const exp = vmnExpArgs(input).map((args) => ({
    label: args[0] === "model" ? args[1] : args[0],
    command: `vmn-exp ${join([...args, ...store])}`,
  }));
  const vmn = vmnArgs(input, runOf(input).verstr).map((args) => ({
    label: args[0], command: `vmn ${join(args)}`,
  }));
  return [...exp, ...vmn];
}
