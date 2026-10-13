/** Which run the Changes card diffs this one against (plan 20 D7): the
 *  baselines the server found, in D7's order, plus any run the URL names
 *  (the failure card's "last good"). Pure, for the card and its links. */
import type { BaselineRun, RunBaselines } from "../apiRunCode";
import { runText } from "../shell/crumbs";

export type BaselineKey = keyof RunBaselines;
export const BASELINE_KEYS: readonly BaselineKey[] =
  ["base", "parent", "forked_from", "rerun_of", "previous", "best"];

/** The run page's query param holding a baseline key or a run ref. */
export const BASELINE_PARAM = "baseline";
/** The Changes card's element id, for `#changes` links. */
export const CHANGES_ID = "changes";

/** `baseline=<ref>`: the run page query that diffs against *ref*. */
export const changesSearch = (ref: string) => new URLSearchParams({ [BASELINE_PARAM]: ref }).toString();

const KEY_LABEL: Record<BaselineKey, string> = {
  base: "base version", parent: "parent", forked_from: "forked from",
  rerun_of: "rerun of", previous: "previous", best: "best",
};

/** One picker entry: `verstr` null for `base` (the run's own patch). */
export interface BaselineChoice {
  id: string;
  label: string;
  verstr: string | null;
}

const existing = (b: RunBaselines) =>
  BASELINE_KEYS.filter((k) => b[k]).map((k) => [k, b[k] as BaselineRun] as const);

/** `base` when the run captured a patch, else `previous`, else the first that exists. */
export function defaultBaseline(b: RunBaselines): BaselineKey | null {
  if (b.base) return "base";
  if (b.previous) return "previous";
  return existing(b)[0]?.[0] ?? null;
}

const refId = (ref: string) => `ref:${ref}`;
const isOther = (b: RunBaselines, requested: string | null): requested is string =>
  !!requested && !(requested in KEY_LABEL) && !existing(b).some(([, r]) => r.verstr === requested);

export function baselineChoices(b: RunBaselines, requested: string | null): BaselineChoice[] {
  const choices: BaselineChoice[] = existing(b).map(([k, r]) => ({
    id: k,
    label: k === "base" ? KEY_LABEL.base : `${KEY_LABEL[k]} ${runText(r)}`,
    verstr: k === "base" ? null : r.verstr,
  }));
  if (isOther(b, requested)) choices.push({ id: refId(requested), label: `vs ${requested}`, verstr: requested });
  return choices;
}

/** The chosen entry's id: the requested key or ref, else the D7 default. */
export function resolveBaseline(b: RunBaselines, requested: string | null): string | null {
  if (requested && (requested as BaselineKey) in KEY_LABEL && b[requested as BaselineKey]) return requested;
  const byVerstr = existing(b).find(([, r]) => r.verstr === requested);
  if (byVerstr) return byVerstr[0];
  if (isOther(b, requested)) return refId(requested);
  return defaultBaseline(b);
}
