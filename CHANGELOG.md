# Changelog

## 0.2.0

- Select the collection universe from the entity register's latest annual-account year.
- Combine year changes and category-70 announcements, gated by the accounts API load log.
- Persist pending signals, load queues, HTTP outcomes, filing identities, and full response history.
- Preserve all SELSKAP/KONSERN periods and evolving fields, including same-ID content revisions.
- Export complete JSONL, dynamically discovered Parquet fields, and checksummed resumable data releases.
- Add tested software and data release workflows for GitHub.
- Replace the GCS/Cloud Run-specific deployment workflow with a local CLI and GitHub release storage.

This is a breaking change: previous GCS environment variables and deployment scripts are no longer used.
