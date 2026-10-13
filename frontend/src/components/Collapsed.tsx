import { useEffect, useRef, useState, type ReactNode } from "react";

/* Shows the first screenful of long content behind a fade, with a button to
   expand it. The report runs to dozens of table rows; most visitors want the
   summary, and the rest is one click away. */
export function Collapsed({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  // `inert` keeps the clipped part out of the tab order until expanded.
  // Set through the DOM: React 18 doesn't know the attribute.
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (body.current) body.current.inert = !open;
  }, [open]);
  return (
    <div>
      <div className={open ? "" : "relative max-h-[26rem] overflow-hidden"}>
        <div ref={body}>{children}</div>
        {!open && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white dark:from-slate-900"
          />
        )}
      </div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="mt-3 text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
      >
        {open ? "Show less" : `${label} ↓`}
      </button>
    </div>
  );
}
