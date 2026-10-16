import { useRef, useState } from "react";

// "Embed" button + modal for a notice: a copyable <iframe> snippet pointing at
// the backend's /embed/notices/{id} card, plus a live preview of that card.
// Native <dialog> + showModal() gives focus trapping and Esc-to-close for free.
export function EmbedButton({ noticeId, employer }: { noticeId: string; employer: string }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const origin = window.location.origin;
  const src = `${origin}/embed/notices/${noticeId}`;
  const snippet =
    `<iframe src="${src}" title="${escapeAttr(employer)} WARN notice" ` +
    `width="100%" height="260" style="max-width:480px;border:0;color-scheme:normal" loading="lazy"></iframe>\n` +
    `<p style="font-size:12px">Source: <a href="${origin}/notices/${noticeId}">WARN Index</a></p>`;

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
      <button type="button" className="btn-secondary" onClick={show}>
        Embed
      </button>
      <dialog
        ref={dialogRef}
        onClose={() => setOpen(false)}
        // A click on the backdrop lands on the <dialog> element itself.
        onClick={(e) => e.target === e.currentTarget && close()}
        className="w-[min(36rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-xl backdrop:bg-slate-900/50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"
      >
        <div className="space-y-4 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Embed this notice</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Paste this HTML into your page or CMS. The card stays up to date.
              </p>
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
              rows={5}
              onFocus={(e) => e.currentTarget.select()}
              aria-label="Embed code"
              className="w-full resize-none rounded-md border border-slate-200 bg-white p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            />
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Preview
            </span>
            {/* Mounted only while open, so the page doesn't fetch the card until asked. */}
            {open && (
              <iframe
                src={src}
                title="Embed preview"
                width="100%"
                height={260}
                className="mt-2 max-w-[480px] border-0"
                // The card declares no color-scheme. In dark mode the site does, and a
                // mismatch makes the browser paint an opaque backdrop behind the frame
                // (the snippet carries the same reset for hosts with a dark scheme).
                style={{ colorScheme: "normal" }}
              />
            )}
          </div>
        </div>
      </dialog>
    </>
  );
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}
