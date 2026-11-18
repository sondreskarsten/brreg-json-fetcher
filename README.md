# Norske årsregnskap

**Last ned regnskapstall for norske virksomheter – gratis CSV, oppdatert hver måned.**

*Norwegian annual accounts — free monthly CSV downloads. [English below](#in-english).*

> Inneholder data under [Norsk lisens for offentlige data (NLOD) 2.0](https://data.norge.no/nlod/no/2.0) tilgjengeliggjort av Brønnøysundregistrene.

Dette er en uoffisiell kopi. Den drives ikke av Brønnøysundregistrene og er ikke godkjent av dem.

## Last ned

**Nyeste utgivelse: [`data-2026-11`](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11)**, publisert 5. november 2026.

- 719 866 organisasjoner er sjekket for regnskap.
- 443 315 av dem har regnskap. De øvrige har ikke regnskap hos kilden, eller bruker en regnskapsplan uten publiserte nøkkeltall.
- 1 240 276 regnskapsrader for de tre siste regnskapsårene.
- Regnskapsfilene er på 2,58 GB, fordelt på tre CSV-deler.

[Åpne utgivelsen](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11) · [Alle utgivelser](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases)

## Hva du får

Nøkkeltall fra årsregnskapene i Regnskapsregisteret, én rad per regnskap. Tallene omfatter blant annet eiendeler, egenkapital, gjeld, driftsinntekter, driftsresultat og årsresultat, for selskapsregnskap og konsernregnskap.

Hver måned kommer en ny utgivelse. En utgivelse endres aldri etter publisering, og hver fil har en kontrollsum. Eldre måneder blir liggende, så du kan gå tilbake til tallene slik de så ut da.

Hver organisasjon som er sjekket, har et registrert utfall. Du ser om regnskap ble funnet, om det ikke finnes, eller om regnskapsplanen ikke har publiserte nøkkeltall.

En egen endringslogg viser hva som er endret fra forrige måned.

## Dekning

- Alle organisasjonsformer i Enhetsregisteret. Enkeltpersonforetak er med bare når de har sendt inn årsregnskap.
- De tre siste regnskapsårene kilden gir ut, hentet på nytt hver måned. I `data-2026-11` er det hovedsakelig 2023, 2024 og 2025.
- Organisasjoner som forsvinner fra registeret, blir stående med status og eventuell slettedato.

Tall for `data-2026-11`:

| | Antall |
| --- | ---: |
| Organisasjoner i registernedlastingen | 1 184 327 |
| Sjekket for regnskap | 719 866 |
| Med regnskap | 443 315 |
| Uten regnskap hos kilden | 275 345 |
| Regnskapsplan uten publiserte nøkkeltall, for eksempel banker og forsikringsselskaper | 1 206 |
| Regnskapsrader, selskap og konsern | 1 240 276 |
| Regnskap | 1 227 343 |
| Regnskap med konsernregnskap | 12 933 |

## Filene

Filnavnene varierer mellom utgivelsene:

| Innhold | `data-2026-10` | `data-2026-11` | Fra `data-2026-12` |
| --- | --- | --- | --- |
| Regnskapstall | `accounts*.csv`, bare AS og ASA | `accounts-00001.csv` til `accounts-00003.csv` | `accounts-0000N.csv` |
| Én rad per organisasjon | `observations.csv` | `observations.csv` | `organisations.csv` |
| Sammendrag av registeret | | `register_*.csv` | |

- **`accounts-0000N.csv`**: regnskapstallene. Hver del har egen overskriftsrad og kan åpnes alene. Legg delene under hverandre for hele tabellen.
- **`observations.csv`**: én rad per sjekket organisasjon, med organisasjonsform, registerstatus og utfallet av oppslaget.
- **`organisations.csv`**: alle organisasjoner i registeret, med navn, organisasjonsform, kommune, næringskode, om de har ansatte, mva-registrering og utfallet av oppslaget.
- **`manifest.json`** beskriver filene, radtallene og kolonnene. **`SHA256SUMS`** har kontrollsummene. **`DATA_NOTICE.md`** har lisens og kildehenvisning.
- **`enheter.json.gz`** er hele registernedlastingen måneden bygger på. **`checkpoint.sqlite3.gz`** er innsamlingens arbeidsdatabase.

Hele `data-2026-11` er på 3,94 GB. Endringsloggen ligger i egne `changelog-YYYY-MM`-utgivelser. Utgivelser som begynner med `checkpoint-`, er ikke datasett og kan ignoreres.

Kolonner og definisjoner står i [docs/DATA.md](docs/DATA.md).

## Kom i gang

Koble regnskapet til organisasjonstabellen med `_meta.orgnr` i regnskapet og `orgnr` i organisasjonstabellen. Velg kolonner etter navn, ikke etter plassering. En tom celle betyr at tallet ikke er rapportert. Den betyr ikke null.

Nyttige kolonner er `journalnr`, `regnskapstype`, `_meta.orgnr`, `_meta.fiscal_year`, `resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter` for driftsinntekter, `resultatregnskapResultat.aarsresultat` for årsresultat og `eiendeler.sumEiendeler` for sum eiendeler.

### Excel

Last ned én del, for eksempel `accounts-00003.csv`, og åpne den direkte. Filene er UTF-8 med komma som skilletegn.

### R

[`examples/enrich.R`](examples/enrich.R) henter regnskapstallene for en liste med organisasjonsnumre fra en utgivelse.

### Kommandolinje

Skriptet laster ned regnskapsfilene, organisasjonstabellen, `SHA256SUMS` og `DATA_NOTICE.md` for en utgivelse og kontrollerer filene. Det virker både for `data-2026-11` og for `data-2026-12` og senere. Lagre det som `last-ned.sh` og kjør `bash last-ned.sh data-2026-11`. Det krever `curl`, `python3` og `sha256sum`.

```bash
#!/usr/bin/env bash
set -euo pipefail
TAG="${1:-data-2026-11}"
BASE="https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/download/$TAG"
curl -fSLO "$BASE/manifest.json"
# Every table in "dataset" that has a "files" list: accounts, and
# observations (up to data-2026-11) or organisations (from data-2026-12).
python3 -c '
import json
with open("manifest.json", encoding="utf-8") as source:
    dataset = json.load(source)["dataset"]
for table in dataset.values():
    if isinstance(table, dict):
        for name in table.get("files", []):
            print(name)
print("SHA256SUMS")
print("DATA_NOTICE.md")
' > files.txt
while IFS= read -r file; do
  curl -fSLO "$BASE/$file"
done < files.txt
sha256sum -c --ignore-missing SHA256SUMS
```

## Endringslogg

Hver måned etter den første får en egen utgivelse, `changelog-YYYY-MM`, som sammenligner månedens data med forrige måned. `changes-YYYY-MM.csv` har månedens endringer, og `changes.csv` har alle måneder så langt. Loggen viser nye regnskap, regnskap som er sendt inn på nytt, endrede tall og regnskap som har falt ut, med gammel og ny verdi for hvert tall. Fra oktober til november 2026 ble 384 regnskap sendt inn på nytt. Se [endringsloggen i docs/DATA.md](docs/DATA.md#change-log-between-months).

## Lisens og kildehenvisning

Dataene er tilgjengeliggjort av Brønnøysundregistrene under [NLOD 2.0](https://data.norge.no/nlod/no/2.0). Når du bruker eller deler dem videre, tar du med kildehenvisningen øverst og lenken til lisensen, og du sier hva du har endret. Hver utgivelse har en `DATA_NOTICE.md` med ordlyden. [DATA_LICENSE.md](DATA_LICENSE.md) beskriver lisensen og hvilke endringer denne kopien gjør i kildedataene.

Oppgi utgivelsen du brukte. Utgivelsesnavnene er permanente:

> Norske årsregnskap, utgivelse `data-2026-11`. Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene. https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11

## Spørsmål og feil

Meld fra ved å opprette en [issue på GitHub](https://github.com/sondreskarsten/regnskapsregisteret-dataset/issues). Er det feil i et selskaps egne tall, er det kilden hos Brønnøysundregistrene som gjelder.

[Oppslagssiden](https://sondreskarsten.github.io/regnskapsregisteret-dataset/) viser nøkkeltallene for én organisasjon i nettleseren. [docs/COLLECTOR.md](docs/COLLECTOR.md) beskriver hvordan dataene samles inn og kontrolleres.

## In English

Inneholder data under [Norsk lisens for offentlige data (NLOD) 2.0](https://data.norge.no/nlod/no/2.0) tilgjengeliggjort av Brønnøysundregistrene. This is an unofficial copy. It is not operated or endorsed by Brønnøysundregistrene.

### Download

The latest release is [`data-2026-11`](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11), published 5 November 2026. It checked 719,866 organisations for accounts. 443,315 of them have accounts. The release holds 1,240,276 account rows for the latest three fiscal years. The accounts files are 2.58 GB in three CSV parts. All releases are on the [releases page](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases).

### Coverage

All legal forms in Enhetsregisteret. Sole proprietorships are included only when they have filed an annual account. Each month covers the latest three fiscal years the source returns, mainly 2023 to 2025 in `data-2026-11`. Of the 719,866 organisations checked, 275,345 have no accounts on file and 1,206 use an accounting plan without published key figures, such as banks and insurers.

### Files

| Content | `data-2026-10` | `data-2026-11` | From `data-2026-12` |
| --- | --- | --- | --- |
| Accounts | `accounts*.csv`, AS and ASA only | `accounts-00001.csv` to `accounts-00003.csv` | `accounts-0000N.csv` |
| One row per organisation | `observations.csv` | `observations.csv` | `organisations.csv` |
| Register summaries | | `register_*.csv` | |

Every release also has `manifest.json`, `SHA256SUMS` and `DATA_NOTICE.md`. The monthly change log is published as `changelog-YYYY-MM`. Column definitions are in [docs/DATA.md](docs/DATA.md).

### Getting started

Join the accounts to the organisation table on `_meta.orgnr` = `orgnr`. Select columns by name. A blank cell means not reported, not zero. In Excel, open one accounts part directly. In R, [`examples/enrich.R`](examples/enrich.R) fetches the accounts for a list of organisation numbers from a release. On the command line, use the script under [Kommandolinje](#kommandolinje). It works for `data-2026-11` and later releases.

### Licence and citation

The data is made available by Brønnøysundregistrene under [NLOD 2.0](https://data.norge.no/nlod/no/2.0). Keep the attribution line and the licence link, and say what you changed. Cite the release tag you used:

> Norske årsregnskap, release `data-2026-11`. Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene. https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11

Questions and errors: open an [issue](https://github.com/sondreskarsten/regnskapsregisteret-dataset/issues).
