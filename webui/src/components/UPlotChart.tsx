import { memo, useEffect, useRef, useState } from "react";
import type uPlot from "uplot";

export interface CursorInfo {
  /** Cursor position in CSS pixels inside the plot area. */
  left: number;
  top: number;
  /** The same position in data units. */
  x: number;
  y: number;
}

interface Props {
  /** Rebuilds the plot when it changes identity — memoize it. */
  options: Omit<uPlot.Options, "width">;
  /** Swapped in place (no rebuild) when it changes identity. */
  data: uPlot.AlignedData;
  /** Per curve (data slot 1..n): whether it is switched off. */
  hidden?: boolean[];
  /** Curve index to highlight, dimming the others. */
  focus?: number | null;
  onCursor?: (c: CursorInfo | null) => void;
}

/** uPlot needs a real canvas; jsdom and very old browsers get an empty frame. */
function canvasSupported(): boolean {
  return typeof window.matchMedia === "function"
    && !!document.createElement("canvas").getContext("2d");
}

function emitCursor(u: uPlot, cb?: (c: CursorInfo | null) => void) {
  if (!cb) return;
  const { left, top } = u.cursor;
  if (left == null || top == null || left < 0) cb(null);
  else cb({ left, top, x: u.posToVal(left, "x"), y: u.posToVal(top, "y") });
}

/** Thin lifecycle wrapper: create on mount (lazily loading uPlot), resize
 *  with the container, swap data in place, destroy on unmount. */
function UPlotChart({ options, data, hidden, focus = null, onCursor }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const dataRef = useRef(data);
  dataRef.current = data;
  const cursorRef = useRef(onCursor);
  cursorRef.current = onCursor;
  const shownRef = useRef<boolean[]>([]);
  // Bumped once a plot exists so the hidden/focus effects re-apply to it.
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el || !canvasSupported()) return;
    let cancelled = false;
    let plot: uPlot | null = null;
    let ro: ResizeObserver | undefined;
    import("./uplotLoader").then(({ default: UPlot }) => {
      if (cancelled) return;
      const hooks = {
        ...options.hooks,
        setCursor: [...(options.hooks?.setCursor ?? []), (u: uPlot) => emitCursor(u, cursorRef.current)],
      };
      plot = new UPlot({ ...options, width: el.clientWidth || 600, hooks }, dataRef.current, el);
      plotRef.current = plot;
      shownRef.current = [];
      setGeneration((g) => g + 1);
      if (typeof ResizeObserver !== "undefined") {
        ro = new ResizeObserver(([entry]) => {
          const width = Math.floor(entry.contentRect.width);
          if (width > 0 && width !== plot?.width) plot?.setSize({ width, height: options.height });
        });
        ro.observe(el);
      }
    });
    return () => {
      cancelled = true;
      ro?.disconnect();
      plot?.destroy();
      plotRef.current = null;
    };
  }, [options]);

  useEffect(() => {
    plotRef.current?.setData(data);
  }, [data]);

  // Only the curves whose visibility changed: each setSeries resets scales.
  useEffect(() => {
    const u = plotRef.current;
    if (!u || !hidden) return;
    hidden.forEach((off, i) => {
      if (shownRef.current[i] !== !off) u.setSeries(i + 1, { show: !off });
    });
    shownRef.current = hidden.map((off) => !off);
  }, [hidden, generation]);

  useEffect(() => {
    const u = plotRef.current;
    if (!u) return;
    if (focus === null) u.setSeries(null as unknown as number, { focus: false });
    else u.setSeries(focus + 1, { focus: true });
  }, [focus, generation]);

  return <div ref={ref} style={{ width: "100%", minHeight: options.height }} />;
}

export default memo(UPlotChart);
