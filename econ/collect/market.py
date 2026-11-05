"""市场行情：指数、汇率、商品。"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

os.environ.setdefault("TQDM_DISABLE", "1")

import akshare as ak  # noqa: E402

from ..util import now_cn  # noqa: E402

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

MARKET_SYMBOLS = [
    ("sse", "上证指数", "1.000001", 2),
    ("szse", "深证成指", "0.399001", 2),
    ("cyb", "创业板指", "0.399006", 2),
    ("hs300", "沪深300", "1.000300", 2),
    ("hsi", "恒生指数", "100.HSI", 2),
    ("usdcnh", "美元/离岸人民币", "133.USDCNH", 4),
]

FUTURES_SYMBOLS = [
    ("copper", "沪铜主力", "CU0", 0),
    ("brent", "原油(SC)主力", "SC0", 1),
    ("gold", "沪金主力", "AU0", 2),
]


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"mkt_{key}.csv"


def _save(cache_dir: Path, key: str, series: pd.Series) -> None:
    if series is None or series.empty:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), "value": series.to_numpy()}).to_csv(
        _cache_path(cache_dir, key), index=False, encoding="utf-8"
    )


def _load(cache_dir: Path, key: str) -> pd.Series:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return pd.Series(dtype="float64")
    try:
        df = pd.read_csv(path)
        return pd.Series(
            pd.to_numeric(df["value"], errors="coerce").to_numpy(),
            index=pd.to_datetime(df["date"]),
        ).dropna()
    except Exception:  # noqa: BLE001
        return pd.Series(dtype="float64")


def _kline(session: requests.Session, secid: str, timeout: int = 20) -> pd.Series:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "1",
        "beg": "20180101",
        "end": "20500101",
        "lmt": "3000",
    }
    r = session.get(KLINE_URL, params=params, timeout=timeout, headers={"Referer": "https://quote.eastmoney.com/"})
    r.raise_for_status()
    data = r.json().get("data") or {}
    klines = data.get("klines") or []
    rows: list[tuple[pd.Timestamp, float]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 3:
            continue
        try:
            rows.append((pd.Timestamp(parts[0]), float(parts[2])))
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        return pd.Series(dtype="float64")
    rows.sort(key=lambda x: x[0])
    return pd.Series([v for _, v in rows], index=pd.DatetimeIndex([d for d, _ in rows]))


def _futures(symbol: str) -> pd.Series:
    df = ak.futures_main_sina(symbol=symbol, start_date="20180101", end_date=now_cn().strftime("%Y%m%d"))
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    dates = pd.to_datetime(df["日期"], errors="coerce")
    vals = pd.to_numeric(df["收盘价"], errors="coerce")
    out = pd.DataFrame({"date": dates, "value": vals}).dropna()
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    return pd.Series(out["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(out["date"]))


def _change(series: pd.Series, periods: int) -> float | None:
    s = series.dropna()
    if len(s) <= periods:
        return None
    return float((s.iloc[-1] / s.iloc[-1 - periods] - 1.0) * 100.0)


def _snapshot_item(key: str, name: str, series: pd.Series, decimals: int) -> dict[str, Any] | None:
    s = series.dropna()
    if s.empty:
        return None
    return {
        "key": key,
        "name": name,
        "date": s.index[-1].strftime("%Y-%m-%d"),
        "price": float(s.iloc[-1]),
        "chg_1d": _change(s, 1),
        "chg_1m": _change(s, 21),
        "chg_3m": _change(s, 63),
        "decimals": decimals,
    }


def collect_market(cache_dir: Path, session: requests.Session, offline: bool = False) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    series: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    labels: dict[str, str] = {}

    for key, name, secid, _decimals in MARKET_SYMBOLS:
        labels[key] = name
        if offline:
            s = _load(cache_dir, key)
        else:
            try:
                s = _kline(session, secid)
                if s.empty:
                    raise ValueError("empty")
                _save(cache_dir, key, s)
            except Exception as exc:  # noqa: BLE001
                s = _load(cache_dir, key)
                errors[key] = f"{type(exc).__name__}: {exc}"
        series[key] = s

    for key, name, symbol, _decimals in FUTURES_SYMBOLS:
        labels[key] = name
        if offline:
            s = _load(cache_dir, key)
        else:
            try:
                s = _futures(symbol)
                if s.empty:
                    raise ValueError("empty")
                _save(cache_dir, key, s)
            except Exception as exc:  # noqa: BLE001
                s = _load(cache_dir, key)
                errors[key] = f"{type(exc).__name__}: {exc}"
        series[key] = s

    snapshot: list[dict[str, Any]] = []
    for key, name, _secid, decimals in MARKET_SYMBOLS + FUTURES_SYMBOLS:
        item = _snapshot_item(key, labels[key], series.get(key, pd.Series(dtype="float64")), decimals)
        if item:
            snapshot.append(item)

    return {
        "series": series,
        "snapshot": snapshot,
        "errors": errors,
        "ok": any(not s.empty for s in series.values()),
        "fetched_at": now_cn().isoformat(),
    }
