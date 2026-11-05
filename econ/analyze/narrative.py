"""把分数翻译成人话：规则版 + 可选大模型版。"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from ..util import fmt_num, fmt_signed

logger = logging.getLogger("econ.narrative")


def _unit(unit: str) -> str:
    if unit == "pct":
        return " 个百分点"
    return unit


def _value_text(item: dict[str, Any]) -> str:
    value = item.get("value")
    if value is None:
        return "—"
    decimals = int(item.get("decimals", 1))
    return f"{value:,.{decimals}f}{_unit(item.get('unit', ''))}"


def _state(score: float | None) -> str:
    if score is None:
        return "未知"
    if score >= 60:
        return "偏强"
    if score >= 52.5:
        return "偏暖"
    if score >= 47.5:
        return "中性"
    if score >= 40:
        return "偏弱"
    return "偏冷"


def _news_state(score: float | None, thresholds: dict[str, float]) -> str:
    if score is None:
        return "中性"
    if score >= thresholds.get("positive", 55):
        return "偏乐观"
    if score <= thresholds.get("negative", 45):
        return "偏悲观"
    return "中性"


def _direction(delta: float | None) -> str:
    if delta is None:
        return "方向不明"
    if delta >= 2:
        return "明显改善"
    if delta >= 0.5:
        return "小幅改善"
    if delta <= -2:
        return "明显走弱"
    if delta <= -0.5:
        return "小幅走弱"
    return "基本持平"


def _next_month_label(period: str, fallback: str) -> str:
    try:
        ts = datetime.strptime(period[:7], "%Y-%m")
        month = ts.month + 1
        year = ts.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        return f"{month}月"
    except Exception:  # noqa: BLE001
        return fallback


def build_context(
    computed: dict[str, Any],
    news: dict[str, Any],
    market: dict[str, Any],
    cfg: dict[str, Any],
    report_date: datetime,
) -> dict[str, Any]:
    news_thresholds = cfg.get("thresholds", {}).get("news", {})
    indicators = computed["indicators"]
    rows = []
    for key, info in indicators.items():
        ind = info.indicator
        rows.append(
            {
                "key": key,
                "name": ind.name,
                "pillar": ind.pillar,
                "value": info.value,
                "unit": ind.unit,
                "decimals": ind.decimals,
                "score": round(info.score, 1) if info.score is not None else None,
                "status": info.status,
                "period": info.latest_date.strftime("%Y-%m") if info.latest_date else "",
            }
        )

    pos = [c for c in computed["contributions"] if c["total_contribution"] > 0][:4]
    neg = [c for c in computed["contributions"] if c["total_contribution"] < 0][-4:][::-1]
    pillars = []
    for key, p in computed["pillars"].items():
        pillars.append(
            {
                "key": key,
                "name": cfg.get("pillars", {}).get(key, {}).get("name", key),
                "score": round(p["score"], 1) if p["score"] is not None else None,
                "delta": round(p["delta_3m"], 1) if p["delta_3m"] is not None else None,
                "coverage": p["coverage"],
            }
        )

    cpi = indicators.get("cpi_yoy")
    cpi_text = _value_text({"value": cpi.value, "unit": cpi.indicator.unit, "decimals": cpi.indicator.decimals}) if cpi else "—"
    pmi = indicators.get("pmi_mfg")
    pmi_text = fmt_num(pmi.value, 1) if pmi else "—"
    fai = indicators.get("fai_yoy")
    retail = indicators.get("retail_yoy")
    exports = indicators.get("exports_yoy")

    market_rows = market.get("snapshot", [])
    usdcnh = next((x for x in market_rows if x["key"] == "usdcnh"), None)
    copper = next((x for x in market_rows if x["key"] == "copper"), None)
    sse = next((x for x in market_rows if x["key"] == "sse"), None)

    return {
        "date": report_date.strftime("%Y-%m-%d"),
        "weekday": "一二三四五六日"[report_date.weekday()],
        "composite": computed["composite"],
        "temperature": computed["temperature"],
        "regime": computed["regime"],
        "delta_3m": computed["delta_3m"],
        "direction": _direction(computed["delta_3m"]),
        "coverage": computed["coverage"],
        "improving_share": computed["improving_share"],
        "pillars": pillars,
        "positive": pos,
        "negative": neg,
        "news_score": news.get("news_score"),
        "news_state": _news_state(news.get("news_score"), news_thresholds),
        "policy_score": news.get("policy_score"),
        "policy_label": news.get("policy_label"),
        "news_counts": news.get("counts", {}),
        "top_news": [
            {"title": x["title"], "source": x["source"], "label": x["label"], "sentiment": x["sentiment"]}
            for x in news.get("top", [])[:10]
        ],
        "positive_news": [
            {"title": x["title"], "source": x["source"], "sentiment": x["sentiment"]}
            for x in news.get("positive", [])[:4]
        ],
        "negative_news": [
            {"title": x["title"], "source": x["source"], "sentiment": x["sentiment"]}
            for x in news.get("negative", [])[:4]
        ],
        "cpi": cpi_text,
        "pmi": pmi_text,
        "fai": _value_text({"value": fai.value, "unit": fai.indicator.unit, "decimals": fai.indicator.decimals}) if fai else "—",
        "retail": _value_text({"value": retail.value, "unit": retail.indicator.unit, "decimals": retail.indicator.decimals}) if retail else "—",
        "exports": _value_text({"value": exports.value, "unit": exports.indicator.unit, "decimals": exports.indicator.decimals}) if exports else "—",
        "usdcnh": usdcnh,
        "copper": copper,
        "sse": sse,
        "rows": rows,
        "cpi_period": indicators["cpi_yoy"].latest_date.strftime("%Y-%m") if indicators.get("cpi_yoy") and indicators["cpi_yoy"].latest_date else "",
        "loan_period": indicators["loan_yoy"].latest_date.strftime("%Y-%m") if indicators.get("loan_yoy") and indicators["loan_yoy"].latest_date else "",
        "ip_period": indicators["ip_yoy"].latest_date.strftime("%Y-%m") if indicators.get("ip_yoy") and indicators["ip_yoy"].latest_date else "",
    }


def template_narrative(ctx: dict[str, Any]) -> dict[str, Any]:
    comp = ctx["composite"]
    delta = ctx["delta_3m"]
    temp = ctx["temperature"]
    regime = ctx["regime"]
    direction = ctx["direction"]

    pos_names = "、".join(f"{x['name']}（{_value_text(x)}）" for x in ctx["positive"][:3]) or "暂无明显支撑"
    neg_names = "、".join(f"{x['name']}（{_value_text(x)}）" for x in ctx["negative"][:3]) or "暂无明显拖累"

    if comp is None:
        verdict = "数据不足，暂不下结论"
        summary = "本次运行可用指标过少，建议检查数据源后重试。"
        return {
            "verdict": verdict,
            "summary": summary,
            "drivers": [],
            "risks": ["数据覆盖不足，结论可靠性低"],
            "watch": ["检查数据源连接", "关注下一批宏观数据"],
            "source": "rules",
        }

    data_state = "偏强" if comp >= 52.5 else "偏弱" if comp < 47.5 else "中性"
    news_state = ctx["news_state"]
    policy_label = ctx.get("policy_label", "中性")
    if data_state == "偏弱" and news_state == "偏悲观":
        verdict = "数据与情绪共振向下，短期以防御为主"
    elif data_state == "偏弱" and policy_label == "偏宽松" and news_state == "偏乐观":
        verdict = "弱现实、强预期，政策发力期关注落地效果"
    elif data_state == "偏弱" and policy_label == "偏宽松":
        verdict = "弱现实、政策托底，关注宽信用能否传导"
    elif data_state == "偏弱":
        verdict = "数据偏弱、政策尚未明显加码，等待方向"
    elif data_state == "偏强" and news_state == "偏悲观":
        verdict = "数据尚可但预期转弱，警惕后续动能衰减"
    elif data_state == "偏强" and news_state == "偏乐观":
        verdict = "数据与情绪共振向上，景气度处于上行段"
    else:
        verdict = "多空信号交织，经济处于分化震荡期"

    extra = []
    external = next((p for p in ctx["pillars"] if p["key"] == "external"), None)
    housing = next((p for p in ctx["pillars"] if p["key"] == "housing"), None)
    if external and external["score"] is not None and external["score"] < 40:
        extra.append("外部环境偏紧")
    if housing and housing["score"] is not None and housing["score"] < 40:
        extra.append("地产链仍是拖累")
    if extra:
        verdict += "；" + "，".join(extra)

    summary = (
        f"经济温度 {comp:.1f}，处于「{temp}」区间，较 3 个月前{direction}"
        f"{'' if delta is None else f'（{fmt_signed(delta, 1)} 分）'}。"
        f"结构上，{regime}格局：{pos_names}是主要支撑，{neg_names}是主要拖累。"
        f"最新 CPI {ctx['cpi']}、制造业 PMI {ctx['pmi']}，社零 {ctx['retail']}、固投 {ctx['fai']}、出口 {ctx['exports']}。"
        f"新闻面{news_state}（{ctx['news_score'] or 50:.0f} 分），政策信号{ctx['policy_label']}。"
    )

    drivers = [f"{x['name']}：{_value_text(x)}，评分 {x['score']:.0f}" for x in ctx["positive"][:3]]
    risks = [
        f"{x['name']}：{_value_text(x)}，评分 {x['score']:.0f}"
        for x in ctx["negative"][:3]
    ]
    if news_state == "偏悲观":
        risks.append("新闻情绪偏弱，注意预期自我强化")
    if ctx["coverage"] < 0.75:
        risks.append(f"数据覆盖率仅 {ctx['coverage'] * 100:.0f}%，结论置信度受影响")

    watch = []
    if ctx["cpi_period"]:
        watch.append(f"{_next_month_label(ctx['cpi_period'], '下月')} CPI / PPI")
    if ctx["loan_period"]:
        watch.append(f"{_next_month_label(ctx['loan_period'], '下月')} 社融 / 信贷")
    if ctx["ip_period"]:
        watch.append(f"{_next_month_label(ctx['ip_period'], '下月')} 工业、社零、固投")
    watch.append("美联储表态与关税/贸易政策变化")
    watch = watch[:4]

    return {
        "verdict": verdict,
        "summary": summary,
        "drivers": drivers,
        "risks": risks,
        "watch": watch,
        "source": "rules",
    }


def _llm_key(cfg: dict[str, Any]) -> str:
    llm = cfg.get("llm", {})
    if str(llm.get("enabled", "auto")).lower() in ("false", "0", "no", "off"):
        return ""
    key = os.environ.get(str(llm.get("api_key_env", "ECON_LLM_API_KEY")), "") or str(llm.get("api_key", "") or "")
    return key.strip()


def llm_narrative(ctx: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    key = _llm_key(cfg)
    if not key:
        return None
    try:
        from openai import OpenAI

        llm = cfg.get("llm", {})
        client = OpenAI(
            api_key=key,
            base_url=str(llm.get("base_url", "https://api.deepseek.com")),
            timeout=float(llm.get("timeout", 60)),
        )
        payload = {
            "date": ctx["date"],
            "composite_0_100": ctx["composite"],
            "temperature": ctx["temperature"],
            "regime": ctx["regime"],
            "delta_3m": ctx["delta_3m"],
            "direction": ctx["direction"],
            "coverage": ctx["coverage"],
            "pillars": ctx["pillars"],
            "main_supports": [
                {"name": x["name"], "value": _value_text(x), "score": x["score"]}
                for x in ctx["positive"][:4]
            ],
            "main_drags": [
                {"name": x["name"], "value": _value_text(x), "score": x["score"]}
                for x in ctx["negative"][:4]
            ],
            "news_score_0_100": ctx["news_score"],
            "news_state": ctx["news_state"],
            "policy_stance": ctx["policy_label"],
            "headlines": [x["title"] for x in ctx["top_news"][:8]],
            "key_data": {
                "CPI": ctx["cpi"],
                "PMI": ctx["pmi"],
                "社零": ctx["retail"],
                "固投": ctx["fai"],
                "出口": ctx["exports"],
            },
        }
        system = (
            "你是一名严谨的中国宏观分析师。根据给定的结构化数据，写一份克制、可读的每日判断。"
            "硬性要求：1) 只能引用输入中出现的数字，绝对不能编造或外推；2) 明确区分“数据现实”和“新闻预期”；"
            "3) 指出 1-3 个主要支撑、1-3 个主要拖累、2-3 个风险；4) 不做点位预测，不喊口号；"
            "5) 输出必须是 JSON，字段为 verdict（一句话，<=40字）、summary（120-180字）、"
            "drivers（字符串数组）、risks（字符串数组）、watch（字符串数组，未来2-4周关注点）。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            resp = client.chat.completions.create(
                model=str(llm.get("model", "deepseek-chat")),
                messages=messages,
                temperature=0.3,
                max_tokens=int(llm.get("max_tokens", 1200)),
                response_format={"type": "json_object"},
            )
        except Exception:  # noqa: BLE001
            resp = client.chat.completions.create(
                model=str(llm.get("model", "deepseek-chat")),
                messages=messages,
                temperature=0.3,
                max_tokens=int(llm.get("max_tokens", 1200)),
            )
        content = (resp.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        out = {
            "verdict": str(data.get("verdict", ""))[:80],
            "summary": str(data.get("summary", ""))[:500],
            "drivers": [str(x)[:120] for x in (data.get("drivers") or [])][:4],
            "risks": [str(x)[:120] for x in (data.get("risks") or [])][:4],
            "watch": [str(x)[:120] for x in (data.get("watch") or [])][:4],
            "source": "llm",
        }
        if not out["verdict"] or not out["summary"]:
            return None
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 解读失败，改用规则版：%s", exc)
        return None


def generate(ctx: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    base = template_narrative(ctx)
    llm = llm_narrative(ctx, cfg)
    if llm:
        # 规则版作为兜底字段，LLM 只覆盖文字部分
        for key in ("verdict", "summary", "drivers", "risks", "watch"):
            if llm.get(key):
                base[key] = llm[key]
        base["source"] = "llm"
    return base
