import { useCallback, useState } from "react";

/** A value its owner may control: *value* wins when defined, else local
 *  state seeded from *defaultValue*. Every change is reported to *onChange*. */
export function useControllable<T>(
  value: T | undefined, defaultValue: T, onChange?: (v: T) => void,
): [T, (v: T) => void] {
  const [own, setOwn] = useState(defaultValue);
  const controlled = value !== undefined;
  const set = useCallback((v: T) => {
    if (!controlled) setOwn(v);
    onChange?.(v);
  }, [controlled, onChange]);
  return [controlled ? value : own, set];
}
