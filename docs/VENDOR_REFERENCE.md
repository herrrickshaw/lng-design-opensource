# Industrial Component Vendor Reference — Cross-Checking Conceptual Sizing Against Published Catalogs

## Purpose

This project (and its sibling, `coal-to-urea-design-opensource`) compute
continuous design numbers — a vessel diameter, a control-valve Cv, an
exchanger duty — the same way `lng_design/equipment_catalog.py` matches
computed vessel diameters and TEMA shell sizes to standard series cited
to the GPSA Engineering Data Book and the *Pipeline Rules of Thumb
Handbook*. This document extends that same idea one step further, out to
*real, named* equipment suppliers: for each vendor below, does their own
public catalog/datasheet publish a genuine numeric series (a size table,
a pressure-class table, a duty range) that a computed sizing output can
be sanity-checked against — "does a computed 2.4 m vessel diameter, or a
computed valve Cv, correspond to something a named manufacturer actually
publishes"?

**This is explicitly not vendor endorsement, not a procurement
recommendation, and not a source of proprietary engineering data.**
Every entry below cites a document that is freely reachable on the
vendor's own website (or, where noted, the vendor's own CDN) with no
login — a Screener.in-style paywalled or account-gated resource would
fail the same "literature-only" bar this project already holds itself
to for stock/financial data. Every URL listed here was fetched and its
content inspected (via `curl`/`pdftotext`, or a browser where a site
blocks scripted fetches) as part of writing this document; nothing here
is a search-result title taken on faith. Where a vendor's real,
relevant products exist but their detailed datasheets sit behind a free
account (Velan), or no independently verifiable public dimensional
catalog could be found (Worthington Industries, CB&I/McDermott), that is
stated explicitly rather than papered over with a fabricated or
unverified link.

Figures quoted below (pressure ranges, size ranges, orifice areas, plate
counts) are transcribed from the cited document at the time of writing
(September 2026) and are the vendor's own published *typical/standard*
ranges — not a live product configurator, not a quote, and not
necessarily the full extent of what the vendor offers. Vendor catalogs
change; re-verify before relying on a specific number in an automated
check.

---

## 1. Valves

`lng_design` doesn't yet size valves; `coal-to-urea-design-opensource`
needs both cryogenic-adjacent service (any LNG-sourced fuel gas, boil-off)
and — its real focus — high-pressure (150–300 bar) ammonia/CO₂/syngas
service. API 6A pressure classes (2000/3000/5000/10000/15000/20000/30000
psi = 138/207/345/690/1034/1379/2068 bar) bracket the 150–300 bar
(2176–4351 psi) range well; that's the recurring cross-check below.

| Vendor | Public resource (verified) | Series/ratings published | Relevance |
|---|---|---|---|
| **Emerson (Fisher)** | [Fisher™ HP Series Control Valves bulletin](https://emerson.com/documents/automation/product-bulletin-fisher-hp-series-control-valves-en-123584.pdf) (D101635X012, Feb 2024, emerson.com) | Single-port, high-pressure globe/angle control valves; balanced-trim pressure limit **149 bar (2160 psig)** for two-stage Cavitrol III trim, **207 bar (3000 psig)** for other configurations; class ratings per ASME B16.34; full Cv/trim tables by NPS and trim type. | Coal-to-urea: high-pressure syngas/ammonia control valves — the 149–207 bar range sits inside the project's 140–300 bar synthesis-loop pressure band. |
| **Emerson (Anderson Greenwood / Crosby, pilot-operated PRVs)** | [Series 200/400/500/700/800 Pilot Operated Relief Valves datasheet](https://www.emerson.com/is/content/emerson/en/final-control/pressure-management/prv/general/documents/PRM-TDS-Series-200_400_500_700_800-Pilot-Operated-Relief-Valves-VCTDS-00543-EN.pdf) (VCTDS-00543-EN, emerson.com) | Sizes 1"×2" to 10"×14"; **orifice areas 0.110–63.5 in²**; **set pressures 15 psig to >6170 psig (1.72–425.5 barg)**; explicit cryogenic-liquid variants (Type 249/259/269, set pressure range 25–1440 psig). | Both repos: the cryogenic-liquid variant covers LNG boil-off/relief service; the full set-pressure range (up to 425 barg) comfortably brackets the 140–300 bar ammonia/urea PRV duty. |
| **LESER GmbH & Co. KG** | [API Extended Catalog (English)](https://www.leser.com/-/media/files/catalogue/english/api_extended_catalog_en.pdf) (leser.com) | Full **API 526 standard orifice-letter table, D through T**, with actual orifice diameter and area given in both mm/mm² and inch/in² for each safety-relief-valve model in the catalog (e.g. orifice D = 14.0 mm / 154 mm² = 0.551 in² / 0.239 in²), across the catalog's set-pressure/size combinations. | Both repos: the canonical public source for the API 526 orifice-letter series the project's own PRV sizing should round up to — same role LESER's catalog plays as `equipment_catalog.py`'s GPSA/TEMA tables. |
| **SLB (Cameron)** | [FLS Gate Valve](https://www.slb.com/valves/api-spec-6a-technologies/api-spec-6a-gate-valves/fls-gate-valve) and [FLS-R Gate Valve](https://www.slb.com/valves/api-spec-6a-technologies/api-spec-6a-gate-valves/fls-r-gate-valve) product pages (slb.com) | API 6A slab-style gate valves; published table of **nominal bore size (1-13/16" to 11")  ×  API 6A working-pressure class (2,000 / 3,000 / 5,000 / 10,000 / 15,000 / 20,000 / 30,000 psi)** showing which bore/class combinations the FL/FLS/FLS-R product lines actually cover. | Coal-to-urea: the closest thing to a real published "valve size × pressure-class" series for genuinely high-pressure gate valves — directly brackets 150–300 bar ammonia/CO₂/syngas block-valve service. |
| **Crane Co.** | [Forged Steel Gate, Globe, and Check Valves — Technical Data Sheet](https://cranecpe.com/wp-content/uploads/CPE-CRANE-FORGEDSTEEL-TDS-EN-LT-2019_10_14-web.pdf) (cranecpe.com, a Crane Co. Process Flow Technologies site) | Class 800 and Class 1500 valve series with published **shell/seat/back-seat hydrostatic and pneumatic test pressures** (e.g. Class 1500 shell hydro test 5,550 psi, seat 4,125 psi); face-to-face and end-connection standards (ASME B16.11, API 598, API 624). | Coal-to-urea: Class 1500 (≈ 255 bar cold working pressure per ASME B16.34) is a direct cross-check point for mid-range ammonia/CO₂ block and isolation valves. |
| **Velan Inc.** | Real, relevant product lines confirmed live on velan.com — [API 602 Cryogenic Globe Valve](https://velan.com/products/api-602-cryogenic-globe-valves/), [Torqseal® Triple Offset Cryogenic Valve](https://velan.com/products/torqseal-triple-offset-cryogenic-valves/), Cast Steel Cryogenic Valves — **but** the "Documents" tab on every one of these product pages is gated behind a free "My Velan" account login. | Named per the task brief (cryogenic gate/globe/check/butterfly valves down to ‑253.9 °C / ‑425 °F, per the product pages' own text) but not included with a datasheet link, since this project's bar is public/no-login. | Would be directly relevant to LNG cryogenic block/control valves if a public datasheet becomes available. |

---

## 2. Heat exchangers

`lng_design` already sizes TEMA shell-and-tube exchangers and API 661 air
coolers against public standard series (`equipment_catalog.py`); the
entries below extend that to plate, plate-fin, and brazed-aluminum types,
plus a higher-pressure shell-and-tube source for the coal-to-urea side
(syngas coolers, waste-heat boilers, ammonia condensers routinely exceed
the ≈600 psi ceiling of a "standard" shell-and-tube design).

| Vendor | Public resource (verified) | Series/ratings published | Relevance |
|---|---|---|---|
| **API Heat Transfer (Basco®)** | [Basco® Engineered Shell & Tube Heat Exchangers brochure](https://www.apiheattransfer.com/wp-content/uploads/2024/11/Basco-Shell-And-Tube-Heat-Exchangers_R4.pdf) (apiheattransfer.com) | Custom shell-and-tube, **shell diameters 2"–115", tube lengths to 50 ft**; per-design-type pressure ranges spelled out explicitly, up to **1,200–6,000 psi tubeside** (a "bonnet end" high-pressure design) and 75–3,000 psi tubeside / 75–1,500 psi shellside for other types. | Both repos: the 1,200–6,000 psi (≈83–414 bar) tubeside range is a genuine, named-vendor bracket for coal-to-urea syngas coolers and waste-heat boilers at 140–300 bar; the general shell-diameter/length series also extends `lng_design`'s TEMA table to larger, custom sizes. |
| **Chart Industries (Chart Energy & Chemicals)** | [Brazed Aluminum Heat Exchangers brochure](https://files.chartindustries.com/Brazed-Aluminum-Heat-Exchangers.pdf) (chartindustries.com) | BAHX / cold-box plate-fin exchangers; explicit "Specialized Chart Expertise — High Pressure Capability" section: **BAHX offered in excess of 160 barg (2,320 psig)**. Does not publish a numeric size/duty table in this particular brochure (that level of detail is project-quoted). | LNG: BAHX/plate-fin exchangers are the standard main cryogenic heat exchanger technology this project's shell-and-tube/air-cooler catalog doesn't yet cover; the >160 barg figure is a useful upper-bound sanity check for any high-pressure BAHX duty. |
| **Alfa Laval** | [T2 gasketed plate heat exchanger product leaflet](https://www.alfalaval.com/globalassets/documents/products/heat-transfer/plate-heat-exchangers/gasketed-plate-and-frame-heat-exchangers/industrial/t2_pdleaflet_pct00082en.pdf) (alfalaval.com) | Gasketed PHE; published **free-channel size (2.4 mm), max. design pressure 16.0 barg / 232 psig at 180 °C**, dimensional drawing, materials table. | Coal-to-urea (lower-pressure duty only): relevant to utility/cooling-water and boiler-feedwater loops around the plant, not the 140–300 bar synthesis-loop streams themselves — PHEs of this class don't reach ammonia/urea-reactor pressures. |
| **Kelvion Holding GmbH** | [GBS-Series brazed plate heat exchanger datasheet](https://a.storyblok.com/f/122742/x/d97758d3c0/pf_phe_bphe_gbs_en.pdf) (linked from kelvion.com's [GBS-series product page](https://www.kelvion.com/us/products/product/gbs-series/); PDF served from Kelvion's own CMS asset host) | Copper-brazed PHE; **working pressure up to 40 bar / 580 psi, working temperature ‑196 °C to +200 °C (‑321 °F to +392 °F)**, per-model dimension and weight table. | Both repos, lower-pressure duty: the ‑196 °C cold end covers LNG boil-off/vapor-service heat recovery; not rated for the coal-to-urea synthesis-loop pressures. |
| **SPX FLOW (APV)** | [APV Heat Transfer Technology catalog](https://www.spxflow.com/assets/pdf/apv-heat-transfer-technology-1010-05-03-2012-gb.pdf) (spxflow.com) | Gasketed PHE; **plate area 0.01–4.6 m² per plate**, unit duty up to **≈3,800 m² total plate area**. No explicit pressure-class table in this particular catalog. | Named per the task brief; useful as a general plate-count/duty-scale cross-check for utility-side gasketed exchangers, not for high-pressure or cryogenic process streams. |

---

## 3. Pressure vessels / storage tanks

Neither this project's `equipment_catalog.py` GPSA vessel-diameter table
nor TEMA shell sizes extend to genuinely high-pressure reactor vessels
(ammonia converters at 150–300 bar, urea reactors at 140–250 bar) or to
large cryogenic storage tanks. Unlike valves and standard shell-and-tube
exchangers, this category turned out to have the thinnest public,
standardized-series coverage — most of it is bespoke, project-quoted
equipment, which is itself worth recording honestly rather than forcing
a citation that doesn't exist.

| Vendor | Public resource (verified) | Series/ratings published | Relevance |
|---|---|---|---|
| **Chart Industries (Chart Bulk Storage)** | [Bulk Storage Product Catalog](https://files.chartindustries.com/13608592_BulkCatalog.pdf) (chartbulktanks.com / chartindustries.com) | Vertical and horizontal cryogenic bulk tanks; explicit statement **"vertical and horizontal tanks available from 1,500 to 264,000 gallon (6 to 1,000 m³) capacities... 40 to 250 psig (2.8 to 17.2 barg) or custom pressure"**, plus per-model tables of gross/net capacity (gal/L), MAWP (psig/bar), diameter, height, and weight for each product line. | LNG: a genuine, named-vendor dimensional/MAWP series for cryogenic storage tanks — the closest thing in this category to `equipment_catalog.py`'s GPSA vessel-diameter table, and directly usable to round a computed LNG storage/surge-tank size up to a real catalog model. |
| **L&T Heavy Engineering (Larsen & Toubro)** | [Ammonia Converters](https://www.larsentoubro.com/heavy-engineering/products-services/process-plant/fertiliser/ammonia-converters) and [Urea Reactors](https://www.larsentoubro.com/heavy-engineering/products-services/process-plant/fertiliser/urea-reactors/) product pages (larsentoubro.com) | Not a selectable standard series (these are one-off, project-engineered vessels) — but genuine published reference figures: **world's heaviest multi-wall ammonia converter, 860 MT (incl. 200 MT SS converter basket)**; converter baskets up to 190 MT (35+ supplied); 100+ waste-heat boiler packages supplied; a urea stripper/absorber example at **38 m long × 3.3 m diameter**; processes licensed include Haldor Topsøe, KBR, ThyssenKrupp Uhde, Casale. | Coal-to-urea: the one category where no TEMA/GPSA-style catalog exists — these are order-of-magnitude, named-vendor sanity checks (does a computed converter weight/basket size land anywhere near what's actually been built), not a lookup table to round up to. |
| **Worthington Industries** | *Not included* — real cryogenic-cylinder products exist (confirmed via press materials/distributor pages, e.g. 180–265 L net capacity liquid cylinders), but no independently verifiable public page with a dimensional/pressure series on Worthington's own site was found. | — | Named per the task brief; flagged rather than cited with an unverified link. |
| **CB&I / McDermott** | *Not included* — mcdermott.com blocks scripted/automated fetches (HTTP 403 from its edge/WAF on the pages checked), so no citable public page with tank dimensional data could be verified for this document, even though CB&I is a real, well-known full-containment LNG tank EPC contractor (e.g. widely reported 200,000 m³ full-containment tanks for recent US LNG export projects). | — | Named per the task brief; flagged rather than cited with an unverified link. |

---

## Notes on what didn't make the cut

A number of vendors named in the original research brief turned out, on
inspection, not to clear the "genuinely public, freely accessible, shows
real numeric data" bar used throughout this document:

- **Flowserve, Circor** — both have real, extensive product lines
  (Flowserve Valdisk/Valtek control valves; Circor's Pibiviesse, R.G.
  Laurence, Circle Seal lines), but the Cv-table and catalog PDFs found
  in searches resolved either to third-party aggregators (DirectIndustry,
  Scribd) or to pages this document's author could not independently
  fetch and confirm within the time available — they are plausible leads
  for a follow-up pass but are not cited here on that basis alone.
- Several **DirectIndustry-hosted PDFs** turned up for Alfa Laval,
  Kelvion, Velan, and others; DirectIndustry is a third-party catalog
  aggregator, not the vendor's own website, so it was used only to
  *locate* the vendor's own hosted copy of the same document (as done
  for Alfa Laval and Kelvion above), never cited directly.
- The two **Emerson brochure URLs** that came up first in search results
  for the Anderson Greenwood/Crosby/Varec PRV *product overview* (as
  opposed to the pilot-operated-valve datasheet actually cited above)
  turned out to be dead — they now 301-redirect to Emerson's generic
  search page. This is exactly the kind of stale-link trap this
  document's verification step (fetch, don't trust the search snippet)
  was meant to catch.
