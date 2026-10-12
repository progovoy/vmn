/** `document.title` (plan 19 §1.4): `<subject> · <scope> — vmn-exp`, the
 *  subject being the leaf and the scope its nearest container. */
import type { CrumbInput } from "./contracts";
import { crumbsFor, isAppRoute } from "./crumbs";

const SUFFIX = " — vmn-exp";

/** The subject and scope; an unknown scope is dropped. */
function parts(input: CrumbInput): [string, string?] {
  const { routeId, ws, app, search } = input;
  const crumbs = crumbsFor(input);
  const leaf = crumbs[crumbs.length - 1].label;
  switch (routeId) {
    case "apps": return [ws ?? leaf];
    case "experiments": return [`${app} experiments`, ws];
    case "tree": {
      const v = search.get("v");
      return [v ? `stamp tree ${v}` : leaf, app];
    }
    case "models": case "reports": return [leaf, ws];
    case "model": return [leaf, "models"];
    case "report": return [leaf, "reports"];
    case "report-edit": return [`edit ${crumbs[1].label}`];
    default: return isAppRoute(routeId) ? [leaf, app] : [leaf];
  }
}

/** The title's subject alone: what the announcer and ⌘K's Recent name. */
export const subjectFor = (input: CrumbInput): string => parts(input)[0];

/** *stuck* prefixes `(N stuck) ` on app routes. */
export function titleFor(input: CrumbInput, opts: { stuck?: number } = {}): string {
  const [subject, scope] = parts(input);
  const stuck = opts.stuck && isAppRoute(input.routeId) ? `(${opts.stuck} stuck) ` : "";
  return `${stuck}${subject}${scope ? ` · ${scope}` : ""}${SUFFIX}`;
}
