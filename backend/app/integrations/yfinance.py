"""Commodity prices via Yahoo Finance (gold, crude, copper futures, ...).

yfinance is synchronous (requests) so calls run in a worker thread.  Intraday
history is limited to the last few days at 1m/5m resolution, which is plenty
for a rolling anomaly baseline.
"""

import asyncio

import pandas as pd
import yfinance as yf

from app.utils.logger import logger

log = logger.bind(component="market")

EXCHANGE_NAME = "yfinance"

# Friendly asset codes for the tickers used in settings.yaml
ASSET_CODES = {"GC=F": "GOLD", "CL=F": "OIL", "HG=F": "COPPER", "SI=F": "SILVER", "NG=F": "NATGAS", "BZ=F": "BRENT", "TTF=F": "TTF"}


def asset_code(ticker: str) -> str:
    return ASSET_CODES.get(ticker, ticker.replace("=F", "").upper())


def _history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    frame = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    return frame if frame is not None else pd.DataFrame()


async def fetch_ohlcv(ticker: str, interval: str = "5m", period: str = "1d") -> list[list]:
    """Return ccxt-style rows ``[[ts_ms, o, h, l, c, v], ...]`` in UTC."""
    frame = await asyncio.to_thread(_history, ticker, period, interval)
    if frame.empty:
        log.warning("yfinance: no {} data for {}", interval, ticker)
        return []
    index = frame.index.tz_convert("UTC") if frame.index.tz is not None else frame.index.tz_localize("UTC")
    rows = []
    for ts, row in zip(index, frame.itertuples(index=False)):
        if pd.isna(row.Close):
            continue
        rows.append([int(ts.timestamp() * 1000), float(row.Open), float(row.High), float(row.Low), float(row.Close), float(row.Volume or 0)])
    return rows


async def fetch_price(ticker: str) -> float | None:
    rows = await fetch_ohlcv(ticker, interval="1m", period="1d")
    return rows[-1][4] if rows else None
