/** The old `overlay?runs=a,b` and `compare?v=a&to=b` URLs (bookmarks, report
 *  links, CLI output) open the Compare page's curves / code tab instead. */
import { Navigate, useLocation } from "react-router-dom";
import { compareSearch } from "./selection";

export type LegacyPage = "overlay" | "code";

/** The Compare page's search for an old page's *search*. */
export function legacyCompareSearch(from: LegacyPage, search: URLSearchParams): string {
  if (from === "overlay") {
    const runs = (search.get("runs") ?? "").split(",").filter(Boolean);
    return compareSearch("curves", runs);
  }
  const refs = [search.get("v"), search.get("to")].filter((r): r is string => !!r);
  return compareSearch("code", refs);
}

export function LegacyCompareRedirect({ from }: { from: LegacyPage }) {
  const { pathname, search } = useLocation();
  const base = pathname.replace(/\/(overlay|compare)\/?$/, "");
  const to = `${base}/compare-runs?${legacyCompareSearch(from, new URLSearchParams(search))}`;
  return <Navigate replace to={to} />;
}
