import { useCallback, useEffect, useRef, useState } from "react";
import { tFromY, type Brushes } from "../util/parallelData";

/** A drag shorter than this is a click: it clears that axis's brush. */
const MIN_BRUSH_PX = 3;

/** Per-axis brushes, several at once. A drag listens on the window (so it
 *  survives leaving the axis), redraws at most once per animation frame, and
 *  commits synchronously on mouseup. */
export function useAxisBrush(
  toY: (clientY: number) => number, top: number, plotH: number,
  onCommit: (brushes: Brushes) => void,
) {
  const [brushes, setBrushes] = useState<Brushes>(() => new Map());
  const committed = useRef<Brushes>(brushes);
  const stopDrag = useRef<(() => void) | null>(null);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;

  useEffect(() => () => stopDrag.current?.(), []);

  const onStart = useCallback((dim: number, clientY: number) => {
    stopDrag.current?.();
    const y0 = toY(clientY);
    let y1 = y0;
    let frame = 0;
    const withRange = () => {
      const next = new Map(committed.current);
      next.set(dim, [tFromY(y0, top, plotH), tFromY(y1, top, plotH)]);
      return next;
    };
    const move = (e: MouseEvent) => {
      y1 = toY(e.clientY);
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; setBrushes(withRange()); });
    };
    const up = () => {
      stop();
      const next = withRange();
      if (Math.abs(y1 - y0) < MIN_BRUSH_PX) next.delete(dim);
      committed.current = next;
      setBrushes(next);
      commitRef.current(next);
    };
    function stop() {
      cancelAnimationFrame(frame);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      stopDrag.current = null;
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    stopDrag.current = stop;
  }, [toY, top, plotH]);

  const clear = useCallback(() => {
    stopDrag.current?.();
    committed.current = new Map();
    setBrushes(committed.current);
  }, []);

  return { brushes, onStart, clear };
}
