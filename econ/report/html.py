"""HTML / Markdown 报告渲染。"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analyze.scoring import indicator_rows
from ..registry import INDICATOR_MAP, PILLAR_ICONS, PILLAR_ORDER
from ..util import CN_TZ, atomic_write
from . import charts


def _unit_text(unit: str) -> str:
    if unit == "pct":
        return " 个百分点"
    return unit


def fmt_value(value: float | None, unit: str = "", decimals: int = 1) -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "—"
    return f"{value:,.{decimals}f}{_unit_text(unit)}"


def fmt_signed(value: float | None, decimals: int = 1, unit: str = "%") -> str:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{decimals}f}{unit}"


def _cls(value: float | None, neutral: float = 0.05) -> str:
    if value is None:
        return "flat"
    if value > neutral:
        return "up"
    if value < -neutral:
        return "down"
    return "flat"


def _time_text(published: str) -> str:
    try:
        dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        now = datetime.now(CN_TZ)
        if dt.date() == now.date():
            return f"今天 {dt:%H:%M}"
        if dt.date() == (now - timedelta(days=1)).date():
            return f"昨天 {dt:%H:%M}"
        return f"{dt:%m-%d %H:%M}"
    except Exception:  # noqa: BLE001
        return ""


def _status_label(status: str) -> str:
    return {"ok": "", "stale": "滞后", "expired": "过期", "missing": "缺失"}.get(status, "")


def _score_class(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 60:
        return "high"
    if score <= 40:
        return "low"
    return ""


def _signal_class(signal: str) -> str:
    return {"偏强": "high", "偏弱": "low"}.get(signal, "")


def _label_class(label: str) -> str:
    return {"利好": "positive", "利空": "negative"}.get(label, "neutral")


def _spring(date: datetime) -> str:
    return "一二三四五六日"[date.weekday()]


def _data_cutoff(computed: dict[str, Any], market: list[dict[str, Any]]) -> str:
    inds = computed.get("indicators", {})
    pmi = inds.get("pmi_mfg")
    cpi = inds.get("cpi_yoy")
    gdp = inds.get("gdp_yoy")
    parts = []
    if cpi and cpi.latest_date:
        parts.append(f"{cpi.latest_date:%Y-%m}（多数月度）")
    if pmi and pmi.latest_date and (not cpi or pmi.latest_date.strftime("%Y-%m") != cpi.latest_date.strftime("%Y-%m")):
        parts.append(f"{pmi.latest_date:%Y-%m}（PMI）")
    if gdp and gdp.latest_date:
        parts.append(f"{gdp.latest_date:%Y-%m}（GDP 季度）")
    if market:
        dates = [x.get("date") for x in market if x.get("date")]
        if dates:
            parts.append(f"{max(dates)}（行情）")
    return " · ".join(parts[:4]) if parts else "—"


def _news_view(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        out.append(
            {
                **item,
                "label_class": _label_class(item.get("label", "中性")),
                "time_text": _time_text(item.get("published", "")),
                "categories": item.get("categories") or ["其他"],
                "keywords": (item.get("keywords") or [])[:3],
            }
        )
    return out


def _market_view(market: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in market:
        decimals = int(item.get("decimals", 2))
        out.append(
            {
                **item,
                "price_text": f"{item['price']:,.{decimals}f}",
                "chg_1d_text": fmt_signed(item.get("chg_1d"), 2 if item["key"] == "usdcnh" else 1),
                "chg_1m_text": fmt_signed(item.get("chg_1m"), 2 if item["key"] == "usdcnh" else 1),
                "chg_3m_text": fmt_signed(item.get("chg_3m"), 2 if item["key"] == "usdcnh" else 1),
                "cls_1d": _cls(item.get("chg_1d")),
                "cls_1m": _cls(item.get("chg_1m")),
                "cls_3m": _cls(item.get("chg_3m")),
            }
        )
    return out


def _pillar_view(computed: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    names = {k: v.get("name", k) for k, v in cfg.get("pillars", {}).items()}
    for key in PILLAR_ORDER:
        p = computed["pillars"].get(key, {})
        score = p.get("score")
        delta = p.get("delta_3m")
        if score is None:
            score_text, color, width = "—", "#cbd5e1", 0
            delta_text = "数据不足"
        else:
            score_text = f"{score:.1f}"
            color = charts._color(score)
            width = max(0.0, min(100.0, score))
            if delta is None:
                delta_text = "较 3 个月：—"
            else:
                arrow = "▲" if delta > 0.05 else "▼" if delta < -0.05 else "•"
                delta_text = f"较 3 个月 {arrow} {abs(delta):.1f}"
        out.append(
            {
                "key": key,
                "name": names.get(key, key),
                "icon": PILLAR_ICONS.get(key, "•"),
                "score": score,
                "score_text": score_text,
                "color": color,
                "width": width,
                "weight_pct": f"{float(p.get('weight', 0)) * 100:.0f}",
                "delta_text": delta_text,
                "top_pos": p.get("top_pos", [])[:2],
                "top_neg": p.get("top_neg", [])[:2],
            }
        )
    return out


def _indicator_groups(computed: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rows = indicator_rows(computed)
    names = {k: v.get("name", k) for k, v in cfg.get("pillars", {}).items()}
    groups = []
    for key in PILLAR_ORDER:
        members = [r for r in rows if r["pillar"] == key]
        for r in members:
            score = r.get("score")
            r["value_text"] = fmt_value(r.get("value"), r.get("unit", ""), int(r.get("decimals", 1)))
            r["prior_text"] = fmt_value(r.get("prior"), r.get("unit", ""), int(r.get("decimals", 1)))
            r["score_text"] = f"{score:.0f}" if score is not None else "—"
            r["score_class"] = _score_class(score)
            delta = r.get("score_delta_3m")
            r["delta_text"] = fmt_signed(delta, 1, "")
            r["delta_class"] = "delta-up" if delta is not None and delta > 0.05 else "delta-down" if delta is not None and delta < -0.05 else "muted"
            r["signal_class"] = _signal_class(r.get("signal", ""))
            r["status_label"] = _status_label(r.get("status", ""))
            r["period"] = r.get("period") or "—"
        p = computed["pillars"].get(key, {})
        groups.append(
            {
                "key": key,
                "name": names.get(key, key),
                "score_text": f"{p['score']:.1f}" if p.get("score") is not None else "—",
                "weight_pct": f"{float(p.get('weight', 0)) * 100:.0f}",
                "rows": members,
            }
        )
    return groups


def _sources_view(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in statuses:
        out.append(
            {
                "name": s.get("name", ""),
                "count": s.get("count", 0),
                "cls": "ok" if s.get("ok") else "fail",
                "error": s.get("error", ""),
            }
        )
    return out


def _spark_panels(computed: dict[str, Any], market: dict[str, Any]) -> list[dict[str, Any]]:
    inds = computed["indicators"]
    panels = []

    def add(key: str, name: str, ref, unit: str, decimals: int, series=None):
        s = series if series is not None else (inds.get(key).series if inds.get(key) else None)
        if s is not None and not s.empty:
            panels.append({"key": key, "name": name, "series": s, "ref": ref, "unit": unit, "decimals": decimals})

    add("pmi_mfg", "制造业 PMI", 50, "", 1)
    add("cpi_yoy", "CPI 同比", 1.5, "%", 1)
    add("ppi_yoy", "PPI 同比", 0, "%", 1)
    add("m1_yoy", "M1 同比", 0, "%", 1)
    add("home_breadth", "70 城新房环比上涨占比", 50, "%", 0)
    fx = market.get("series", {}).get("usdcnh")
    add("usdcnh", "美元/离岸人民币", None, "", 4, fx)
    return panels


def build_view(report: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    computed = report["computed"]
    news = report["news"]
    market = report.get("market", {})
    narrative = report["narrative"]
    date: datetime = report["date"]
    generated_at: datetime = report["generated_at"]

    pillars = _pillar_view(computed, cfg)
    names = {k: v.get("name", k) for k, v in cfg.get("pillars", {}).items()}
    rows = indicator_rows(computed)
    missing = [r["name"] for r in rows if r["status"] in ("missing", "expired")]
    stale = [f"{r['name']}（{_status_label(r['status'])}）" for r in rows if r["status"] == "stale"]
    sources = _sources_view(report.get("sources", []))
    market_view = _market_view(market.get("snapshot", []))

    coverage = computed.get("coverage") or 0
    improving = computed.get("improving_share")
    policy_score = news.get("policy_score")
    news_score = news.get("news_score")

    methodology = " · ".join(
        f"{cfg.get('pillars', {}).get(k, {}).get('name', k)} {float(cfg.get('pillars', {}).get(k, {}).get('weight', 0)) * 100:.0f}%"
        for k in PILLAR_ORDER
    )

    return {
        "title": cfg.get("app", {}).get("title", "每日经济观察"),
        "date": date.strftime("%Y-%m-%d"),
        "date_cn": f"{date.year}年{date.month}月{date.day}日 星期{_spring(date)}",
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M"),
        "data_cutoff": _data_cutoff(computed, market.get("snapshot", [])),
        "gauge_svg": charts.gauge_svg(computed.get("composite"), computed.get("temperature", ""), computed.get("delta_3m")),
        "trend_svg": charts.trend_svg(computed.get("history"), cfg.get("thresholds", {}).get("temperature", {})),
        "radar_svg": charts.radar_svg([{"key": k, **computed["pillars"][k]} for k in PILLAR_ORDER], names),
        "sparklines_svg": charts.sparklines_svg(_spark_panels(computed, market)),
        "composite": computed.get("composite"),
        "temperature": computed.get("temperature"),
        "regime": computed.get("regime"),
        "direction": narrative.get("direction") or "",
        "verdict": narrative.get("verdict", ""),
        "summary": narrative.get("summary", ""),
        "drivers": narrative.get("drivers", []),
        "risks": narrative.get("risks", []),
        "watch": narrative.get("watch", []),
        "narrative_source": "AI 辅助解读" if narrative.get("source") == "llm" else "规则引擎生成",
        "news_state": narrative.get("news_state", "中性"),
        "policy_label": news.get("policy_label", "中性"),
        "coverage_pct": f"{coverage * 100:.0f}%",
        "improving_pct": f"{improving * 100:.0f}%" if improving is not None else "—",
        "news_score": f"{news_score:.0f}" if news_score is not None else "—",
        "policy_score": f"{policy_score:.0f}" if policy_score is not None else "—",
        "pillars": pillars,
        "indicator_groups": _indicator_groups(computed, cfg),
        "news_top": _news_view(news.get("top", [])),
        "news_positive": _news_view(news.get("positive", [])[:5]),
        "news_negative": _news_view(news.get("negative", [])[:5]),
        "news_policy": _news_view(news.get("policy_items", [])[:5]),
        "news_total": news.get("counts", {}).get("total", 0),
        "market": market_view,
        "sources": sources,
        "source_ok": sum(1 for s in sources if s["cls"] == "ok"),
        "source_total": len(sources),
        "missing_text": "、".join(missing[:8]) + (" 等" if len(missing) > 8 else "") if missing else "无",
        "stale_text": "、".join(stale[:8]) if stale else "无",
        "methodology_weights": methodology,
        "run_id": report.get("run_id", ""),
    }


def render_html(report: dict[str, Any], cfg: dict[str, Any], out_path: Path) -> Path:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("report.html")
    html = tpl.render(**build_view(report, cfg))
    atomic_write(out_path, html)
    return out_path
