"""Blockchain tracker rules: OFAC address extraction, chain detection, transaction risk scoring, clustering.

Pure functions - the bot supplies the data.
"""

import hashlib
import re
from dataclasses import dataclass

OFAC_ADDRESS_RE = re.compile(r"Digital Currency Address - (?P<symbol>[A-Z0-9]{2,6}) (?P<address>[A-Za-z0-9]{20,120})")

# OFAC symbol -> blockchain (when the address format is not enough on its own)
SYMBOL_CHAIN = {
    "XBT": "bitcoin", "BTC": "bitcoin", "BCH": "bitcoin_cash", "LTC": "litecoin", "ETH": "ethereum", "ETC": "ethereum_classic", "USDC": "ethereum",
    "USDT": "ethereum", "DAI": "ethereum", "BNB": "bsc", "BSC": "bsc", "ARB": "arbitrum", "TRX": "tron", "XMR": "monero", "ZEC": "zcash",
    "DASH": "dash", "XVG": "verge", "BTG": "bitcoin_gold", "SOL": "solana", "DOGE": "dogecoin", "XRP": "ripple", "TON": "ton",
}
TRACEABLE = {"bitcoin", "ethereum", "tron"}  # chains the bot can poll without credentials


@dataclass(frozen=True)
class SanctionedAddress:
    blockchain: str
    address: str
    symbol: str


def detect_chain(symbol: str, address: str) -> str:
    """Address shape wins over the ticker: OFAC lists USDT on both Ethereum (0x...) and Tron (T...)."""
    if address.startswith("0x") and len(address) == 42:
        return "bsc" if symbol in ("BNB", "BSC") else ("arbitrum" if symbol == "ARB" else "ethereum")
    if address.startswith("T") and len(address) == 34:
        return "tron"
    if symbol in ("XBT", "BTC") or (address.startswith(("bc1", "1", "3")) and symbol in ("XBT", "BTC", "USDT") and 26 <= len(address) <= 62):
        return "bitcoin"
    if address.startswith("bnb1"):
        return "bnb_beacon"
    if symbol in ("ETH", "USDT", "USDC", "ETC", "BNB", "ARB", "DAI"):
        return "unknown"  # ticker says EVM but the address is not 0x + 40 hex (typo / truncated listing)
    return SYMBOL_CHAIN.get(symbol, symbol.lower())


def parse_ofac_addresses(remarks: str | None) -> list[SanctionedAddress]:
    if not remarks:
        return []
    out: list[SanctionedAddress] = []
    seen: set[tuple[str, str]] = set()
    for match in OFAC_ADDRESS_RE.finditer(remarks):
        symbol, address = match.group("symbol"), match.group("address")
        chain = detect_chain(symbol, address)
        if chain in ("ethereum", "bsc", "arbitrum", "ethereum_classic"):
            address = address.lower()
        key = (chain, address)
        if key in seen:
            continue
        seen.add(key)
        out.append(SanctionedAddress(chain, address, symbol))
    return out


def normalize_address(blockchain: str, address: str) -> str:
    return address.lower() if blockchain in ("ethereum", "bsc", "arbitrum", "ethereum_classic") else address


# ------------------------------------------------------------- risk scoring
@dataclass
class TxAssessment:
    risk_score: float
    pattern: str
    involves_sanctioned: bool
    involves_mixer: bool
    involves_exchange: bool
    source_entity: str | None
    destination_entity: str | None
    summary: str


def assess_transaction(
    amount_usd: float | None,
    from_labels: list[dict],
    to_labels: list[dict],
    whale_usd: float,
    token: str,
) -> TxAssessment:
    """Combine counterparty labels (wallet_type/owner/label dicts) with size into a risk score and pattern."""

    def kinds(labels: list[dict]) -> set[str]:
        return {lbl.get("wallet_type") for lbl in labels if lbl.get("wallet_type")}

    def name(labels: list[dict]) -> str | None:
        for lbl in labels:
            if lbl.get("owner_name") or lbl.get("label"):
                return lbl.get("owner_name") or lbl.get("label")
        return None

    from_kinds, to_kinds = kinds(from_labels), kinds(to_labels)
    sanctioned = "sanctioned" in from_kinds or "sanctioned" in to_kinds
    mixer = "mixer" in from_kinds or "mixer" in to_kinds
    exchange = "exchange" in from_kinds or "exchange" in to_kinds
    usd = amount_usd or 0.0
    whale = usd >= whale_usd
    if sanctioned and exchange:
        pattern, score = ("exchange_cashout" if "exchange" in to_kinds else "exchange_withdrawal_to_sanctioned"), 0.95
    elif sanctioned and mixer:
        pattern, score = "sanctioned_mixer_usage", 0.95
    elif sanctioned:
        pattern, score = "sanctioned_counterparty", 0.85
    elif mixer:
        pattern, score = "mixer_usage", 0.6 + (0.2 if whale else 0)
    elif whale:
        pattern, score = "whale_transfer", 0.4 + min(0.3, usd / (whale_usd * 20))
    else:
        pattern, score = "watched_wallet_activity", 0.3
    if usd >= whale_usd * 5:
        score = min(1.0, score + 0.05)
    src, dst = name(from_labels), name(to_labels)
    size = f"${usd:,.0f}" if usd else "unknown value"
    summary = f"{pattern.replace('_', ' ')}: {size} {token} from {src or 'unlabelled'} to {dst or 'unlabelled'}"
    return TxAssessment(round(min(score, 1.0), 2), pattern, sanctioned, mixer, exchange, src, dst, summary[:300])


# ---------------------------------------------------------------- clustering
def cospend_cluster(input_addresses: list[str]) -> set[str]:
    """Common-input-ownership heuristic: every input of one Bitcoin transaction is (usually) controlled by one party."""
    return {a for a in input_addresses if a and a not in ("coinbase",)}


def cluster_id(blockchain: str, seed_address: str) -> str:
    return hashlib.sha1(f"{blockchain}:{seed_address}".encode()).hexdigest()[:16]


def usd_value(amount: float | None, token: str, prices: dict[str, float]) -> float | None:
    if amount is None:
        return None
    if token in ("USDT", "USDC", "DAI", "BUSD"):
        return round(amount, 2)
    price = prices.get(token)
    return round(amount * price, 2) if price else None
