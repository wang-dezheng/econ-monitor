"""新闻采集：国内财经媒体、官方发布、境外 RSS。"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..util import CN_TZ, clean_html, dedupe_news, http_get, now_cn, read_json, short, write_json


def _epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(float(value)), CN_TZ)
    except Exception:  # noqa: BLE001
        return None


def _struct(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime(*value[:6], tzinfo=timezone.utc).astimezone(CN_TZ)
    except Exception:  # noqa: BLE001
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CN_TZ)
        except Exception:  # noqa: BLE001
            continue
    try:
        ts = pd.to_datetime(text, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime().replace(tzinfo=CN_TZ)
    except Exception:  # noqa: BLE001
        return None


def _item(
    *,
    title: str,
    url: str,
    summary: str,
    source: str,
    region: str,
    published: datetime | None,
    weight: float,
    official: bool = False,
    media: str = "",
) -> dict[str, Any] | None:
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if len(title) < 6 or not url:
        return None
    published = published or now_cn()
    return {
        "title": short(title, 230 if official else 160),
        "url": url,
        "summary": short(clean_html(summary), 320),
        "source": source,
        "media": media,
        "region": region,
        "published": published.isoformat(),
        "ts": published.timestamp(),
        "weight": float(weight),
        "official": bool(official),
    }


def _parse_sina(payload: dict, src: dict, cutoff: datetime) -> list[dict]:
    rows = (((payload or {}).get("result") or {}).get("data") or [])
    out = []
    for row in rows:
        published = _epoch(row.get("ctime")) or _epoch(row.get("intime"))
        if published and published < cutoff:
            continue
        item = _item(
            title=row.get("title", ""),
            url=row.get("url", ""),
            summary=row.get("intro") or row.get("summary") or "",
            source=src["name"],
            region="domestic",
            published=published,
            weight=src.get("weight", 1.0),
            media=row.get("media_name", ""),
        )
        if item:
            out.append(item)
    return out


def _parse_eastmoney(text: str, src: dict, cutoff: datetime) -> list[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    payload = json.loads(text[start : end + 1])
    rows = payload.get("LivesList") or []
    out = []
    for row in rows:
        published = _parse_dt(row.get("showtime"))
        if published and published < cutoff:
            continue
        item = _item(
            title=row.get("title", ""),
            url=row.get("url_w") or row.get("url_unique") or "",
            summary=row.get("digest", ""),
            source=src["name"],
            region="domestic",
            published=published,
            weight=src.get("weight", 1.0),
        )
        if item:
            out.append(item)
    return out


def _parse_wscn(payload: dict, src: dict, cutoff: datetime) -> list[dict]:
    rows = (((payload or {}).get("data") or {}).get("items") or [])
    out = []
    for row in rows:
        published = _epoch(row.get("display_time"))
        if published and published < cutoff:
            continue
        body = row.get("content_text") or ""
        title = row.get("title") or body
        item = _item(
            title=title,
            url=row.get("uri") or "",
            summary=body,
            source=src["name"],
            region="domestic",
            published=published,
            weight=src.get("weight", 1.0),
        )
        if item:
            out.append(item)
    return out


_DATE_IN_URL = re.compile(r"(?:t|/)(20\d{2})(\d{2})(\d{2})")


def _parse_official(content: bytes, base_url: str, src: dict, cutoff: datetime) -> list[dict]:
    soup = BeautifulSoup(content, "lxml")
    found: dict[str, dict] = {}
    for a in soup.select("a"):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        href = (a.get("href") or "").strip()
        if len(title) < 8 or not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        m = _DATE_IN_URL.search(href)
        if not m:
            continue
        try:
            published = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 9, 0, tzinfo=CN_TZ)
        except ValueError:
            continue
        if published < cutoff:
            continue
        url = urljoin(base_url, href)
        title = re.sub(r"\s+20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s*$", "", title).strip()
        item = _item(
            title=title,
            url=url,
            summary="",
            source=src["name"],
            region="domestic",
            published=published,
            weight=src.get("weight", 1.4),
            official=True,
        )
        if not item:
            continue
        prev = found.get(url)
        if prev is None or len(item["title"]) > len(prev["title"]):
            found[url] = item
    return list(found.values())


def _parse_rss(content: bytes, src: dict, cutoff: datetime) -> list[dict]:
    feed = feedparser.parse(content)
    out = []
    for entry in feed.entries[:80]:
        published = _struct(entry.get("published_parsed")) or _struct(entry.get("updated_parsed"))
        if published and published < cutoff:
            continue
        title = entry.get("title", "")
        if src.get("id", "").startswith("google_news"):
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()
        summary = entry.get("summary") or entry.get("description") or ""
        link = entry.get("link") or ""
        item = _item(
            title=title,
            url=link,
            summary=clean_html(summary),
            source=src["name"],
            region="overseas",
            published=published,
            weight=src.get("weight", 1.0),
            media=(entry.get("source") or {}).get("title", "") if isinstance(entry.get("source"), dict) else "",
        )
        if item:
            out.append(item)
    return out


def _fetch_source(
    src: dict,
    region: str,
    session: requests.Session,
    timeout: int,
    cutoff_media: datetime,
    cutoff_official: datetime,
    max_articles: int,
) -> tuple[list[dict], dict[str, Any]]:
    started = time.time()
    status: dict[str, Any] = {
        "id": src.get("id", ""),
        "name": src.get("name", ""),
        "region": region,
        "ok": False,
        "count": 0,
        "error": "",
        "latency_ms": 0,
        "cached": False,
    }
    try:
        src_type = src.get("type", "rss")
        if src_type == "official":
            r = http_get(session, src["url"], retries=1, timeout=timeout)
            items = _parse_official(r.content, src["url"], src, cutoff_official)
        elif src_type == "rss":
            r = http_get(session, src["url"], retries=1, timeout=timeout, allow_insecure=True)
            items = _parse_rss(r.content, src, cutoff_media)
        elif src_type == "sina_roll":
            r = http_get(session, src["url"], retries=1, timeout=timeout)
            items = _parse_sina(r.json(), src, cutoff_media)
        elif src_type == "eastmoney_flash":
            r = http_get(session, src["url"], retries=1, timeout=timeout)
            items = _parse_eastmoney(r.text, src, cutoff_media)
        elif src_type == "wscn_live":
            r = http_get(session, src["url"], retries=1, timeout=timeout)
            items = _parse_wscn(r.json(), src, cutoff_media)
        else:
            raise ValueError(f"unknown source type: {src_type}")

        items = items[:max_articles]
        status["count"] = len(items)
        status["ok"] = True
        status["error"] = "" if items else "未抓到符合时间窗口的新闻"
        return items, status
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
        return [], status
    finally:
        status["latency_ms"] = int((time.time() - started) * 1000)


def collect_news(
    cfg: dict,
    cache_dir: Path,
    *,
    offline: bool = False,
    no_overseas: bool = False,
    proxy_override: str | None = None,
) -> dict[str, Any]:
    """抓取新闻。境内、境外并发；境外失败自动降级。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "news_last.json"
    if offline:
        cached = read_json(cache_file, {}) or {}
        return {
            "items": cached.get("items", []),
            "statuses": [{**s, "cached": True, "ok": bool(s.get("ok"))} for s in cached.get("statuses", [])],
            "cached": True,
        }

    news_cfg = cfg.get("news", {})
    net = cfg.get("network", {})
    mode = str(net.get("proxy_for", "overseas"))
    proxy = proxy_override if proxy_override is not None else str(net.get("proxy", "") or "")
    domestic_proxy = proxy if proxy and mode in ("all",) else None
    overseas_proxy = proxy if proxy and mode in ("overseas", "all") else None
    timeout = int(net.get("timeout", 18))
    overseas_timeout = min(timeout, int(net.get("overseas_probe_timeout", 8)))
    max_articles = int(news_cfg.get("max_articles", 500))
    window_hours = int(news_cfg.get("window_hours", 48))
    official_days = int(news_cfg.get("official_window_days", 7))

    now = now_cn()
    cutoff_media = now - timedelta(hours=window_hours)
    cutoff_overseas = now - timedelta(hours=max(window_hours, 72))
    cutoff_official = now - timedelta(days=official_days)

    domestic_cfg = [s for s in news_cfg.get("domestic", []) if s.get("enabled", True)]
    overseas_cfg = [
        s
        for s in news_cfg.get("overseas", [])
        if (not no_overseas) and str(s.get("enabled", "auto")).lower() not in ("false", "0", "no", "off")
    ]

    domestic_session = requests.Session()
    domestic_session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
    overseas_session = requests.Session()
    overseas_session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "en,zh;q=0.8"})
    if domestic_proxy:
        domestic_session.proxies.update({"http": domestic_proxy, "https": domestic_proxy})
    if overseas_proxy:
        overseas_session.proxies.update({"http": overseas_proxy, "https": overseas_proxy})

    all_items: list[dict] = []
    statuses: list[dict] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for src in domestic_cfg:
            futures.append(
                pool.submit(
                    _fetch_source,
                    src,
                    "domestic",
                    domestic_session,
                    timeout,
                    cutoff_media,
                    cutoff_official,
                    max_articles,
                )
            )
        for src in overseas_cfg:
            futures.append(
                pool.submit(
                    _fetch_source,
                    src,
                    "overseas",
                    overseas_session,
                    overseas_timeout,
                    cutoff_overseas,
                    cutoff_official,
                    max_articles,
                )
            )
        for future in as_completed(futures):
            try:
                items, status = future.result()
            except Exception as exc:  # noqa: BLE001
                items, status = [], {
                    "id": "",
                    "name": "unknown",
                    "region": "unknown",
                    "ok": False,
                    "count": 0,
                    "error": str(exc),
                    "latency_ms": 0,
                }
            all_items.extend(items)
            statuses.append(status)

    # 官方源优先；同一条新闻保留官方版本
    all_items.sort(key=lambda x: (x.get("official", False), x.get("ts", 0)), reverse=True)
    deduped = dedupe_news(all_items)
    deduped.sort(key=lambda x: x.get("ts", 0), reverse=True)
    deduped = deduped[:max_articles]

    statuses.sort(key=lambda s: (s.get("region") != "domestic", not s.get("ok"), s.get("name", "")))
    payload = {
        "collected_at": now.isoformat(),
        "items": deduped,
        "statuses": statuses,
    }
    write_json(cache_file, payload)
    return {"items": deduped, "statuses": statuses, "cached": False}
