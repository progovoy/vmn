import { useEffect, useState } from "react";

/** Whether the tab is in the foreground: a hidden tab nobody is looking at
 *  has no reason to keep asking the server. */
export function useTabVisible(): boolean {
  const [visible, setVisible] = useState(
    () => document.visibilityState !== "hidden"
  );

  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  return visible;
}
