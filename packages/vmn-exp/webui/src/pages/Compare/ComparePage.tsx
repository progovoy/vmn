/** The one Compare page (plan 20 D6): curves | table | code tabs in `?tab=`,
 *  sharing the repeated `?sel=` selection and its chips. */
import { Link, useParams } from "react-router-dom";
import { appName as toAppName } from "../../api";
import { PageHead } from "../../components/ui";
import { setAllParams, useUrlState } from "../../hooks/useUrlState";
import CodeTab from "./CodeTab";
import CurvesTab from "./CurvesTab";
import SelectionChips from "./SelectionChips";
import TableTab from "./TableTab";
import { codePair, compareTab, selectedRefs, type CompareTab } from "./selection";
import "./compare.css";

const TAB_LABELS: Record<CompareTab, string> = { curves: "Curves", table: "Table", code: "Code" };

function Tabs({ base, current, params }: { base: string; current: CompareTab; params: URLSearchParams }) {
  const hrefOf = (t: CompareTab) => {
    const p = new URLSearchParams(params);
    p.set("tab", t);
    return `${base}/compare-runs?${p}`;
  };
  return (
    <nav className="compare-tabs" role="tablist" aria-label="compare view">
      {(Object.keys(TAB_LABELS) as CompareTab[]).map((t) => (
        <Link key={t} role="tab" aria-selected={t === current} to={hrefOf(t)} replace>
          {TAB_LABELS[t]}
        </Link>
      ))}
    </nav>
  );
}

export default function ComparePage() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const base = `/ws/${ws}/app/${app}`;
  const { params, update } = useUrlState();
  const tab = compareTab(params);
  const refs = selectedRefs(params);
  const [from, to] = codePair(params);

  const setSel = (next: string[]) => update((p) => setAllParams(p, "sel", next));
  const onRemove = (ref: string) => setSel(refs.filter((r) => r !== ref));
  const onAdd = (ref: string) => { if (!refs.includes(ref)) setSel([...refs, ref]); };
  // With more than two selected, the "to" picker keeps the selection and
  // picks the other side in `?to=`; otherwise a picker edits the selection.
  const onFrom = (ref: string) => setSel(refs.length > 2 ? [ref, ...refs.slice(1)] : [ref, to]);
  const onTo = (ref: string) => (refs.length > 2
    ? update((p) => p.set("to", ref))
    : setSel([from, ref]));

  return (
    <>
      <Link className="back-link" to={base}>← experiments</Link>
      <PageHead title="Compare" what={toAppName(app)} mono={false} />
      <SelectionChips ws={ws} app={app} refs={refs} onRemove={onRemove} onAdd={onAdd} />
      <Tabs base={base} current={tab} params={params} />
      <div role="tabpanel" aria-label={TAB_LABELS[tab]}>
        {tab === "curves" && <CurvesTab ws={ws} app={app} refs={refs} />}
        {tab === "table" && <TableTab ws={ws} app={app} refs={refs} />}
        {tab === "code" && <CodeTab ws={ws} app={app} v={from} to={to} onFrom={onFrom} onTo={onTo} />}
      </div>
    </>
  );
}
