"""Source-data attribution, separate from any licence for this collector's code."""

REPOSITORY = "https://github.com/sondreskarsten/brreg-json-fetcher"
LICENCE_URL = "https://data.norge.no/nlod/no/2.0"
ACCOUNTS_CATALOG = (
    "https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret"
)
ENTITY_DOCUMENTATION = "https://data.brreg.no/enhetsregisteret/api/docs/index.html"
ATTRIBUTION = (
    "Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 "
    "tilgjengeliggjort av Brønnøysundregistrene."
)
NOTICE = f"""# Unofficial BRREG data mirror / Uoffisielt dataspeil

{REPOSITORY} is an independent mirror maintained by sondreskarsten.
It is not operated, approved or endorsed by Brønnøysundregistrene.
Brønnøysundregistrene is the source provider, not the author of this mirror.

{ATTRIBUTION}
Licence: {LICENCE_URL}
Accounts source and licence evidence: {ACCOUNTS_CATALOG}
Accounts API: https://data.brreg.no/regnskapsregisteret/regnskap
Entity-register documentation and licence: {ENTITY_DOCUMENTATION}
Entity source: https://data.brreg.no/enhetsregisteret/api/enheter/lastned

Changes by this mirror: monthly sampling; AS/ASA selection with a reported
annual-account year; conversion of accounts JSON to CSV, one filing per row;
dotted field names; added observation/provenance metadata; compression and
packaging. Missing values in flattened CSV are blank; complete filing JSON
and stored response bytes retain the source representation for inspection.
The retained full entity-register download includes other legal forms too.

The snapshot is collected over a time window, not at one simultaneous instant.
See manifest.json for dates, coverage, pending work and SHA-256 checksums.
Checkpoint prereleases are incomplete recovery state, not finished datasets.
Source data may contain errors, omissions or later revisions. No guarantee of
accuracy, completeness, availability or fitness for a particular purpose is made.

Downstream users must retain source attribution, licence/source links and
identify their own changes; do not imply official endorsement. NLOD's exclusions,
including third-party rights and personal-data requirements, continue to apply.
The source licence comes from Brønnøysundregistrene; this mirror does not
sublicense its rights or apply NLOD to the collector's software.

Verification and legal references:
{REPOSITORY}/blob/main/DATA_LICENSE.md
"""


def data_provenance():
    return {
        "mirror": REPOSITORY,
        "official": False,
        "provider": "Brønnøysundregistrene",
        "licence": "NLOD-2.0",
        "licence_url": LICENCE_URL,
        "attribution": ATTRIBUTION,
        "accounts_catalog": ACCOUNTS_CATALOG,
        "entity_documentation": ENTITY_DOCUMENTATION,
        "notice": "DATA_NOTICE.md",
        "verified_on": "2026-10-06",
    }
