/** The Compare page's URL state: `?tab=` and the repeated `?sel=`. Pure, so
 *  the page, its redirects and the shell's crumbs/CLI read it alike. */
export type CompareTab = "curves" | "table" | "code";
export const COMPARE_TABS: readonly CompareTab[] = ["curves", "table", "code"];

export function compareTab(search: URLSearchParams): CompareTab {
  const t = search.get("tab");
  return (COMPARE_TABS as readonly string[]).includes(t ?? "") ? (t as CompareTab) : "curves";
}

/** Every selected ref in order, deduped, blanks dropped (uncapped: each tab caps). */
export const selectedRefs = (search: URLSearchParams) =>
  [...new Set(search.getAll("sel").filter(Boolean))];

/** The pair the code tab diffs: the first selected run against `?to=` (the
 *  picker used with more than two selected), else the second; the old code
 *  diff page's defaults fill a missing side. */
export function codePair(search: URLSearchParams): [string, string] {
  const refs = selectedRefs(search);
  return [refs[0] ?? "@1", search.get("to") || refs[1] || "latest"];
}

/** `?tab=…&sel=…` for *refs*, plus any *extra* params. */
export function compareSearch(tab: CompareTab, refs: readonly string[], extra?: URLSearchParams): string {
  const p = new URLSearchParams({ tab });
  refs.forEach((r) => p.append("sel", r));
  extra?.forEach((v, k) => { if (k !== "tab" && k !== "sel") p.append(k, v); });
  return p.toString();
}
