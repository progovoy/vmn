import { useState } from "react";
import type { MediaItem } from "../types";
import { ImagePreview } from "./ArtifactPreview";

/** A range input over a key's logged steps (by index); hidden for one step. */
export function StepSlider({ label, count, index, onChange }: {
  label: string; count: number; index: number; onChange: (i: number) => void;
}) {
  if (count < 2) return null;
  return (
    <input
      type="range" className="media-step" aria-label={label}
      min={0} max={count - 1} value={index}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

function ImageKey({ name, items, url }: {
  name: string; items: MediaItem[]; url: (path: string) => string;
}) {
  // null follows the newest step as a live run logs more.
  const [picked, setPicked] = useState<number | null>(null);
  const index = Math.min(picked ?? items.length - 1, items.length - 1);
  const item = items[index];
  return (
    <figure className="media-tile">
      <div className="media-tile-head">
        <span className="mono">{name}</span>
        <span className="muted">step {item.step}</span>
      </div>
      <ImagePreview key={item.path} url={url(item.path)} name={`${name} @ ${item.step}`} />
      {item.caption && <figcaption>{item.caption}</figcaption>}
      <StepSlider label={`step of ${name}`} count={items.length} index={index} onChange={setPicked} />
    </figure>
  );
}

/** A grid of logged images, one tile per key with a step slider. */
export default function MediaImages({ media, url }: {
  media: Record<string, MediaItem[]>; url: (path: string) => string;
}) {
  const keys = Object.keys(media).filter((k) => media[k].length > 0);
  if (keys.length === 0) return null;
  return (
    <div className="media-grid">
      {keys.map((k) => <ImageKey key={k} name={k} items={media[k]} url={url} />)}
    </div>
  );
}
