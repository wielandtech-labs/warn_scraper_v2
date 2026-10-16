import { Fragment, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { STATE_NAMES } from "../lib/format";
import { Figure, Figures } from "./Figures";

/**
 * Renderer for the constrained markdown produced by warn_v2/reports/render.py:
 * #/## headings, pipe tables (with an alignment row and \| cell escapes),
 * whole-line _italic_ meta lines, --- rules, - lists, **bold**, and plain
 * paragraphs. Everything is built as React elements — no raw HTML is ever
 * injected — so the LLM-authored narrative can't smuggle markup, and the
 * &lt;/&gt; entities the backend escapes are shown as literal characters.
 *
 * A real markdown library would pull in a parser + sanitizer dependency the
 * frontend can't add without regenerating package-lock.json locally (no Node
 * toolchain on the dev machine); this covers the report format exactly.
 *
 * Presentation follows the site's editorial theme and recognises the
 * generator's recurring shapes, so every report (national, state, industry)
 * gets them without per-report code:
 * - the headline "**A: x · B: y**" line becomes a strip of signed figures;
 * - change columns (Δ, Δ%) are signed and coloured: a rise in job losses is
 *   bad news (brand red ▲), a fall muted (▼);
 * - "Workers affected" columns in ranked tables get inline bars;
 * - the monthly-trend table is drawn as this-year vs last-year columns and
 *   the model-outlook table as estimate-and-band rows, each with its table
 *   one click away.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "para"; text: string; meta: boolean }
  | { kind: "table"; header: string[]; align: ("left" | "right")[]; rows: string[][] }
  | { kind: "list"; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "hr" };

/** Split a table row on unescaped pipes; `\|` inside a cell is a literal pipe. */
function splitRow(line: string): string[] {
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === "\\" && line[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (ch === "|") {
      cells.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  // The generator writes leading/trailing pipes, which split into empty
  // edge cells — drop those.
  if (cells.length && cells[0].trim() === "") cells.shift();
  if (cells.length && cells[cells.length - 1].trim() === "") cells.pop();
  return cells.map((c) => c.trim());
}

function parseTable(lines: string[]): Block {
  const rows = lines.map(splitRow);
  const isAlignRow = rows.length >= 2 && rows[1].every((c) => /^:?-{3,}:?$/.test(c));
  const header = rows[0];
  const align = isAlignRow
    ? rows[1].map((c): "left" | "right" => (c.endsWith(":") ? "right" : "left"))
    : header.map((): "left" => "left");
  return { kind: "table", header, align, rows: rows.slice(isAlignRow ? 2 : 1) };
}

function parseBlocks(md: string): Block[] {
  const lines = md.split(/\r?\n/);
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ kind: "heading", level: h[1].length, text: h[2] });
      i++;
      continue;
    }
    if (/^-{3,}\s*$/.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }
    if (line.trimStart().startsWith("|")) {
      const tbl: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith("|")) {
        tbl.push(lines[i].trim());
        i++;
      }
      blocks.push(parseTable(tbl));
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "list", items });
      continue;
    }
    // Blockquote — the industry scorecards' coverage caveat.
    if (line.trimStart().startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith(">")) {
        quote.push(lines[i].trimStart().replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ kind: "quote", text: quote.join(" ").trim() });
      continue;
    }
    // Paragraph: join consecutive non-blank lines that aren't another block.
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trimStart().startsWith("|") &&
      !lines[i].trimStart().startsWith(">") &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^-{3,}\s*$/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i])
    ) {
      para.push(lines[i].trim());
      i++;
    }
    const text = para.join(" ").trim();
    // Whole-paragraph _italics_ are the report's meta/footnote lines.
    const meta = text.length > 2 && text.startsWith("_") && text.endsWith("_");
    blocks.push({ kind: "para", text: meta ? text.slice(1, -1) : text, meta });
  }
  return blocks;
}

function unescapeEntities(s: string): string {
  return s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

/** Text with **bold** spans as React nodes; everything else stays plain text. */
function inline(text: string): ReactNode {
  const parts = unescapeEntities(text).split(/\*\*([^*]+)\*\*/g);
  if (parts.length === 1) return parts[0];
  return parts.map((p, i) =>
    i % 2 === 1 ? (
      <strong key={i} className="font-semibold text-slate-900 dark:text-slate-100">
        {p}
      </strong>
    ) : (
      <Fragment key={i}>{p}</Fragment>
    ),
  );
}

// A cell of digits/sign/percent reads better in tabular figures.
const NUMERIC_CELL = /^[+\-−]?[\d,.]+%?$/;
// "31,185 (18,653–43,717)": an estimate with its band.
const BAND_CELL = /^([\d,.]+)\s*\(([\d,.]+)[–-]([\d,.]+)\)$/;
const STATE_BY_NAME = new Map(Object.entries(STATE_NAMES).map(([code, name]) => [name, code]));

/** Parsed figure, 0 for anything non-numeric ("—", blank) so bars and
 *  scales never see NaN. */
const num = (s: string | undefined) => {
  const n = Number((s ?? "").replace(/[,%+]/g, "").replace(/^−/, "-"));
  return Number.isFinite(n) ? n : 0;
};


/** Sign of a change cell: 1 rise, -1 fall, 0 flat/unknown. */
function signOf(cell: string): number {
  const t = cell.trim();
  if (/^[-−]/.test(t)) return -1;
  const n = Number(t.replace(/[+,%]/g, ""));
  return Number.isFinite(n) && n > 0 ? 1 : 0;
}

/** A change value, signed and coloured: a rise in job losses is bad news. */
function Delta({ cell }: { cell: string }) {
  const s = signOf(cell);
  if (!NUMERIC_CELL.test(cell.trim())) return <>{inline(cell)}</>;
  return (
    <span
      className={`whitespace-nowrap tabular-nums ${
        s > 0 ? "text-brand dark:text-brand-dark" : s < 0 ? "text-slate-500 dark:text-slate-400" : ""
      }`}
    >
      <span aria-hidden className="mr-0.5 text-[0.65em]">
        {s > 0 ? "▲" : s < 0 ? "▼" : ""}
      </span>
      {cell.replace(/^-/, "−")}
    </span>
  );
}

const isDeltaHeader = (h: string) => /^(Δ|∆)|\bvs\b|change/i.test(h);

/** The bold "A: x · B: y · C: z" headline as a strip of figures. */
function headlineParts(text: string): { label: string; value: string }[] | null {
  const m = /^\*\*(.+)\*\*$/.exec(text.trim());
  if (!m) return null;
  const parts = m[1].split(/\s+·\s+/).map((p) => {
    const i = p.lastIndexOf(":");
    return i > 0 ? { label: p.slice(0, i).trim(), value: p.slice(i + 1).trim() } : null;
  });
  if (parts.length < 2 || parts.some((p) => !p)) return null;
  return parts as { label: string; value: string }[];
}

function HeadlineFigures({ parts }: { parts: { label: string; value: string }[] }) {
  return (
    <Figures cols={parts.length >= 3 ? 3 : 2}>
      {parts.map((p) => {
        const s = signOf(p.value);
        return (
          <Figure
            key={p.label}
            label={unescapeEntities(p.label)}
            accent={s > 0}
            value={
              <>
                <span aria-hidden className="mr-1 text-sm">
                  {s > 0 ? "▲" : s < 0 ? "▼" : ""}
                </span>
                {p.value.replace(/^-/, "−")}
              </>
            }
          />
        );
      })}
    </Figures>
  );
}

/** "Generated … · Current window … · …" as a quiet row of chips. */
function MetaChips({ text }: { text: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {text.split(/\s+·\s+/).map((part) => (
        <span
          key={part}
          className="rounded-full border border-slate-200 px-2.5 py-0.5 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400"
        >
          {inline(part)}
        </span>
      ))}
    </div>
  );
}

function ShowTable({ children }: { children: ReactNode }) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">
        Show table
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

/* Monthly trend: this year's workers as solid columns, the same month last
   year as an outline behind them -- the comparison the table makes, at a
   glance. Notices stay in the table. */
function MonthlyChart({ header, rows }: { header: string[]; rows: string[][] }) {
  const cur = header.findIndex((h) => /workers affected/i.test(h));
  const prev = header.findIndex((h) => /last y/i.test(h));
  const data = rows.map((r) => ({ month: r[0], cur: num(r[cur]), prev: num(r[prev]) }));
  const max = Math.max(1, ...data.flatMap((d) => [d.cur, d.prev]));
  const label = (m: string) => {
    const d = new Date(`${m}-01T00:00:00Z`);
    if (Number.isNaN(d.getTime())) return m;
    const mon = d.toLocaleDateString(undefined, { month: "short", timeZone: "UTC" });
    return d.getUTCMonth() === 0 ? `${mon} ’${String(d.getUTCFullYear()).slice(2)}` : mon;
  };
  return (
    <figure>
      <div className="flex h-36 items-end gap-1.5" role="img" aria-label="Workers affected by month, this year against the same month last year">
        {data.map((d) => (
          <div
            key={d.month}
            className="relative flex h-full flex-1 items-end"
            title={`${d.month}: ${d.cur.toLocaleString()} workers (same month last year ${d.prev.toLocaleString()})`}
          >
            <div
              aria-hidden
              className="absolute inset-x-0 bottom-0 rounded-t-sm border border-dashed border-slate-400 dark:border-slate-500"
              style={{ height: `${(d.prev / max) * 100}%` }}
            />
            <div
              aria-hidden
              className="absolute inset-x-[18%] bottom-0 rounded-t-sm bg-brand/80"
              style={{ height: `${(d.cur / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div aria-hidden className="mt-1 flex gap-1.5 border-t border-slate-200 pt-1 dark:border-slate-800">
        {data.map((d) => (
          <div key={d.month} className="flex-1 text-center text-[0.6rem] text-slate-500 dark:text-slate-400">
            {label(d.month)}
          </div>
        ))}
      </div>
      <figcaption className="mt-2 flex flex-wrap gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-brand/80" /> Workers affected
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-slate-400" /> Same month last year
        </span>
      </figcaption>
    </figure>
  );
}

/* Model outlook: each month's estimate as a dot on its 80% band, on one
   shared scale -- the uncertainty the table spells out in parentheses. */
function BandChart({ header, rows }: { header: string[]; rows: string[][] }) {
  // Prefer the workers column; fall back to the last band column.
  const bandCols = header.map((_, j) => j).filter((j) => rows.every((r) => BAND_CELL.test(r[j] ?? "")));
  const col = bandCols.find((j) => /workers/i.test(header[j])) ?? bandCols[bandCols.length - 1];
  const data = rows.map((r) => {
    const m = BAND_CELL.exec(r[col])!;
    return { label: r[0], est: num(m[1]), lo: num(m[2]), hi: num(m[3]) };
  });
  const max = Math.max(1, ...data.map((d) => d.hi));
  const x = (v: number) => `${(v / max) * 100}%`;
  return (
    <figure>
      <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">
        {header[col].replace(/\s*\(.*\)$/, "")} — estimate and 80% band
      </p>
      <ul className="space-y-1.5" role="img" aria-label={`${header[col]} by month: model estimate with 80% band`}>
        {data.map((d) => (
          <li key={d.label} className="grid grid-cols-[4.5rem_1fr_4.5rem] items-center gap-3 text-xs">
            <span className="tabular-nums text-slate-600 dark:text-slate-400">{d.label}</span>
            <span className="relative h-4">
              <span className="absolute inset-x-0 top-1/2 h-px bg-slate-100 dark:bg-slate-800" />
              <span
                className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-brand/25"
                style={{ left: x(d.lo), width: `calc(${x(d.hi)} - ${x(d.lo)})` }}
              />
              <span
                className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand dark:border-slate-900"
                style={{ left: x(d.est) }}
              />
            </span>
            <span className="text-right font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {d.est.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function DataTable({ b }: { b: Extract<Block, { kind: "table" }> }) {
  // Ranked "where it's shifting" tables: bar the workers column, link states.
  const ranked = b.header.some(isDeltaHeader);
  const workersCol = ranked ? b.header.findIndex((h) => /^workers affected$/i.test(h)) : -1;
  const barMax =
    workersCol >= 0 ? Math.max(1, ...b.rows.map((r) => num(r[workersCol]))) : 1;
  // Only a by-state table's first column holds state names; county tables
  // can hold "Delaware" or "Washington" counties.
  const linkStates = /^state$/i.test(b.header[0] ?? "");
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-200 text-left text-[0.65rem] uppercase tracking-[0.1em] text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <tr>
            {b.header.map((cell, j) => (
              <th
                key={j}
                className={`px-2 pb-2 pt-1 font-semibold ${b.align[j] === "right" ? "text-right" : ""}`}
              >
                {inline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {b.rows.map((row, j) => (
            <tr key={j} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
              {row.map((cell, k) => {
                const code = k === 0 && linkStates ? STATE_BY_NAME.get(cell) : undefined;
                return (
                  <td
                    key={k}
                    className={`px-2 py-1.5 align-top ${b.align[k] === "right" ? "text-right" : ""} ${
                      NUMERIC_CELL.test(cell) ? "tabular-nums" : ""
                    } ${k === 0 ? "font-medium text-slate-900 dark:text-slate-100" : ""}`}
                  >
                    {code ? (
                      <Link
                        to="/states/$state"
                        params={{ state: code }}
                        className="hover:text-sky-700 hover:underline dark:hover:text-sky-400"
                      >
                        {cell}
                      </Link>
                    ) : isDeltaHeader(b.header[k] ?? "") ? (
                      <Delta cell={cell} />
                    ) : k === workersCol && NUMERIC_CELL.test(cell) ? (
                      <span className="inline-flex items-center justify-end gap-2 tabular-nums">
                        <span
                          aria-hidden
                          className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-slate-100 sm:block dark:bg-slate-800"
                        >
                          <span
                            className="block h-full rounded-full bg-brand/70"
                            style={{ width: `${Math.max(3, (num(cell) / barMax) * 100)}%` }}
                          />
                        </span>
                        {cell}
                      </span>
                    ) : (
                      inline(cell)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TableBlock({ b }: { b: Extract<Block, { kind: "table" }> }) {
  const monthly =
    /^month$/i.test(b.header[0] ?? "") &&
    b.header.some((h) => /workers affected/i.test(h)) &&
    b.header.some((h) => /last y/i.test(h)) &&
    b.rows.length >= 3;
  const banded =
    /^month$/i.test(b.header[0] ?? "") &&
    b.rows.length >= 2 &&
    b.header.some((_, j) => j > 0 && b.rows.every((r) => BAND_CELL.test(r[j] ?? "")));
  if (monthly || banded) {
    return (
      <div>
        {monthly ? <MonthlyChart header={b.header} rows={b.rows} /> : <BandChart header={b.header} rows={b.rows} />}
        <ShowTable>
          <DataTable b={b} />
        </ShowTable>
      </div>
    );
  }
  return <DataTable b={b} />;
}

/** Drop each `## <title>` section in `titles`, up to the next H1/H2. */
function withoutSections(blocks: Block[], titles: string[]): Block[] {
  let skipping = false;
  return blocks.filter((b) => {
    if (b.kind === "heading" && b.level <= 2) skipping = titles.includes(b.text.trim());
    return !skipping;
  });
}

/** Move the headline-figures line up to just after the generation stamp,
 *  so it is the first thing a collapsed report shows. */
function headlineFirst(blocks: Block[]): Block[] {
  const from = blocks.findIndex((b) => b.kind === "para" && !b.meta && headlineParts(b.text));
  if (from < 0) return blocks;
  const rest = blocks.filter((_, i) => i !== from);
  const stamp = rest.findIndex((b) => b.kind === "para" && b.meta);
  const firstSection = rest.findIndex((b) => b.kind === "heading" && b.level === 2);
  // Only a stamp ahead of the first section is the generation stamp.
  const to = stamp >= 0 && (firstSection < 0 || stamp < firstSection) ? stamp + 1 : 0;
  return [...rest.slice(0, to), blocks[from], ...rest.slice(to)];
}

export function ReportMarkdown({
  markdown,
  skipH1 = false,
  leadWithHeadline = false,
  skipSections = [],
}: {
  markdown: string;
  /** Drop the report's H1 when the surrounding card already provides context. */
  skipH1?: boolean;
  /** Show the "**A: x · B: y**" figures strip first, ahead of the sections. */
  leadWithHeadline?: boolean;
  /** `##` section titles to leave out, when the page already shows them. */
  skipSections?: string[];
}) {
  let blocks = parseBlocks(markdown);
  if (skipSections.length) blocks = withoutSections(blocks, skipSections);
  if (leadWithHeadline) blocks = headlineFirst(blocks);
  let sawMeta = false;
  let sawSection = false;
  return (
    <div className="space-y-4 text-[0.94rem] leading-7 text-slate-700 dark:text-slate-300">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "heading": {
            if (b.level === 1) {
              if (skipH1) return null;
              return (
                <h3 key={i} className="font-display text-2xl font-semibold leading-tight text-slate-900 dark:text-slate-50">
                  {inline(b.text)}
                </h3>
              );
            }
            if (b.level > 2) {
              return (
                <h5 key={i} className="pt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {inline(b.text)}
                </h5>
              );
            }
            // Sections open with a hairline rule, as the site's pages do.
            const first = !sawSection;
            sawSection = true;
            return (
              <h4
                key={i}
                className={`font-display text-xl font-semibold leading-snug text-slate-900 dark:text-slate-50 ${
                  first ? "pt-2" : "mt-8 border-t border-slate-200 pt-6 dark:border-slate-800"
                }`}
              >
                {inline(b.text)}
              </h4>
            );
          }
          case "hr":
            return <hr key={i} className="!mt-8 border-slate-200 dark:border-slate-800" />;
          case "quote":
            return (
              <blockquote
                key={i}
                className="rounded-r-lg border-l-4 border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
              >
                {inline(b.text)}
              </blockquote>
            );
          case "list":
            return (
              <ul key={i} className="space-y-2">
                {b.items.map((item, j) => (
                  <li key={j} className="flex gap-3">
                    <span aria-hidden className="mt-[0.7rem] h-1.5 w-3 shrink-0 rounded-full bg-brand" />
                    <span>{inline(item)}</span>
                  </li>
                ))}
              </ul>
            );
          case "table":
            return <TableBlock key={i} b={b} />;
          case "para": {
            if (b.meta) {
              // The first meta line is the report's generation/window stamp.
              if (!sawMeta && !sawSection) {
                sawMeta = true;
                return <MetaChips key={i} text={b.text} />;
              }
              return (
                <p key={i} className="text-xs italic leading-relaxed text-slate-500 dark:text-slate-400">
                  {inline(b.text)}
                </p>
              );
            }
            const parts = headlineParts(b.text);
            if (parts) return <HeadlineFigures key={i} parts={parts} />;
            return <p key={i}>{inline(b.text)}</p>;
          }
        }
      })}
    </div>
  );
}
