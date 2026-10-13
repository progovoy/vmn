/** The shared segmented control (`.segmented`, styles/filter.css): one
 *  labelled group of buttons, the chosen one pressed. */
export default function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string;
  options: readonly (readonly [T, string])[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button
          key={v} type="button" className={value === v ? "primary" : ""}
          aria-pressed={value === v} onClick={() => onChange(v)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
