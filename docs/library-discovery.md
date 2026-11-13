# Library discovery evidence

The Solus nearby list can omit libraries that resolve by exact LocationID.
Dropdown search filters the returned choices only; it is not global name
search. The integration shows all unique returned LocationIDs, retains `Name`
when supplied and otherwise displays LocationID. It sends no radius, country,
result-count or text-search parameter. Manual exact lookup remains available.

## Anonymous Solus observations — 2026-11-13

These bounded public probes used public sample coordinates `(69.0, 19.0)`,
not HA/home coordinates, and no DeviceID, bootstrap, credentials or account
requests. Only sanitized structure/results were recorded; bodies stayed in
memory. The successful follow-ups supersede earlier blanket HTTP 403 findings.
The mobile User-Agent and Accept are recorded in [protocol.md](protocol.md).

| Public source/request | Observed result |
| --- | --- |
| [Exact Malselv repo](https://repo.sol.us/id/9e246e4d-0f45-4857-803e-73be8a83c10e/2026.42) | HTTP 200; keys `API`, `BGC`, `FGC`, `HI`, `ID`, `II`, `Server`, `VS`, `VT`, `VU`; no explicit name/title keys. `API` points to `api-eu1.sol.us`; `HI` is an image-delivery URL, not a structured directory. Other abbreviated string meanings remain unknown. |
| [QueryWithID](https://locator.sol.us/v4/Locator.asmx/QueryWithID), POST with random `rnd`, exact `Malselv` | HTTP 200, `d` object, `Status: ok`; keys `APIUrl`, `AppID`, `Distance`, `LocationID`, `LocationIconData`, `ServerUrl`, `Status`, `__type`; no name/title. |
| [FindWithLocation](https://locator.sol.us/v4/Locator.asmx/FindWithLocation), POST with random `rnd`, sample above | HTTP 200, direct `d` list, one candidate `Skjervoy`, `Status: ok`, same keys and no name/title. |
| [Global-app repo](https://repo.sol.us/id/5C72D777-E044-4B76-97A8-F240FA42E9BD/2026.42) | HTTP 200; exactly `ID: str`, `Server: str`, `API: str`; no nested directory/name structure or further safe provider-linked metadata/scripts. |
| [Locator WSDL](https://locator.sol.us/v4/Locator.asmx?WSDL) | HTTP 520; operations/schema unavailable. |
| [Service root](https://locator.sol.us/v4/Locator.asmx) / [method description](https://locator.sol.us/v4/Locator.asmx?op=FindWithLocation) | HTTP 500 for both. |
| [Provider-linked API root](https://api-eu1.sol.us/) / [owner-verified frontend](https://m-eu1.sol.us/) / [locator host root](https://locator.sol.us/) | HTTP 404 / 200 / 403; frontend exposed only `ssl.jpg`, no script/metadata links. |

These observations do not establish global completeness, the cause of provider
filtering, results at the owner's coordinates, a working global-search method,
or that name fields never occur elsewhere. No unknown methods or speculative
radius fields were invoked. Do not invent friendly names from LocationIDs.

## Norwegian National Library directory — 2026-11-13

Primary sources: [full BaseBibliotek export](https://www.nb.no/baser/bibliotek/eksport/bb-full.xml),
[linked schema](https://www.nb.no/baser/bibliotek/eksport/basebibliotek.xsd),
[export directory](https://www.nb.no/baser/bibliotek/eksport/),
[NB description/update policy](https://bibliotekutvikling.no/lan-fra-nasjonalbiblioteket/basebibliotek/),
[search interface](https://www.nb.no/basebibliotek/) and
[national-service integration requirements](https://bibliotekutvikling.no/kunnskapsorganisering/krav-til-biblioteksystem-integrering-mot-nasjonale-tjenester/).

The owner-authorized investigation processed XML/XSD in memory with bounded
reads and saved no raw export or contact data. Export HTTP 200: 6,521,281 bytes,
6,220 records in namespace `http://nb.no/BaseBibliotek`; root export timestamp
`2026-11-12 21:00:18`, HTTP Last-Modified `Thu, 12 Nov 2026 20:00:50 GMT`.
NB describes daily updates and library-maintained entries. These observed times
are not a publication guarantee. The register covers Norwegian library-number
holders and foreign interlibrary-loan partners, not Solus app support.

The schema's `inst` contains authoritative institution/branch names; `katsyst`
is catalogue system (`Axiell` in 321 records). `eressurser/OAI` and
`eressurser/nncip_uri` hold resource URLs. No `Solus`, `GlobalAppID`, `TemplateID`,
`LocationID` or `OAIrepositoryID` marker occurred in the inspected export.
The branch IDs below occur in OAI URL suffixes, not an OAIrepositoryID element.

| Actual `inst` (display whitespace collapsed) | Quria host | OAI suffix |
| --- | --- | --- |
| Målselv bibliotek Hovedbiblioteket | `malselv.quria.axiell.com` | `NO-2192400` |
| Målselv folkebibliotek Øverbygd bibliotek | `malselv.quria.axiell.com` | `NO-2192412` |
| Skjervøy folkebibliotek Hovedbiblioteket | `nordtroms.quria.axiell.com` | `NO-2194100` |
| Lyngen folkebibliotek | `nordtroms.quria.axiell.com` | `NO-2193800` |
| Nordreisa bibliotek Hovedbiblioteket | `nordtroms.quria.axiell.com` | `NO-2194200` |
| Gratangen bibliotek | `astafjord.quria.axiell.com` | `NO-2191900` |
| Loabága girjerádju - Lavangen bibliotek | `astafjord.quria.axiell.com` | `NO-2192000` |
| Salangen bibliotek | `astafjord.quria.axiell.com` | `NO-2192300` |

Among 271 records with inspected Quria OAI/NCIP hosts, there were 104 distinct
hosts and 36 shared by several records. Målselv's two branches share one NCIP
URL/tenant, with distinct OAI suffixes. Nine Nord-Troms records share a tenant;
Gratangen, Lavangen and Salangen also share one. Quria tenant IDs differ from
the owner-verified Målselv Solus AppID. Hostnames and NCIP tenants therefore
cannot safely join NB records to Solus LocationID/AppID. `katsyst=Axiell` does
not establish Solus app/login support. An OAI branch ID distinguishes NB/Quria
records, but no observed Solus response supplies that join key.

A future optional directory/enrichment would require a separately designed,
verified crosswalk with provenance and explicit branch/ambiguity handling.
No first-match, accent-stripping, municipality-name or hostname heuristic is
implemented. NB links are metadata, never credential destinations. No new
runtime dependency or per-login XML download is added. No explicit reuse
licence was found in the consulted official export/schema/description sources;
public availability alone does not establish redistribution terms.

This task preserves the investigation as documentation only. It does not
validate live OAI/NCIP availability, map all Axiell libraries to Solus or fetch
national-library data at integration runtime.
