# regnskapsregisteret-dataset

**The annual-accounts key figures Regnskapsregisteret publishes, for every organisation it serves, as one monthly CSV download.**

regnskapsregisteret-dataset is a monthly copy of the key figures (nøkkeltall) that Regnskapsregisteret publishes for each organisation: balance sheet, income statement, audit and accounting-principle flags, for company and consolidated accounts. One release per month, checksummed and immutable, with a log of what changed since the month before. It holds what the source API returns: the latest three fiscal years per organisation, and no figures for banks, insurers and other organisations whose accounting plan the API does not support. Those are listed with that outcome instead of being left out.

> Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene.

Unofficial mirror maintained by [sondreskarsten](https://github.com/sondreskarsten). Not operated, approved or endorsed by Brønnøysundregistrene. Sources: [Regnskapsregisteret key-figures distribution](https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret) and [Enhetsregisteret](https://data.brreg.no/enhetsregisteret/api/docs/index.html). Licence: [NLOD 2.0](https://data.norge.no/nlod/no/2.0); see [licence scope and changes made by this mirror](DATA_LICENSE.md).

## Use this instead of looking up companies in bulk

The source API answers one organisation per request. Anyone who needs many companies has to send hundreds of thousands of requests, and so does the next person, and the one after. This dataset does that once a month so nobody else has to.

| | Batch lookups against the API | regnskapsregisteret-dataset |
| --- | --- | --- |
| Effort | about 720,000 requests, five days at a polite rate | one download |
| Load on Brønnøysundregistrene | once per researcher, per project, per rerun | once per month in total |
| History | latest three fiscal years, as they stand today | one release per month since October 2026, so earlier states stay downloadable |
| Corrections | a resubmitted filing silently replaces the old one | the old version stays in the earlier release, and the change log lists every changed field |
| Reproducibility | results depend on the day you ran | cite `data-2026-11`; everyone gets the same checksummed bytes |
| What you did not get | invisible | every organisation has an outcome: accounts, none on file, unsupported accounting plan, left the register and when |
| Representativeness | unknown | population tables for the whole register, ENK included, with coverage per cell for reweighting |

Corrections are not rare. Between the October and November 2026 releases, 390 filings were resubmitted; 313 of them changed reported figures, mostly equity, debt and the annual result. (Counted with the 0.7.0 rules; the published `changelog-2026-11` predates them and labels 9 of these differently.)

**When to call Brønnøysundregistrene instead:** you need one company, you need today's value, or you need something with legal standing. For a single company use the [lookup page](https://sondreskarsten.github.io/brreg-json-fetcher/) or [data.brreg.no](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs) directly.

## Data product definition

| | |
| --- | --- |
| **Product** | A monthly, complete, immutable copy of the annual-accounts key figures (nøkkeltall) that Regnskapsregisteret publishes through its open API |
| **Source** | `data.brreg.no/regnskapsregisteret/regnskap/{orgnr}`, one request per organisation, plus the full Enhetsregisteret download as the list of organisations |
| **Population** | Every organisation in Enhetsregisteret, except sole proprietorships (ENK) without a filed annual account. Organisations that later leave the register are kept |
| **Unit** | One filing: organisation × account type (SELSKAP or KONSERN) × fiscal year |
| **Content per filing** | About 30 key figures: total assets, current and fixed assets, equity, debt, revenue, operating result, financial items, tax, annual result; plus period, currency, accounting plan, audit and accounting-principle flags, filing id and journal number |
| **Depth** | The latest three fiscal years the API returns at collection time. Earlier years exist only in earlier releases |
| **Cadence** | One release per month. The register list is taken at the start of the month and collection takes about five days; each row carries its own observation time |
| **Format** | UTF-8 CSV with header, one file set per release, described by `manifest.json` and verified by `SHA256SUMS` |
| **Stability** | A published release never changes. Columns are the union of fields the source returned that month, so new source fields appear as new columns |
| **Licence** | Source data under NLOD 2.0 with attribution to Brønnøysundregistrene; see `DATA_NOTICE.md` in each release |

**Each month delivers three things:**

| Release | Contents |
| --- | --- |
| `data-YYYY-MM` | `accounts*.csv`, the filings. `observations.csv`, one outcome per organisation: accounts returned, none on file, unsupported accounting plan, and register status. `register_*.csv`, population tables for the whole register, ENK included |
| `changelog-YYYY-MM` | Every difference from the previous month, one row per changed field: new filings, resubmissions, aged-out years, status changes, groups that stopped filing consolidated accounts. Plus the cumulative log |
| `checkpoint-…` (prerelease) | Recovery state of a collection in progress. Not part of the product; ignore these |

**Not in the product:** the full annual accounts, notes, auditor's report or PDF; line items below the key figures; figures for organisations whose accounting plan the source API does not serve (banks, insurers, pension funds and some others), which are listed with that outcome; anything older than the first release, `data-2026-10`, which covered AS and ASA only.

## Get the data

Completed months are published on the [releases page](https://github.com/sondreskarsten/brreg-json-fetcher/releases) with the tag **`data-YYYY-MM`**. Pick the newest `data-` tag; `checkpoint-` prereleases are recovery state for a collection still in progress, and `v*` releases are the collector software. The lookup page lists the latest completed month and its assets automatically.

Direct asset URLs follow this pattern (large CSV datasets use numbered filenames listed in the manifest):

```text
https://github.com/sondreskarsten/brreg-json-fetcher/releases/download/data-YYYY-MM/accounts.csv
https://github.com/sondreskarsten/brreg-json-fetcher/releases/download/data-YYYY-MM/observations.csv
https://github.com/sondreskarsten/brreg-json-fetcher/releases/download/data-YYYY-MM/manifest.json
```

```bash
TAG=data-2026-11  # Choose an existing completed data release.
BASE="https://github.com/sondreskarsten/brreg-json-fetcher/releases/download/$TAG"
curl -fSLO "$BASE/manifest.json"
# The manifest names every independently readable CSV, including split files.
python3 - <<'PYCSV' > csv-files.txt
import json
with open("manifest.json") as source:
    dataset = json.load(source)["dataset"]
for table in ("accounts", "observations"):
    for name in dataset[table]["files"]:
        print(name)
PYCSV
while IFS= read -r file; do
  curl -fSLO "$BASE/$file" || exit 1
done < csv-files.txt
for file in DATA_NOTICE.md SHA256SUMS; do
  curl -fSLO "$BASE/$file" || exit 1
done
sha256sum -c --ignore-missing SHA256SUMS
```

| Asset | Contents |
| --- | --- |
| `enheter.json.gz` | Original full source download used for this month's seed |
| `accounts.csv` | One row per returned regnskap (filing); up to six rows per organisation |
| `observations.csv` | One row per eligible organisation: register status, accounts lookup status, actual observation time, response hash and error body |
| `register_population.csv`, `register_by_*.csv` | Population summary of the whole register, ENK included, binned by legal form, county, industry, employees and VAT, with accounts coverage per cell |
| `register_changes.csv`, `register_codebook.csv` | Monthly entries and exits per legal form, county and industry; code labels and binning rules |
| `checkpoint.sqlite3.gz` | Resumable queue, frozen seed, historical filings, observations and exact response bytes |
| `DATA_NOTICE.md` | Source attribution, NLOD link, changes and unofficial-mirror notice |
| `manifest.json`, `SHA256SUMS` | CSV schema, row counts, cycle, provenance, coverage and checksums |

`data-2026-11` covers 719,866 organisations from a register of 1,184,327 and holds 1,240,276 filings. `data-2026-10` covered only AS and ASA with a reported annual-account year: 402,763 organisations. Counts change every month.

### Reading the CSV

CSV uses UTF-8, comma separators, a header, and standard quoting for commas, double quotes and embedded newlines. Account fields are flattened into dotted columns (for example `eiendeler.sumEiendeler`). Columns are discovered from every filing, including newly introduced fields, so read the header rather than relying on a fixed column list. Missing fields are blank. `_meta.orgnr`, `_meta.fiscal_year` and `_meta.snapshot_date` identify the organisation, fiscal year and seed date. `regnskapstype` distinguishes SELSKAP and KONSERN; `id` and `journalnr` are preserved. `_meta.filing_json` preserves the complete filing, including the distinction between absent and null fields. Empty objects and arrays are JSON text.

An organisation returning three years of SELSKAP and three years of KONSERN produces six account rows. A 404 or unsupported plan produces no account row; its outcome remains in `observations.csv`. Banks, insurers, pension funds and other organisations whose accounting plan the BRREG API does not support appear there with `outcome` = `unsupported` and the API's own message (for example `oppstillingsplan som ikke er stottet (BANK)`); organisations with no accounts on file appear with `outcome` = `not_found`.

`observations.csv` also carries three register columns. `register_status` is `listed` when the organisation was in this month's register download. When an organisation collected in an earlier month is missing from the download, it is kept and looked up individually at `GET /enhetsregisteret/api/enheter/{orgnr}`: `deleted` (with `register_deleted_date` = BRREG's `slettedato`), `not_found` (the register no longer knows the number), `still_registered` (the single lookup still returns it, so it was absent from the bulk file for another reason), `lookup_failed` (counted like a failed fetch: the month stays open and the lookup is retried on the next run), or `missing` (not yet looked up; only in incomplete local exports). `register_checked_on` is the date of that status. Removed organisations are still queried for accounts each month, so their last filings stay in `accounts.csv` for as long as the API returns them. A valid empty array also produces no account rows, with a successful observation. The monthly seed date is not the actual lookup date: observation timestamps describe when the data was fetched during the multi-day collection, which can span days. The monthly dataset is a collection made during that window, **not a simultaneous month-end observation**. The manifest records the seed date and collection start/finish.

The stable **logical account key** is `(organisasjonsnummer, regnskapstype, year(tilDato))`. The **filing identity** is its `id`. A new ID for the same logical key is a resubmission. `journalnr` can be shared by SELSKAP and KONSERN and is not a unique filing key.

CSV files exceeding 1 GiB split at record boundaries into `accounts-00001.csv`, etc., each with its own header and checksum. Each file can be read independently; no CSV record is cut in half. Other oversized assets use ordered `.partNNNN` files with assembled checksums described in `manifest.json`. Published releases are immutable.

Downstream use must retain the source attribution and licence link above and identify its own changes; see `DATA_NOTICE.md` in every release and [DATA_LICENSE.md](DATA_LICENSE.md).

### Register population summary

The accounts dataset covers organisations with public filings. To say how that sample relates to the whole register, every data release also summarises the complete Enhetsregisteret download, ENK and all other legal forms included, without any orgnr-level data. `register_population.csv` has one row per cell of `organisasjonsform × fylke × nace2 × has_employees × vat_registered`; `register_by_form.csv`, `register_by_form_fylke.csv`, `register_by_form_nace2.csv` and `register_by_form_employees_vat.csv` are the marginals for spreadsheet use. `fylke` is the first two digits of the business address kommunenummer (postal address as fallback, 2024 county codes), `nace2` the NACE division of `naeringskode1`, `has_employees` whether `antallAnsatte` is above zero. Each row carries `n` and its share of the legal form and of the register, counts for Foretaksregisteret, konkurs, avvikling and a filed year, distributions (n, mean, sd, p10, p25, median, p75, p90, min, max) of age since registration, employees among those with any, and share capital, and the accounts outcome counts for the cell (`n_ok`, `n_not_found`, `n_unsupported`, `n_pending`, `n_error`, `n_not_in_universe`), the number of filings and `coverage_ratio = n_ok / n`. Weighting the accounts sample by the inverse coverage ratio projects it onto the register population.

Organisations collected in an earlier month that have since left the register stay in the population, so `n_listed` is this month's live register and `n_removed` the retained departures; `n = n_listed + n_removed`. `register_changes.csv` counts, per legal form, county and industry, organisations in this month's download that were not in the previous one, and organisations in the previous download that are absent now, the latter split by the single-entity lookup (`deleted`, `not_found`, `still_registered`, or `unchecked` for ENK and other organisations outside the fetch universe). The first download has no predecessor and logs no changes. A checkpoint migrated from an older schema publishes its population tables from the first seed taken with the new code onward. `register_codebook.csv` lists the codes with labels and the binning rules. Small cells are not suppressed: the register is public and the tables hold no orgnr. The manifest's `population` section repeats the totals by form and the ENK entries and exits.

### Change log between months

Every completed month after the first also publishes **`changelog-YYYY-MM`**, built by comparing the new `data-YYYY-MM` release with the previous month's data release. It is shaped like an update feed: one row per field operation, and the rows of one transition share an `event_id`. `changes-YYYY-MM.csv` holds that month's events; `changes.csv` is the cumulative log since the first comparison, with `event_id` continuing across months.

Columns: `event_id, release, orgnr, regnskapstype, fiscal_year, endringstype, journalnr_old, journalnr_new, id_old, id_new, op, path, old_value, new_value`. The unit is `orgnr × regnskapstype × fiscal year`; `id` and `journalnr` ride along as attributes. `journalnr` is ten digits, the year Regnskapsregisteret received the submission followed by a sequence number, so a new `journalnr` is a new submission.

| `endringstype` | Meaning | Rows |
| --- | --- | --- |
| `Ny` | The key was not in the prior release | one `add` row; `new_value` is the filing's SHA-256 in that month's `accounts.csv` |
| `Resubmitted` | Same key, new `journalnr` or `id` | one `replace`/`add`/`remove` row per changed field; a single row with empty `op` when the structured figures are identical |
| `Revised` | Same key, same `journalnr` and `id`, a value differs | one row per changed field; the API cannot tell a BRREG re-extraction from an upstream correction |
| `KeyChanged` | A filing moved to another fiscal year under the same `journalnr` | field rows, including `regnskapsperiode.tilDato` |
| `AgedOut` | The key left the response because a newer year arrived and the API returns the latest three fiscal years across both account types | one `remove` row |
| `Sletting` | The key left the response for any other reason, for example the API now answers 404 | one `remove` row |
| `KonsernEnded` | The submission for this fiscal year has company accounts but no consolidated accounts, and the year before had both. Logged on the SELSKAP key when that year first appears, or when its KONSERN filing leaves after a resubmission | `konsernregnskap.last_fiscal_year` and the SELSKAP filing's `virksomhet.morselskap`, which says whether the company still reports being a parent |
| `Status` | Organisation-level change in `outcome`, `http_status`, `message`, `organisasjonsform`, `latest_filing_year`, `register_status` or `register_deleted_date` | one row per changed field |

The cumulative file refuses to chain onto a previous change log for any cycle other than the prior data release, so a skipped month cannot leave a silent gap. Two transitions inside one month collapse into one net transition, and a resubmission reversed before the next release is invisible: Regnskapsregisteret has no update feed, so the log records net monthly transitions. A `Revised` event has no date of its own beyond the release month.

## How to cite

Cite the release tag, which is immutable:

> regnskapsregisteret-dataset, release `data-2026-11`. Unofficial monthly mirror of Regnskapsregisteret key figures. Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene. https://github.com/sondreskarsten/brreg-json-fetcher/releases/tag/data-2026-11

## Look up one organisation

[sondreskarsten.github.io/brreg-json-fetcher](https://sondreskarsten.github.io/brreg-json-fetcher/) fetches one organisation's accounts in the browser and offers a per-filing CSV. It also lists the latest monthly release. Details and caveats are in [docs/COLLECTOR.md](docs/COLLECTOR.md#lookup-page).

## How it is made

A scheduled GitHub Actions workflow downloads the full Enhetsregisteret at the start of each month (later if the previous month is still being finished; the seed date is in every release), fetches every eligible organisation once over several days, and publishes the release when the queue is empty. The collector, its recovery behaviour, the source API's quirks and how to run it yourself are documented in [docs/COLLECTOR.md](docs/COLLECTOR.md). Release history of the software is in [CHANGELOG.md](CHANGELOG.md).
