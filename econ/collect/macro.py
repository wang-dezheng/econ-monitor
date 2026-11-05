"""宏观与地产数据采集。"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("TQDM_MININTERVAL", "9999")

import akshare as ak  # noqa: E402

from ..util import (  # noqa: E402
    parse_any_date,
    parse_month_label,
    parse_quarter_label,
    to_monthly,
    to_series,
)


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.csv"


def save_cache(cache_dir: Path, key: str, series: pd.Series) -> None:
    if series is None or series.empty:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), "value": series.to_numpy()})
    df.to_csv(_cache_path(cache_dir, key), index=False, encoding="utf-8")


def load_cache(cache_dir: Path, key: str) -> pd.Series:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return pd.Series(dtype="float64")
    try:
        df = pd.read_csv(path)
        idx = pd.to_datetime(df["date"])
        return pd.Series(pd.to_numeric(df["value"], errors="coerce").to_numpy(), index=idx).dropna()
    except Exception:  # noqa: BLE001
        return pd.Series(dtype="float64")


def _result(key: str, series: pd.Series, source: str, error: str = "", cached: bool = False) -> dict[str, Any]:
    latest = None
    if series is not None and not series.empty:
        latest = series.dropna().index.max()
    return {
        "key": key,
        "series": series if series is not None else pd.Series(dtype="float64"),
        "source": source,
        "error": error,
        "cached": cached,
        "latest": latest,
        "ok": bool(series is not None and not series.empty),
    }


def _run_one(
    key: str,
    label: str,
    fn: Callable[[], pd.Series],
    cache_dir: Path,
    use_cache: bool = True,
) -> dict[str, Any]:
    started = time.time()
    try:
        series = fn()
        if series is not None and not series.empty:
            series = series[~series.index.duplicated(keep="last")].sort_index()
            if use_cache:
                save_cache(cache_dir, key, series)
            return _result(key, series, label)
        raise ValueError("empty series")
    except Exception as exc:  # noqa: BLE001
        cached = load_cache(cache_dir, key) if use_cache else pd.Series(dtype="float64")
        if not cached.empty:
            return _result(key, cached, label, f"{type(exc).__name__}: {exc}", cached=True)
        return _result(key, pd.Series(dtype="float64"), label, f"{type(exc).__name__}: {exc}")
    finally:
        _ = time.time() - started


# ---------------------------- 单个指标 ----------------------------

@lru_cache(maxsize=1)
def _pmi() -> tuple[pd.Series, pd.Series]:
    df = ak.macro_china_pmi()
    mfg = to_series(df, "月份", "制造业-指数")
    non = to_series(df, "月份", "非制造业-指数")
    return mfg, non


def _cpi() -> pd.Series:
    df = ak.macro_china_cpi()
    return to_series(df, "月份", "全国-同比增长")


def _ppi() -> pd.Series:
    df = ak.macro_china_ppi()
    return to_series(df, "月份", "当月同比增长")


def _gdp() -> pd.Series:
    df = ak.macro_china_gdp()
    return to_series(df, "季度", "国内生产总值-同比增长", parser=parse_quarter_label)


def _ip() -> pd.Series:
    df = ak.macro_china_gyzjz()
    return to_series(df, "月份", "同比增长")


def _retail() -> pd.Series:
    df = ak.macro_china_consumer_goods_retail()
    return to_series(df, "月份", "同比增长")


def _fai() -> pd.Series:
    df = ak.macro_china_gdzctz()
    return to_series(df, "月份", "同比增长")


def _exports() -> pd.Series:
    df = ak.macro_china_hgjck()
    return to_series(df, "月份", "当月出口额-同比增长")


def _consumer_confidence() -> pd.Series:
    df = ak.macro_china_xfzxx()
    return to_series(df, "月份", "消费者信心指数-指数值")


@lru_cache(maxsize=1)
def _money() -> tuple[pd.Series, pd.Series]:
    df = ak.macro_china_money_supply()
    m2 = to_series(df, "月份", "货币和准货币(M2)-同比增长")
    m1 = to_series(df, "月份", "货币(M1)-同比增长")
    return m2, m1


def _loan() -> pd.Series:
    df = ak.macro_china_new_financial_credit()
    return to_series(df, "月份", "当月-同比增长")


def _lpr() -> pd.Series:
    df = ak.macro_china_lpr()
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    dates = pd.to_datetime(df["TRADE_DATE"], errors="coerce")
    vals = pd.to_numeric(df["LPR1Y"], errors="coerce")
    out = pd.DataFrame({"date": dates, "value": vals}).dropna()
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    s = pd.Series(out["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(out["date"]))
    return to_monthly(s)


def _rates() -> pd.DataFrame:
    df = ak.bond_zh_us_rate()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    return df.dropna(subset=["日期"]).set_index("日期").sort_index()


def _us_cpi() -> pd.Series:
    df = ak.macro_usa_cpi_yoy()
    s = to_series(df, "时间", "现值")
    return s.dropna()


# ---------------------------- 地产 ----------------------------

def _fetch_house_page(session: requests.Session, page: int, timeout: int) -> list[dict]:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_ECONOMY_HOUSE_PRICE",
        "columns": "REPORT_DATE,CITY,FIRST_COMHOUSE_SAME,FIRST_COMHOUSE_SEQUENTIAL,"
        "SECOND_HOUSE_SAME,SECOND_HOUSE_SEQUENTIAL",
        "pageNumber": str(page),
        "pageSize": "500",
        "sortColumns": "REPORT_DATE,CITY",
        "sortTypes": "-1,-1",
        "source": "WEB",
        "client": "WEB",
    }
    r = session.get(url, params=params, timeout=timeout, headers={"Referer": "https://data.eastmoney.com/"})
    r.raise_for_status()
    payload = r.json()
    return (payload.get("result") or {}).get("data") or []


def collect_housing(cache_dir: Path, session: requests.Session, timeout: int = 25, pages: int = 12) -> dict[str, Any]:
    """70 城房价：扩散指数、均价同比、一线二手房环比。"""
    try:
        rows: list[dict] = []
        for page in range(1, pages + 1):
            batch = _fetch_house_page(session, page, timeout)
            if not batch:
                break
            rows.extend(batch)
            oldest = min(str(x.get("REPORT_DATE", ""))[:10] for x in batch)
            if oldest < "2020-01-01":
                break
        if not rows:
            raise ValueError("empty housing data")
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)
        for col in [
            "FIRST_COMHOUSE_SAME",
            "FIRST_COMHOUSE_SEQUENTIAL",
            "SECOND_HOUSE_SAME",
            "SECOND_HOUSE_SEQUENTIAL",
        ]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.drop_duplicates(["date", "CITY"], keep="last")

        breadth_rows: list[tuple[pd.Timestamp, float]] = []
        yoy_rows: list[tuple[pd.Timestamp, float]] = []
        tier1_rows: list[tuple[pd.Timestamp, float]] = []
        for date, group in df.groupby("date"):
            mom = group["FIRST_COMHOUSE_SEQUENTIAL"].dropna()
            yoy = group["FIRST_COMHOUSE_SAME"].dropna()
            if len(mom) < 50:
                continue
            breadth_rows.append((date, float((mom > 100).mean() * 100)))
            if len(yoy) >= 50:
                yoy_rows.append((date, float(yoy.mean())))
            t1 = group[group["CITY"].isin(["北京", "上海", "广州", "深圳"])]["SECOND_HOUSE_SEQUENTIAL"].dropna()
            if len(t1) >= 3:
                tier1_rows.append((date, float(t1.mean())))

        def make(rows_: list[tuple[pd.Timestamp, float]]) -> pd.Series:
            if not rows_:
                return pd.Series(dtype="float64")
            rows_.sort(key=lambda x: x[0])
            return pd.Series([v for _, v in rows_], index=pd.DatetimeIndex([d for d, _ in rows_]))

        breadth = make(breadth_rows)
        yoy = make(yoy_rows)
        tier1 = make(tier1_rows)
        if not breadth.empty:
            save_cache(cache_dir, "home_breadth", breadth)
        if not yoy.empty:
            save_cache(cache_dir, "home_price_yoy", yoy)
        if not tier1.empty:
            save_cache(cache_dir, "tier1_secondhand_mom", tier1)
        return {
            "series": {
                "home_breadth": breadth,
                "home_price_yoy": yoy,
                "tier1_secondhand_mom": tier1,
            },
            "ok": not breadth.empty,
            "error": "",
            "city_months": int(df["date"].nunique()),
            "latest_cities": int(df[df["date"] == df["date"].max()]["CITY"].nunique()),
        }
    except Exception as exc:  # noqa: BLE001
        cached = {
            "home_breadth": load_cache(cache_dir, "home_breadth"),
            "home_price_yoy": load_cache(cache_dir, "home_price_yoy"),
            "tier1_secondhand_mom": load_cache(cache_dir, "tier1_secondhand_mom"),
        }
        return {
            "series": cached,
            "ok": any(not s.empty for s in cached.values()),
            "error": f"{type(exc).__name__}: {exc}",
            "cached": True,
            "city_months": 0,
            "latest_cities": 0,
        }


# ---------------------------- 汇总 ----------------------------

def collect_macro(cache_dir: Path, offline: bool = False, max_workers: int = 4) -> dict[str, Any]:
    """并发抓取所有宏观序列。返回 {key: result_dict} 和附加 meta。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, tuple[str, Callable[[], Any]]] = {
        "pmi_mfg": ("国家统计局", lambda: _pmi()[0]),
        "pmi_nonmfg": ("国家统计局", lambda: _pmi()[1]),
        "cpi_yoy": ("国家统计局", _cpi),
        "ppi_yoy": ("国家统计局", _ppi),
        "gdp_yoy": ("国家统计局", _gdp),
        "ip_yoy": ("国家统计局", _ip),
        "retail_yoy": ("国家统计局", _retail),
        "fai_yoy": ("国家统计局", _fai),
        "exports_yoy": ("海关总署", _exports),
        "consumer_confidence": ("国家统计局", _consumer_confidence),
        "m2_yoy": ("中国人民银行", lambda: _money()[0]),
        "m1_yoy": ("中国人民银行", lambda: _money()[1]),
        "loan_yoy": ("中国人民银行", _loan),
        "lpr_chg_3m": ("中国人民银行", _lpr),
        "us_cpi_yoy": ("美国劳工部", _us_cpi),
    }

    results: dict[str, dict] = {}
    if offline:
        for key, (label, _) in jobs.items():
            cached = load_cache(cache_dir, key)
            results[key] = _result(key, cached, label, "offline", cached=not cached.empty)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_run_one, key, label, fn, cache_dir): key
                for key, (label, fn) in jobs.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as exc:  # noqa: BLE001
                    results[key] = _result(key, pd.Series(dtype="float64"), jobs[key][0], str(exc))

    # 派生：M1-M2
    m1 = results.get("m1_yoy", {}).get("series", pd.Series(dtype="float64"))
    m2 = results.get("m2_yoy", {}).get("series", pd.Series(dtype="float64"))
    if not m1.empty and not m2.empty:
        gap = (m1 - m2).dropna()
        save_cache(cache_dir, "m1_m2_gap", gap)
        results["m1_m2_gap"] = _result("m1_m2_gap", gap, "中国人民银行")
    else:
        results["m1_m2_gap"] = _result(
            "m1_m2_gap", load_cache(cache_dir, "m1_m2_gap"), "中国人民银行", "m1/m2 缺失"
        )

    # 美债收益率与利差
    meta: dict[str, Any] = {}
    rate_meta = {
        "us_10y": ("美国国债收益率10年", "美国财政部"),
        "us_2y": ("美国国债收益率2年", "美国财政部"),
        "us_curve": ("美国国债收益率10年-2年", "美国财政部"),
        "cn_10y": ("中国国债收益率10年", "中国债券信息网"),
    }
    if offline:
        for key, (_col, label) in rate_meta.items():
            cached = load_cache(cache_dir, key)
            results[key] = _result(key, cached, label, "offline", cached=not cached.empty)
            if not cached.empty:
                meta[key] = float(cached.iloc[-1])
    else:
        try:
            rates = _rates()
            for key, (col, label) in rate_meta.items():
                if col in rates.columns:
                    s = pd.to_numeric(rates[col], errors="coerce").dropna()
                    results[key] = _result(key, s, label)
                    if not s.empty:
                        meta[key] = float(s.iloc[-1])
                        save_cache(cache_dir, key, s)
        except Exception as exc:  # noqa: BLE001
            for key, (_col, label) in rate_meta.items():
                cached = load_cache(cache_dir, key)
                results[key] = _result(key, cached, label, str(exc), cached=not cached.empty)
                if not cached.empty:
                    meta[key] = float(cached.iloc[-1])

    return {"indicators": results, "meta": meta}


def fill_derived(results: dict[str, dict]) -> None:
    """把需要 3 个月变化的序列预先算好（保持原始单位，registry 里再变换）。"""
    # 目前变换在 scoring 模块统一做，这里保留空函数以便扩展。
    _ = results
