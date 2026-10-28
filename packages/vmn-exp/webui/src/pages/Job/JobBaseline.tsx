/** The outer run against its baseline (plan 28 N3): the Overview's card —
 *  the run it is compared with and how it was picked, the chip, the rollup
 *  deltas (goal metrics' best and median, failures, p90 duration, attention
 *  shares, the metrics both log themselves) and its direct children paired
 *  by key, the worse ones marked — and the header's chip. Both read one
 *  query, refetched as the outer run's done count moves, so the chip shows
 *  while matched children are still finishing. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { jobBaseline, type BaselineCompare, type BaselineDelta } from "../../apiBaseline";
import BaselineChip, { pickedText } from "../../components/BaselineChip";
import { fmtDelta } from "../../components/diffDeltaTone";
import { fleetLabel } from "../../components/fleetRows";
import { Skeleton } from "../../components/ui";
import { withSignal } from "../../requestScope";
import { appHref, fmtDuration, fmtPct, fmtVal, runHref } from "../../util";
import { jobPrefix } from "./jobQueries";

interface Props { ws: string; app: string; verstr: string; done: number }

export function useJobBaseline(ws: string, app: string, v: string, done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "baseline", done],
    queryFn: ({ signal }) => withSignal(signal, () => jobBaseline(ws, app, v)),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

/** The header's chip, linked to the baseline run; nothing without one. */
export function JobBaselineChip({ ws, app, verstr, done }: Props) {
  const data = useJobBaseline(ws, app, verstr, done).data;
  if (!data?.chip || !data.baseline) return null;
  return <BaselineChip chip={data.chip} baseline={data.baseline} href={runHref(appHref(ws, app), data.baseline.verstr)} />;
}

type Format = (v: number) => string;
const signed = (v: number, fmt: Format) => `${v > 0 ? "+" : v < 0 ? "-" : ""}${fmt(Math.abs(v))}`;
const pts = (v: number) => `${fmtVal(v)} pts`;
const share = (v: number) => fmtPct(v * 100);
const sharePts = (v: number) => pts(Math.round(v * 1000) / 10);

function DeltaRow({ label, d, fmt = fmtVal, deltaFmt = fmt }: {
  label: string; d: BaselineDelta | null; fmt?: Format; deltaFmt?: Format;
}) {
  if (!d) return null;
  const shown = (v: number | null) => (v == null ? "–" : fmt(v));
  const tone = d.better == null ? "" : d.better ? "delta-better" : "delta-worse";
  return (
    <tr>
      <th scope="row">{label}</th>
      <td className="num">{shown(d.value)}</td>
      <td className="num">{shown(d.baseline)}</td>
      <td className="num"><span className={tone}>{d.delta == null ? "–" : signed(d.delta, deltaFmt)}</span></td>
    </tr>
  );
}

function DeltaTable({ data }: { data: BaselineCompare }) {
  return (
    <table className="baseline-deltas" aria-label="Against the baseline">
      <thead><tr><th /><th scope="col">this</th><th scope="col">baseline</th><th scope="col">Δ</th></tr></thead>
      <tbody>
        {Object.entries(data.metrics).flatMap(([m, d]) => [
          <DeltaRow key={`best ${m}`} label={`best ${m}`} d={d.best} />,
          <DeltaRow key={`median ${m}`} label={`median ${m}`} d={d.median} />,
        ])}
        <DeltaRow label="failed" d={data.failed_pct} fmt={fmtPct} deltaFmt={pts} />
        <DeltaRow label="p90 duration" d={data.duration_p90} fmt={fmtDuration} />
        {data.attention.map((a) => (
          <DeltaRow key={a.key} label={`${a.label} share`} d={a} fmt={share} deltaFmt={sharePts} />
        ))}
        {Object.entries(data.own).map(([m, d]) => <DeltaRow key={`own ${m}`} label={m} d={d} />)}
      </tbody>
    </table>
  );
}

const fieldName = (field: string) => field.slice(field.indexOf(".") + 1);

function PairTable({ data, appBase }: { data: BaselineCompare; appBase: string }) {
  if (!data.by || !data.pairs.length) return null;
  const noun = `${fieldName(data.by)} values`;
  return (
    <>
      <p className="muted">{`${data.pairs.length} of ${data.pairs_total} ${noun} matched`}</p>
      <div className="baseline-pairs">
        <table aria-label={`Per ${fieldName(data.by)}`}>
          <thead><tr><th scope="col">{fieldName(data.by)}</th><th scope="col">this</th><th scope="col">baseline</th><th scope="col">Δ {data.metric}</th><th /></tr></thead>
          <tbody>
            {data.pairs.map((p) => (
              <tr key={p.key} className={p.worse ? "pair-worse" : undefined}>
                <td><Link to={runHref(appBase, p.verstr)}>{p.label}</Link></td>
                <td className="num">{fmtVal(p.value)}</td>
                <td className="num">{fmtVal(p.baseline)}</td>
                <td className="num">{fmtDelta(p.delta)}</td>
                <td className="muted">{!p.done ? "not finished" : p.worse && data.chip?.quantile ? `past the baseline's ${data.chip.quantile}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const noBaseline = (match: string[]) => (match.length
  ? `No ended outer run with the same ${match.join(", ")} yet (tag one baseline=true to pin it).`
  : "No earlier ended outer run beside it yet (tag one baseline=true to pin it).");

export default function JobBaseline({ ws, app, verstr, done }: Props) {
  const query = useJobBaseline(ws, app, verstr, done);
  const appBase = appHref(ws, app);
  if (query.isError) return <p className="error" role="alert">{query.error.message}</p>;
  const data = query.data;
  if (!data) return <Skeleton />;
  if (!data.baseline) return <p className="muted">{noBaseline(data.match)}</p>;
  return (
    <div className="job-baseline">
      <p>
        vs <Link to={runHref(appBase, data.baseline.verstr)}>{fleetLabel(data.baseline)}</Link>{" "}
        <span className="muted">{pickedText(data.baseline.source, data.match)}</span>
      </p>
      {data.chip && <p><BaselineChip chip={data.chip} /></p>}
      <DeltaTable data={data} />
      <PairTable data={data} appBase={appBase} />
    </div>
  );
}
