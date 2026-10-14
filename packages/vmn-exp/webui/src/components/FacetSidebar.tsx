/** A job's facet sidebar (plan 23 W3): its runs per status and, per param,
 *  per value (a mini histogram for a many-valued numeric param), counted
 *  over the job's subtree after the other filters. A click adds the value's
 *  clause as a filter token. On a phone it is a drawer behind a button. */
import { useId, useMemo, useState } from "react";
import type { FacetOpts } from "../api";
import { NONE_GROUP } from "../apiGroups";
import { useFacetParams, useParamCounts, useStatusCounts, type FacetParam, type ValueCount } from "../hooks/useFacetCounts";
import { NARROW_QUERY, useMediaQuery } from "../hooks/useMediaQuery";
import { fmtCount, plural } from "../util";
import { binClauses, numericBins, numericKeys } from "../util/facetBins";
import { STATUS_ORDER, statusText } from "../util/filterTokens";
import { groupClause } from "../util/groupClause";
import "./FacetSidebar.css";

/** Params listed before "More params". */
const SHOWN_PARAMS = 8;

type Add = (clauses: string[]) => void;

function Values({ title, values, clauseOf, onAdd }: {
  title: string; values: ValueCount[]; clauseOf: (key: string) => string | null; onAdd: Add;
}) {
  const top = Math.max(1, ...values.map((v) => v.count));
  return (
    <ul className="facet-values" aria-label={title}>
      {values.map((v) => {
        const clause = clauseOf(v.key);
        if (!clause) return null;
        return (
          <li key={v.key}>
            <button type="button" className="facet-value" aria-label={`${clause} (${plural(v.count, "run")})`} onClick={() => onAdd([clause])}>
              <span className="facet-fill" style={{ width: `${(v.count / top) * 100}%` }} aria-hidden="true" />
              <span className="facet-name">{v.key === NONE_GROUP ? "(none)" : v.key}</span>
              <span className="facet-count">{fmtCount(v.count)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** `412 distinct values`: a many-valued param with no numbers to bin. */
const Distinct = ({ n }: { n: number }) => <p className="facet-more muted">{plural(n, "distinct value")}</p>;

function Histogram({ field, numbers, distinct, onAdd }: {
  field: string; numbers: unknown[]; distinct: number; onAdd: Add;
}) {
  const bins = useMemo(() => numericBins(numbers), [numbers]);
  if (!bins.length) return <Distinct n={distinct} />;
  const top = Math.max(1, ...bins.map((b) => b.count));
  return (
    <div role="group" aria-label={`${field} histogram`} className="facet-hist">
      {bins.map((b) => {
        const clauses = binClauses(field, b);
        const label = `${clauses.join(" and ")} (${plural(b.count, "run")})`;
        return (
          <button
            key={b.lo} type="button" className="facet-bin" aria-label={label} title={label}
            disabled={!b.count} onClick={() => onAdd(clauses)}
          >
            <span style={{ height: `${(b.count / top) * 100}%` }} aria-hidden="true" />
          </button>
        );
      })}
      {bins.length > 0 && (
        <span className="facet-hist-axis" aria-hidden="true">
          <span>{bins[0].lo}</span><span>{bins[bins.length - 1].hi}</span>
        </span>
      )}
    </div>
  );
}

function ParamFacet({ ws, app, param, opts, onAdd }: {
  ws: string; app: string; param: FacetParam; opts: FacetOpts; onAdd: Add;
}) {
  const field = `params.${param.key}`;
  const q = useParamCounts(ws, app, param, opts);
  const data = q.data;
  const nums = data && numericKeys(data.values.map((v) => v.key));
  // Numbers read in order; other values most common first.
  const values = data && nums
    ? data.values.map((v, i) => ({ v, n: nums[i] })).sort((a, b) => a.n - b.n).map((x) => x.v)
    : data?.values;
  return (
    <section className="facet" aria-label={field}>
      <h3 className="facet-title mono">{field}</h3>
      {!data ? (q.isError
        ? <p className="facet-more muted">Couldn't count its values</p>
        : <div className="facet-loading skel-bar" aria-hidden="true" />)
        : data.numbers ? <Histogram field={field} numbers={data.numbers} distinct={data.values.length + data.more} onAdd={onAdd} />
        : (
          <>
            <Values title={`${field} values`} values={values!} clauseOf={(k) => groupClause(field, k)} onAdd={onAdd} />
            {data.more > 0 && <p className="facet-more muted">{`+${plural(data.more, "more value")}`}</p>}
          </>
        )}
    </section>
  );
}

function StatusFacet({ ws, app, opts, onAdd }: { ws: string; app: string; opts: FacetOpts; onAdd: Add }) {
  const counts = useStatusCounts(ws, app, opts).data;
  const ordered = counts && [...counts].sort(
    (a, b) => STATUS_ORDER.indexOf(a.key as never) - STATUS_ORDER.indexOf(b.key as never),
  );
  return (
    <section className="facet" aria-label="status">
      <h3 className="facet-title">Status</h3>
      {ordered
        ? <Values title="status values" values={ordered} clauseOf={(k) => statusText([k])} onAdd={onAdd} />
        : <div className="facet-loading skel-bar" aria-hidden="true" />}
    </section>
  );
}

function Facets({ ws, app, opts, onAdd }: { ws: string; app: string; opts: FacetOpts; onAdd: Add }) {
  const params = useFacetParams(ws, app, opts);
  const [all, setAll] = useState(false);
  const shown = all ? params : params.slice(0, SHOWN_PARAMS);
  return (
    <>
      <StatusFacet ws={ws} app={app} opts={opts} onAdd={onAdd} />
      {shown.map((p) => <ParamFacet key={p.key} ws={ws} app={app} param={p} opts={opts} onAdd={onAdd} />)}
      {params.length > shown.length && (
        <button type="button" className="link facet-all" onClick={() => setAll(true)}>
          {`More params (${params.length - shown.length})`}
        </button>
      )}
    </>
  );
}

export default function FacetSidebar({ ws, app, scope, query, status, onAdd }: {
  ws: string; app: string; scope: string;
  /** The board's server query and status CSV: the counts follow them. */
  query: string; status: string;
  onAdd: Add;
}) {
  const narrow = useMediaQuery(NARROW_QUERY);
  const [open, setOpen] = useState(false);
  const id = useId();
  const opts = useMemo(() => ({ scope, query, status }), [scope, query, status]);
  const body = <Facets ws={ws} app={app} opts={opts} onAdd={onAdd} />;
  if (!narrow) return <aside className="facet-sidebar" aria-label="Facets">{body}</aside>;
  return (
    <div className="facet-drawer">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>Facets</button>
      {open && <aside id={id} className="facet-sidebar" aria-label="Facets">{body}</aside>}
    </div>
  );
}
