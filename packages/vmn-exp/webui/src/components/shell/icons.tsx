/** The shell's icon set: authored 15×15 stroke drawings in `currentColor`.
 *  Shell components take icons from here only, never unicode glyphs. */

/** A full circle as a path, so every icon is drawn from `<path>`s alone. */
const ring = (cx: number, cy: number, r: number) =>
  `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;

const PATHS = {
  experiments: ["M3 12.5v-3.5", "M7.5 12.5v-7", "M12 12.5v-10"],
  tree: [ring(4, 3, 1.5), ring(4, 12, 1.5), ring(11, 4.5, 1.5), "M4 4.5v6", "M11 6c0 3-7 2-7 4.5"],
  actions: ["M2.5 4l3.5 3.5-3.5 3.5", "M8 11.5h4.5"],
  apps: ["M2.5 2.5h4v4h-4z", "M8.5 2.5h4v4h-4z", "M2.5 8.5h4v4h-4z", "M8.5 8.5h4v4h-4z"],
  models: ["M7.5 2l5.5 3-5.5 3-5.5-3z", "M2 8l5.5 3 5.5-3", "M2 10.5l5.5 3 5.5-3"],
  reports: ["M3.5 1.5h6l2.5 2.5v9.5h-8.5z", "M5.5 6.5h4", "M5.5 9h4", "M5.5 11.5h2.5"],
  key: [ring(5, 10, 2.5), "M6.8 8.2l5.7-5.7", "M10.5 4.2l1.6 1.6", "M8.9 5.8l1 1"],
  menu: ["M2 4h11", "M2 7.5h11", "M2 11h11"],
  search: [ring(6.5, 6.5, 4), "M9.5 9.5l3.5 3.5"],
  copy: ["M5 5h7.5v7.5h-7.5z", "M10 5v-2.5h-7.5v7.5h2.5"],
  check: ["M2.5 8l3 3 7-7"],
  "chevron-down": ["M4 6l3.5 3.5 3.5-3.5"],
  "chevron-right": ["M6 4l3.5 3.5-3.5 3.5"],
  "chevron-left": ["M9 4l-3.5 3.5 3.5 3.5"],
  external: ["M8.5 2.5h4v4", "M12.5 2.5l-5.5 5.5", "M10.5 9v3.5h-8v-8h3.5"],
  close: ["M3.5 3.5l8 8", "M11.5 3.5l-8 8"],
  "theme-system": ["M2 3h11v7.5h-11z", "M5.5 13h4", "M7.5 10.5v2.5"],
  sun: [
    ring(7.5, 7.5, 2.5), "M7.5 1v1.5", "M7.5 12.5v1.5", "M1 7.5h1.5", "M12.5 7.5h1.5",
    "M2.9 2.9l1.1 1.1", "M11 11l1.1 1.1", "M2.9 12.1l1.1-1.1", "M11 4l1.1-1.1",
  ],
  moon: ["M12.5 9.5a5.5 5.5 0 0 1-7-7a5.5 5.5 0 1 0 7 7z"],
  run: [ring(7.5, 7.5, 5.5), "M6.5 5.5l3 2-3 2z"],
  app: ["M7.5 1.5l5.5 3v6l-5.5 3-5.5-3v-6z", "M2 4.5l5.5 3 5.5-3", "M7.5 7.5v6"],
  workspace: ["M1.5 3.5h4l1.5 2h6.5v7h-12z"],
  store: [
    "M2.5 4c0-1.1 2.2-2 5-2s5 .9 5 2-2.2 2-5 2-5-.9-5-2z",
    "M2.5 4v7c0 1.1 2.2 2 5 2s5-.9 5-2v-7", "M2.5 7.5c0 1.1 2.2 2 5 2s5-.9 5-2",
  ],
  page: ["M3.5 1.5h5.5l3 3v9h-8.5z", "M9 1.5v3h3"],
  command: [
    "M5.5 5.5h4v4h-4z",
    "M5.5 5.5v-1.5a1.5 1.5 0 1 0-1.5 1.5h1.5", "M9.5 5.5v-1.5a1.5 1.5 0 1 1 1.5 1.5h-1.5",
    "M5.5 9.5v1.5a1.5 1.5 0 1 1-1.5-1.5h1.5", "M9.5 9.5v1.5a1.5 1.5 0 1 0 1.5-1.5h-1.5",
  ],
  settings: [
    "M2 4h4.5", "M10.5 4h2.5", ring(8.5, 4, 1.5), "M2 11h1.5", "M7.5 11h5.5", ring(5.5, 11, 1.5),
  ],
} satisfies Record<string, string[]>;

export type IconName = keyof typeof PATHS;
export const ICON_NAMES = Object.keys(PATHS) as IconName[];

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 15 15" fill="none" stroke="currentColor"
      strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
    >
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
