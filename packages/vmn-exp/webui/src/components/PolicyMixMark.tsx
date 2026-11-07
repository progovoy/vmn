/** The `*` beside an aggregate some of whose runs override the schema's
 *  summary policy (plan 32 F1); *text* (see `mixText`) is its title. */
export default function PolicyMixMark({ text }: { text: string | null }) {
  if (!text) return null;
  return <span className="policy-mix-mark" title={text}>*</span>;
}
