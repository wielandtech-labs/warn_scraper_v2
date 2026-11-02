import { useRef, useState, type ReactNode } from "react";

import { escapeAttr, stateBadgeSnippet } from "../lib/embed";

// "Embed" trigger + modal: a copyable HTML snippet pointing at one of the
// backend's /embed/* endpoints, plus a live preview. Native <dialog> +
// showModal() gives focus trapping and Esc-to-close for free.
//
// Every snippet carries a plain <a href> back to the matching page on this
// site. That outer link is what other sites actually give us; a link inside
// an <iframe> counts for the frame's own document, not the host page.
function EmbedDialog({
  trigger,
  triggerClassName = "btn-secondary",
  heading,
  intro,
  snippet,
  rows = 5,
  preview,
}: {
  trigger: string;
  triggerClassName?: string;
  heading: string;
  intro: string;
  snippet: string;
  rows?: number;
  // Rendered only while the dialog is open, so the page doesn't fetch the
  // embed until asked.
  preview: () => ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  // Where the current click started: a text selection dragged out of the
  // textarea also ends with a click on the <dialog> itself.
  const downOnBackdrop = useRef(false);

  const show = () => {
    setOpen(true);
    dialogRef.current?.showModal();
  };
  const close = () => dialogRef.current?.close();

  const handleCopy = () => {
    navigator.clipboard.writeText(snippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <>
      <button type="button" className={triggerClassName} onClick={show}>
        {trigger}
      </button>
      <dialog
        ref={dialogRef}
        onClose={() => setOpen(false)}
        // A click on the backdrop lands on the <dialog> element itself.
        onMouseDown={(e) => (downOnBackdrop.current = e.target === e.currentTarget)}
        onClick={(e) => e.target === e.currentTarget && downOnBackdrop.current && close()}
        className="w-[min(36rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-xl backdrop:bg-slate-900/50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"
      >
        <div className="space-y-4 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">{heading}</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">{intro}</p>
            </div>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="rounded-md px-2 text-xl leading-none text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              ×
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
            <div className="flex items-center justify-between gap-2 pb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                HTML
              </span>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700"
              >
                {copied ? (
                  <span className="text-emerald-600 dark:text-emerald-400">Copied!</span>
                ) : (
                  <span>Copy code</span>
                )}
              </button>
            </div>
            <textarea
              readOnly
              value={snippet}
              rows={rows}
              onFocus={(e) => e.currentTarget.select()}
              aria-label="Embed code"
              className="w-full resize-none rounded-md border border-slate-200 bg-white p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            />
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Preview
            </span>
            {open && <div className="mt-2">{preview()}</div>}
          </div>
        </div>
      </dialog>
    </>
  );
}

export function EmbedButton({ noticeId, employer }: { noticeId: string; employer: string }) {
  const origin = window.location.origin;
  const src = `${origin}/embed/notices/${noticeId}`;
  const snippet =
    `<iframe src="${src}" title="${escapeAttr(employer)} WARN notice" ` +
    `width="100%" height="260" style="max-width:480px;border:0;color-scheme:normal" loading="lazy"></iframe>\n` +
    `<p style="font-size:12px">Source: <a href="${origin}/notices/${noticeId}">WARN Index</a></p>`;
  return (
    <EmbedDialog
      trigger="Embed"
      heading="Embed this notice"
      intro="Paste this HTML into your page or CMS. The card stays up to date."
      snippet={snippet}
      preview={() => (
        <iframe
          src={src}
          title="Embed preview"
          width="100%"
          height={260}
          className="max-w-[480px] border-0"
          // The card declares no color-scheme. In dark mode the site does, and a
          // mismatch makes the browser paint an opaque backdrop behind the frame
          // (the snippet carries the same reset for hosts with a dark scheme).
          style={{ colorScheme: "normal" }}
        />
      )}
    />
  );
}

export function StateBadgeEmbedButton({
  code,
  name,
  triggerClassName,
}: {
  code: string;
  name: string;
  triggerClassName?: string;
}) {
  const origin = window.location.origin;
  return (
    <EmbedDialog
      trigger="Embed"
      triggerClassName={triggerClassName}
      heading={`Embed the ${name} layoff badge`}
      intro={`Shows workers affected by ${name} WARN notices in the last 30 days, refreshed daily. Works in any page, README or newsletter.`}
      snippet={stateBadgeSnippet(origin, code, name)}
      rows={3}
      preview={() => (
        <img
          src={`${origin}/embed/badge/state/${code}.svg`}
          alt={`${name} WARN layoffs badge`}
          height={20}
        />
      )}
    />
  );
}
