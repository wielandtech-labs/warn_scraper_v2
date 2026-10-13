import { useState } from "react";

/* A company's own site icon, served through /api/logos/{id} (fetched and
   cached server side -- the browser never contacts the company's site).

   A monogram tile is always painted first, so the slot has its final size
   from the first frame (no layout shift) and every row has an image even
   when the company has no website or no usable icon. The logo fades in over
   it only once it has actually loaded; a 404 just leaves the monogram. */

// Muted tile tints, picked by a stable hash of the name so a company keeps
// its color across pages. Identity only -- never data.
const TINTS = [
  "bg-[#e8eef8] text-[#1c5cab] dark:bg-[#17263d] dark:text-[#9ec5f4]",
  "bg-[#e6f2ec] text-[#0f6b4b] dark:bg-[#142a21] dark:text-[#7fd1ad]",
  "bg-[#f3ece0] text-[#8a5a00] dark:bg-[#2e2414] dark:text-[#e3b768]",
  "bg-[#ece9f6] text-[#4a3aa7] dark:bg-[#221e38] dark:text-[#b4abf0]",
  "bg-[#f0efec] text-[#3d3c39] dark:bg-[#2c2c2a] dark:text-[#e1e0d9]",
];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

const STOP = new Set(["inc", "llc", "corp", "corporation", "co", "the", "ltd", "lp", "of", "and"]);

function initials(name: string): string {
  const words = name
    .replace(/[^A-Za-z0-9 ]+/g, " ")
    .split(/\s+/)
    .filter((w) => w && !STOP.has(w.toLowerCase()));
  const letters = words.slice(0, 2).map((w) => w[0].toUpperCase());
  return letters.join("") || name.slice(0, 1).toUpperCase();
}

interface Props {
  name: string;
  companyId: number | null | undefined;
  /** false = known to have no website: skip the request entirely. */
  hasWebsite?: boolean;
  size?: number;
  className?: string;
}

export function CompanyLogo({ name, companyId, hasWebsite, size = 32, className = "" }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const tryImage = companyId != null && hasWebsite !== false && !failed;
  return (
    <span
      aria-hidden
      className={`relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-lg font-display font-semibold ${TINTS[hash(name) % TINTS.length]} ${className}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
    >
      {initials(name)}
      {tryImage && (
        <img
          src={`/api/logos/${companyId}`}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className={`absolute inset-0 h-full w-full bg-white object-contain p-[12%] transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
        />
      )}
    </span>
  );
}
