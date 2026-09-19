/** Largest-Triangle-Three-Buckets (LTTB) downsampling.
 *
 *  Reduces a time-series to `target` points while preserving its visual shape.
 *  Returns the original array unchanged when its length is already <= target.
 *
 *  Reference: Sveinn Steinarsson, "Downsampling Time Series for Visual
 *  Representation", MSc thesis, University of Iceland, 2013. */
export interface XY {
  x: number;
  y: number;
}

export function downsampleLTTB(data: XY[], target: number): XY[] {
  const n = data.length;
  if (n <= target || n <= 2) return data;
  if (target <= 0) return [];
  if (target === 1) return [data[0]];
  if (target === 2) return [data[0], data[n - 1]];

  const out: XY[] = [data[0]];
  const bucketSize = (n - 2) / (target - 2);

  let prev = 0; // index of the last selected point

  for (let i = 1; i < target - 1; i++) {
    const bucketStart = Math.floor((i - 1) * bucketSize) + 1;
    const bucketEnd = Math.min(Math.floor(i * bucketSize) + 1, n - 1);

    // average of the *next* bucket (look-ahead)
    const nextStart = Math.floor(i * bucketSize) + 1;
    const nextEnd = Math.min(Math.floor((i + 1) * bucketSize) + 1, n - 1);
    let avgX = 0;
    let avgY = 0;
    const nextLen = nextEnd - nextStart;
    for (let j = nextStart; j < nextEnd; j++) {
      avgX += data[j].x;
      avgY += data[j].y;
    }
    avgX /= nextLen || 1;
    avgY /= nextLen || 1;

    // pick the point in the current bucket that forms the largest triangle
    let maxArea = -1;
    let bestIdx = bucketStart;
    const px = data[prev].x;
    const py = data[prev].y;

    for (let j = bucketStart; j < bucketEnd; j++) {
      const area = Math.abs(
        (px - avgX) * (data[j].y - py) - (px - data[j].x) * (avgY - py)
      );
      if (area > maxArea) {
        maxArea = area;
        bestIdx = j;
      }
    }

    out.push(data[bestIdx]);
    prev = bestIdx;
  }

  out.push(data[n - 1]);
  return out;
}
