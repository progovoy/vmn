/** The board's row density (plan 23 W8): compact one-line rows for scanning
 *  many runs, comfortable two-line ones for reading. */
export const DENSITIES = ["comfortable", "compact"] as const;
export type Density = (typeof DENSITIES)[number];

/** The user's last pick, used by boards whose URL has no `density=`. */
export const DENSITY_KEY = "vmn_board_density";

export const parseDensity = (v: string | null): Density | null =>
  (DENSITIES as readonly string[]).includes(v ?? "") ? (v as Density) : null;

export function storedDensity(): Density {
  try { return parseDensity(localStorage.getItem(DENSITY_KEY)) ?? "comfortable"; } catch { return "comfortable"; }
}

export function rememberDensity(d: Density) {
  try { localStorage.setItem(DENSITY_KEY, d); } catch { /* not persisted */ }
}
