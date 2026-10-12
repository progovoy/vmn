import { nextTheme, useTheme, useThemeVersion, type ThemePref } from "../hooks/useTheme";
import { Icon, type IconName } from "./shell/icons";
import "./ThemeToggle.css";

const ICON: Record<ThemePref, IconName> = { system: "theme-system", light: "sun", dark: "moon" };

const systemIsDark = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;

/** "system (dark)" names the palette "system" resolves to right now. */
const labelOf = (pref: ThemePref) =>
  pref === "system" ? `system (${systemIsDark() ? "dark" : "light"})` : pref;

/** Cycles the palette: follow the system, then light, then dark. */
export default function ThemeToggle() {
  const [pref, setPref] = useTheme();
  useThemeVersion(); // re-render when the OS palette flips
  const label = `Theme: ${labelOf(pref)}. Switch to ${nextTheme(pref)}`;
  return (
    <button
      className="theme-toggle"
      aria-label={label}
      title={label}
      onClick={() => setPref(nextTheme(pref))}
    >
      <Icon name={ICON[pref]} />
    </button>
  );
}
