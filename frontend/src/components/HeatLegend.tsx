import { fmtNum } from "../lib/format";
import { HEAT_STOPS } from "../lib/themeColors";

/** The heat ramp with its fixed scale, over the map while a period is shown:
 *  the same color means the same density of workers in every frame. */
export function HeatLegend({ max }: { max: number | undefined }) {
  const gradient = `linear-gradient(to right, ${HEAT_STOPS.map(([s, c]) => `${c} ${s * 100}%`).join(", ")})`;
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-7 left-3 w-40 rounded-lg bg-white/90 px-2 py-1.5 text-[0.65rem] leading-tight text-slate-600 shadow dark:bg-slate-900/90 dark:text-slate-300"
    >
      <div className="h-2 rounded-full" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between">
        <span>fewer</span>
        <span>more workers</span>
      </div>
      <div className="text-slate-500 dark:text-slate-400">
        Same scale every period{max ? `; one place counts in full from ${fmtNum(max)} workers` : ""}
      </div>
    </div>
  );
}
