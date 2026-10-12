import { useEffect } from "react";

/** Keep `document.title` at *title*. */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title;
  }, [title]);
}
