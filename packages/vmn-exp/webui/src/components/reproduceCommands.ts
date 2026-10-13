/** The Reproduce menu's commands (plan 20 D8): copy-first, each with one line
 *  saying where the code lands. */
import { vmnCommand, vmnExpCommand } from "../shell/cliCommands";

export interface ReproduceCommand { verb: string; command: string; hint: string }

const HINTS: Record<string, string> = {
  restore: "into this checkout (saves dirty work first)",
  rerun: "in a throwaway worktree",
  export: "a bundle for a container",
};

/** restore, rerun (only for a run that recorded a command) and export. */
export function reproduceCommands(appName: string, verstr: string, opts: {
  storeUri?: string; hasCommand: boolean;
}): ReproduceCommand[] {
  const verbs = opts.hasCommand ? ["restore", "rerun", "export"] : ["restore", "export"];
  return verbs.map((verb) => ({
    verb, hint: HINTS[verb], command: vmnExpCommand([verb, appName, "-v", verstr], opts.storeUri),
  }));
}

export const gotoCommand = (appName: string, verstr: string) =>
  vmnCommand(["goto", "-v", verstr, appName]);

/** The query listing the reruns of *verstr*. */
export const rerunsQuery = (verstr: string) => `rerun_of = "${verstr}"`;
