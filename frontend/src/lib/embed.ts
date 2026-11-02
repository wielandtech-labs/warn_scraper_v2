// HTML snippets other sites paste in. Each one wraps the embed in a plain
// <a href> back to the matching page here: that outer link is the backlink.

// The state badge is a plain SVG <img> wrapped in a link to the state page,
// so it works anywhere an image does: blogs, READMEs, newsletters.
export function stateBadgeSnippet(origin: string, code: string, name: string): string {
  return (
    `<a href="${origin}/states/${code}">` +
    `<img src="${origin}/embed/badge/state/${code}.svg" ` +
    `alt="${escapeAttr(name)} WARN layoffs, last 30 days (WARN Index)" height="20"></a>`
  );
}

export function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}
