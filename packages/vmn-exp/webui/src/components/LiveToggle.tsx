/** The auto-refresh switch: "Live" with a pulsing dot while on, "Live off"
 *  while off — the label always says which state it is in. */
export default function LiveToggle({ live, onToggle, style }: {
  live: boolean;
  onToggle: () => void;
  style?: React.CSSProperties;
}) {
  return (
    <button
      className={`live-toggle${live ? " primary" : ""}`}
      aria-pressed={live}
      onClick={onToggle}
      title={live ? "Auto-refresh is on" : "Auto-refresh is off"}
      style={style}
    >
      {live && <span className="live-dot" aria-hidden />}
      {live ? "Live" : "Live off"}
    </button>
  );
}
