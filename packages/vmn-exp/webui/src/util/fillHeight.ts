/** How tall a scroll box (the board's table, the facet sidebar) may be so
 *  the page around it fits its viewport: the page then never scrolls as
 *  well, and each column is one scroll. Pure. */
export const MIN_FILL_HEIGHT = 240;

export interface PageBox {
  /** The page's scroll container's visible height. */
  viewport: number;
  /** The box's offset from the top of the scrolled content. */
  elTop: number;
  /** What its column holds below it, the page's bottom padding included. */
  below: number;
}

export function fillHeight({ viewport, elTop, below }: PageBox): number {
  return Math.max(MIN_FILL_HEIGHT, Math.floor(viewport - elTop - below));
}
