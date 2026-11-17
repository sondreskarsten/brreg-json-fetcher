# regnskapsregisteret-dataset

**Annual-accounts key figures for every Norwegian organisation that files accounts, as a monthly open dataset.**

Each month this repository publishes one complete, ready-to-use CSV dataset of the key figures (nøkkeltall) from Regnskapsregisteret: assets, equity, debt, revenue, operating result and annual result, for company and consolidated accounts. Alongside it come a record of what changed since the previous month and summary tables of the whole business register, so the figures can be put in context.

`data-2026-11`, the latest release, holds **1,240,276 filings from 719,866 organisations**.

> Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene.

An independent, unofficial mirror maintained by [sondreskarsten](https://github.com/sondreskarsten). Not operated or endorsed by Brønnøysundregistrene.

## What you get

- **The whole population in one table.** Every organisation in Enhetsregisteret with accounts on file, across all legal forms, with the latest three fiscal years each. Open it in Excel, R, Python or a database.
- **A history that does not disappear.** Every month is a separate, permanent release. When a company's figures are corrected or an old year drops out at the source, the earlier state is still here.
- **Corrections you can see.** Companies resubmit accounts. The monthly change log lists each resubmission and every figure that changed, with old and new value. From October to November 2026 that was 390 filings.
- **No silent gaps.** Every organisation has a recorded outcome: accounts returned, no accounts on file, accounting plan not available from the source, or removed from the register and when.
- **Context for your sample.** Summary tables of the full register by legal form, county, industry, employees and VAT registration, sole proprietorships included, show how the organisations with accounts compare with those without.
- **Results others can reproduce.** A release never changes after publication and every file has a checksum. Cite the release tag and anyone can retrieve exactly the same data.

## At a glance

| | |
| --- | --- |
| **Source** | Regnskapsregisteret's open key-figures API and the Enhetsregisteret register download, both from Brønnøysundregistrene |
| **Coverage** | All organisations in Enhetsregisteret except sole proprietorships (ENK) without a filed annual account. Organisations that later leave the register are kept |
| **One row is** | One filing: organisation × account type (company or consolidated) × fiscal year |
| **Figures per filing** | About 30: total, current and fixed assets; equity; short- and long-term debt; revenue; operating result; financial items; tax; annual result. Plus period, currency, audit and accounting-principle flags |
| **Years** | The latest three fiscal years available at the source each month |
| **Updated** | Monthly. The register list is taken at the start of the month; collection takes about five days and every row carries its observation time |
| **Format** | UTF-8 CSV with header, a `manifest.json` describing the files, and `SHA256SUMS` |
| **First release** | `data-2026-10` (limited to AS and ASA). All legal forms from `data-2026-11` |
| **Licence** | NLOD 2.0, with attribution to Brønnøysundregistrene |

### What each month contains

| Release | Contents |
| --- | --- |
| `data-YYYY-MM` | `accounts*.csv`: the filings. `observations.csv`: one outcome per organisation. `register_*.csv`: summary tables of the whole register |
| `changelog-YYYY-MM` | `changes-YYYY-MM.csv`: every difference from the previous month. `changes.csv`: all months so far |
| `checkpoint-…` (prerelease) | Working state of a collection in progress. Not a dataset; ignore these |

### What it does not contain

The full annual accounts, notes, auditor's report and PDF are not included, nor line items below the key figures. Banks, insurers, pension funds and a few other groups use accounting plans the source does not publish key figures for; they are listed in `observations.csv` with that outcome. For a legally authoritative or up-to-the-minute figure for one organisation, consult Brønnøysundregistrene directly.

## Download

1. Open the [releases page](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases) and choose the newest release whose tag starts with `data-`.
2. Download the files you need from its asset list. For most uses that is the `accounts` files and `observations.csv`.
3. For the monthly changes, open the matching `changelog-` release.

The accounts are split into several files of at most 1 GB (`accounts-00001.csv`, `accounts-00002.csv`, …). Each part has its own header and can be opened on its own; stack them for the full table.

<details>
<summary>Download and verify from the command line</summary>

```bash
TAG=data-2026-11  # Choose an existing completed data release.
BASE="https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/download/$TAG"
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

</details>

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

## Licence and attribution

The data is made available by Brønnøysundregistrene under [NLOD 2.0](https://data.norge.no/nlod/no/2.0). If you use or redistribute it, keep the attribution line above and the licence link, and say what you changed. Each release includes a `DATA_NOTICE.md` with the exact wording. [DATA_LICENSE.md](DATA_LICENSE.md) describes the licence scope and the changes this mirror makes to the source data.

## How to cite

Cite the release you used. Release tags are permanent:

> regnskapsregisteret-dataset, release `data-2026-11`. Unofficial monthly mirror of Regnskapsregisteret key figures. Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene. https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11

## More

- **One organisation:** the [lookup page](https://sondreskarsten.github.io/regnskapsregisteret-dataset/) shows a single organisation's key figures in the browser.
- **How the dataset is produced:** [docs/COLLECTOR.md](docs/COLLECTOR.md) documents the collection process, quality checks and the source's behaviour, and how to run it yourself.
- **Questions or errors:** open an [issue](https://github.com/sondreskarsten/regnskapsregisteret-dataset/issues). For an error in a company's own figures, the source record at Brønnøysundregistrene is authoritative.
