"""Category-70 signals; reject truncated or unrecognised HTML results."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from .client import SourceError

REGIONS = ("100", "200", "300", "400", "500", "600", "999")


@dataclass(frozen=True)
class Announcement:
    kid: str
    orgnr: str


class SearchPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hits = set()

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        parsed = urlsplit(href)
        if not parsed.path.endswith("hent_en.jsp"):
            return
        query = parse_qs(parsed.query)
        kid = query.get("kid", [""])[0]
        orgnr = query.get("sokeverdi", [""])[0]
        if not kid.isdigit() or not re.fullmatch(r"\d{9}", orgnr):
            raise SourceError("Announcement link has an invalid kid or orgnr")
        self.hits.add(Announcement(kid, orgnr))


def parse_page(html):
    page = SearchPage()
    page.feed(html)
    text = " ".join(" ".join(page.text).split())
    if "Antall treff overstiger" in text:
        return None  # Explicit overflow, never an empty result.
    match = re.search(r"Antall treff\s*:?\s*([\d][\d .]*)", text)
    if match:
        count = int(re.sub(r"\D", "", match.group(1)))
    elif re.search(r"ingen (?:kunngjøringer|treff)|søket (?:ditt )?ga ingen", text, re.IGNORECASE):
        count = 0
    else:
        raise SourceError("Unrecognised announcement page (possibly Ugyldig input)")
    if count != len(page.hits):
        raise SourceError(f"Announcement page reports {count} hits; parsed {len(page.hits)}")
    return page.hits


def announcements_for_day(client, day):
    hits = parse_page(client.announcement_html(day))
    if hits is not None:
        return hits
    complete = set()
    for region in REGIONS:
        regional = parse_page(client.announcement_html(day, region))
        if regional is not None:
            complete.update(regional)
            continue
        for county in client.counties(region):
            local = parse_page(client.announcement_html(day, region, county))
            if local is None:
                raise SourceError(
                    f"Announcement search still exceeds 5,000 hits on {day}, "
                    f"region {region}, county {county}; cannot checkpoint an incomplete day"
                )
            complete.update(local)
    return complete
