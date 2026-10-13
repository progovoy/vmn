import type { ReactNode } from "react";

/** The shared on/off chip (`button.status-toggle`): the leaderboard's status
 *  and archived shortcuts, the Reports page's archived switch. */
export default function ToggleChip({ pressed, onChange, title, className, children }: {
  pressed: boolean;
  onChange: (pressed: boolean) => void;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={className ? `status-toggle ${className}` : "status-toggle"}
      aria-pressed={pressed}
      title={title}
      onClick={() => onChange(!pressed)}
    >
      {children}
    </button>
  );
}
