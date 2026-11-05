"""每日经济观察 · 公共工具。"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import requests

CN_TZ = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def today_str() -> str:
    return now_cn().strftime("%Y-%m-%d")


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("econ")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)

    file_handler = RotatingFileHandler(
        log_dir / f"econ-{now_cn():%Y%m%d}.log",
        maxBytes=2_000_000,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def make_session(proxy: str | None = None, timeout: int = 18) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    s.request = _wrap_timeout(s.request, timeout)  # type: ignore[method-assign]
    return s


def _wrap_timeout(fn: Callable, timeout: int) -> Callable:
    def inner(method: str, url: str, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return fn(method, url, **kwargs)

    return inner


def http_get(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    retries: int = 2,
    timeout: int = 18,
    allow_insecure: bool = False,
) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=timeout, verify=not allow_insecure)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    assert last is not None
    raise last


def http_post(
    session: requests.Session,
    url: str,
    *,
    json_body: dict | None = None,
    headers: dict | None = None,
    retries: int = 2,
    timeout: int = 30,
) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = session.post(url, json=json_body, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    assert last is not None
    raise last


_MONTH_RE = re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})")
_YEAR_MONTH_RE = re.compile(r"^(20\d{2})(\d{2})$")
_QUARTER_RE = re.compile(r"(20\d{2})\s*年\s*第\s*(\d)\s*(?:[-—至]\s*(\d)\s*)?季度")


def parse_month_label(value: Any) -> pd.Timestamp | None:
    """把 '2026年09月份' / '202604' / date / datetime 统一成月末。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(value)
        return ts + pd.offsets.MonthEnd(0)
    text = str(value).strip()
    m = _YEAR_MONTH_RE.match(text)
    if m:
        ts = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        return ts + pd.offsets.MonthEnd(0)
    m = _MONTH_RE.search(text)
    if m:
        ts = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        return ts + pd.offsets.MonthEnd(0)
    return None


def parse_quarter_label(value: Any) -> pd.Timestamp | None:
    text = str(value)
    m = _QUARTER_RE.search(text)
    if not m:
        return parse_month_label(value)
    year = int(m.group(1))
    last_q = int(m.group(3) or m.group(2))
    last_q = min(max(last_q, 1), 4)
    ts = pd.Timestamp(year=year, month=last_q * 3, day=1)
    return ts + pd.offsets.MonthEnd(0)


def parse_any_date(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).normalize()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return pd.Timestamp(datetime.strptime(text, fmt)).normalize()
        except Exception:  # noqa: BLE001
            continue
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


def to_series(df: pd.DataFrame, date_col: str, value_col: str, parser=parse_month_label) -> pd.Series:
    if df is None or df.empty or date_col not in df.columns or value_col not in df.columns:
        return pd.Series(dtype="float64")
    dates = df[date_col].map(parser)
    vals = pd.to_numeric(df[value_col], errors="coerce")
    out = pd.DataFrame({"date": dates, "value": vals}).dropna()
    if out.empty:
        return pd.Series(dtype="float64")
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    return pd.Series(out["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(out["date"])).sort_index()


def to_monthly(series: pd.Series, freq: str = "M") -> pd.Series:
    """统一到月末。季度数据在季度结束后才可用，因此按季度末 ffill。"""
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    s = series.dropna().sort_index()
    if freq == "Q":
        q = s.resample("QE").last().dropna()
        if q.empty:
            return pd.Series(dtype="float64")
        idx = pd.date_range(q.index.min(), q.index.max(), freq="ME")
        return q.reindex(idx, method="ffill")
    return s.resample("ME").last().dropna()


def pct_change_months(series: pd.Series, months: int = 3) -> pd.Series:
    return (series / series.shift(months) - 1.0) * 100.0


def diff_months_bp(series: pd.Series, months: int = 3) -> pd.Series:
    return (series - series.shift(months)) * 100.0


def fmt_num(value: float | None, decimals: int = 1, unit: str = "") -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "—"
    text = f"{value:,.{decimals}f}"
    if unit:
        return f"{text}{unit}"
    return text


def fmt_signed(value: float | None, decimals: int = 1, unit: str = "") -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "—"
    if abs(value) < 10 ** (-decimals) / 2:
        value = 0.0
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{decimals}f}{unit}"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def tanh(value: float) -> float:
    return math.tanh(value)


def short(text: str | None, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def stable_id(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]


def dedupe_news(items: Iterable[dict], threshold: float = 0.86) -> list[dict]:
    """标题去重：规范化后相同，或字符二元组 Jaccard 相似度超阈值。"""
    out: list[dict] = []
    seen: list[set[str]] = []
    norm_titles: list[str] = []
    norm_seen: set[str] = set()
    for item in items:
        title = re.sub(r"[\s\W_]+", "", item.get("title", ""))
        if len(title) < 6:
            continue
        if title in norm_seen:
            continue
        duplicate = False
        # 一个标题是另一个的子串（官方长标题 vs 媒体短标题）
        for prev_title in norm_titles:
            if min(len(title), len(prev_title)) >= 10 and (title in prev_title or prev_title in title):
                duplicate = True
                break
        if duplicate:
            continue
        grams = {title[i : i + 2] for i in range(len(title) - 1)}
        for prev in seen:
            if not grams or not prev:
                continue
            inter = len(grams & prev)
            union = len(grams | prev)
            if union and inter / union >= threshold:
                duplicate = True
                break
        if duplicate:
            continue
        norm_seen.add(title)
        norm_titles.append(title)
        seen.append(grams)
        out.append(item)
    return out
