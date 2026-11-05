"""指标打分与合成指数。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from ..registry import INDICATORS, INDICATOR_MAP, PILLAR_ORDER, Indicator
from ..util import clamp, to_monthly


@dataclass
class IndicatorScore:
    indicator: Indicator
    series: pd.Series          # 变换后的序列
    scores: pd.Series          # 0-100 分
    latest_date: pd.Timestamp | None
    value: float | None
    prior: float | None
    score: float | None
    score_3m_ago: float | None
    age_days: int | None
    status: str                # ok / stale / expired / missing
    effective_weight: float


def _transform(series: pd.Series, ind: Indicator) -> pd.Series:
    s = to_monthly(series, ind.freq)
    if s.empty:
        return s
    if ind.transform == "pct3":
        return ((s / s.shift(3) - 1.0) * 100.0).dropna()
    if ind.transform == "diff3_bp":
        return ((s - s.shift(3)) * 100.0).dropna()
    if ind.transform == "minus100":
        return (s - 100.0).dropna()
    return s


def _z_scores(s: pd.Series, ind: Indicator, cfg: dict[str, Any]) -> pd.Series:
    window = int(cfg.get("z_window_months", 60))
    minp_cfg = int(cfg.get("z_min_periods", 30))
    minp = min(minp_cfg, max(8, len(s) // 2))
    med = s.rolling(window, min_periods=minp).median()
    mad = (s - med).abs().rolling(window, min_periods=minp).median()
    scale = 1.4826 * mad
    std = s.rolling(window, min_periods=minp).std()
    scale = scale.where(scale > 1e-9, std)
    z = (s - med) / scale.replace(0, np.nan)
    z = z.clip(-float(cfg.get("z_clip", 2.5)), float(cfg.get("z_clip", 2.5)))
    return (50.0 + float(cfg.get("z_scale", 16)) * z * ind.direction).clip(0, 100)


def _level_scores(s: pd.Series, ind: Indicator) -> pd.Series:
    if not ind.anchors:
        return pd.Series(np.nan, index=s.index)
    values = np.interp(s.to_numpy(dtype=float), np.array(ind.anchor_x), np.array(ind.anchor_y))
    return pd.Series(values, index=s.index).clip(0, 100)


def score_indicator(
    ind: Indicator,
    raw: pd.Series,
    cfg: dict[str, Any],
    today: datetime,
) -> IndicatorScore:
    missing = IndicatorScore(ind, pd.Series(dtype="float64"), pd.Series(dtype="float64"), None, None, None, None, None, None, "missing", 0.0)
    if raw is None or raw.empty:
        return missing
    s = _transform(raw, ind)
    if s.empty:
        return missing
    scores = _z_scores(s, ind, cfg) if ind.method == "z" else _level_scores(s, ind)
    valid = scores.dropna()
    if valid.empty:
        return missing
    score_date = valid.index.max()
    value = float(s.loc[score_date])
    prior_values = s[s.index < score_date]
    prior = float(prior_values.iloc[-1]) if not prior_values.empty else None
    score = float(valid.loc[score_date])
    before = valid[valid.index <= score_date - pd.DateOffset(months=3)]
    score_3m = float(before.iloc[-1]) if not before.empty else None
    # 日频指标用真实最后观察日展示，避免显示“未来”的月末日期
    raw_obs = raw.dropna()
    latest_date = raw_obs.index.max() if ind.freq == "D" and not raw_obs.empty else score_date
    age = (pd.Timestamp(today).tz_localize(None).normalize() - pd.Timestamp(latest_date).normalize()).days
    normal = int(cfg.get("stale_days", {}).get(ind.freq, 75))
    drop = int(cfg.get("drop_days", {}).get(ind.freq, 120))
    if age > drop:
        status, weight = "expired", 0.0
    elif age > normal:
        status, weight = "stale", ind.weight * 0.6
    else:
        status, weight = "ok", ind.weight
    return IndicatorScore(ind, s, scores, latest_date, value, prior, score, score_3m, age, status, weight)


def _weighted_average(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    cols = [c for c in frame.columns if c in weights and weights[c] > 0]
    if not cols:
        return pd.Series(np.nan, index=frame.index)
    w = pd.Series({c: weights[c] for c in cols})
    data = frame[cols]
    numerator = (data * w).sum(axis=1, min_count=1)
    denominator = (data.notna() * w).sum(axis=1)
    return (numerator / denominator.replace(0, np.nan)).clip(0, 100)


def _temperature(score: float, thresholds: dict[str, float]) -> str:
    if score < thresholds.get("cold", 40):
        return "偏冷"
    if score < thresholds.get("cool", 47.5):
        return "偏弱"
    if score < thresholds.get("warm", 52.5):
        return "中性"
    if score < thresholds.get("hot", 60):
        return "偏暖"
    return "偏热"


def _regime(growth: float | None, cpi: float | None) -> str:
    if growth is None or cpi is None:
        return "数据不足"
    if growth >= 55:
        return "过热" if cpi >= 3 else "扩张"
    if growth < 45:
        if cpi >= 3:
            return "滞胀"
        if cpi < 1:
            return "偏冷 / 通缩压力"
        return "放缓"
    return "弱复苏 / 分化"


def compute(
    results: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    today: datetime,
) -> dict[str, Any]:
    scoring_cfg = cfg.get("scoring", {})
    pillar_cfg = cfg.get("pillars", {})
    thresholds = cfg.get("thresholds", {}).get("temperature", {})

    indicator_scores: dict[str, IndicatorScore] = {}
    for ind in INDICATORS:
        raw = results.get(ind.base_key, {}).get("series", pd.Series(dtype="float64"))
        indicator_scores[ind.key] = score_indicator(ind, raw, scoring_cfg, today)

    # ---------- 当期五维得分 ----------
    pillars: dict[str, dict[str, Any]] = {}
    pillar_scores: dict[str, float] = {}
    contributions: list[dict[str, Any]] = []

    for pillar in PILLAR_ORDER:
        members = [x for x in INDICATORS if x.pillar == pillar]
        avail = [x for x in members if indicator_scores[x.key].status in ("ok", "stale")]
        weight_sum = sum(indicator_scores[x.key].effective_weight for x in avail)
        if not avail or weight_sum <= 0:
            pillars[pillar] = {
                "score": None,
                "delta_3m": None,
                "coverage": 0.0,
                "weight": float(pillar_cfg.get(pillar, {}).get("weight", 0.0)),
                "top_pos": [],
                "top_neg": [],
            }
            continue
        score = sum(
            (indicator_scores[x.key].score or 50.0) * indicator_scores[x.key].effective_weight
            for x in avail
        ) / weight_sum
        deltas = []
        for x in avail:
            info = indicator_scores[x.key]
            if info.score is not None and info.score_3m_ago is not None:
                deltas.append((info.score - info.score_3m_ago) * info.effective_weight)
        delta = sum(deltas) / weight_sum if deltas else None
        pillar_scores[pillar] = float(score)

        contribs = []
        for x in avail:
            info = indicator_scores[x.key]
            w_norm = info.effective_weight / weight_sum
            contrib = ((info.score or 50.0) - 50.0) * w_norm
            contribs.append(
                {
                    "key": x.key,
                    "name": x.name,
                    "score": info.score,
                    "value": info.value,
                    "unit": x.unit,
                    "decimals": x.decimals,
                    "weight": info.effective_weight,
                    "contribution": contrib,
                    "status": info.status,
                    "period": info.latest_date.strftime("%Y-%m") if info.latest_date is not None else "",
                    "source": x.source,
                    "note": x.note,
                }
            )
        contribs.sort(key=lambda z: z["contribution"], reverse=True)
        pillars[pillar] = {
            "score": float(score),
            "delta_3m": float(delta) if delta is not None else None,
            "coverage": float(weight_sum / sum(x.weight for x in members)) if members else 0.0,
            "weight": float(pillar_cfg.get(pillar, {}).get("weight", 0.0)),
            "top_pos": [c for c in contribs if c["contribution"] > 0][:2],
            "top_neg": [c for c in contribs if c["contribution"] < 0][-2:][::-1],
        }
        for c in contribs:
            c["pillar"] = pillar
            c["pillar_weight"] = float(pillar_cfg.get(pillar, {}).get("weight", 0.0))
            contributions.append(c)

    active_pillars = {k: v for k, v in pillar_scores.items() if v is not None}
    total_pw = sum(float(pillar_cfg.get(k, {}).get("weight", 0.0)) for k in active_pillars)
    if total_pw > 0:
        composite = sum(v * float(pillar_cfg.get(k, {}).get("weight", 0.0)) for k, v in active_pillars.items()) / total_pw
    else:
        composite = None

    # 把指标贡献换算成对总分的贡献
    for c in contributions:
        pw = c["pillar_weight"]
        active_pw_sum = sum(
            float(pillar_cfg.get(k, {}).get("weight", 0.0)) for k in active_pillars
        )
        c["total_contribution"] = c["contribution"] * (pw / active_pw_sum) if active_pw_sum else 0.0
    contributions.sort(key=lambda z: z["total_contribution"], reverse=True)

    # ---------- 历史序列 ----------
    score_frame = pd.DataFrame({k: v.scores for k, v in indicator_scores.items()})
    if score_frame.empty:
        history = pd.Series(dtype="float64")
        history_pillars = pd.DataFrame()
    else:
        score_frame = score_frame.sort_index()
        pillar_frames: dict[str, pd.Series] = {}
        for pillar in PILLAR_ORDER:
            cols = {x.key: x.weight for x in INDICATORS if x.pillar == pillar}
            pillar_frames[pillar] = _weighted_average(score_frame, cols)
        history_pillars = pd.DataFrame(pillar_frames)
        pw = {k: float(pillar_cfg.get(k, {}).get("weight", 0.0)) for k in PILLAR_ORDER}
        history = _weighted_average(history_pillars, pw)

    # 历史覆盖率：至少一半权重有数据
    today_naive = pd.Timestamp(today).tz_localize(None).normalize()
    if not history.empty:
        history = history.dropna()
        if not history.empty:
            history = history[history.index >= (today_naive - pd.DateOffset(months=72))]
            if not history.empty and composite is not None:
                if history.index[-1].to_period("M") == today_naive.to_period("M"):
                    history.iloc[-1] = composite
                else:
                    history.loc[today_naive + pd.offsets.MonthEnd(0)] = composite
            history = history.tail(int(cfg.get("app", {}).get("history_months", 36)))

    comp_3m = None
    if not history.empty and len(history) > 3:
        comp_3m = float(history.iloc[-4])
    delta = (composite - comp_3m) if (composite is not None and comp_3m is not None) else None
    improving = 0
    total_avail = 0
    for info in indicator_scores.values():
        if info.score is not None and info.score_3m_ago is not None and info.status != "expired":
            total_avail += 1
            if info.score > info.score_3m_ago:
                improving += 1
    improving_share = improving / total_avail if total_avail else None

    coverage = 0.0
    total_weight = sum(x.weight for x in INDICATORS)
    if total_weight:
        coverage = sum(
            x.effective_weight for x in indicator_scores.values() if x.status in ("ok", "stale")
        ) / total_weight

    cpi_info = indicator_scores.get("cpi_yoy")
    growth_score = pillars.get("growth", {}).get("score")
    regime = _regime(growth_score, cpi_info.value if cpi_info and cpi_info.value is not None else None)

    return {
        "indicators": indicator_scores,
        "pillars": pillars,
        "composite": round(float(composite), 1) if composite is not None else None,
        "composite_3m_ago": round(comp_3m, 1) if comp_3m is not None else None,
        "delta_3m": round(float(delta), 1) if delta is not None else None,
        "history": history,
        "history_pillars": history_pillars,
        "coverage": round(coverage, 2),
        "improving_share": round(improving_share, 2) if improving_share is not None else None,
        "temperature": _temperature(composite, thresholds) if composite is not None else "数据不足",
        "regime": regime,
        "contributions": contributions,
    }


def indicator_rows(computed: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pillar in PILLAR_ORDER:
        members = sorted(
            [x for x in INDICATORS if x.pillar == pillar],
            key=lambda z: z.weight,
            reverse=True,
        )
        for ind in members:
            info: IndicatorScore = computed["indicators"][ind.key]
            score_delta = None
            if info.score is not None and info.score_3m_ago is not None:
                score_delta = info.score - info.score_3m_ago
            rows.append(
                {
                    "key": ind.key,
                    "name": ind.name,
                    "pillar": pillar,
                    "unit": ind.unit,
                    "decimals": ind.decimals,
                    "value": info.value,
                    "prior": info.prior,
                    "score": round(info.score, 1) if info.score is not None else None,
                    "score_delta_3m": round(score_delta, 1) if score_delta is not None else None,
                    "period": info.latest_date.strftime("%Y-%m-%d") if info.latest_date is not None else "",
                    "age_days": info.age_days,
                    "status": info.status,
                    "weight": ind.weight,
                    "source": ind.source,
                    "note": ind.note,
                    "signal": (
                        "偏强" if info.score is not None and info.score >= 60
                        else "偏弱" if info.score is not None and info.score <= 40
                        else "中性" if info.score is not None
                        else "—"
                    ),
                }
            )
    return rows
