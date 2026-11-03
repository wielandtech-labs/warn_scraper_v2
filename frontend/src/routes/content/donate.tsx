import { useState } from "react";

import { DONATION_COINS, SOURCE_URL, type DonationCoin } from "../../lib/donate";
import { ContentPage } from "./ContentPage";

function CoinCard({ coin }: { coin: DonationCoin }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(coin.address).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-slate-200 p-4 sm:flex-row sm:items-center dark:border-slate-800">
      <img
        src={`/donate/${coin.id}.svg`}
        alt={`${coin.name} donation address QR code`}
        width={160}
        height={160}
        className="h-40 w-40 shrink-0 self-center rounded-md bg-white p-1"
      />
      <div className="min-w-0 space-y-2">
        <h2 className="!mt-0">
          {coin.name} ({coin.symbol})
        </h2>
        <code className="block break-all rounded-md bg-slate-100 p-2 text-xs dark:bg-slate-800">
          {coin.address}
        </code>
        {coin.note && <p className="text-sm text-slate-500 dark:text-slate-400">{coin.note}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-secondary" onClick={copy}>
            {copied ? "Copied!" : "Copy address"}
          </button>
          <a className="btn-secondary !no-underline" href={coin.uri}>
            Open in wallet
          </a>
        </div>
      </div>
    </div>
  );
}

export function DonatePage() {
  return (
    <ContentPage
      title="Support WARN Index"
      docTitle="Donate — Support the Free WARN Layoff Tracker — WARN Index"
      intro="WARN Index is free and open source, with no ads and no paywall. Donations keep the servers and the daily scrapers running."
    >
      <p>
        Every day WARN Index checks more than 50 state labor agency sites, then
        normalizes, geocodes, and publishes what it finds. That takes servers,
        storage, and upkeep whenever a state changes its site. If the data is
        useful to you, a donation in crypto helps cover it.
      </p>

      <div className="space-y-4">
        {DONATION_COINS.map((coin) => (
          <CoinCard key={coin.id} coin={coin} />
        ))}
      </div>

      <h2>Before you send</h2>
      <ul>
        <li>
          Check the address: these are the only addresses WARN Index uses, and
          they are published in the{" "}
          <a href={SOURCE_URL}>open-source code</a>. If a page shows you
          anything else, don&apos;t send.
        </li>
        <li>Send each coin on its own network. Crypto sent on the wrong network can be lost.</li>
        <li>
          WARN Index is not a registered nonprofit, so donations are not tax-deductible.
        </li>
      </ul>

      <h2>Other ways to help</h2>
      <p>
        Cite or link WARN Index when you use the data (see{" "}
        <a href="/cited-by">Cited by</a>), embed a state badge on your site, or
        report a data problem to{" "}
        <a href="mailto:info@warnindex.com">info@warnindex.com</a>.
      </p>
    </ContentPage>
  );
}
