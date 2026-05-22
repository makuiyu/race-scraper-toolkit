"""Normalization pipeline.

Cleans and unifies fields across heterogeneous sources:
    * dates             -> ``YYYY-MM-DD``
    * event_type        -> a fixed vocabulary (marathon/half/trail/ultra/...)
    * country           -> ISO 3166-1 alpha-2 (handling IOC alpha-3 inputs)
    * event_status      -> a fixed vocabulary, derived from dates if missing
    * list fields       -> always lists (never ``None``)

The country handling is the trickiest piece: World Athletics uses IOC alpha-3
codes (e.g. ``CHN``), UTMB uses full names (``China``), and AIMS uses display
names too. We translate everything to ISO alpha-2 (``CN``).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import scrapy

logger = logging.getLogger(__name__)

_EVENT_TYPE_MAP: dict[str, str] = {
    "road race": "marathon",
    "road running": "marathon",
    "marathon": "marathon",
    "half_marathon": "half_marathon",
    "half marathon": "half_marathon",
    "half-marathon": "half_marathon",
    "trail run": "trail",
    "trail running": "trail",
    "trail": "trail",
    "ultra": "ultra",
    "ultramarathon": "ultra",
    "ultra trail": "ultra",
    "ironman": "triathlon_full",
    "full distance triathlon": "triathlon_full",
    "70.3": "triathlon_70_3",
    "half ironman": "triathlon_70_3",
    "triathlon": "triathlon_full",
}

# Hand-curated full-name -> ISO alpha-2 for the most common race countries.
# This replaces `pycountry` to keep the dependency footprint small.
_COUNTRY_NAME_TO_ALPHA2: dict[str, str] = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "andorra": "AD",
    "angola": "AO", "argentina": "AR", "armenia": "AM", "australia": "AU",
    "austria": "AT", "azerbaijan": "AZ", "bahrain": "BH", "bangladesh": "BD",
    "belarus": "BY", "belgium": "BE", "belize": "BZ", "benin": "BJ",
    "bhutan": "BT", "bolivia": "BO", "botswana": "BW", "brazil": "BR",
    "brunei": "BN", "bulgaria": "BG", "burkina faso": "BF", "burundi": "BI",
    "cambodia": "KH", "cameroon": "CM", "canada": "CA", "chad": "TD",
    "chile": "CL", "china": "CN", "colombia": "CO", "congo": "CG",
    "costa rica": "CR", "croatia": "HR", "cuba": "CU", "cyprus": "CY",
    "czech republic": "CZ", "czechia": "CZ", "denmark": "DK",
    "dominican republic": "DO", "ecuador": "EC", "egypt": "EG",
    "el salvador": "SV", "estonia": "EE", "ethiopia": "ET", "finland": "FI",
    "france": "FR", "gabon": "GA", "georgia": "GE", "germany": "DE",
    "ghana": "GH", "greece": "GR", "guatemala": "GT", "haiti": "HT",
    "honduras": "HN", "hong kong": "HK", "hungary": "HU", "iceland": "IS",
    "india": "IN", "indonesia": "ID", "iran": "IR", "iraq": "IQ",
    "ireland": "IE", "israel": "IL", "italy": "IT", "jamaica": "JM",
    "japan": "JP", "jordan": "JO", "kazakhstan": "KZ", "kenya": "KE",
    "korea": "KR", "south korea": "KR", "north korea": "KP", "kuwait": "KW",
    "kyrgyzstan": "KG", "laos": "LA", "latvia": "LV", "lebanon": "LB",
    "libya": "LY", "lithuania": "LT", "luxembourg": "LU", "macau": "MO",
    "macao": "MO", "madagascar": "MG", "malaysia": "MY", "mali": "ML",
    "malta": "MT", "mexico": "MX", "moldova": "MD", "monaco": "MC",
    "mongolia": "MN", "montenegro": "ME", "morocco": "MA", "mozambique": "MZ",
    "myanmar": "MM", "namibia": "NA", "nepal": "NP", "netherlands": "NL",
    "new zealand": "NZ", "nicaragua": "NI", "niger": "NE", "nigeria": "NG",
    "norway": "NO", "oman": "OM", "pakistan": "PK", "panama": "PA",
    "paraguay": "PY", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "puerto rico": "PR", "qatar": "QA", "romania": "RO",
    "russia": "RU", "rwanda": "RW", "san marino": "SM", "saudi arabia": "SA",
    "senegal": "SN", "serbia": "RS", "singapore": "SG", "slovakia": "SK",
    "slovenia": "SI", "south africa": "ZA", "spain": "ES", "sri lanka": "LK",
    "sudan": "SD", "sweden": "SE", "switzerland": "CH", "syria": "SY",
    "taiwan": "TW", "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH",
    "togo": "TG", "tunisia": "TN", "turkey": "TR", "türkiye": "TR",
    "uganda": "UG", "ukraine": "UA", "united arab emirates": "AE", "uae": "AE",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "united states": "US", "united states of america": "US", "usa": "US",
    "uruguay": "UY", "uzbekistan": "UZ", "venezuela": "VE", "vietnam": "VN",
    "yemen": "YE", "zambia": "ZM", "zimbabwe": "ZW",
    # Misc aliases.
    "中国": "CN", "日本": "JP",
}

# fmt: off
# IOC alpha-3 codes used by World Athletics. These differ from ISO alpha-3
# in ~41 cases (e.g. CHN/CHN matches, but GER<->DEU, NED<->NLD, SUI<->CHE).
_IOC_ALPHA3: dict[str, str] = {
    "AFG": "AF", "ALB": "AL", "ALG": "DZ", "AND": "AD", "ANG": "AO",
    "ANT": "AG", "ARG": "AR", "ARM": "AM", "ARU": "AW", "AUS": "AU",
    "AUT": "AT", "AZE": "AZ", "BAH": "BS", "BAN": "BD", "BAR": "BB",
    "BDI": "BI", "BEL": "BE", "BEN": "BJ", "BER": "BM", "BHU": "BT",
    "BIH": "BA", "BIZ": "BZ", "BLR": "BY", "BOL": "BO", "BOT": "BW",
    "BRA": "BR", "BRN": "BH", "BRU": "BN", "BUL": "BG", "BUR": "BF",
    "CAF": "CF", "CAM": "KH", "CAN": "CA", "CAY": "KY", "CGO": "CG",
    "CHA": "TD", "CHI": "CL", "CHN": "CN", "CIV": "CI", "CMR": "CM",
    "COD": "CD", "COK": "CK", "COL": "CO", "COM": "KM", "CPV": "CV",
    "CRC": "CR", "CRO": "HR", "CUB": "CU", "CYP": "CY", "CZE": "CZ",
    "DEN": "DK", "DJI": "DJ", "DMA": "DM", "DOM": "DO", "ECU": "EC",
    "EGY": "EG", "ERI": "ER", "ESA": "SV", "ESP": "ES", "EST": "EE",
    "ETH": "ET", "FIJ": "FJ", "FIN": "FI", "FRA": "FR", "FSM": "FM",
    "GAB": "GA", "GAM": "GM", "GBR": "GB", "GBS": "GW", "GEO": "GE",
    "GEQ": "GQ", "GER": "DE", "GHA": "GH", "GIB": "GI", "GRE": "GR",
    "GRN": "GD", "GUA": "GT", "GUI": "GN", "GUM": "GU", "GUY": "GY",
    "HAI": "HT", "HKG": "HK", "HON": "HN", "HUN": "HU", "INA": "ID",
    "IND": "IN", "IRI": "IR", "IRL": "IE", "IRQ": "IQ", "ISL": "IS",
    "ISR": "IL", "ISV": "VI", "ITA": "IT", "IVB": "VG", "JAM": "JM",
    "JOR": "JO", "JPN": "JP", "KAZ": "KZ", "KEN": "KE", "KGZ": "KG",
    "KIR": "KI", "KOR": "KR", "KOS": "XK", "KSA": "SA", "KUW": "KW",
    "LAO": "LA", "LAT": "LV", "LBA": "LY", "LBR": "LR", "LCA": "LC",
    "LES": "LS", "LIB": "LB", "LIE": "LI", "LTU": "LT", "LUX": "LU",
    "MAC": "MO", "MAD": "MG", "MAR": "MA", "MAS": "MY", "MAW": "MW",
    "MDA": "MD", "MDV": "MV", "MEX": "MX", "MGL": "MN", "MHL": "MH",
    "MKD": "MK", "MLI": "ML", "MLT": "MT", "MNE": "ME", "MON": "MC",
    "MOZ": "MZ", "MRI": "MU", "MSR": "MS", "MTN": "MR", "MYA": "MM",
    "NAM": "NA", "NCA": "NI", "NED": "NL", "NEP": "NP", "NGR": "NG",
    "NIG": "NE", "NOR": "NO", "NRU": "NR", "NZL": "NZ", "OMA": "OM",
    "PAK": "PK", "PAN": "PA", "PAR": "PY", "PER": "PE", "PHI": "PH",
    "PLE": "PS", "PLW": "PW", "PNG": "PG", "POL": "PL", "POR": "PT",
    "PRK": "KP", "PUR": "PR", "QAT": "QA", "ROC": "TW", "ROU": "RO",
    "RSA": "ZA", "RUS": "RU", "RWA": "RW", "SAM": "WS", "SEN": "SN",
    "SEY": "SC", "SGP": "SG", "SKN": "KN", "SLE": "SL", "SLO": "SI",
    "SMR": "SM", "SOL": "SB", "SOM": "SO", "SRB": "RS", "SRI": "LK",
    "SSD": "SS", "STP": "ST", "SUD": "SD", "SUI": "CH", "SUR": "SR",
    "SVK": "SK", "SWE": "SE", "SWZ": "SZ", "SYR": "SY", "TAN": "TZ",
    "TGA": "TO", "THA": "TH", "TJK": "TJ", "TKM": "TM", "TLS": "TL",
    "TOG": "TG", "TPE": "TW", "TTO": "TT", "TUN": "TN", "TUR": "TR",
    "TUV": "TV", "UAE": "AE", "UGA": "UG", "UKR": "UA", "URU": "UY",
    "USA": "US", "UZB": "UZ", "VAN": "VU", "VEN": "VE", "VIE": "VN",
    "VIN": "VC", "YEM": "YE", "ZAM": "ZM", "ZIM": "ZW",
}
# fmt: on

_EVENT_STATUS_MAP: dict[str, str] = {
    "upcoming": "upcoming",
    "open": "open",
    "registration_open": "open",
    "closed": "closed",
    "registration_closed": "closed",
    "lottery": "lottery",
    "coming_soon": "upcoming",
    "finished": "finished",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


def _parse_date(raw: str | None) -> str | None:
    """Best-effort date parse. Ambiguous formats (MM/DD vs DD/MM) are *not*
    guessed — those must be handled by the spider before reaching the pipeline.
    """
    if not raw:
        return None
    raw = raw.strip()
    formats = [
        "%Y-%m-%d",       # 2025-01-02
        "%Y%m%d",         # 20250102
        "%B %d, %Y",      # January 2, 2025
        "%b %d, %Y",      # Jan 2, 2025
        "%d %B %Y",       # 2 January 2025
        "%d %b %Y",       # 2 Jan 2025
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_type(raw: str | None) -> str:
    if not raw:
        return "other"
    return _EVENT_TYPE_MAP.get(raw.lower().strip(), "other")


def normalize_country(raw: str | None) -> str | None:
    """Resolve a country reference (name / IOC alpha-3 / ISO alpha-2) to ISO alpha-2.

    Returns ``None`` if the input is empty or unrecognized.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if not stripped:
        return None

    # Already ISO alpha-2?
    if len(stripped) == 2 and stripped.isascii():
        return stripped.upper()

    upper = stripped.upper()
    # IOC alpha-3 (used by World Athletics).
    if len(upper) == 3 and upper in _IOC_ALPHA3:
        return _IOC_ALPHA3[upper]

    # Full name lookup.
    lookup = stripped.lower()
    if lookup in _COUNTRY_NAME_TO_ALPHA2:
        return _COUNTRY_NAME_TO_ALPHA2[lookup]

    logger.debug("unknown country value, dropping: %r", stripped)
    return None


def normalize_status(raw: str | None) -> str:
    if not raw:
        return "upcoming"
    return _EVENT_STATUS_MAP.get(raw.lower().strip(), "upcoming")


def _status_from_dates(item: dict[str, Any]) -> str | None:
    """Derive event_status from dates. Dates are more objective than the
    source's self-reported status. Returns ``None`` if no dates are present.
    """
    today = datetime.now(UTC).date()

    def to_date(raw: object) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            return None

    finish = to_date(item.get("race_end_date")) or to_date(item.get("race_start_date"))
    if finish and finish < today:
        return "finished"

    reg_close = to_date(item.get("registration_close_date"))
    if reg_close and reg_close < today:
        return "closed"

    reg_open = to_date(item.get("registration_open_date"))
    if reg_open and reg_open <= today:
        return "open"

    if finish:
        return "upcoming"

    return None


class NormalizePipeline:
    """Scrapy pipeline applying all field normalizations in one pass."""

    def process_item(self, item: Any, spider: scrapy.Spider | None = None) -> Any:
        # Trim text fields.
        for text_field in ("name", "name_en", "city", "province", "series"):
            value = item.get(text_field)
            if value:
                item[text_field] = str(value).strip()

        # Normalize dates.
        for date_field in (
            "race_start_date",
            "race_end_date",
            "registration_open_date",
            "registration_close_date",
            "lottery_date",
            "result_date",
        ):
            if item.get(date_field):
                item[date_field] = _parse_date(str(item[date_field]))

        if item.get("event_type"):
            item["event_type"] = normalize_type(str(item["event_type"]))

        if item.get("country"):
            item["country"] = normalize_country(str(item["country"]))

        # event_status: prefer source-declared, fall back to date-derived.
        source_status = item.get("event_status")
        if source_status:
            item["event_status"] = normalize_status(str(source_status))
        else:
            item["event_status"] = _status_from_dates(item) or "upcoming"

        # Ensure list fields are lists.
        for list_field in ("registration_urls", "distances", "tags"):
            if not item.get(list_field):
                item[list_field] = []

        return item
