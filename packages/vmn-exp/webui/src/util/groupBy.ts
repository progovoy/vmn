/** What the board can group its runs by (plan 22 G2) and how a group sums
 *  up a metric (G10): the URL's `group=`/`agg=` values and their labels. */
import { GROUP_AGGREGATES, type GroupAggregate } from "../apiGroups";
import type { ExperimentFacets } from "../types";

/** `none`, a link, `branch`/`status`, or `tags.<key>`/`params.<key>`. */
export type GroupBy = string;
export type Aggregate = GroupAggregate;

export interface GroupOption {
  value: GroupBy;
  label: string;
}

export const NO_GROUP = "none";

/** The links between runs; the run a link points at heads the group. */
export const LINK_GROUPS: readonly GroupOption[] = [
  { value: "parent", label: "parent run" },
  { value: "forked_from", label: "forked from" },
  { value: "rerun_of", label: "rerun of" },
  { value: "code_verstr", label: "same code" },
];

const PLAIN_FIELDS = ["branch", "status"];
const KEYED_FIELD = /^(tags|params)\.(.+)$/;

/** A param is offered only with at most this many distinct values. */
export const MAX_PARAM_VALUES = 20;

export const AGGREGATES: readonly Aggregate[] = GROUP_AGGREGATES;

type GroupFacets = Partial<ExperimentFacets> | null | undefined;

/** Groups only a job's Runs tab offers (plan 23 §3.4): inside one job, its
 *  failures by signature. */
const SCOPED_FIELDS = ["failure_sig"];

/** The Fields section: branch, status (with *scoped*, the failure
 *  signature), every tag key, and each param with few enough values to make
 *  groups of. */
export function groupFields(facets: GroupFacets, scoped = false): GroupOption[] {
  const params = Object.entries(facets?.param_values ?? {})
    .filter(([, n]) => n <= MAX_PARAM_VALUES)
    .map(([k]) => `params.${k}`);
  const tags = (facets?.tag_keys ?? []).map((k) => `tags.${k}`);
  const plain = scoped ? [...PLAIN_FIELDS, ...SCOPED_FIELDS] : PLAIN_FIELDS;
  return [...plain, ...tags, ...params].map((value) => ({ value, label: value }));
}

/** Grouped by parent run when some run has one, else not grouped. */
export const defaultGroup = (facets: Pick<ExperimentFacets, "parented"> | null | undefined): GroupBy =>
  facets?.parented ? "parent" : NO_GROUP;

/** A URL `group=` value the board knows, else null. */
export function parseGroup(raw: string | null): GroupBy | null {
  if (!raw) return null;
  if (raw === NO_GROUP || [...PLAIN_FIELDS, ...SCOPED_FIELDS].includes(raw) || KEYED_FIELD.test(raw)) return raw;
  return LINK_GROUPS.some((l) => l.value === raw) ? raw : null;
}

/** A URL `agg=` value the board knows, else null. */
export const parseAggregate = (raw: unknown): Aggregate | null =>
  (AGGREGATES as readonly unknown[]).includes(raw) ? (raw as Aggregate) : null;

/** The label a grouping shows by: a link's name, a field as written. */
export const groupLabel = (group: GroupBy): string =>
  LINK_GROUPS.find((l) => l.value === group)?.label ?? group;
