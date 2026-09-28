import { nextTheme, useTheme, type ThemePref } from "../hooks/useTheme";

const ICON: Record<ThemePref, string> = { system: "◐", light: "☀", dark: "☾" };

/** Cycles the palette: follow the system, then light, then dark. */
export default function ThemeToggle() {
  const [pref, setPref] = useTheme();
  return (
    <button
      className="theme-toggle"
      aria-label="Theme"
      title={`Theme: ${pref} (click to switch)`}
      onClick={() => setPref(nextTheme(pref))}
    >
      {ICON[pref]}
    </button>
  );
}
