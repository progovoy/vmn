/** The one not-found page (plan 19 §1.6): it renders inside the shell, says
 *  what is missing, and offers the way back. Pages render it too, so it reads
 *  only usePageScope and queries, never the router's matches. */
import { useEffect, useRef, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { facetsQuery, useApps } from "../../queries";
import { CopyButton } from "../ui";
import { usePageScope } from "../../shell/usePageScope";
import { useOverrideRoute } from "../../shell/shellOverride";
import { notFoundCopy, type Line } from "../../shell/notFoundCopy";
import type { NotFoundProps } from "../../shell/contracts";
import "./NotFound.css";

const wsOf = (p: NotFoundProps) => ("ws" in p ? p.ws : undefined);

/** The app's run count, asked for only by a run's not-found. */
function useRunTotal(p: NotFoundProps): number | null {
  const run = p.kind === "run" ? p : null;
  const q = useQuery({ ...facetsQuery(run?.ws ?? "", run?.appTag ?? ""), enabled: run !== null });
  return q.data?.total ?? null;
}

function Text({ line }: { line: Line }) {
  return (
    <>
      {line.map((seg, i): ReactNode => {
        if (typeof seg === "string") return seg;
        if (seg.to) return <Link key={i} className="mono" to={seg.to}>{seg.mono}</Link>;
        return <code key={i}>{seg.mono}</code>;
      })}
    </>
  );
}

/** The heading takes focus on mount, so a screen reader hears what happened. */
export function FocusedHeading({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return <h1 ref={ref} tabIndex={-1}>{children}</h1>;
}

export default function NotFound(props: NotFoundProps) {
  useOverrideRoute("not-found");
  const scope = usePageScope(wsOf(props));
  const apps = useApps(props.kind === "app" ? props.ws : undefined).data;
  const runTotal = useRunTotal(props);
  const copy = notFoundCopy(props, {
    workspaces: scope.workspaces.map((w) => w.name),
    apps: apps?.map((a) => a.name),
    runTotal,
    isStore: !scope.isGit,
    storeUri: scope.workspace?.store,
    canAttach: scope.canAttach,
  });
  return (
    <section className="not-found">
      <FocusedHeading><Text line={copy.h1} /></FocusedHeading>
      {copy.body.map((line, i) => <p key={i}><Text line={line} /></p>)}
      <div className="nf-actions">
        {copy.actions.map((a, i) => (
          <Link key={a.to} className={i === 0 ? "nf-action primary" : "nf-action"} to={a.to}>
            <Text line={a.label} />
          </Link>
        ))}
      </div>
      {copy.hint && <p className="nf-hint">{copy.hint}</p>}
      {copy.cli && (
        <div className="nf-cli">
          <div className="cli-hint">{copy.cli}</div>
          <CopyButton text={copy.cli} label="Copy command" />
        </div>
      )}
    </section>
  );
}

/** The `*` route: no page at this address. */
export function RouteNotFound() {
  return <NotFound kind="route" pathname={useLocation().pathname} />;
}
