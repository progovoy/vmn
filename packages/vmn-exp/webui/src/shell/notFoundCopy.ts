/** What each not-found page says and offers (plan 19 §1.6), kept pure so
 *  every string is pinned by a unit test. NotFound.tsx only renders it. */
import { closest } from "../util/closest";
import type { NotFoundProps } from "./contracts";

/** Plain text, or a mono identifier (a link when `to` is set). */
export type Seg = string | { mono: string; to?: string };
export type Line = Seg[];
export interface NotFoundAction { label: Line; to: string }
export interface NotFoundCopy {
  h1: Line;
  /** One paragraph per line. */
  body: Line[];
  /** The first is the primary action. */
  actions: NotFoundAction[];
  hint?: string;
  cli?: string;
}

/** What the page knows beyond its props. */
export interface NotFoundFacts {
  workspaces: string[];
  /** The workspace's apps, in name form (kind `app`). */
  apps?: string[];
  /** The app's run count (kind `run`), when known. */
  runTotal?: number | null;
  isStore?: boolean;
  storeUri?: string;
  /** Whether "Attach a checkout" may be offered (kind `workspace`). */
  canAttach?: boolean;
}

const LISTED = 5;
const ALL_WORKSPACES: NotFoundAction = { label: ["All workspaces"], to: "/" };

export const plain = (line: Line) =>
  line.map((s) => (typeof s === "string" ? s : s.mono)).join("");

const nameOf = (tag: string) => tag.replaceAll("-", "/");
const tagOf = (name: string) => name.replaceAll("/", "-");
const appBase = (ws: string, tag: string) => `/ws/${ws}/app/${tag}`;

/** `a, b, c` as links, the first five only. */
function linkList(names: string[], href: (name: string) => string): Line {
  return names.slice(0, LISTED).flatMap((name, i) => [
    ...(i ? [", "] : []), { mono: name, to: href(name) },
  ]);
}

function routeCopy(pathname: string, facts: NotFoundFacts): NotFoundCopy {
  const ws = /^\/ws\/([^/]+)/.exec(pathname)?.[1];
  const known = ws !== undefined && facts.workspaces.includes(ws);
  return {
    h1: ["No page at this address"],
    body: [[{ mono: pathname }, " isn't a vmn-exp ui page."]],
    actions: [ALL_WORKSPACES, ...(known ? [{ label: [`Open ${ws}`], to: `/ws/${ws}` }] : [])],
    hint: "⌘K jumps to any run, app or page.",
  };
}

function workspaceCopy(ws: string, facts: NotFoundFacts): NotFoundCopy {
  const href = (name: string) => `/ws/${name}`;
  const names = facts.workspaces;
  const guess = closest(ws, names);
  const body: Line[] = [names.length
    ? ["Workspaces on this server: ", ...linkList(names, href), "."]
    : ["This server has no workspaces yet."]];
  if (guess) body.push(["Did you mean ", { mono: guess, to: href(guess) }, "?"]);
  const attach = { label: [`Attach a checkout as ${ws}`], to: `/?add=1&name=${encodeURIComponent(ws)}` };
  return {
    h1: ["No workspace named ", { mono: ws }],
    body,
    actions: [ALL_WORKSPACES, ...(facts.canAttach ? [attach] : [])],
    cli: "vmn-exp ui --repo <path>",
  };
}

function appCopy(ws: string, appTag: string, facts: NotFoundFacts): NotFoundCopy {
  const apps = facts.apps ?? [];
  const guess = closest(nameOf(appTag), apps);
  const href = (name: string) => appBase(ws, tagOf(name));
  const body: Line[] = [];
  if (guess) body.push(["Did you mean ", { mono: guess, to: href(guess) }, "?"]);
  if (apps.length) body.push(["Apps here: ", ...linkList(apps, href), "."]);
  else if (facts.isStore) body.push(["This store has no runs yet."]);
  else {
    body.push([
      `${ws} has no apps yet. An app appears after its first `, { mono: "vmn stamp -r patch <app>" },
      " or ", { mono: "vmn-exp run <app> -- <cmd>" }, ".",
    ]);
  }
  return {
    h1: ["No app ", { mono: nameOf(appTag) }, ` in ${ws}`],
    body,
    actions: [guess
      ? { label: [`Open ${guess}`], to: href(guess) }
      : { label: [`Open ${ws}`], to: `/ws/${ws}` }],
  };
}

function runCopy(ws: string, appTag: string, ref: string, facts: NotFoundFacts): NotFoundCopy {
  const app = nameOf(appTag);
  const base = appBase(ws, appTag);
  const total = facts.runTotal;
  const byIndex = /^@\d+$/.test(ref);
  let line: Line;
  if (byIndex && total === 0) line = [`${app} has no runs yet.`];
  else if (byIndex && total != null) line = [`${app} has ${total} runs (@1–@${total}).`];
  else {
    line = [
      "It may have been pruned (", { mono: "vmn-exp prune" },
      "), or recorded offline and not pushed yet (", { mono: "vmn-exp push" }, ").",
    ];
  }
  const copy: NotFoundCopy = {
    h1: ["No run ", { mono: ref }, ` in ${app}`],
    body: [line],
    actions: [{ label: ["Back to experiments"], to: base }],
    cli: `vmn-exp list ${app}`,
  };
  if (byIndex) return copy;
  // A verstr or prefix may still match a run under another name: search for it.
  const query = `verstr ~ "${ref.replaceAll('"', "")}"`;
  copy.actions.push({ label: ["Search runs for ", { mono: ref }], to: `${base}?q=${encodeURIComponent(query)}` });
  copy.cli += ` --query '${query}'`;
  return copy;
}

function needsGitCopy(ws: string, appTag: string, page: "tree" | "actions", facts: NotFoundFacts): NotFoundCopy {
  const where: Line = facts.storeUri ? [" (", { mono: facts.storeUri }, ")"] : [];
  return {
    h1: [page === "tree" ? "Stamp tree needs a git workspace" : "Actions need a git workspace"],
    body: [[
      `${ws} is a store workspace`, ...where,
      ". Versions live in git tags: open a git workspace of this app, or run ",
      { mono: `vmn show ${nameOf(appTag)}` }, " in a checkout.",
    ]],
    actions: [{ label: ["Open experiments"], to: appBase(ws, appTag) }],
  };
}

export function notFoundCopy(props: NotFoundProps, facts: NotFoundFacts): NotFoundCopy {
  switch (props.kind) {
    case "route": return routeCopy(props.pathname, facts);
    case "workspace": return workspaceCopy(props.ws, facts);
    case "app": return appCopy(props.ws, props.appTag, facts);
    case "run": return runCopy(props.ws, props.appTag, props.ref, facts);
    case "model":
      return {
        h1: ["No model ", { mono: props.name }, ` in ${props.ws}`],
        body: [["It may have been deleted (", { mono: "vmn-exp model delete" }, ")."]],
        actions: [{ label: ["All models"], to: `/ws/${props.ws}/models` }],
        cli: "vmn-exp model list",
      };
    case "report":
      return {
        h1: ["No report ", { mono: props.rid }, ` in ${props.ws}`],
        body: [],
        actions: [{ label: ["All reports"], to: `/ws/${props.ws}/reports` }],
      };
    case "control-plane":
      return {
        h1: ["API tokens need a control plane"],
        body: [[
          "This server has no control plane. Start it with ",
          { mono: "vmn-exp ui --config server.yml" }, ".",
        ]],
        actions: [ALL_WORKSPACES],
      };
    case "needs-git": return needsGitCopy(props.ws, props.appTag, props.page, facts);
  }
}

/** An HttpError's status, if it has one. */
export const httpStatus = (e: unknown): number | undefined =>
  (e as { status?: number } | null)?.status;

const detailOf = (e: unknown): string => {
  const detail = (e as { body?: { detail?: unknown } } | null)?.body?.detail;
  return typeof detail === "string" ? detail : "";
};

/** The run detail's "no such run" answers: a 404 for the experiment, or a 400
 *  for a ref that is no version at all. Any other failure is a real error. */
export function isMissingRun(e: unknown): boolean {
  const status = httpStatus(e);
  if (status === 404) return detailOf(e).startsWith("Experiment ");
  if (status === 400) return detailOf(e).startsWith("Invalid version");
  return false;
}
