# Changelog

## 0.9.1

- The dataset is presented as **Norske årsregnskap** (Norwegian annual accounts). Release titles, release notes and `DATA_NOTICE.md` use the name. The repository address is unchanged.
- README rewritten: download first, Norwegian with an English section, file names documented per release. The download script works for releases with `observations.csv` and with `organisations.csv`. The detailed column and change-log reference moves to `docs/DATA.md`.
- Add `examples/enrich.R`: fetch the accounts for a list of organisation numbers from a release in R.

## 0.9.0

Change log layout v2. `changelog-2026-12` and later differ from `changelog-2026-11`:

- An event is a change to one regnskap: an organisation and fiscal year, identified by the `journalnr` of its SELSKAP row. The KONSERN row on the same `journalnr` is part of the same event. Before, SELSKAP and KONSERN were logged as separate events.
- New columns `konsern_old` and `konsern_new` say whether the regnskap had consolidated accounts before and after. A resubmission that removes them is `true` to `false` with a `KONSERN` row of `op` = `remove`; one that adds them is `false` to `true`.
- `regnskapstype`, `id_old` and `id_new` now describe the part a row belongs to.
- A KONSERN row the source still returns from an earlier submission is not compared. The manifest counts them as `konsern_rows_from_earlier_submissions`.
- `KonsernEnded` is logged only when a new year arrives without consolidated accounts. Their removal from an existing year is a `Resubmitted` event.
- When the previous published change log has another layout, the release step rebuilds the earlier months from the data releases, so `changes.csv` stays complete.
- October to November 2026 in this layout: 384 `Resubmitted`, of which 6 added consolidated accounts and none removed them; 1,960 `AgedOut`; 47 `KonsernEnded`.

## 0.8.0

Data format v2. Releases from this version differ from `data-2026-11` and earlier:

- `organisations.csv` replaces `observations.csv` and the `register_*.csv` summary tables. It has one row per organisation in the register, sole proprietorships included, with name, legal form, municipality, industry code, `har_registrert_antall_ansatte`, employee count, VAT and Foretaksregisteret registration, status flags, registration date, capital, register status and the accounts outcome. Organisations whose accounts are not requested have `accounts_requested` = `false` and `outcome` = `not_requested`.
- `accounts.csv` starts with its key columns: `journalnr`, `regnskapstype`, `_meta.orgnr`, `_meta.fiscal_year`, period start and end. A row is identified by `journalnr` + `regnskapstype`.
- The manifest's `dataset` section names each table's grain and key, and no longer has a `population` section.
- Checkpoint schema 6 adds the organisation name and the registered-employees flag.

- The repository is renamed to `regnskapsregisteret-dataset`; links, the lookup page address, the citation file and the notice written into each release now use the new name. Old GitHub links redirect.
- README rewritten as a product page: what the dataset is, what you get, key facts at a glance, download steps, file reference, licence and citation.

## 0.7.0

- The project is presented as **regnskapsregisteret-dataset**, a data source. The README leads with a data product definition and why to use the dataset instead of batch lookups against the source API; collector documentation moves to `docs/COLLECTOR.md`. Repository URLs are unchanged until the repository itself is renamed, after which GitHub redirects them.
- Add `CITATION.cff`. Remove the retired Cloud Run entry points `Dockerfile`, `runner.py` and `parser.py`; use `brreg-fetch collect` and `brreg-fetch export`.

- Change log: new `KonsernEnded` event when a company that filed consolidated accounts for one fiscal year files only company accounts for the next. Consolidated accounts are part of the same submission, so their absence is a property of the filing, not a delay.
- Change log: an old KONSERN year that leaves the response because a newer SELSKAP year arrived (or the reverse) is `AgedOut`, not `Sletting`; the API's three-year window is shared across account types. A resubmission that changes the period start is one `Resubmitted` event instead of a `Sletting` plus a `Ny`. `changelog-2026-11` was built before this fix: 25 of its 34 `Sletting` events are aged-out KONSERN years and 9 are period-start resubmissions paired with a `Ny` row.

## 0.6.0

- Publish register population summaries with every data release: `register_population.csv` (organisasjonsform × fylke × NACE division × employees × VAT), four marginal tables, `register_changes.csv` (monthly entries and exits, ENK included, exits split by the single-entity lookup) and `register_codebook.csv`. Every cell carries counts, flags, age, employee and share-capital distributions, and the accounts-API outcome counts and coverage ratio needed to reweight the accounts sample onto the full register.
- Checkpoint schema 5 stores the binning attributes and a first-seen date per entity; schema 4 checkpoints migrate in place and fill the attributes at the next seed.

## 0.5.0

- Publish `changelog-YYYY-MM` after each data release: a field-level log of filings and lookup status compared with the previous month, shaped like an update feed, with a cumulative file across months. Recover a crash between the data release and its change log on the next run.
- Register lookups run on the worker pool within the segment budget, and a failed lookup keeps the month open like a failed fetch.
- Add a change-log smoke test workflow that collects a sample against the live API and compares it with the newest data release.
- Collect every legal form; ENK is included when the register reports a filed annual account (regnskapsloven § 1-2 nr. 11 sole proprietorships). The latest-filed-year filter is removed for all other forms, so unsupported accounting plans (BANK, SKADE, LIV, PENSJ, ...) and organisations without accounts are reported in `observations.csv` instead of being filtered out of the seed.
- Never drop an organisation once collected. One missing from a later register download is kept in the queue and looked up individually; `observations.csv` gains `register_status`, `register_deleted_date` and `register_checked_on`.
- Checkpoint schema 4 adds the register columns; schema 3 checkpoints migrate in place.
- Reorient the README toward downloading the completed monthly dataset.
- Link the `gh-pages` lookup site, which lists the latest data release and offers manually initiated account lookups, parsed previews and per-filing CSV downloads, with public-proxy attribution and response-format caveats.

## 0.4.1

- Document verified NLOD 2.0 source-data licensing and Norwegian legal context.
- Identify the repository and data releases as an unofficial mirror.
- Include attribution, source links and transformation notices in release notes, manifests and checksummed notice assets.

## 0.4.0

- Publish CSV with one row per returned filing, including all SELSKAP/KONSERN years.
- Export lookup coverage and errors in a separate CSV, keeping raw history in the checkpoint.
- Discover all source columns and split large CSV files only at record boundaries.
- Remove the Parquet dependency.

## 0.3.0

- Replace announcement and API-load change detection with a fresh full AS/ASA seed each collection month.
- Freeze the seed across multi-day runs and month boundaries; refetch every eligible entity for the next cycle.
- Save durable recovery checkpoints after one-hour segments and publish one completed monthly data release.
- Recover interrupted final publication before starting a new month's seed, retaining the exact original download.
- Preserve historical accounts while rebuilding the current filing view for each new month.

## 0.2.2

- Recognise both `stottet` and `støttet` in unsupported accounting-plan errors, based on live GitHub-runner responses; avoid retrying these permanent errors.

## 0.2.1

- Seed collection from the downloaded Enhetsregisteret copy, restricted to AS/ASA entities with a nonmissing filed-account year.
- Retain the compressed source download and export the filtered seed with legal form.
- Migrate old checkpoints and refresh eligibility before collection.
- Add a GitHub-hosted live API test that retains returned JSON and Parquet data.

## 0.2.0

- Select the collection universe from the entity register's latest annual-account year.
- Combine year changes and category-70 announcements, gated by the accounts API load log.
- Persist pending signals, load queues, HTTP outcomes, filing identities, and full response history.
- Preserve all SELSKAP/KONSERN periods and evolving fields, including same-ID content revisions.
- Export complete JSONL, dynamically discovered Parquet fields, and checksummed resumable data releases.
- Add tested software and data release workflows for GitHub.
- Replace cloud-specific deployment with a local CLI and GitHub release storage.

This is a breaking change: previous cloud-storage environment variables and deployment scripts are no longer used.
