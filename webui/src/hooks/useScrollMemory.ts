import { useCallback, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

/** Scroll offsets by history entry, for this tab's lifetime. */
const offsets = new Map<string, number>();

/** The scroll offset this history entry last had (0 the first time), and a
 *  saver for the current one — so Back lands where the user left off. */
export function useScrollMemory() {
  const { key } = useLocation();
  const keyRef = useRef(key);
  keyRef.current = key;
  const [initial] = useState(() => offsets.get(key) ?? 0);
  const save = useCallback((offset: number) => {
    offsets.set(keyRef.current, offset);
  }, []);
  return { initial, save };
}
