import { US_MAP_VIEWBOX, US_STATE_PATHS } from "./usStatePaths";

// Per-state bounding boxes and label anchors in US_MAP_VIEWBOX space, measured
// once from the real path geometry by the browser (getBBox / isPointInFill)
// and cached for the session. Measuring beats a hand-kept table: it can't
// drift from the path data, and it costs ~51 cheap DOM calls once.

export interface StateGeometry {
  box: { x: number; y: number; width: number; height: number };
  /** A point inside the shape, near its bbox centre (Michigan's and
   *  Florida's bbox centres fall in water). */
  anchor: { x: number; y: number };
}

let cache: Record<string, StateGeometry> | null = null;

export function stateGeometry(): Record<string, StateGeometry> {
  if (cache) return cache;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", US_MAP_VIEWBOX);
  // Laid out (so getBBox works) but invisible and size-less.
  svg.style.cssText = "position:absolute;width:0;height:0;visibility:hidden;pointer-events:none";
  document.body.appendChild(svg);
  const out: Record<string, StateGeometry> = {};
  try {
    for (const [code, d] of Object.entries(US_STATE_PATHS)) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
      const b = path.getBBox();
      out[code] = {
        box: { x: b.x, y: b.y, width: b.width, height: b.height },
        anchor: insidePoint(path, b),
      };
    }
  } finally {
    svg.remove();
  }
  cache = out;
  return out;
}

/** Bbox centre if it's inside the fill, else the nearest inside point on a
 *  coarse grid. Falls back to the centre where isPointInFill is missing. */
function insidePoint(path: SVGPathElement, b: DOMRect): { x: number; y: number } {
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  if (typeof path.isPointInFill !== "function") return { x: cx, y: cy };
  const inside = (x: number, y: number) => path.isPointInFill(new DOMPoint(x, y));
  if (inside(cx, cy)) return { x: cx, y: cy };
  const steps = 12;
  let best: { x: number; y: number } | null = null;
  let bestDist = Infinity;
  for (let i = 1; i < steps; i++) {
    for (let j = 1; j < steps; j++) {
      const x = b.x + (b.width * i) / steps;
      const y = b.y + (b.height * j) / steps;
      const dist = (x - cx) ** 2 + (y - cy) ** 2;
      if (dist < bestDist && inside(x, y)) {
        best = { x, y };
        bestDist = dist;
      }
    }
  }
  return best ?? { x: cx, y: cy };
}
