# Source-data licence and unofficial mirror status

Verified on **6 October 2026**. This records the evidence and scope of our reuse; it is not a legal opinion about every possible downstream use.

**sondreskarsten/brreg-json-fetcher is an independent, unofficial mirror and transformation of public data supplied by Brønnøysundregistrene.** It is not an official registry, is not affiliated with or endorsed by Brønnøysundregistrene, and does not replace its current records.

> Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene.

The applicable source-data licence is [Norsk lisens for offentlige data (NLOD) 2.0](https://data.norge.no/nlod/no/2.0). We preserve the original provider's licence and attribution, rather than claiming to grant its rights ourselves.

## What establishes the licence

| Evidence | Finding and scope |
| --- | --- |
| [Official data.norge.no Regnskapsregisteret catalogue](https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret) | The **Nøkkeltall fra Årsregnskapet** distribution names “Norwegian Licence for Open Government Data” and links to the controlled identifier `http://publications.europa.eu/resource/authority/licence/NLOD_2_0`. The associated API points to `https://data.brreg.no/regnskapsregisteret/regnskap`, the endpoint used here. |
| [BRREG's checked-in API specification, pinned to the reviewed commit](https://github.com/brreg/regnskapsregister-api/blob/50cb8d1bd29eafe2083fd3880fec1b4c00949815/src/main/resources/specification/regnskapsregister.json) | `info.license.url` is `http://data.norge.no/nlod/no/2.0`. This corroborates the catalogue. This older specification is not our authority for current response shape or API availability. |
| [Current runtime OpenAPI](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs) | Version 1.1.16 was served at review time. Its `info` omits a licence field; we therefore do **not** claim the runtime specification alone establishes the licence. |
| [Enhetsregisteret API documentation](https://data.brreg.no/enhetsregisteret/api/docs/index.html) | Explicitly links “Norsk lisens for offentlige data (NLOD)” to `https://data.norge.no/nlod/no/2.0`. This is the separate licence evidence for the entity-register seed download. |
| [BRREG's datasets and APIs page](https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/) | States “Datasettene følger Norsk lisens for åpne data (NLOD).” This corroborates its open-data policy; the distribution-specific evidence above is more precise. |

**Conclusion:** the accounts key-figures API and the open Enhetsregisteret seed have explicit NLOD 2.0 evidence. This does not establish a blanket licence for all Regnskapsregisteret products. The catalogue separately lists document/PDF and paid subscription distributions without the same explicit licence declaration. This collector does not download annual-account PDFs, notes or paid feeds. A future expansion to those products needs a separate check. Catalogue descriptions of API maintenance and coverage can lag live behaviour; licensing evidence must not be read as a service guarantee.

## Permission and conditions

[NLOD 2.0](https://data.norge.no/nlod/no/2.0) provides:

- **Section 2:** royalty-free permission to copy, use, adapt, combine and redistribute the covered information, in any medium and for any purpose, subject to its conditions. It does not allow us to sublicense or transfer the provider's licence.
- **Section 5:** identify the provider, link the licence and source where practicable, and clearly disclose changes. Its commentary does not require attribution in every individual data cell; attribution must be easy to find. We include it in this document, the README, release notes, a checksummed `DATA_NOTICE.md` asset and machine-readable manifest provenance.
- **Section 6:** do not misrepresent the information or imply the provider endorses the mirror or its users.
- **Sections 7–8:** the information is provided as-is; there is no guarantee of accuracy, currency or service availability.
- **Section 3:** personal data without the required lawful basis, confidentiality, third-party rights and certain other protected material are excluded. Public availability is not a universal permission to process personal data.
- **Section 11:** Norwegian law governs the licence, with its stated jurisdiction provisions. We do not invent a different governing-law clause for the source data.

Changes by **sondreskarsten/brreg-json-fetcher**: monthly collection; selection of AS/ASA with a reported annual-account year; JSON-to-CSV conversion; one filing per row; dotted column names; added provenance, fiscal-year and observation fields; compression, partitioning and packaging. An organisation's number and journal number repeat as needed for separate filings. Blank CSV leaves may represent missing or null source values; complete filing JSON preserves the distinction. Values are in the source currency, not converted to NOK. The collection window can span several days and is not a simultaneous month-end valuation.

The accounts selection is AS/ASA-only, but **the original retained Enhetsregisteret download is the whole main-entity register**, including other legal forms and source fields. The SQLite checkpoint also retains registry and response history. Do not assume these assets contain only corporate financial figures or that NLOD alone resolves personal-data obligations. Anyone redistributing or otherwise processing personal information must assess their purpose and lawful basis under the applicable rules. This verification does not assert a particular GDPR basis for every record or use.

## Norwegian legal context

The licence is the specific reuse evidence. Public-access legislation supplies context, but does not replace the licence or override privacy and third-party rights. The provisions below were checked against Lovdata; your [norwegian-laws](https://github.com/sondreskarsten/norwegian-laws) repository was also used as a searchable secondary mirror.

| Provision | Relevance |
| --- | --- |
| [Regnskapsloven § 8-1](https://lovdata.no/lov/1998-07-17-56/§8-1) | Establishes public access to annual accounts and specified related reports. The section also contains exceptions, including rules for branch accounts. It is not a declaration that every document is free of copyright or privacy restrictions. |
| [Regnskapsloven § 8-2](https://lovdata.no/lov/1998-07-17-56/§8-2) | Establishes submission duties to Regnskapsregisteret; it explains the register's collection role, not an independent blanket redistribution licence. |
| [Offentleglova § 7](https://lovdata.no/lov/2006-05-19-16/§7) | Information made accessible under public-access legislation may be used for any purpose unless other legislation or third-party rights prevent it. The qualifying clause matters. |
| [Åndsverkloven § 24](https://lovdata.no/lov/2018-06-15-40/§24) | Protects qualifying databases against certain extraction and reuse. Access to individual facts is not by itself permission for every bulk database use; NLOD expressly supplies reuse rights within its scope. |
| [Åndsverkloven § 14](https://lovdata.no/lov/2018-06-15-40/§14) | Excludes laws and certain official-authority documents from copyright protection, subject to its exceptions. Company-filed annual accounts do not automatically become such documents just because a registry holds them. |
| [Personopplysningsloven § 1](https://lovdata.no/lov/2018-06-15-38/§1), GDPR Articles 5–6 | Incorporates the GDPR into Norwegian law. Where information identifies natural persons, lawful processing, purpose, minimisation and other applicable requirements remain relevant. NLOD § 3 expressly preserves this distinction. |

Secondary law texts reviewed at commit [`d08dfb1`](https://github.com/sondreskarsten/norwegian-laws/tree/d08dfb111117dba88758815d0a6ba9c590d7316d/lover): `lov-1998-07-17-56.md`, `lov-2006-05-19-16.md`, `lov-2018-06-15-40.md`, and `lov-2018-06-15-38.md`. This is itself a mirror, not an official legal authority. Check the current Lovdata text and commencement provisions when relying on a rule; listed future amendments are not necessarily in force.

## Data and software are different

This notice concerns the upstream **data**, not a grant of NLOD rights over the collector's source code, dependencies or BRREG's API implementation. No separate collector software licence has been selected in this repository. Public GitHub visibility alone is not a general open-source licence. Dependency licences remain separate.

For data errors, check the current source record and its observation date. For mirror/export errors or attribution concerns, [open an issue](https://github.com/sondreskarsten/brreg-json-fetcher/issues). Do not publish private information in an issue. If material is identified as outside NLOD's scope, the licence's section 3 requires stopping use under the licence and deleting that material; this notice does not claim that immutable release conventions override that obligation.
