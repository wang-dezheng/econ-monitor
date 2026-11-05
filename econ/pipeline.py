"""主流程：采集 → 打分 → 解读 → 渲染。"""
from __future__ import annotations

import logging
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .analyze import narrative as narrative_mod
from .analyze import scoring, sentiment
from .collect import macro, market, news
from .config import load_config
from .report import html as html_report
from .report import markdown as md_report
from .store import Store
from .util import CN_TZ, atomic_write, ensure_dirs, now_cn, write_json

logger = logging.getLogger("econ.pipeline")


def _merge_results(
    macro_data: dict[str, Any],
    housing_data: dict[str, Any],
    market_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    results = dict(macro_data.get("indicators", {}))
    housing_sources = {
        "home_breadth": "国家统计局 / 东方财富",
        "home_price_yoy": "国家统计局 / 东方财富",
        "tier1_secondhand_mom": "国家统计局 / 东方财富",
    }
    for key, series in housing_data.get("series", {}).items():
        results[key] = {
            "key": key,
            "series": series,
            "source": housing_sources.get(key, "国家统计局"),
            "cached": housing_data.get("cached", False),
            "ok": series is not None and not series.empty,
            "latest": series.dropna().index.max() if series is not None and not series.empty else None,
        }
    market_sources = {"usdcnh": "东方财富", "copper": "上海期货交易所", "brent": "上海国际能源交易中心"}
    for key, source in market_sources.items():
        series = market_data.get("series", {}).get(key, pd.Series(dtype="float64"))
        results[key] = {
            "key": key,
            "series": series,
            "source": source,
            "cached": False,
            "ok": series is not None and not series.empty,
            "latest": series.dropna().index.max() if series is not None and not series.empty else None,
        }
    return results


def _offline_housing(cache_dir: Path) -> dict[str, Any]:
    series = {
        "home_breadth": macro.load_cache(cache_dir, "home_breadth"),
        "home_price_yoy": macro.load_cache(cache_dir, "home_price_yoy"),
        "tier1_secondhand_mom": macro.load_cache(cache_dir, "tier1_secondhand_mom"),
    }
    return {
        "series": series,
        "ok": any(not s.empty for s in series.values()),
        "error": "offline",
        "cached": True,
    }


def _render_index(reports_dir: Path, title: str = "每日经济观察") -> Path:
    files = sorted([p for p in reports_dir.glob("*.html") if p.name != "index.html"], reverse=True)
    rows = []
    for path in files:
        try:
            label = datetime.strptime(path.stem, "%Y-%m-%d").strftime("%Y年%m月%d日")
        except ValueError:
            label = path.stem
        rows.append(f'<li><a href="{path.name}">{label}</a><span>{path.name}</span></li>')
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 归档</title>
<style>
body{{margin:0;background:#f4f6f9;color:#15202b;font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;}}
.wrap{{max-width:860px;margin:0 auto;padding:48px 22px;}}
h1{{font-size:24px;margin:0 0 6px;}} p{{color:#7b8794;font-size:12px;margin:0 0 24px;}}
ul{{list-style:none;padding:0;margin:0;display:grid;gap:8px;}}
li{{background:#fff;border:1px solid #e8ecf1;border-radius:12px;padding:14px 16px;display:flex;justify-content:space-between;align-items:center;}}
a{{color:#15202b;text-decoration:none;font-size:14px;}} a:hover{{color:#b83227;}}
span{{color:#94a3b8;font-size:11px;}}
.foot{{margin-top:24px;color:#94a3b8;font-size:11px;line-height:1.8;}}
</style></head><body><div class="wrap">
<h1>{title} · 归档</h1><p>按日期倒序 · 双击任意一天查看完整看板</p>
<ul>{''.join(rows) or '<li>暂无报告</li>'}</ul>
<div class="foot">本页面由程序自动生成。报告为个人研究用途，不构成投资建议。</div>
</div></body></html>"""
    out = reports_dir / "index.html"
    atomic_write(out, html)
    return out


def run(
    config_path: str = "config.yaml",
    *,
    offline: bool = False,
    no_overseas: bool = False,
    no_llm: bool = False,
    open_after: bool = False,
    proxy_override: str | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    data_dir = Path(cfg["app"]["data_dir"])
    reports_dir = Path(cfg["app"]["report_dir"])
    cache_dir = data_dir / "cache"
    ensure_dirs(data_dir, reports_dir, cache_dir, Path(cfg["app"]["log_dir"]))

    if no_llm:
        cfg.setdefault("llm", {})["enabled"] = False

    now = now_cn()
    run_id = now.strftime("%Y%m%d-%H%M%S")
    logger.info("开始运行 %s", run_id)

    # 1) 数据
    macro_data = macro.collect_macro(cache_dir, offline=offline)
    logger.info("宏观序列完成：%d 个", len(macro_data.get("indicators", {})))

    net = cfg.get("network", {})
    proxy = proxy_override if proxy_override is not None else str(net.get("proxy", "") or "")
    domestic_proxy = proxy if proxy and str(net.get("proxy_for", "overseas")) == "all" else None
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    if domestic_proxy:
        session.proxies.update({"http": domestic_proxy, "https": domestic_proxy})

    if offline:
        market_data = market.collect_market(cache_dir, session, offline=True)
        housing_data = _offline_housing(cache_dir)
    else:
        market_data = market.collect_market(cache_dir, session, offline=False)
        housing_data = macro.collect_housing(cache_dir, session, timeout=int(net.get("timeout", 18)))
    logger.info("行情/地产完成：行情 %d 项，地产 %s", len(market_data.get("snapshot", [])), "OK" if housing_data.get("ok") else "FAIL")

    results = _merge_results(macro_data, housing_data, market_data)
    computed = scoring.compute(results, cfg, now)
    logger.info("经济温度：%s (%s)", computed.get("composite"), computed.get("temperature"))

    # 2) 新闻
    news_data = news.collect_news(
        cfg,
        cache_dir,
        offline=offline,
        no_overseas=no_overseas,
        proxy_override=proxy_override,
    )
    news_analysis = sentiment.analyze_news(
        news_data.get("items", []),
        max_items=int(cfg.get("report", {}).get("max_news", 14)),
    )
    logger.info("新闻：入库 %d 条，情绪 %.1f", news_analysis["counts"]["total"], news_analysis["news_score"])

    # 3) 解读
    ctx = narrative_mod.build_context(computed, news_analysis, market_data, cfg, now)
    narrative = narrative_mod.generate(ctx, cfg)
    narrative["direction"] = ctx["direction"]
    narrative["news_state"] = ctx["news_state"]
    logger.info("解读来源：%s", narrative.get("source"))

    report = {
        "run_id": run_id,
        "date": now,
        "generated_at": now,
        "computed": computed,
        "news": news_analysis,
        "market": market_data,
        "sources": news_data.get("statuses", []),
        "narrative": narrative,
        "offline": offline,
    }

    # 4) 渲染
    html_path = reports_dir / f"{now:%Y-%m-%d}.html"
    md_path = reports_dir / f"{now:%Y-%m-%d}.md"
    html_report.render_html(report, cfg, html_path)
    md_report.render_markdown(report, cfg, md_path)
    _render_index(reports_dir, cfg.get("app", {}).get("title", "每日经济观察"))

    rows = scoring.indicator_rows(computed)
    snapshot = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "report_date": now.strftime("%Y-%m-%d"),
        "composite": computed.get("composite"),
        "temperature": computed.get("temperature"),
        "regime": computed.get("regime"),
        "delta_3m": computed.get("delta_3m"),
        "coverage": computed.get("coverage"),
        "improving_share": computed.get("improving_share"),
        "pillars": {
            k: {
                "score": v.get("score"),
                "delta_3m": v.get("delta_3m"),
                "weight": v.get("weight"),
                "coverage": v.get("coverage"),
            }
            for k, v in computed["pillars"].items()
        },
        "news": {
            "score": news_analysis.get("news_score"),
            "policy_score": news_analysis.get("policy_score"),
            "policy_label": news_analysis.get("policy_label"),
            "counts": news_analysis.get("counts"),
        },
        "narrative": narrative,
        "indicators": rows,
        "market": market_data.get("snapshot", []),
        "sources": news_data.get("statuses", []),
        "files": {"html": html_path.name, "markdown": md_path.name},
    }
    write_json(data_dir / "latest.json", snapshot)

    # 5) 入库
    try:
        store = Store(data_dir / "econ.db")
        store.save_run(
            run_id=run_id,
            report_date=now.strftime("%Y-%m-%d"),
            composite=computed.get("composite"),
            pillars={k: v.get("score") for k, v in computed["pillars"].items()},
            news_score=news_analysis.get("news_score"),
            policy_score=news_analysis.get("policy_score"),
            regime=computed.get("regime", ""),
            verdict=narrative.get("verdict", ""),
            payload={
                "composite": computed.get("composite"),
                "temperature": computed.get("temperature"),
                "delta_3m": computed.get("delta_3m"),
                "coverage": computed.get("coverage"),
                "pillars": {
                    k: {"score": v.get("score"), "delta_3m": v.get("delta_3m")}
                    for k, v in computed["pillars"].items()
                },
                "news": snapshot["news"],
                "narrative": narrative,
                "sources": news_data.get("statuses", []),
            },
            indicators=rows,
            news_items=news_analysis.get("articles", []),
            source_statuses=news_data.get("statuses", []),
        )
        store.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 SQLite 失败（不影响报告）：%s", exc)

    logger.info("报告已生成：%s", html_path)
    if open_after:
        try:
            webbrowser.open(html_path.as_uri())
        except Exception as exc:  # noqa: BLE001
            logger.warning("无法自动打开浏览器：%s", exc)

    return {
        "html": str(html_path),
        "markdown": str(md_path),
        "latest": str(data_dir / "latest.json"),
        "composite": computed.get("composite"),
        "temperature": computed.get("temperature"),
        "regime": computed.get("regime"),
        "news_score": news_analysis.get("news_score"),
        "report": report,
    }
