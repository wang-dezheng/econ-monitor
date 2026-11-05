"""Markdown 日报：便于存档、搜索、二次编辑。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..analyze.scoring import indicator_rows
from ..registry import PILLAR_ORDER
from ..util import atomic_write, fmt_num, fmt_signed, short


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _cell(value: float | None, unit: str = "", decimals: int = 1) -> str:
    if value is None:
        return "—"
    u = " 个百分点" if unit == "pct" else unit
    return f"{value:,.{decimals}f}{u}"


def render_markdown(report: dict[str, Any], cfg: dict[str, Any], out_path: Path) -> Path:
    computed = report["computed"]
    news = report["news"]
    narrative = report["narrative"]
    market = report.get("market", {})
    date: datetime = report["date"]
    pillars = computed["pillars"]
    names = {k: v.get("name", k) for k, v in cfg.get("pillars", {}).items()}

    lines: list[str] = []
    lines.append(f"# 每日经济观察 · {date:%Y-%m-%d}")
    lines.append("")
    lines.append(
        f"> 经济温度 **{computed.get('composite')}** · {computed.get('temperature')} · "
        f"{computed.get('regime')} · 较3个月 {fmt_signed(computed.get('delta_3m'), 1, '')} 分"
    )
    lines.append("")
    lines.append("## 一句话判断")
    lines.append("")
    lines.append(f"**{narrative.get('verdict', '')}**")
    lines.append("")
    lines.append(narrative.get("summary", ""))
    lines.append("")
    lines.append(
        f"- 新闻面：{narrative.get('news_state')}（{news.get('news_score')} 分）；"
        f"政策信号：{news.get('policy_label')}（{news.get('policy_score')} 分）"
    )
    lines.append(f"- 数据覆盖：{computed.get('coverage', 0) * 100:.0f}%；改善面：{(computed.get('improving_share') or 0) * 100:.0f}%")
    lines.append(f"- 解读来源：{'AI 辅助' if narrative.get('source') == 'llm' else '规则引擎'}")
    lines.append("")

    lines.append("## 五维温度")
    lines.append("")
    lines.append("| 维度 | 得分 | 较3个月 | 权重 | 主要支撑 | 主要拖累 |")
    lines.append("|---|---:|---:|---:|---|---|")
    for key in PILLAR_ORDER:
        p = pillars.get(key, {})
        pos = "、".join(x["name"] for x in p.get("top_pos", [])) or "—"
        neg = "、".join(x["name"] for x in p.get("top_neg", [])) or "—"
        lines.append(
            f"| {names.get(key, key)} | {p.get('score'):.1f} | {fmt_signed(p.get('delta_3m'), 1, '')} | "
            f"{float(p.get('weight', 0)) * 100:.0f}% | {pos} | {neg} |"
            if p.get("score") is not None
            else f"| {names.get(key, key)} | — | — | {float(p.get('weight', 0)) * 100:.0f}% | — | — |"
        )
    lines.append("")

    lines.append("## 支撑与拖累")
    lines.append("")
    lines.append("**主要支撑**")
    for x in narrative.get("drivers", []) or []:
        lines.append(f"- {x}")
    lines.append("")
    lines.append("**主要风险**")
    for x in narrative.get("risks", []) or []:
        lines.append(f"- {x}")
    lines.append("")
    lines.append("**未来关注**")
    for x in narrative.get("watch", []) or []:
        lines.append(f"- {x}")
    lines.append("")

    lines.append("## 关键指标")
    rows = indicator_rows(computed)
    for key in PILLAR_ORDER:
        members = [r for r in rows if r["pillar"] == key]
        if not members:
            continue
        lines.append("")
        lines.append(f"### {names.get(key, key)}")
        lines.append("")
        lines.append("| 指标 | 最新 | 上期 | 评分 | 3月变化 | 状态 | 数据期 |")
        lines.append("|---|---:|---:|---:|---:|---|---|")
        for r in members:
            status = {"ok": "", "stale": "滞后", "expired": "过期", "missing": "缺失"}.get(r["status"], "")
            lines.append(
                f"| {_md(r['name'])} | {_cell(r['value'], r['unit'], r['decimals'])} | "
                f"{_cell(r['prior'], r['unit'], r['decimals'])} | "
                f"{r['score']:.0f} | {fmt_signed(r['score_delta_3m'], 1, '')} | {status} | {r['period'] or '—'} |"
                if r["score"] is not None
                else f"| {_md(r['name'])} | — | — | — | — | {status or '缺失'} | — |"
            )
    lines.append("")

    lines.append("## 今日要闻")
    lines.append("")
    for i, item in enumerate(news.get("top", [])[:12], 1):
        lines.append(f"{i}. [{_md(short(item['title'], 90))}]({item['url']}) · {item['source']} · **{item['label']}**")
    if not news.get("top"):
        lines.append("今日没有抓到符合宏观相关性的新闻。")
    lines.append("")

    if news.get("policy_items"):
        lines.append("### 政策信号")
        lines.append("")
        for item in news["policy_items"][:6]:
            lines.append(f"- [{_md(short(item['title'], 90))}]({item['url']}) · {item['source']}")
        lines.append("")

    lines.append("## 利好 / 利空")
    lines.append("")
    lines.append("| 利好 | 利空 |")
    lines.append("|---|---|")
    pos = news.get("positive", [])[:6]
    neg = news.get("negative", [])[:6]
    for i in range(max(len(pos), len(neg))):
        p = _md(short(pos[i]["title"], 60)) if i < len(pos) else ""
        n = _md(short(neg[i]["title"], 60)) if i < len(neg) else ""
        lines.append(f"| {p} | {n} |")
    lines.append("")

    lines.append("## 市场快照")
    lines.append("")
    lines.append("| 品种 | 最新 | 1日 | 1月 | 3月 | 日期 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for item in market.get("snapshot", []):
        dec = int(item.get("decimals", 2))
        lines.append(
            f"| {item['name']} | {item['price']:,.{dec}f} | {fmt_signed(item.get('chg_1d'), 2 if item['key'] == 'usdcnh' else 1)} | "
            f"{fmt_signed(item.get('chg_1m'), 2 if item['key'] == 'usdcnh' else 1)} | "
            f"{fmt_signed(item.get('chg_3m'), 2 if item['key'] == 'usdcnh' else 1)} | {item.get('date', '')} |"
        )
    lines.append("")

    rows_all = indicator_rows(computed)
    missing = [r["name"] for r in rows_all if r["status"] in ("missing", "expired")]
    stale = [f"{r['name']}（{'滞后' if r['status'] == 'stale' else '过期'}）" for r in rows_all if r["status"] in ("stale", "expired")]
    lines.append("## 数据质量")
    lines.append("")
    lines.append(f"- 权重覆盖：{computed.get('coverage', 0) * 100:.0f}%")
    lines.append(f"- 缺失/过期：{'、'.join(missing) if missing else '无'}")
    lines.append(f"- 滞后：{'、'.join(stale) if stale else '无'}")
    lines.append(f"- 报告编号：{report.get('run_id', '')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("数据来源：国家统计局、中国人民银行、海关总署、财政部、国家发改委、东方财富、新浪财经、华尔街见闻及可选境外公开 RSS。")
    lines.append("")
    lines.append("本报告由程序自动生成，仅用于个人研究，不构成投资建议。")
    lines.append("")

    atomic_write(out_path, "\n".join(lines))
    return out_path
