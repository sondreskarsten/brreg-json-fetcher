"""Register population summaries: every legal form, including ENK, binned for comparison."""

import json
import math
from array import array
from datetime import date

from .export import outcome_label, write_csv

DIMENSIONS = ["organisasjonsform", "fylke", "nace2", "has_employees", "vat_registered"]
TABLES = {
    "register_population": DIMENSIONS,
    "register_by_form": ["organisasjonsform"],
    "register_by_form_fylke": ["organisasjonsform", "fylke"],
    "register_by_form_nace2": ["organisasjonsform", "nace2"],
    "register_by_form_employees_vat": ["organisasjonsform", "has_employees", "vat_registered"],
}
CHANGE_DIMENSIONS = ["organisasjonsform", "fylke", "nace2"]
UNKNOWN = "unknown"
QUANTILES = [("p10", 0.1), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("p90", 0.9)]
MEASURES = ["age_years", "employees", "share_capital"]
FLAGS = [
    "listed",
    "removed",
    "in_fetch_universe",
    "foretaksregisteret",
    "konkurs",
    "under_avvikling",
    "tvangsavvikling",
    "filed_year",
]
OUTCOMES = ["ok", "not_found", "unsupported", "pending", "error", "not_in_universe"]
EXIT_STATUSES = ["deleted", "not_found", "still_registered", "unchecked"]

FYLKER = {
    "03": "Oslo",
    "11": "Rogaland",
    "15": "Møre og Romsdal",
    "18": "Nordland",
    "21": "Svalbard",
    "22": "Jan Mayen",
    "31": "Østfold",
    "32": "Akershus",
    "33": "Buskerud",
    "34": "Innlandet",
    "39": "Vestfold",
    "40": "Telemark",
    "42": "Agder",
    "46": "Vestland",
    "50": "Trøndelag",
    "55": "Troms",
    "56": "Finnmark",
    UNKNOWN: "No Norwegian kommunenummer on the business or postal address",
}

NACE2 = {
    "01": "Crop and animal production, hunting and related service activities",
    "02": "Forestry and logging",
    "03": "Fishing and aquaculture",
    "05": "Mining of coal and lignite",
    "06": "Extraction of crude petroleum and natural gas",
    "07": "Mining of metal ores",
    "08": "Other mining and quarrying",
    "09": "Mining support service activities",
    "10": "Manufacture of food products",
    "11": "Manufacture of beverages",
    "12": "Manufacture of tobacco products",
    "13": "Manufacture of textiles",
    "14": "Manufacture of wearing apparel",
    "15": "Manufacture of leather and related products",
    "16": "Manufacture of wood and of products of wood and cork, except furniture",
    "17": "Manufacture of paper and paper products",
    "18": "Printing and reproduction of recorded media",
    "19": "Manufacture of coke and refined petroleum products",
    "20": "Manufacture of chemicals and chemical products",
    "21": "Manufacture of basic pharmaceutical products and pharmaceutical preparations",
    "22": "Manufacture of rubber and plastic products",
    "23": "Manufacture of other non-metallic mineral products",
    "24": "Manufacture of basic metals",
    "25": "Manufacture of fabricated metal products, except machinery and equipment",
    "26": "Manufacture of computer, electronic and optical products",
    "27": "Manufacture of electrical equipment",
    "28": "Manufacture of machinery and equipment n.e.c.",
    "29": "Manufacture of motor vehicles, trailers and semi-trailers",
    "30": "Manufacture of other transport equipment",
    "31": "Manufacture of furniture",
    "32": "Other manufacturing",
    "33": "Repair and installation of machinery and equipment",
    "35": "Electricity, gas, steam and air conditioning supply",
    "36": "Water collection, treatment and supply",
    "37": "Sewerage",
    "38": "Waste collection, treatment and disposal activities; materials recovery",
    "39": "Remediation activities and other waste management services",
    "41": "Construction of buildings",
    "42": "Civil engineering",
    "43": "Specialised construction activities",
    "45": "Wholesale and retail trade and repair of motor vehicles and motorcycles",
    "46": "Wholesale trade, except of motor vehicles and motorcycles",
    "47": "Retail trade, except of motor vehicles and motorcycles",
    "49": "Land transport and transport via pipelines",
    "50": "Water transport",
    "51": "Air transport",
    "52": "Warehousing and support activities for transportation",
    "53": "Postal and courier activities",
    "55": "Accommodation",
    "56": "Food and beverage service activities",
    "58": "Publishing activities",
    "59": "Motion picture, video and television programme production, sound recording and music publishing",
    "60": "Programming and broadcasting activities",
    "61": "Telecommunications",
    "62": "Computer programming, consultancy and related activities",
    "63": "Information service activities",
    "64": "Financial service activities, except insurance and pension funding",
    "65": "Insurance, reinsurance and pension funding, except compulsory social security",
    "66": "Activities auxiliary to financial services and insurance activities",
    "68": "Real estate activities",
    "69": "Legal and accounting activities",
    "70": "Activities of head offices; management consultancy activities",
    "71": "Architectural and engineering activities; technical testing and analysis",
    "72": "Scientific research and development",
    "73": "Advertising and market research",
    "74": "Other professional, scientific and technical activities",
    "75": "Veterinary activities",
    "77": "Rental and leasing activities",
    "78": "Employment activities",
    "79": "Travel agency, tour operator and other reservation service and related activities",
    "80": "Security and investigation activities",
    "81": "Services to buildings and landscape activities",
    "82": "Office administrative, office support and other business support activities",
    "84": "Public administration and defence; compulsory social security",
    "85": "Education",
    "86": "Human health activities",
    "87": "Residential care activities",
    "88": "Social work activities without accommodation",
    "90": "Creative, arts and entertainment activities",
    "91": "Libraries, archives, museums and other cultural activities",
    "92": "Gambling and betting activities",
    "93": "Sports activities and amusement and recreation activities",
    "94": "Activities of membership organisations",
    "95": "Repair of computers and personal and household goods",
    "96": "Other personal service activities",
    "97": "Activities of households as employers of domestic personnel",
    "98": "Undifferentiated goods- and services-producing activities of private households for own use",
    "99": "Activities of extraterritorial organisations and bodies",
    UNKNOWN: "No naeringskode1 in the register",
}

RULES = [
    ("organisasjonsform", "organisasjonsform.kode from the register; blank is 'unknown'"),
    (
        "fylke",
        (
            "first two digits of forretningsadresse.kommunenummer, else postadresse.kommunenummer, "
            "else 'unknown'"
        ),
    ),
    ("nace2", "first two digits of naeringskode1.kode, else 'unknown'"),
    ("has_employees", "'yes' when antallAnsatte is above zero, else 'no'"),
    ("vat_registered", "registrertIMvaregisteret: 'yes' or 'no'"),
    ("age_years", "(seed date - registreringsdatoEnhetsregisteret) / 365.25"),
    ("employees", "antallAnsatte, summarised only over organisations with at least one"),
    ("share_capital", "kapital.belop in the register's currency, mostly AS"),
    ("listed", "organisation is in this month's register download"),
    (
        "removed",
        (
            "organisation was collected in an earlier month and is absent from this month's "
            "download; it stays in the population and in the fetch universe, so n_listed is the "
            "live register and n = n_listed + n_removed"
        ),
    ),
    ("in_fetch_universe", "organisation was queued for the accounts API this month"),
    (
        "coverage_ratio",
        (
            "n_ok / n: the share of the cell whose accounts the API returned; weight by its inverse "
            "to project the accounts sample onto the register population"
        ),
    ),
    ("entries", "organisations in this month's download that were not in the previous one"),
    (
        "exits",
        (
            "organisations in the previous download that are absent from this month's; exit_* "
            "splits them by the single-entity lookup, 'unchecked' when no lookup was made (ENK "
            "and other organisations outside the fetch universe) or it failed"
        ),
    ),
]


def fylke(kommunenummer):
    code = (kommunenummer or "")[:2]
    return code if code else UNKNOWN


def nace2(naeringskode):
    code = (naeringskode or "")[:2]
    return code if code else UNKNOWN


def yes_no(value):
    return "yes" if value else "no"


def age_years(registered, seed_day):
    try:
        return round(
            (date.fromisoformat(seed_day) - date.fromisoformat(registered)).days / 365.25, 2
        )
    except (TypeError, ValueError):
        return None


class Cell:
    __slots__ = ("filings", "flags", "measures", "n", "outcomes")

    def __init__(self):
        self.n = 0
        self.flags = dict.fromkeys(FLAGS, 0)
        self.outcomes = dict.fromkeys(OUTCOMES, 0)
        self.filings = 0
        self.measures = {name: array("d") for name in MEASURES}


def number(value, digits=2):
    rounded = round(value, digits)
    return int(rounded) if float(rounded).is_integer() else rounded


def describe(values):
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": "", "sd": "", **{q: "" for q, _ in QUANTILES}, "min": "", "max": ""}
    ordered = sorted(values)
    mean = sum(ordered) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in ordered) / (n - 1)) if n > 1 else ""
    out = {"n": n, "mean": number(mean), "sd": number(sd) if sd != "" else ""}
    for name, q in QUANTILES:
        position = (n - 1) * q
        low = math.floor(position)
        high = min(low + 1, n - 1)
        out[name] = number(ordered[low] + (ordered[high] - ordered[low]) * (position - low))
    out["min"] = number(ordered[0])
    out["max"] = number(ordered[-1])
    return out


def stat_columns():
    columns = ["n", "share_of_form", "share_of_total"]
    columns += [f"n_{flag}" for flag in FLAGS]
    for name in MEASURES:
        columns += [
            f"{name}_{k}" for k in ("n", "mean", "sd", *[q for q, _ in QUANTILES], "min", "max")
        ]
    columns += [f"n_{outcome}" for outcome in OUTCOMES]
    columns += ["n_filings", "coverage_ratio"]
    return columns


def entity_rows(state):
    """One row per register entity with this month's accounts outcome and filing count."""
    query = """
        SELECT e.orgnr, e.organisasjonsform, e.year, e.active, e.observed_on, e.first_seen,
               e.register_status, e.kommunenummer, e.naeringskode, e.antall_ansatte, e.mva,
               e.foretaksregisteret, e.konkurs, e.under_avvikling, e.tvangsavvikling,
               e.registreringsdato, e.kapital,
               o.status AS http_status, o.message, w.orgnr AS pending,
               (SELECT count(*) FROM current_filings c WHERE c.orgnr=e.orgnr) AS filings
        FROM entities e
        LEFT JOIN observations o ON o.seq = (
            SELECT max(seq) FROM observations WHERE orgnr=e.orgnr AND generation=?
        )
        LEFT JOIN work w ON w.orgnr=e.orgnr
    """
    yield from state.db.execute(query, (state.get("cycle"),))


def outcome_of(row):
    if not row["active"]:
        return "not_in_universe"
    return outcome_label(row["http_status"], row["message"], row["pending"] is not None)


def new_change():
    return {"entries": 0, "exits": 0, **{f"exit_{s}": 0 for s in EXIT_STATUSES}}


def summarise(state, seed_day):
    tables = {name: {} for name in TABLES}
    changes = {}
    total = 0
    form_totals = {}
    # Entries and exits are relative to the previous download; the first one has none.
    previous_day = state.get("previous_entities_date")
    for row in entity_rows(state):
        total += 1
        form = row["organisasjonsform"] or UNKNOWN
        form_totals[form] = form_totals.get(form, 0) + 1
        dims = {
            "organisasjonsform": form,
            "fylke": fylke(row["kommunenummer"]),
            "nace2": nace2(row["naeringskode"]),
            "has_employees": yes_no((row["antall_ansatte"] or 0) > 0),
            "vat_registered": yes_no(row["mva"]),
        }
        listed = row["observed_on"] == seed_day
        flags = {
            "listed": listed,
            "removed": not listed,
            "in_fetch_universe": bool(row["active"]),
            "foretaksregisteret": bool(row["foretaksregisteret"]),
            "konkurs": bool(row["konkurs"]),
            "under_avvikling": bool(row["under_avvikling"]),
            "tvangsavvikling": bool(row["tvangsavvikling"]),
            "filed_year": row["year"] is not None,
        }
        measures = {
            "age_years": age_years(row["registreringsdato"], seed_day),
            "employees": row["antall_ansatte"] if (row["antall_ansatte"] or 0) > 0 else None,
            "share_capital": row["kapital"],
        }
        outcome = outcome_of(row)
        for name, keys in TABLES.items():
            cells = tables[name]
            key = tuple(dims[k] for k in keys)
            cell = cells.get(key)
            if cell is None:
                cell = cells[key] = Cell()
            cell.n += 1
            for flag, value in flags.items():
                cell.flags[flag] += value
            cell.outcomes[outcome] += 1
            cell.filings += row["filings"]
            for measure, value in measures.items():
                if value is not None:
                    cell.measures[measure].append(float(value))
        entered = previous_day is not None and row["first_seen"] == seed_day
        exited = previous_day is not None and row["observed_on"] == previous_day
        if entered or exited:
            key = tuple(dims[k] for k in CHANGE_DIMENSIONS)
            change = changes.setdefault(key, new_change())
            change["entries"] += entered
            if exited:
                change["exits"] += 1
                status = row["register_status"]
                if status not in ("deleted", "not_found", "still_registered"):
                    status = "unchecked"
                change[f"exit_{status}"] += 1
    return tables, changes, total, form_totals


def table_rows(cells, keys, total, form_totals):
    for key in sorted(cells):
        cell = cells[key]
        row = dict(zip(keys, key, strict=True))
        form = row["organisasjonsform"]
        row.update(
            n=cell.n,
            share_of_form=f"{cell.n / form_totals[form]:.6f}",
            share_of_total=f"{cell.n / total:.6f}",
        )
        for flag in FLAGS:
            row[f"n_{flag}"] = cell.flags[flag]
        for name in MEASURES:
            for k, v in describe(cell.measures[name]).items():
                row[f"{name}_{k}"] = v
        for outcome in OUTCOMES:
            row[f"n_{outcome}"] = cell.outcomes[outcome]
        row["n_filings"] = cell.filings
        row["coverage_ratio"] = f"{cell.outcomes['ok'] / cell.n:.6f}"
        yield row


def change_rows(changes):
    for key in sorted(changes):
        row = dict(zip(CHANGE_DIMENSIONS, key, strict=True))
        row.update(changes[key])
        yield row


def codebook_rows(state):
    labels = json.loads(state.get("organisasjonsform_labels", "{}"))
    for code in sorted(labels):
        yield {"dimension": "organisasjonsform", "code": code, "label": labels[code]}
    yield {
        "dimension": "organisasjonsform",
        "code": UNKNOWN,
        "label": "No legal form in the register",
    }
    for code, label in FYLKER.items():
        yield {"dimension": "fylke", "code": code, "label": label}
    for code, label in NACE2.items():
        yield {"dimension": "nace2", "code": code, "label": label}
    for value in ("yes", "no"):
        yield {
            "dimension": "has_employees",
            "code": value,
            "label": "antallAnsatte above zero" if value == "yes" else "no registered employees",
        }
        yield {
            "dimension": "vat_registered",
            "code": value,
            "label": "registrertIMvaregisteret " + value,
        }
    for name, rule in RULES:
        yield {"dimension": "rule", "code": name, "label": rule}


def export_population(state, destination, max_bytes):
    """Write the population tables, the monthly entries/exits and the codebook."""
    seed_day = state.get("entities_date", "")
    tables, changes, total, form_totals = summarise(state, seed_day)
    columns = stat_columns()
    dataset = {
        "snapshot_date": seed_day,
        "previous_snapshot_date": state.get("previous_entities_date"),
        "entities": total,
        "tables": {},
    }
    for name, keys in TABLES.items():
        dataset["tables"][name] = write_csv(
            table_rows(tables[name], keys, total, form_totals),
            [*keys, *columns],
            destination,
            name,
            max_bytes,
        )
    dataset["tables"]["register_changes"] = write_csv(
        change_rows(changes),
        [*CHANGE_DIMENSIONS, "entries", "exits", *[f"exit_{s}" for s in EXIT_STATUSES]],
        destination,
        "register_changes",
        max_bytes,
    )
    dataset["tables"]["register_codebook"] = write_csv(
        codebook_rows(state),
        ["dimension", "code", "label"],
        destination,
        "register_codebook",
        max_bytes,
    )
    by_form = {}
    enk = new_change()
    for key, change in changes.items():
        form = key[0]
        summary = by_form.setdefault(form, {"entries": 0, "exits": 0})
        summary["entries"] += change["entries"]
        summary["exits"] += change["exits"]
        if form == "ENK":
            for k in enk:
                enk[k] += change[k]
    dataset["changes_by_form"] = dict(sorted(by_form.items()))
    dataset["enk"] = {"n": form_totals.get("ENK", 0), **enk}
    dataset["by_form"] = dict(sorted(form_totals.items()))
    return dataset
