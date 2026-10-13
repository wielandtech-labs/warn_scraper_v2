// Put two series with unrelated units (workers affected; an unemployment
// rate) on ONE axis by indexing each to its own average over the periods where
// both have data: 100 = "typical for this window". A shared index is the
// honest alternative to a second y-axis, whose scale is arbitrary and whose
// crossings mean nothing.
//
// The window mean rather than the first period: monthly WARN counts are
// noisy, and a quiet first month would inflate the whole index.

export function rebasePair(
  a: (number | null | undefined)[],
  b: (number | null | undefined)[],
): { a: (number | null)[]; b: (number | null)[] } {
  const both: number[] = [];
  for (let i = 0; i < a.length; i++) {
    if (isNum(a[i]) && isNum(b[i])) both.push(i);
  }
  const mean = (xs: (number | null | undefined)[]) =>
    both.reduce((sum, i) => sum + (xs[i] as number), 0) / both.length;
  const meanA = both.length ? mean(a) : 0;
  const meanB = both.length ? mean(b) : 0;
  const scale = (xs: (number | null | undefined)[], m: number) =>
    xs.map((x) => (isNum(x) && m > 0 ? (x / m) * 100 : null));
  return { a: scale(a, meanA), b: scale(b, meanB) };
}

function isNum(x: number | null | undefined): x is number {
  return typeof x === "number" && Number.isFinite(x);
}
