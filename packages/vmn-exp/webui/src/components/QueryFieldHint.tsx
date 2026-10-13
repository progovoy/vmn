import type { FieldHint } from "../util/queryFields";

/** Why typed text that compares a non-field (`lr=0.1`) searches text, and
 *  the clause it likely meant (`params.lr=0.1`), applied on click. */
export default function QueryFieldHint({ hint, onApply }: {
  hint: FieldHint;
  onApply: (clause: string) => void;
}) {
  return (
    <>
      <span className="mono">{hint.field}</span> isn't a field, so this searches text.
      {hint.suggestion && (
        <>
          {" "}Did you mean{" "}
          <button type="button" className="link mono" onClick={() => onApply(hint.suggestion!)}>
            {hint.suggestion}
          </button>
          ?
        </>
      )}
    </>
  );
}
