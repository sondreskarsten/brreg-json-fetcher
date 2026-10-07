# Changelog

## Unreleased

- Reorient the README toward downloading the completed monthly dataset.
- Link the `gh-pages` lookup site, which lists the latest data release and fetches one organisation's accounts JSON from the BRREG API in the browser.

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
