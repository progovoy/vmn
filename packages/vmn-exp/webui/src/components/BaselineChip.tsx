/** An outer run's baseline chip (plan 28 N3): the server's text
 *  (`▼ best_value from 2024-12 (5 of 41 trade_date values worse than the
 *  baseline's p10)`), coloured by its state, its title naming the run it
 *  compares against; a link when given *href*. */
import { Link } from "react-router-dom";
import type { BaselineChipData, BaselineCompare, BaselineRef, BaselineSource } from "../apiBaseline";
import { fleetLabel } from "./fleetRows";

/** ` with the same a, b and a different c` (plan 34 §2), empty for no fields. */
export function ruleText(match: readonly string[], differ: readonly string[] = []): string {
  const parts = [
    match.length ? `the same ${match.join(", ")}` : "",
    differ.length ? `a different ${differ.join(", ")}` : "",
  ].filter(Boolean);
  return parts.length ? ` with ${parts.join(" and ")}` : "";
}

/** How the baseline was picked; *match* the fields it shares and *differ*
 *  the ones it does not (unknown: "alike"); *pool* the attempts of both
 *  trainings when they are pooled (plan 35 §3). */
export function pickedText(
  source: BaselineSource, match?: readonly string[], differ?: readonly string[], pool?: BaselineCompare["pool"],
): string {
  const pooled = pool ? `, ${poolText(pool)}` : "";
  if (source === "pinned") return `pinned with the tag baseline=true${pooled}`;
  if (source === "to") return `chosen with to=${pooled}`;
  if (!match) return "the latest ended outer run alike";
  return `the latest ended ${pool ? "training" : "outer run"}${ruleText(match, differ) || " beside it"}${pooled}`;
}

const attempts = (n: number) => `${n} attempt${n === 1 ? "" : "s"}`;
/** `pooled by tags.launch_id (2 attempts vs 3)`. */
const poolText = (pool: NonNullable<BaselineCompare["pool"]>) =>
  `pooled by ${pool.by} (${attempts(pool.attempts.length)} vs ${pool.baseline_attempts.length})`;

export const baselineTitle = (ref: BaselineRef) => `vs ${fleetLabel(ref)}, ${pickedText(ref.source)}`;

/** ` · 5 of 39 paired` when some keys lack a value on a side, else nothing. */
const pairedText = ({ paired, total }: BaselineChipData) =>
  paired != null && total != null && paired < total ? ` · ${paired} of ${total} paired` : "";

export default function BaselineChip({ chip, baseline, href }: {
  chip: BaselineChipData; baseline?: BaselineRef | null; href?: string;
}) {
  const className = `baseline-chip baseline-${chip.state}`;
  const title = baseline ? baselineTitle(baseline) : undefined;
  const text = chip.text + pairedText(chip) + (chip.pool_by ? ` · pooled by ${chip.pool_by}` : "");
  if (href) return <Link className={className} to={href} title={title}>{text}</Link>;
  return <span className={className} title={title}>{text}</span>;
}
