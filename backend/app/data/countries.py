"""Country name -> ISO 3166-1 alpha-2 for the names used by OFAC/UN lists (flags, nationalities)."""

COUNTRY_NAME_TO_ISO = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "angola": "AO", "antigua and barbuda": "AG", "argentina": "AR",
    "armenia": "AM", "australia": "AU", "austria": "AT", "azerbaijan": "AZ", "bahamas": "BS", "bahrain": "BH",
    "bangladesh": "BD", "barbados": "BB", "belarus": "BY", "belgium": "BE", "belize": "BZ", "bolivia": "BO",
    "bosnia and herzegovina": "BA", "brazil": "BR", "bulgaria": "BG", "burma": "MM", "myanmar": "MM", "cambodia": "KH",
    "cameroon": "CM", "canada": "CA", "cayman islands": "KY", "central african republic": "CF", "chile": "CL",
    "china": "CN", "colombia": "CO", "comoros": "KM", "congo, democratic republic of the": "CD", "cook islands": "CK",
    "costa rica": "CR", "cote d'ivoire": "CI", "croatia": "HR", "cuba": "CU", "cyprus": "CY", "czech republic": "CZ",
    "denmark": "DK", "djibouti": "DJ", "dominica": "DM", "dominican republic": "DO", "ecuador": "EC", "egypt": "EG",
    "el salvador": "SV", "equatorial guinea": "GQ", "eritrea": "ER", "estonia": "EE", "ethiopia": "ET", "fiji": "FJ",
    "finland": "FI", "france": "FR", "gabon": "GA", "gambia": "GM", "georgia": "GE", "germany": "DE", "ghana": "GH",
    "gibraltar": "GI", "greece": "GR", "guatemala": "GT", "guinea": "GN", "guinea-bissau": "GW", "guyana": "GY",
    "haiti": "HT", "honduras": "HN", "hong kong": "HK", "hungary": "HU", "iceland": "IS", "india": "IN",
    "indonesia": "ID", "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL", "italy": "IT", "jamaica": "JM",
    "japan": "JP", "jordan": "JO", "kazakhstan": "KZ", "kenya": "KE", "kiribati": "KI", "korea, north": "KP",
    "north korea": "KP", "korea, south": "KR", "south korea": "KR", "kuwait": "KW", "kyrgyzstan": "KG", "laos": "LA",
    "latvia": "LV", "lebanon": "LB", "liberia": "LR", "libya": "LY", "lithuania": "LT", "luxembourg": "LU",
    "malaysia": "MY", "maldives": "MV", "mali": "ML", "malta": "MT", "marshall islands": "MH", "mauritania": "MR",
    "mauritius": "MU", "mexico": "MX", "micronesia": "FM", "moldova": "MD", "mongolia": "MN", "montenegro": "ME",
    "morocco": "MA", "mozambique": "MZ", "namibia": "NA", "nauru": "NR", "netherlands": "NL", "new zealand": "NZ",
    "nicaragua": "NI", "niger": "NE", "nigeria": "NG", "niue": "NU", "norway": "NO", "oman": "OM", "pakistan": "PK",
    "palau": "PW", "panama": "PA", "papua new guinea": "PG", "paraguay": "PY", "peru": "PE", "philippines": "PH",
    "poland": "PL", "portugal": "PT", "qatar": "QA", "romania": "RO", "russia": "RU", "russian federation": "RU",
    "saint kitts and nevis": "KN", "saint lucia": "LC", "saint vincent and the grenadines": "VC", "samoa": "WS",
    "san marino": "SM", "sao tome and principe": "ST", "saudi arabia": "SA", "senegal": "SN", "serbia": "RS",
    "seychelles": "SC", "sierra leone": "SL", "singapore": "SG", "slovakia": "SK", "slovenia": "SI",
    "solomon islands": "SB", "somalia": "SO", "south africa": "ZA", "south sudan": "SS", "spain": "ES",
    "sri lanka": "LK", "sudan": "SD", "suriname": "SR", "sweden": "SE", "switzerland": "CH", "syria": "SY",
    "taiwan": "TW", "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH", "togo": "TG", "tonga": "TO",
    "trinidad and tobago": "TT", "tunisia": "TN", "turkey": "TR", "turkiye": "TR", "turkmenistan": "TM", "tuvalu": "TV",
    "uganda": "UG", "ukraine": "UA", "united arab emirates": "AE", "united kingdom": "GB", "united states": "US",
    "uruguay": "UY", "uzbekistan": "UZ", "vanuatu": "VU", "venezuela": "VE", "vietnam": "VN", "yemen": "YE",
    "zambia": "ZM", "zimbabwe": "ZW", "crimea": "UA", "gaza": "PS", "west bank": "PS", "kosovo": "XK", "macau": "MO",
}


def country_to_iso(name: str | None) -> str | None:
    if not name:
        return None
    return COUNTRY_NAME_TO_ISO.get(name.strip().lower())
