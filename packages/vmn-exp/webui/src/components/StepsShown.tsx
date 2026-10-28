/** "latest N of M steps" when a bars/table metric lists only its latest
 *  steps (plan 28 N8); nothing when every step is shown. */
export default function StepsShown({ shown, total }: { shown: number; total: number }) {
  return shown < total ? <span>latest {shown} of {total} steps</span> : null;
}
