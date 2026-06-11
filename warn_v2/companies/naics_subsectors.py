"""2022 NAICS 3-digit subsector code -> title.

Static reference data (the official 2022 NAICS structure). Subsector titles are
not derivable from the code and the stored 6-digit `naics_desc` is often null, so
we keep the full table here. Used for the subsector drill-down in industry
filtering (see warn_v2/companies/naics.py). The accompanying consistency test
(tests/test_naics.py) asserts every key is 3 digits and rolls up to a known
sector — a guard against transcription errors.
"""
from __future__ import annotations

NAICS_SUBSECTORS: dict[str, str] = {
    # 11 — Agriculture, Forestry, Fishing & Hunting
    "111": "Crop Production",
    "112": "Animal Production and Aquaculture",
    "113": "Forestry and Logging",
    "114": "Fishing, Hunting and Trapping",
    "115": "Support Activities for Agriculture and Forestry",
    # 21 — Mining, Quarrying, Oil & Gas Extraction
    "211": "Oil and Gas Extraction",
    "212": "Mining (except Oil and Gas)",
    "213": "Support Activities for Mining",
    # 22 — Utilities
    "221": "Utilities",
    # 23 — Construction
    "236": "Construction of Buildings",
    "237": "Heavy and Civil Engineering Construction",
    "238": "Specialty Trade Contractors",
    # 31-33 — Manufacturing
    "311": "Food Manufacturing",
    "312": "Beverage and Tobacco Product Manufacturing",
    "313": "Textile Mills",
    "314": "Textile Product Mills",
    "315": "Apparel Manufacturing",
    "316": "Leather and Allied Product Manufacturing",
    "321": "Wood Product Manufacturing",
    "322": "Paper Manufacturing",
    "323": "Printing and Related Support Activities",
    "324": "Petroleum and Coal Products Manufacturing",
    "325": "Chemical Manufacturing",
    "326": "Plastics and Rubber Products Manufacturing",
    "327": "Nonmetallic Mineral Product Manufacturing",
    "331": "Primary Metal Manufacturing",
    "332": "Fabricated Metal Product Manufacturing",
    "333": "Machinery Manufacturing",
    "334": "Computer and Electronic Product Manufacturing",
    "335": "Electrical Equipment, Appliance, and Component Manufacturing",
    "336": "Transportation Equipment Manufacturing",
    "337": "Furniture and Related Product Manufacturing",
    "339": "Miscellaneous Manufacturing",
    # 42 — Wholesale Trade
    "423": "Merchant Wholesalers, Durable Goods",
    "424": "Merchant Wholesalers, Nondurable Goods",
    "425": "Wholesale Trade Agents and Brokers",
    # 44-45 — Retail Trade (2022 structure)
    "441": "Motor Vehicle and Parts Dealers",
    "444": "Building Material and Garden Equipment and Supplies Dealers",
    "445": "Food and Beverage Retailers",
    "449": "Furniture, Home Furnishings, Electronics, and Appliance Retailers",
    "455": "General Merchandise Retailers",
    "456": "Health and Personal Care Retailers",
    "457": "Gasoline Stations and Fuel Dealers",
    "458": "Clothing, Clothing Accessories, Shoe, and Jewelry Retailers",
    "459": "Sporting Goods, Hobby, Musical Instrument, Book, and Misc. Retailers",
    # 48-49 — Transportation & Warehousing
    "481": "Air Transportation",
    "482": "Rail Transportation",
    "483": "Water Transportation",
    "484": "Truck Transportation",
    "485": "Transit and Ground Passenger Transportation",
    "486": "Pipeline Transportation",
    "487": "Scenic and Sightseeing Transportation",
    "488": "Support Activities for Transportation",
    "491": "Postal Service",
    "492": "Couriers and Messengers",
    "493": "Warehousing and Storage",
    # 51 — Information (2022 structure)
    "512": "Motion Picture and Sound Recording Industries",
    "513": "Publishing Industries",
    "516": "Broadcasting and Content Providers",
    "517": "Telecommunications",
    "518": "Computing Infrastructure Providers, Data Processing & Hosting",
    "519": "Web Search Portals, Libraries, Archives & Other Information Services",
    # 52 — Finance & Insurance
    "521": "Monetary Authorities-Central Bank",
    "522": "Credit Intermediation and Related Activities",
    "523": "Securities, Commodity Contracts & Other Financial Investments",
    "524": "Insurance Carriers and Related Activities",
    "525": "Funds, Trusts, and Other Financial Vehicles",
    # 53 — Real Estate, Rental & Leasing
    "531": "Real Estate",
    "532": "Rental and Leasing Services",
    "533": "Lessors of Nonfinancial Intangible Assets (except Copyrighted Works)",
    # 54 — Professional, Scientific & Technical Services
    "541": "Professional, Scientific, and Technical Services",
    # 55 — Management of Companies & Enterprises
    "551": "Management of Companies and Enterprises",
    # 56 — Administrative, Support & Waste Management
    "561": "Administrative and Support Services",
    "562": "Waste Management and Remediation Services",
    # 61 — Educational Services
    "611": "Educational Services",
    # 62 — Health Care & Social Assistance
    "621": "Ambulatory Health Care Services",
    "622": "Hospitals",
    "623": "Nursing and Residential Care Facilities",
    "624": "Social Assistance",
    # 71 — Arts, Entertainment & Recreation
    "711": "Performing Arts, Spectator Sports & Related Industries",
    "712": "Museums, Historical Sites, and Similar Institutions",
    "713": "Amusement, Gambling, and Recreation Industries",
    # 72 — Accommodation & Food Services
    "721": "Accommodation",
    "722": "Food Services and Drinking Places",
    # 81 — Other Services (except Public Administration)
    "811": "Repair and Maintenance",
    "812": "Personal and Laundry Services",
    "813": "Religious, Grantmaking, Civic, Professional & Similar Organizations",
    "814": "Private Households",
    # 92 — Public Administration
    "921": "Executive, Legislative & Other General Government Support",
    "922": "Justice, Public Order, and Safety Activities",
    "923": "Administration of Human Resource Programs",
    "924": "Administration of Environmental Quality Programs",
    "925": "Administration of Housing Programs, Urban Planning & Community Dev.",
    "926": "Administration of Economic Programs",
    "927": "Space Research and Technology",
    "928": "National Security and International Affairs",
}
