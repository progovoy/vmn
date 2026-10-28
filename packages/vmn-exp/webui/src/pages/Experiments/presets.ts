/** The Outer runs view's presets (plan 28 §4.5), `view=live|review`: Live
 *  ("what is on the cluster now") and Review ("is this launch good to
 *  ship?"). Each is the Outer runs view with a query the outer runs pass by
 *  their own fields (`top_q`, so a search still matches every run of a
 *  tree) and a default sort; a sort in the URL beats it. An outer run is in
 *  flight while it, or its subtree's rollup, runs, waits or is stuck: its
 *  own status counts too, since a failed run anywhere in a tree makes the
 *  rollup read failed while the rest still runs. */
import { IDX_SORT } from "../LeaderboardHead";
import { JOB_SORTS } from "./jobColumns";

export type Preset = "live" | "review";

/** How long an ended outer run stays in Live. */
export const LIVE_WINDOW = "6h";

const IN_FLIGHT = 'status in ("running", "stuck") or tree_status in ("running", "created", "stuck")';

/** In flight, or ended within LIVE_WINDOW. */
export const LIVE_QUERY = `${IN_FLIGHT} or finished_at >= ago("${LIVE_WINDOW}")`;

/** Ended. */
export const REVIEW_QUERY = `not (${IN_FLIGHT})`;

export const PRESETS: Record<Preset, { label: string; query: string; sort: string }> = {
  live: { label: "Live", query: LIVE_QUERY, sort: JOB_SORTS.attention },
  review: { label: "Review", query: REVIEW_QUERY, sort: IDX_SORT },
};

export const isPreset = (v: string | null | undefined): v is Preset => v === "live" || v === "review";
