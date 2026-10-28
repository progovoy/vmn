/** The palette's CLI grammar (plan 19 §1.5): what a typed or pasted
 *  `vmn-exp`/`vmn` line means. Pure: refs stay as typed; resolving them and
 *  turning an intent into a destination is paletteItems' job. */
import { appTag } from "../../api";
import type { RunState } from "../../types";
import { completeToken, stripCliPrefix, tokenize, type Token } from "./tokenize";

export interface ParseScope { apps: string[]; workspaces: string[]; app?: string }
export type PageName =
  | "models" | "model" | "reports" | "tokens" | "actions" | "experiments" | "apps" | "docs" | "settings";

export type CliIntent =
  | { kind: "none" }
  | { kind: "error"; message: string }
  | { kind: "show"; app: string; ref: string }
  | { kind: "list"; app: string; query: string; archived: boolean }
  | { kind: "compare"; app: string; refs: string[] }
  | { kind: "diff"; app: string; from: string; to?: string }
  | { kind: "overlay"; app: string; refs: string[] }
  | { kind: "goto"; app: string; version?: string }
  | { kind: "copy"; app: string; verb: "restore" | "rerun"; ref: string }
  | { kind: "tree"; app: string; version?: string }
  | { kind: "status"; app: string; status: RunState }
  | { kind: "create"; app: string }
  | { kind: "page"; page: PageName; app?: string; model?: string }
  | { kind: "app"; app: string }
  | { kind: "ws"; ws: string };

const NONE: CliIntent = { kind: "none" };
const error = (message: string): CliIntent => ({ kind: "error", message });

const BARE_REF = /^@\d+$|^@?latest$/;
const REF = /^@\d+$|^@?latest$|^(?=.*\d)[A-Za-z0-9._+-]{4,}$/;
/** `@N`, `latest`, or a verstr or prefix (4+ chars with a digit). */
export const isRef = (token: string) => REF.test(token);
const normRef = (ref: string) => (ref === "@latest" ? "latest" : ref);

const STATES: RunState[] = ["running", "stuck", "failed", "succeeded", "created"];
const QUERY = /\b(metrics|params)\.|\s(==?|!=|<=?|>=?|!?~|in|contains)\s/;
const VALUE_FLAGS = new Set(["--store", "--bucket", "--prefix", "--endpoint-url", "--dir"]);
const USAGE: Record<string, string> = {
  show: "show <app> -v <ref>", list: "list <app> <query>", compare: "compare <app> <ref> <ref>",
  diff: "diff <app> <ref> <ref>", overlay: "overlay <app> <ref> <ref>", goto: "goto -v <version> <app>",
  restore: "restore <app> -v <ref>", rerun: "rerun <app> -v <ref>", tree: "tree <app> [version]",
  status: "status <app> <state>", create: "create <app>", actions: "actions <app>",
  experiments: "experiments <app>", settings: "settings <app>",
};
const SIMPLE_PAGES: Record<string, PageName> = {
  models: "models", reports: "reports", tokens: "tokens", docs: "docs", apps: "apps",
};
/** Every verb the grammar knows, in Tab-completion order. */
export const VERBS = [
  "show", "list", "compare", "diff", "overlay", "goto", "restore", "rerun", "tree", "status",
  "create", "new", "models", "model", "reports", "tokens", "actions", "experiments", "runs",
  "apps", "docs", "app", "ws", "q", "settings",
];

interface Args { app?: string; refs: string[]; to?: string; rest: Token[]; archived: boolean }

const appOf = (scope: ParseScope, word: string) =>
  scope.apps.find((a) => a === word || appTag(a) === word);

/** Flags and positionals the way the CLI reads them: `-v` repeats, the first
 *  token naming an app sets it (for a query, only before the expression
 *  starts), `--query` takes the rest. */
function readArgs(tokens: Token[], scope: ParseScope, query: boolean): Args {
  const args: Args = { refs: [], rest: [], archived: false };
  for (let i = 0; i < tokens.length; i++) {
    const word = tokens[i].value;
    if (word === "-v" || word === "--version") {
      if (tokens[i + 1]) args.refs.push(normRef(tokens[++i].value));
    } else if (word === "--to") {
      if (tokens[i + 1]) args.to = normRef(tokens[++i].value);
    } else if (word === "--query" || word === "-q") {
      args.rest.push(...tokens.slice(i + 1));
      break;
    } else if (word === "--archived") args.archived = true;
    else if (VALUE_FLAGS.has(word)) i++;
    else if (/^--?[A-Za-z]/.test(word) && !tokens[i].quoted) continue;
    else if (!args.app && !(query && args.rest.length) && appOf(scope, word)) args.app = appOf(scope, word);
    else args.rest.push(tokens[i]);
  }
  return args;
}

/** A query typed as words, or pasted as one quoted argument. */
const exprOf = (tokens: Token[]) =>
  tokens.length === 1 && tokens[0].quoted ? tokens[0].value : tokens.map((t) => t.raw).join(" ");

/** The `-v` refs, then the positional ones; a string names the first non-ref. */
function refsOf(args: Args): string[] | string {
  const bad = args.rest.find((t) => !isRef(t.value));
  if (bad) return bad.value;
  return [...args.refs, ...args.rest.map((t) => normRef(t.value))];
}

function parseVerb(verb: string, tokens: Token[], scope: ParseScope): CliIntent {
  if (SIMPLE_PAGES[verb]) return { kind: "page", page: SIMPLE_PAGES[verb] };
  if (verb === "model") {
    const name = tokens[0]?.value.split("@")[0];
    return name ? { kind: "page", page: "model", model: name } : { kind: "page", page: "models" };
  }
  if (verb === "app") {
    if (!tokens[0]) return { kind: "page", page: "apps" };
    const app = appOf(scope, tokens[0].value);
    return app ? { kind: "app", app } : error(`no app named ${tokens[0].value}`);
  }
  if (verb === "ws") {
    const ws = tokens[0]?.value;
    if (!ws) return error("name a workspace: ws <name>");
    return scope.workspaces.includes(ws) ? { kind: "ws", ws } : error(`no workspace named ${ws}`);
  }
  const name = { q: "list", new: "create", runs: "experiments" }[verb] ?? verb;
  const args = readArgs(tokens, scope, name === "list");
  const app = args.app ?? scope.app ?? (scope.apps.length === 1 ? scope.apps[0] : undefined);
  if (!app) return error(`name an app: ${USAGE[name]}`);
  return appVerb(name, app, args);
}

function appVerb(verb: string, app: string, args: Args): CliIntent {
  const first = args.refs[0] ?? args.rest[0]?.value;
  switch (verb) {
    case "list": return { kind: "list", app, query: exprOf(args.rest), archived: args.archived };
    case "goto": case "tree": return { kind: verb, app, version: first };
    case "create": return { kind: "create", app };
    case "actions": case "experiments": case "settings": return { kind: "page", page: verb, app };
    case "status": {
      const state = STATES.find((s) => s === first);
      return state ? { kind: "status", app, status: state } : error(`status is one of ${STATES.join(", ")}`);
    }
  }
  const refs = refsOf(args);
  if (typeof refs === "string") return error(`no app or run named ${refs}`);
  switch (verb) {
    case "compare":
      if (refs.length < 2) return error("compare needs at least 2 runs");
      if (refs.length > 50) return error("compare takes at most 50 runs");
      return { kind: "compare", app, refs };
    case "overlay":
      return refs.length ? { kind: "overlay", app, refs } : error("overlay needs at least 1 run");
    case "diff":
      return refs.length ? { kind: "diff", app, from: refs[0], to: args.to ?? refs[1] }
        : error(`name a run: ${USAGE.diff}`);
  }
  if (!refs.length) return error(`name a run: ${USAGE[verb]}`);
  if (verb === "show") return { kind: "show", app, ref: refs[0] };
  return { kind: "copy", app, verb: verb as "restore" | "rerun", ref: refs[0] };
}

export function parseCliQuery(text: string, scope: ParseScope): CliIntent {
  const tokens = stripCliPrefix(tokenize(text));
  if (!tokens.length) return NONE;
  const head = tokens[0].value;
  const joined = tokens.map((t) => t.raw).join(" ");
  const queryLike = QUERY.test(` ${joined} `);
  // `status in (...)` is a query; `status stuck` is the filter.
  const statusQuery = head === "status" && !STATES.some((s) => s === tokens[1]?.value) && queryLike;
  if (VERBS.includes(head) && !statusQuery) return parseVerb(head, tokens.slice(1), scope);
  if (tokens.length === 1 && BARE_REF.test(head)) return parseVerb("show", tokens, scope);
  if (queryLike) {
    const app = scope.app ?? (scope.apps.length === 1 ? scope.apps[0] : undefined);
    return app ? { kind: "list", app, query: joined, archived: false } : error(`name an app: ${USAGE.list}`);
  }
  if (tokens.length === 1) {
    const app = appOf(scope, head);
    if (app) return { kind: "app", app };
    if (scope.workspaces.includes(head)) return { kind: "ws", ws: head };
  }
  return NONE;
}

/** Tab: the verb or a bare app while it is the only word, else the app. */
export function completeCli(text: string, apps: string[]): string | null {
  const words = stripCliPrefix(tokenize(text));
  const typingFirst = words.length === 1 && !/\s$/.test(text);
  const names = [...new Set(apps.flatMap((a) => [a, appTag(a)]))];
  return completeToken(text, typingFirst ? [...VERBS, ...names] : names);
}
