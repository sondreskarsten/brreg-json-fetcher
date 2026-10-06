# brreg-json-fetcher

Collect a fresh monthly snapshot of Norwegian AS/ASA annual accounts and publish it as a GitHub release. Collection can span multiple runner sessions and multiple days.

## Monthly seed

At the start of each collection month, download the complete Enhetsregisteret main-entity register:

```text
GET https://data.brreg.no/enhetsregisteret/api/enheter/lastned
```

Keep only records where `organisasjonsform.kode` is **AS** or **ASA** and `sisteInnsendteAarsregnskap` is a nonmissing integer year. Missing, null, blank, and NA values are excluded. The seed and its original compressed source download are frozen for the whole collection, even if it runs into the next month.

Every eligible entity is fetched once successfully per cycle, with retries for temporary failures. The collector no longer reads announcements or the accounts API load log. New account submissions are picked up by the next monthly full collection.

The live test on 6 October 2026 downloaded **1,176,724** entity records and selected **402,552 AS** plus **211 ASA** entities. These are observed counts for that download, not hardcoded expectations.

## Multi-day collection on GitHub runners

The **Monthly data collection** workflow runs on `ubuntu-latest`:

1. Inspect the latest monthly data release or recovery checkpoint. If the current month's data release is already complete, stop after reading its manifest.
2. Restore unfinished work. If a new month is due and the previous collection is finished and published, download a fresh seed and queue every eligible entity.
3. Run up to **three one-hour fetch segments**, using four workers. After each segment, publish a durable recovery checkpoint. In-flight requests and export/upload time are additional to the fetch budget; the overall job has a 330-minute limit.
4. If work remains, the next daily continuation restores the queue. Completed entities are not fetched again for that month. Retryable failures remain queued and visibly prevent completion.
5. Once the queue is finished, publish **`data-YYYY-MM`** with the original seed download, account exports, request outcomes, history, and a resumable checkpoint.

The scheduler has a monthly-start trigger on the first day and continuation triggers on the remaining days, at **04:17 UTC** (05:17 Oslo in winter, 06:17 in summer). These are continuation checks, not daily reseeding or daily data releases. When a monthly release is complete, remaining checks that month make no BRREG requests and do not download the large checkpoint.

If October's batch is still running in November, it keeps October's seed and finishes/publishes October first. A subsequent run downloads the current month's seed. Missed historical months cannot be reconstructed from today's register/API; the collector does not manufacture backdated snapshots.

Enable scheduled runs with the repository variable `BRREG_DATA_ENABLED=true` after the workflow is on the default branch. For the first manual run, select `bootstrap: true`; later manual runs resume existing state. The built-in `GITHUB_TOKEN` needs `contents: write`. Runs are serialised to protect the queue.

### Recovery and completion

- `checkpoint-YYYY-MM-...` prereleases contain recovery state. They are not completed monthly datasets. They have no short artifact-retention deadline, so a long collection can resume days or weeks later.
- The first checkpoint for a month also stores the full original Enhetsregisteret download. Later checkpoints reference it by release tag and SHA-256 instead of reuploading it each hour. The final monthly release includes the verified original download again.
- Each response is committed locally. An abrupt runner loss can require repeating work since the last successfully published segment checkpoint; it does not discard earlier segments. Retrying a request preserves response/history identity through hashes and filing IDs.
- A failed checkpoint upload leaves a draft; subsequent runs restore the last published checkpoint. Files left by publication failures are also saved as workflow artifacts for 30 days when possible.
- A crash after the final checkpoint but before the monthly data release is handled on the next run: it publishes that finished month before starting another seed.
- `404` and recognised unsupported accounting plans are recorded terminal outcomes. Network/rate-limit/server failures retain pending work. A finished queue means every seed entity has a terminal outcome, not that every entity returned supported accounts.

The collection window may span days. Each response has an observation timestamp. The monthly dataset is a collection made during that window, **not a simultaneous month-end observation**. The manifest records the seed date and collection start/finish.

## Run locally

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required:

```bash
uv sync --frozen
uv run brreg-fetch collect --workers 4 --max-seconds 3600
uv run brreg-fetch status
# Rerun collect to resume the same month until its queue is finished.
uv run brreg-fetch export --output dist/data --entity-snapshot data/enheter.json.gz
```

State defaults to `data/checkpoint.sqlite3`; the original bulk copy defaults to `data/enheter.json.gz`. Use `--max-entities` for a bounded account sample (the initial source download still covers the full register). `runner.py` and `parser.py` remain compatibility entry points for `collect` and `export`. Use one collector/export process per checkpoint at a time.

For frequent local recovery exports without regenerating all data views:

```bash
uv run brreg-fetch export --checkpoint-only --output dist/checkpoint
```

For a downloaded release:

```bash
(cd downloaded-release && sha256sum -c SHA256SUMS)
uv run brreg-fetch restore --from downloaded-release --state data/checkpoint.sqlite3
```

Restore verifies part checksums, the assembled checksum, SQLite integrity, and schema compatibility. It refuses to overwrite an existing checkpoint. Older change-detection checkpoints are migrated; their filing/response history is preserved, while their old work selection is replaced by a fresh monthly AS/ASA seed.

Exit code `2` means account errors remain; `1` means a source/configuration/export failure. Reaching a segment budget is a successful partial run. Neither a partial run nor an incomplete local export is published as a completed monthly data release.

## Release files

| Asset | Contents |
| --- | --- |
| `enheter.json.gz` | Original full source download used for this month's seed |
| `seed.jsonl.gz` | Frozen eligible AS/ASA seed: orgnr, latest filing year, legal form |
| `accounts.jsonl.gz`, `accounts.parquet` | Successful filings observed in this collection month, with metadata and complete filing JSON |
| `filings-history.jsonl.gz` | Previously observed filing IDs, each with its most recently observed content |
| `responses.jsonl.gz` | Exact distinct response bodies as base64, keyed by SHA-256, including prior revisions and errors |
| `entities.jsonl.gz` | Entity-register eligibility and legal forms |
| `observations.jsonl.gz` | HTTP outcomes, times, cycle identifiers, response hashes, and filing-change counts |
| `work.jsonl.gz` | Remaining work and error messages (empty at successful completion) |
| `checkpoint.sqlite3.gz` | Complete resumable state |
| `manifest.json`, `SHA256SUMS` | Cycle, source provenance, completion, coverage counts, and checksums |

At the start of a new month, the current filing view is cleared and rebuilt from that month's responses; older successes cannot masquerade as new observations. Historical filings and exact responses remain preserved. The internal observation field `generation` identifies the `YYYY-MM` cycle; older migrated observations may contain their original identifier.

Assets exceeding 1 GiB use ordered `.partNNNN` files to stay below GitHub's 2 GiB per-asset limit. The manifest lists part order and full-file checksums. Published monthly releases are immutable; incomplete uploads stay drafts until the full asset set is verified.

Version-matching `v*` tags build a wheel/source **software release draft**, separately from monthly data releases.

## What the accounts API returns

`GET https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}`

OpenAPI version **1.1.16**. Optional parameters are `år` (integer) and `regnskapstype` (`SELSKAP` or `KONSERN`). The year selects the calendar year of `regnskapsperiode.tilDato`, including non-calendar fiscal years and start-up periods spanning more than one year.

| Status | Body and handling |
| --- | --- |
| `200` | A JSON array of filings. Preserve and validate the entire array. |
| `404` | No accounts available through this endpoint. Record the result; retain historical filings. |
| `500` | An error object, potentially including `timestamp`, `status`, `error`, `message`, `path`, `trace`. Preserve it. Recognised unsupported-plan messages are reported separately from transient failures. |
| `429`, transient `5xx`, connection failures | Bounded retries with backoff; unfinished work remains queued. A rate-limit message inside a `200` response is also rejected. |

The supplied observations date a behaviour change to **1 October 2026**: the default response changed from the latest company-level filing to up to three fiscal years per type, KONSERN before SELSKAP, with periods ascending within each type. A live check on 6 October 2026 returned six filings consistent with that behaviour. The collector preserves every returned object and does not rely on the order or a fixed maximum count.

The supplied probes found that explicit year/type requests reveal no years beyond the default response; older years return `404`. Historical coverage therefore starts with what was available at the first collection and grows from observations. The tool does not claim to reconstruct filings that disappeared before collection began.

Since the reported change, unsupported-plan error messages name plans such as `IDEELL`, `VPFO`, `BANK`, `PENSJ`, `SKADE`, `LIV`, `FUNK`, and `BEGREN`. Those errors are not converted into empty successful responses.

A filing contains:

```text
id: integer, unique per filing
journalnr: string
regnskapstype: SELSKAP | KONSERN
virksomhet: { organisasjonsnummer, organisasjonsform, morselskap }
regnskapsperiode: { fraDato, tilDato }
valuta: NOK | USD | EUR | SEK | DKK | GBP | …
avviklingsregnskap: boolean
oppstillingsplan: smaa | store | oevrige
revisjon: { ikkeRevidertAarsregnskap, fravalgRevisjon }
regnkapsprinsipper: { smaaForetak, regnskapsregler }
egenkapitalGjeld: {
  sumEgenkapitalGjeld,
  egenkapital: {
    sumEgenkapital,
    innskuttEgenkapital: { sumInnskuttEgenkaptial },
    opptjentEgenkapital: { sumOpptjentEgenkapital }
  },
  gjeldOversikt: {
    sumGjeld,
    kortsiktigGjeld: { sumKortsiktigGjeld },
    langsiktigGjeld: { sumLangsiktigGjeld }
  }
}
eiendeler: {
  sumEiendeler,
  omloepsmidler: { sumOmloepsmidler },
  anleggsmidler: { sumAnleggsmidler },
  sumBankinnskuddOgKontanter, sumFordringer, sumInvesteringer,
  sumVarer, goodwill
}
resultatregnskapResultat: {
  aarsresultat, ordinaertResultatFoerSkattekostnad, totalresultat,
  ordinaertResultatSkattekostnad, ekstraordinaerePoster,
  skattekostnadEkstraordinaertResultat,
  driftsresultat: {
    driftsresultat,
    driftsinntekter: { sumDriftsinntekter, salgsinntekter },
    driftskostnad: { sumDriftskostnad, loennskostnad }
  },
  finansresultat: {
    nettoFinans,
    finansinntekt: { sumFinansinntekter },
    finanskostnad: {
      sumFinanskostnad, annenRentekostnad, rentekostnadSammeKonsern
    }
  }
}
```

Source spellings such as `regnkapsprinsipper` and `sumInnskuttEgenkaptial` are preserved. `regnskapsregler` may be `regnskapslovenAlminneligRegler`, `forenkletAnvendelseIFRS`, or `IFRS`. Amounts are JSON numbers in full units of `valuta`. An absent leaf is not zero; parent objects can be empty.

The supplied research identifies the five additional asset leaves, the three tax/extraordinary-result leaves, `salgsinntekter`, `loennskostnad`, `annenRentekostnad`, and `rentekostnadSammeKonsern` as additions on 1 October 2026, including retroactive additions to existing filings. The JSON exports retain all fields, including future additions. Parquet discovers the union of field paths across all records before writing, and also includes the full filing in `_meta.filing_json`. Missing and explicit null leaves both become null in flattened columns; the JSON representation preserves the distinction. Mixed-type columns use strings when needed, with exact source values retained in JSON.

The stable **logical account key** is `(organisasjonsnummer, regnskapstype, year(tilDato))`. The **filing identity** is its `id`. A new ID for the same logical key is a resubmission. `journalnr` can be shared by SELSKAP and KONSERN and is not a unique filing key. The collector also hashes content: a changed response with the same ID is recorded as a content revision, not a resubmission.

Other API paths, relative to `/regnskapsregisteret/regnskap`, include `/{orgnr}/{id}`, `/aarsregnskap/kopi/{orgnr}/aar`, `/aarsregnskap/kopi/{orgnr}/{aar}`, `/aarsregnskap/mellombalanse/{orgnr}/aar`, and `/aarsregnskap/mellombalanse/{orgnr}/{id}`. PDF copies and interim-balance retrieval are outside this collector's scope.

## Validation

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv build
```

Tests cover frozen seeds, restart recovery, retries, month boundaries, publication interruption, full-field exports, and source/checkpoint verification. The multi-run lifecycle tests use real SQLite/export/restore operations with simulated source HTTP and GitHub uploads.

The **Live BRREG API sample** workflow remains available on manual dispatch or `api-check-*` tags. It downloads the full seed and fetches five AS plus five ASA entities, retaining actual raw JSON and exports as artifacts. The 6 October test returned **33 filings from eight successful responses**, plus two unsupported BANK-plan responses. It does not launch a full monthly collection.

Sources: [BRREG API repository](https://github.com/brreg/regnskapsregister-api), [live OpenAPI](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs), [entity-register API](https://data.brreg.no/enhetsregisteret/api/docs/index.html).
