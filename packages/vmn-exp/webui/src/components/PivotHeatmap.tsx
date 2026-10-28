/** The pivot heatmap (plan 28 N2): the server's rows x cols grid as a table,
 *  each cell's value written in it and filled on one sequential hue (with a
 *  scale legend), each header and cell a link to the board filtered to its
 *  runs (*hrefOf* a board query; *baseQuery* the runs' own filter). */
import { memo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Pivot, PivotCell } from "../apiPivot";
import {
  cellFill, cellLabel, cellQuery, cellText, pivotRange, scaleText, withQuery,
} from "../util/pivotCells";

interface Props {
  pivot: Pivot;
  rowsField: string;
  colsField: string;
  hrefOf: (query: string) => string;
  baseQuery?: string;
}

function title(pivot: Pivot): string {
  if (pivot.cell === "share") return `share matching ${pivot.match}`;
  if (pivot.cell === "agg") return `${pivot.agg} ${pivot.metric}`;
  return "runs";
}

type Href = (query: string) => string;

/** A link to *query*'s runs, plain text without one. */
function MaybeLink({ query, href, label, style, children }: {
  query: string | null; href: Href; label?: string; style?: object; children: ReactNode;
}) {
  if (!query) return label || style ? <span aria-label={label} title={label} style={style}>{children}</span> : <>{children}</>;
  return <Link to={href(query)} aria-label={label} title={label} style={style}>{children}</Link>;
}

function Cell({ props, href, i, j, cell, range }: {
  props: Props; href: Href; i: number; j: number; cell: PivotCell | null; range: [number | null, number | null];
}) {
  const { pivot } = props;
  if (!cell) return <td className="pivot-empty" />;
  const label = cellLabel(pivot, props.rowsField, props.colsField, i, j, cell);
  return (
    <td className="pivot-cell">
      <MaybeLink query={cellQuery(pivot, cell)} href={href} label={label} style={cellFill(cell.value, range)}>
        {cellText(cell, pivot.cell)}
      </MaybeLink>
    </td>
  );
}

function Legend({ pivot, range }: { pivot: Pivot; range: [number | null, number | null] }) {
  const [lo, hi] = range;
  if (lo === null || hi === null) return null;
  const low = scaleText(lo, pivot.cell), high = scaleText(hi, pivot.cell);
  return (
    <div className="pivot-legend" role="img" aria-label={`Scale: ${low} to ${high}`}>
      <span>{low}</span>
      <span className="pivot-legend-ramp" style={{ background: `linear-gradient(to right, ${cellFill(lo, range).background}, ${cellFill(hi, range).background})` }} />
      <span>{high}</span>
    </div>
  );
}

function CutNote({ pivot, rowsField, colsField }: Pick<Props, "pivot" | "rowsField" | "colsField">) {
  const { rows, cols, rows_total, cols_total } = pivot;
  if (rows_total <= rows.length && cols_total <= cols.length) return null;
  return (
    <p className="muted pivot-note">
      Showing the {rows.length} most common of {rows_total} {rowsField} values and {cols.length} of {cols_total} {colsField} values.
    </p>
  );
}

function PivotHeatmap(props: Props) {
  const { pivot, rowsField, colsField, hrefOf, baseQuery } = props;
  if (!pivot.total) return <p className="muted">No runs to pivot.</p>;
  const range = pivotRange(pivot);
  const href = (q: string) => hrefOf(withQuery(baseQuery, q));
  return (
    <div className="pivot">
      <div className="pivot-scroll">
        <table className="pivot-table" aria-label={`${title(pivot)} by ${rowsField} × ${colsField}`}>
          <thead>
            <tr>
              <th scope="col" className="mono pivot-corner">{rowsField} \ {colsField}</th>
              {pivot.cols.map((c) => <th key={c.key} scope="col" className="mono"><MaybeLink query={c.clause} href={href}>{c.label}</MaybeLink></th>)}
            </tr>
          </thead>
          <tbody>
            {pivot.rows.map((r, i) => (
              <tr key={r.key}>
                <th scope="row" className="mono"><MaybeLink query={r.clause} href={href}>{r.label}</MaybeLink></th>
                {pivot.cells[i].map((cell, j) => <Cell key={pivot.cols[j].key} props={props} href={href} i={i} j={j} cell={cell} range={range} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Legend pivot={pivot} range={range} />
      <CutNote pivot={pivot} rowsField={rowsField} colsField={colsField} />
    </div>
  );
}

/** Memoized: an outer run's Overview re-renders on every summary poll. */
export default memo(PivotHeatmap);
