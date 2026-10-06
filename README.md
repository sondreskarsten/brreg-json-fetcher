# brreg-json-fetcher

Determine which Norwegian entities have annual accounts, detect new filings, and preserve what the BRREG accounts API returns. Publish the resulting data and resumable checkpoints as GitHub releases.

## 1. Which orgnr have annual accounts

The source is Enhetsregisteret, the entity register. Its JSON property `sisteInnsendteAarsregnskap` contains the year of the most recent annual accounts received for an entity. The supplied research refers to this property as `sisteinnsendteaarsregnskap`; the collector accepts both spellings.

| Operation | Endpoint |
| --- | --- |
| Daily bulk download of registered main entities | `GET https://data.brreg.no/enhetsregisteret/api/enheter/lastned` |
| One entity | `GET https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}` |

The collection universe consists of entities with a nonblank integer filing year. Blank or absent values are excluded. This is a selection rule based on the entity register; it does not guarantee that the accounts API supports the entity's accounting plan.

A new or changed year is the first change signal. A resubmission for the same year leaves that year unchanged. The collector streams the bulk JSON, compares complete daily snapshots, and commits the new snapshot only after the download has parsed successfully. Entities missing from the latest bulk file or lacking a filing year leave the active universe; their previously collected history remains available.

## 2. Kunngjøringer as the second change signal

Search public announcements at `https://w2.brreg.no/kunngjoring/kombisok.jsp`.

| Parameter | Meaning | Value used |
| --- | --- | --- |
| `datoFra`, `datoTil` | Announcement date range | `dd.mm.yyyy`; one day per query |
| `id_region` | Geographic region | `0` for the whole country; then `100`–`600` and `999` |
| `id_fylke` | County within a region | County code, discovered from the site's county lookup |
| `id_niva1` | Announcement category | `70`, Godkjente årsregnskap |
| `id_niva2` | Subcategory | `- - -` for all, **including the spaces** |
| `id_bransje1` | Industry | `0` for all |
| `spraak` | Language | `no` |

The response is HTML. Links of the form `hent_en.jsp?kid={kid}&sokeverdi={orgnr}` identify an announcement and its entity. The collector deduplicates by `kid`, checks parsed links against the reported hit count, and rejects error pages even when HTTP status is 200.

A search exceeding 5,000 hits is not paginated. `Antall treff overstiger` triggers subdivision by region, then county. If a single county still overflows, the run fails visibly without marking that day complete. It must not silently omit announcements.

Category 70 covers approved annual accounts, including same-year resubmissions and accounts with sustainability reporting. Category 111 is for interim balance sheets and is not used as an annual-accounts change signal. `hent_nr.jsp?orgnr={orgnr}` provides a manual per-entity completeness check.

The supplied nine-month snapshot analysis found a category-70 announcement within a week for approximately 99% of same-year resubmissions, compared with approximately 7% detected through the entity-register year. These are findings from that analysis, not independently reproduced benchmarks or completeness guarantees.

Each run rechecks a seven-day announcement overlap. Days missed between runs are also collected. Duplicate announcements do not create duplicate work. Unanswered signals remain pending indefinitely; a week is a matching window, not an expiry rule.

## 3. When the accounts API can have changed

`GET https://data.brreg.no/regnskapsregisteret/regnskap/log` returns a JSON array of loaded bulk-file names.

The collector uses newly observed file names as the gate for scheduling account fetches. Reordering or removing log entries is not treated as a new load. On a new load, it queues eligible entities that have never been fetched or have unanswered change signals. The first load observed during bootstrap queues the initial universe.

A day with no new file still updates entity and announcement signals, but schedules no new account requests. Unfinished requests already queued for an earlier load can resume, including after network failures or a run budget is reached. The load checkpoint and its work queue are saved together, so an interruption cannot mark a load handled while losing its requests.

This follows the supplied observation that account updates arrive through these loads. It is an operational assumption, not a guarantee made by the API specification. Schema enrichment can change a response without changing its filing ID. Use `--reconcile` on a run that observes a new load to refetch the entire active universe and detect such changes; selective signals alone cannot discover every same-ID content change.

## 4. What the accounts API returns

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

## 5. Putting it together and releasing the results

1. Read the entity snapshot and compare latest filing years.
2. Collect category-70 announcements, including overlap and missed days.
3. Read the account load log. Queue pending entities when a new file appears.
4. Fetch and preserve complete responses. A newly observed ID answers an entity's signal if first observed no earlier than seven days before the signal date; there is no upper time limit. A same-ID content revision is retained but does not answer the signal. Matching at entity level does not prove which specific announcement caused a filing change.
5. Publish exports and a recoverable checkpoint. Restore that checkpoint before the next run.

### Run locally

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required. No Google credentials are needed.

```bash
uv sync --frozen
uv run brreg-fetch collect --workers 4 --max-entities 1000
uv run brreg-fetch status
uv run brreg-fetch export --output dist/data
```

`data/checkpoint.sqlite3` is the default state location. The first collection downloads the full main-entity register even when `--max-entities` limits account requests. Rerun collection with the same state to continue. `--max-seconds` stops between bounded request batches. Exit code `2` means account fetch errors remain; code `1` means a source, configuration, or export failure. Reaching a count/time budget is a successful partial run, clearly marked `complete: false` in its manifest. Run one collector/export process per checkpoint at a time.

For a full refresh on a newly observed load:

```bash
uv run brreg-fetch collect --reconcile
```

If no new load exists, that invocation does not schedule a refresh; run it again when a new load is available. `runner.py` and `parser.py` are compatibility entry points for `collect` and `export`. The former GCS deployment commands and environment variables have been replaced by this workflow.

### GitHub releases

Two workflows use the repository's built-in `GITHUB_TOKEN` with `contents: write`:

- **Software release:** a `v*` tag must match the package version. Tests and lint run before a wheel, source distribution, and checksums are uploaded. The release stays a draft until uploads succeed.
- **Data release:** manually start the workflow with `bootstrap: true` for the first baseline. Later runs restore the most recently published `data-*` checkpoint, including partial prereleases. Set the repository variable `BRREG_DATA_ENABLED=true` to enable the daily schedule at **04:17 UTC** (05:17 Oslo in winter, 06:17 in summer). Overlapping runs are serialised. The scheduled collection has a four-hour account-fetch budget; bootstrap may need several runs.

The data workflow never silently starts over after authentication, download, or checksum failure. The `bootstrap` input only permits a new baseline when a successful release listing contains no published data checkpoint. Releases use unique run tags and do not overwrite earlier releases. A failed upload leaves a draft. Recovery assets are also kept as workflow artifacts for seven days. Partial collections are published as prereleases; collection failures still fail the workflow after preserving the checkpoint. Data releases are not marked GitHub's “latest” software release.

| Asset | Contents |
| --- | --- |
| `accounts.jsonl.gz` | Most recently observed successful filings; each line includes observation metadata and the full filing object |
| `accounts.parquet` | The same current view, with flattened source fields and complete filing JSON |
| `filings-history.jsonl.gz` | Every observed filing ID, retaining its most recently seen content |
| `responses.jsonl.gz` | Every distinct exact response body, base64 encoded and keyed by SHA-256; includes earlier content revisions and error bodies |
| `entities.jsonl.gz` | Entity years and current eligibility |
| `signals.jsonl.gz` | Entity-year and category-70 signals, including answered/pending state |
| `observations.jsonl.gz` | Request status, time, generation, response hash, new-ID and content-change counts |
| `work.jsonl.gz` | Unfinished requests, retry counts, and the most recent failure message |
| `checkpoint.sqlite3.gz` | Complete state for resuming collection |
| `manifest.json`, `SHA256SUMS` | Coverage/status, asset order, byte counts, SHA-256 checksums |

A current row means “last successfully observed,” not “known current at publication.” Consult observation times and error statuses. A `404` removes an entity from the current filing view while preserving history. A failed request retains the previous successful view. Leaving the entity universe also preserves the last observed accounts; join the entity export to restrict to currently eligible entities. A completed queue does not mean all signals were answered or all accounting plans are supported.

Assets larger than 1 GiB are split into ordered `.partNNNN` files, below GitHub's 2 GiB per-asset limit. To restore a downloaded release:

```bash
# Download an explicit data release tag using gh release download first.
(cd downloaded-release && sha256sum -c SHA256SUMS)
uv run brreg-fetch restore --from downloaded-release --state data/checkpoint.sqlite3
```

Restore checks part and whole-file checksums, SQLite integrity, and schema version. It refuses to overwrite existing state. For other split files, concatenate parts in the order recorded by `manifest.json` and verify the full-file SHA-256 before reading.

### Development and sources

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv build
```

Tests use deterministic source fixtures and exercise signal matching, load gates, HTML truncation, full filing preservation, retry/resume behaviour, and release restoration. Live checks are separate and do not run during CI.

- [BRREG accounts API repository](https://github.com/brreg/regnskapsregister-api)
- [Regnskapsregisteret dataset](https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret)
- [Live OpenAPI](https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs)
- [Entity register API](https://data.brreg.no/enhetsregisteret/api/docs/index.html)
- [Announcement search](https://w2.brreg.no/kunngjoring/)
