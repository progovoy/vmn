/** "Copy as CLI" (plan 19 §1.4): the command that prints what the page
 *  shows. Runs are named by verstr (it survives prune); a store workspace
 *  adds `--store` to `vmn-exp` commands. Pages with no CLI twin get none. */
import type { Workspace } from "../types";
import type { CliCommand, CrumbInput } from "./contracts";
import { codePair, compareTab } from "../pages/Compare/selection";
import { compareRefs, diffRefs, runOf } from "./crumbs";

const SAFE = /^[A-Za-z0-9@%_+=:,./-]+$/;

/** *arg* as one POSIX shell word. */
export function shellQuote(arg: string): string {
  return SAFE.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`;
}

const join = (args: string[]) => args.map(shellQuote).join(" ");

/** The URI a workspace's `vmn-exp` commands pass as `--store`: a store workspace's. */
export const storeUriOf = (w?: Pick<Workspace, "kind" | "store">) =>
  w?.kind === "store" ? w.store : undefined;

/** `vmn-exp <args>`, plus `--store` for a store workspace. */
export const vmnExpCommand = (args: string[], storeUri?: string) =>
  `vmn-exp ${join([...args, ...(storeUri ? ["--store", storeUri] : [])])}`;
export const vmnCommand = (args: string[]) => `vmn ${join(args)}`;

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
      if (compareTab(search) === "code") return [["diff", app, ...codePair(search).flatMap((r) => ["-v", r])]];
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
  const exp = vmnExpArgs(input).map((args) => ({
    label: args[0] === "model" ? args[1] : args[0],
    command: vmnExpCommand(args, input.storeUri),
  }));
  const vmn = vmnArgs(input, runOf(input).verstr).map((args) => ({
    label: args[0], command: vmnCommand(args),
  }));
  return [...exp, ...vmn];
}
