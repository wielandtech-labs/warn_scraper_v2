// Crypto donation addresses: the single source of truth for /donate.
//
// The QR codes in frontend/public/donate/<id>.svg encode each coin's `uri`.
// They are pre-rendered (no runtime QR dependency), so when an address
// changes, regenerate them from this file with segno (pip install segno):
//
//   python -c "import re,segno; src=open('frontend/src/lib/donate.ts').read(); \
//     [segno.make(u, error='m').save(f'frontend/public/donate/{i}.svg', scale=6, \
//     border=2, dark='#0f172a', light='#ffffff', xmldecl=False) \
//     for i,u in re.findall(r'id: \"(\w+)\".*?uri: \"([^\"]+)\"', src, re.S)]"
//
// Because the site is open source, donors can check these addresses against
// the public repo before sending.

export interface DonationCoin {
  id: string;
  name: string;
  symbol: string;
  address: string;
  /** Payment URI (BIP-21 / EIP-681): opens a wallet app, and what the QR encodes. */
  uri: string;
  note?: string;
}

export const DONATION_COINS: DonationCoin[] = [
  {
    id: "btc",
    name: "Bitcoin",
    symbol: "BTC",
    address: "bc1qzerntg08tn5u0xfwhk5s63ulln8ws76nvmxue8",
    uri: "bitcoin:bc1qzerntg08tn5u0xfwhk5s63ulln8ws76nvmxue8",
  },
  {
    id: "eth",
    name: "Ethereum",
    symbol: "ETH",
    address: "0xeE79a5116F506c989A9D2683c7f675E11253f816",
    uri: "ethereum:0xeE79a5116F506c989A9D2683c7f675E11253f816",
    note: "Also accepts ERC-20 tokens such as USDC. Send on Ethereum mainnet only.",
  },
  {
    id: "ltc",
    name: "Litecoin",
    symbol: "LTC",
    address: "ltc1qm36cfdh9a99z9qse3hdu5uxetwndq6g9de8fzx",
    uri: "litecoin:ltc1qm36cfdh9a99z9qse3hdu5uxetwndq6g9de8fzx",
  },
];

export const SOURCE_URL =
  "https://github.com/wielandtech-labs/warn_scraper_v2/blob/main/frontend/src/lib/donate.ts";
