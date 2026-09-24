import { useEffect, useRef, useState, type ReactNode } from "react";

/** How far outside the viewport a chart starts mounting, so scrolling never
 *  reveals an empty frame. */
const ROOT_MARGIN = "200px";

/** Mounts *children* once scrolled near the viewport and keeps them mounted.
 *  Holds a same-height placeholder until then, so the page doesn't jump.
 *  Without IntersectionObserver it renders straight away. */
export default function LazyMount({ height, children }: { height: number; children: ReactNode }) {
  const [shown, setShown] = useState(() => typeof IntersectionObserver === "undefined");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (shown || !ref.current) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setShown(true);
        io.disconnect();
      }
    }, { rootMargin: ROOT_MARGIN });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [shown]);

  return <div ref={ref} style={{ minHeight: height }}>{shown && children}</div>;
}
