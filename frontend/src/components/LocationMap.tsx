import { useTheme } from "../hooks/useTheme";
import { TILE_LAYERS } from "../lib/themeColors";

const TILE = 256;
const ZOOM = 10;
// Tiles either side of the centre tile: 5 x 3 covers a 1280-wide, 260-tall
// frame wherever the point falls inside its tile.
const SPAN_X = 2;
const SPAN_Y = 1;

/* A static map of one point: the same raster tiles the Leaflet maps use,
   laid out as plain <img>s around the location, with a pin. One notice has
   one place -- panning and zooming it isn't worth shipping Leaflet (and its
   CSS) to every notice page. */
export function LocationMap({
  lat,
  lon,
  label,
  height = 220,
}: {
  lat: number;
  lon: number;
  label: string;
  height?: number;
}) {
  const { resolved } = useTheme();
  const tiles = TILE_LAYERS[resolved];
  // Web-Mercator tile coordinates (fractional) of the point.
  const n = 2 ** ZOOM;
  const fx = ((lon + 180) / 360) * n;
  const rad = (lat * Math.PI) / 180;
  const fy = ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n;
  const cx = Math.floor(fx);
  const cy = Math.floor(fy);

  const imgs = [];
  for (let dx = -SPAN_X; dx <= SPAN_X; dx++) {
    for (let dy = -SPAN_Y; dy <= SPAN_Y; dy++) {
      const x = cx + dx;
      const y = cy + dy;
      if (y < 0 || y >= n) continue;
      const src = tiles.url
        .replace("{s}", "a")
        .replace("{z}", String(ZOOM))
        .replace("{x}", String(((x % n) + n) % n))
        .replace("{y}", String(y))
        .replace("{r}", "");
      imgs.push(
        <img
          key={`${dx},${dy}`}
          src={src}
          alt=""
          width={TILE}
          height={TILE}
          loading="lazy"
          decoding="async"
          draggable={false}
          className="absolute max-w-none select-none"
          style={{
            left: `calc(50% + ${Math.round((x - fx) * TILE)}px)`,
            top: `calc(50% + ${Math.round((y - fy) * TILE)}px)`,
          }}
        />,
      );
    }
  }

  return (
    <figure className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
      <div
        role="img"
        aria-label={`Map of ${label}`}
        className="relative overflow-hidden bg-slate-100 dark:bg-slate-800"
        style={{ height }}
      >
        {imgs}
        <span aria-hidden className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <span className="hero-pulse absolute inset-0 rounded-full bg-brand/40" />
          <span className="relative block h-3.5 w-3.5 rounded-full border-2 border-white bg-brand shadow" />
        </span>
      </div>
      <figcaption
        className="bg-white px-2 py-1 text-right text-[0.6rem] text-slate-500 dark:bg-slate-900 dark:text-slate-400 [&_a]:underline"
        // Attribution strings are our own constants (themeColors.ts).
        dangerouslySetInnerHTML={{ __html: tiles.attribution }}
      />
    </figure>
  );
}
