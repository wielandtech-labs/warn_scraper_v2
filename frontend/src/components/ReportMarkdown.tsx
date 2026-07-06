import { Fragment, type ReactNode } from "react";

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
    i % 2 === 1 ? <strong key={i}>{p}</strong> : <Fragment key={i}>{p}</Fragment>,
  );
}

// A cell of digits/sign/percent reads better in tabular figures.
const NUMERIC_CELL = /^[+\-−]?[\d,.]+%?$/;

export function ReportMarkdown({
  markdown,
  skipH1 = false,
}: {
  markdown: string;
  /** Drop the report's H1 when the surrounding card already provides context. */
  skipH1?: boolean;
}) {
  const blocks = parseBlocks(markdown);
  return (
    <div className="space-y-3 text-sm text-slate-700 dark:text-slate-300">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "heading":
            if (b.level === 1) {
              if (skipH1) return null;
              return (
                <h3 key={i} className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  {inline(b.text)}
                </h3>
              );
            }
            return (
              <h4 key={i} className="pt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                {inline(b.text)}
              </h4>
            );
          case "hr":
            return <hr key={i} className="border-slate-200 dark:border-slate-800" />;
          case "quote":
            return (
              <blockquote
                key={i}
                className="border-l-4 border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
              >
                {inline(b.text)}
              </blockquote>
            );
          case "list":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5">
                {b.items.map((item, j) => (
                  <li key={j}>{inline(item)}</li>
                ))}
              </ul>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                    <tr>
                      {b.header.map((cell, j) => (
                        <th
                          key={j}
                          className={`px-2 py-1.5 font-medium ${b.align[j] === "right" ? "text-right" : ""}`}
                        >
                          {inline(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {b.rows.map((row, j) => (
                      <tr key={j}>
                        {row.map((cell, k) => (
                          <td
                            key={k}
                            className={`px-2 py-1 align-top ${
                              b.align[k] === "right" ? "text-right" : ""
                            } ${NUMERIC_CELL.test(cell) ? "tabular-nums" : ""}`}
                          >
                            {inline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "para":
            return b.meta ? (
              <p key={i} className="text-xs italic text-slate-500 dark:text-slate-400">
                {inline(b.text)}
              </p>
            ) : (
              <p key={i} className="leading-relaxed">
                {inline(b.text)}
              </p>
            );
        }
      })}
    </div>
  );
}
