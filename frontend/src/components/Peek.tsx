import { Suspense, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/* A hover/focus card with a little more about the thing under the pointer --
   a state's or company's trend -- without leaving the page.

   - Opens after a short intent delay (pointer or keyboard focus), closes on
     leave, blur, Escape or scroll. Content mounts only while open, so its
     queries fire on intent, not on page load.
   - Portalled to <body> with fixed positioning: list rows live inside
     overflow containers (DataTable scrolls horizontally) that would clip an
     absolutely positioned card.
   - Mouse only: a tap's emulated mouseenter would pop a sticky card on
     phones, so touch keeps the trigger a plain link.
   - Content may be lazy (see peeks.ts): bodies stay out of the entry chunk. */

const OPEN_DELAY = 300;
const CLOSE_DELAY = 120;
const WIDTH = 256;

export function Peek({ children, content }: { children: ReactNode; content: () => ReactNode }) {
  const triggerRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  // `top` places the card below the trigger; `bottom` (from the viewport's
  // bottom edge) above it, whatever the card's height turns out to be.
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number } | null>(null);
  const id = useId();

  function place() {
    const r = triggerRef.current?.getBoundingClientRect();
    if (!r) return;
    const left = Math.min(Math.max(8, r.left), window.innerWidth - WIDTH - 8);
    // Below the trigger, or above it when there's little room below.
    if (r.bottom + 240 > window.innerHeight) setPos({ bottom: window.innerHeight - r.top + 6, left });
    else setPos({ top: r.bottom + 6, left });
  }
  function openSoon() {
    clearTimeout(timer.current);
    timer.current = setTimeout(place, OPEN_DELAY);
  }
  function closeSoon() {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setPos(null), CLOSE_DELAY);
  }
  function keep() {
    clearTimeout(timer.current);
  }

  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("scroll", close, { passive: true, capture: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, { capture: true });
      window.removeEventListener("keydown", onKey);
    };
  }, [pos]);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <span
      ref={triggerRef}
      className="inline"
      onPointerEnter={(e) => e.pointerType === "mouse" && openSoon()}
      onPointerLeave={(e) => e.pointerType === "mouse" && closeSoon()}
      onFocus={openSoon}
      onBlur={closeSoon}
      aria-describedby={pos ? id : undefined}
    >
      {children}
      {pos &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            onMouseEnter={keep}
            onMouseLeave={closeSoon}
            style={{ top: pos.top, bottom: pos.bottom, left: pos.left, width: WIDTH }}
            className="fixed z-[1200] rounded-xl border border-slate-200 bg-white p-4 text-left text-sm shadow-xl dark:border-slate-700 dark:bg-slate-900"
          >
            <Suspense fallback={<div className="h-28 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />}>
              {content()}
            </Suspense>
          </div>,
          document.body,
        )}
    </span>
  );
}
