/* A tiny trend line in plain SVG -- for hover panels and KPI tiles, where
   pulling in Recharts (~100 KB gz) for a 40px glyph would be absurd. Nulls
   break the line. Purely decorative: callers state the numbers in text. */
export function Sparkline({
  values,
  color,
  height = 40,
  className = "",
}: {
  values: (number | null | undefined)[];
  color: string;
  height?: number;
  className?: string;
}) {
  const nums = values.filter((v): v is number => typeof v === "number");
  if (nums.length < 2) return <div style={{ height }} className={className} />;
  const w = 100;
  const max = Math.max(...nums);
  const min = Math.min(0, ...nums);
  const span = max - min || 1;
  const x = (i: number) => (values.length === 1 ? 0 : (i / (values.length - 1)) * w);
  const y = (v: number) => height - 2 - ((v - min) / span) * (height - 4);

  // Contiguous non-null runs become separate segments.
  const runs: { i: number; v: number }[][] = [];
  values.forEach((v, i) => {
    if (typeof v !== "number") {
      runs.push([]);
      return;
    }
    if (runs.length === 0) runs.push([]);
    runs[runs.length - 1].push({ i, v });
  });
  const segments = runs.filter((r) => r.length > 1);
  const line = (r: { i: number; v: number }[]) =>
    r.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(2)},${y(p.v).toFixed(2)}`).join("");

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      aria-hidden
      className={`block w-full ${className}`}
      style={{ height }}
    >
      {segments.map((r, k) => (
        <g key={k}>
          <path
            d={`${line(r)}L${x(r[r.length - 1].i).toFixed(2)},${height}L${x(r[0].i).toFixed(2)},${height}Z`}
            fill={color}
            fillOpacity={0.12}
          />
          <path
            d={line(r)}
            fill="none"
            stroke={color}
            strokeWidth={1.75}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
        </g>
      ))}
    </svg>
  );
}
