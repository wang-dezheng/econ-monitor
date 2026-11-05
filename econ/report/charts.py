"""图表：全部输出 SVG，直接内嵌 HTML，不依赖外部 CDN。"""
from __future__ import annotations

import io
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from ..registry import PILLAR_ORDER  # noqa: E402


def _setup_font() -> None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    candidates = [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC",
        "Noto Sans CJK JP", "Source Han Sans SC", "WenQuanYi Zen Hei", "Arial Unicode MS",
    ]
    chosen = next((c for c in candidates if c in names), "")
    if not chosen:
        for name in sorted(names):
            if any(key in name for key in ("Noto Sans CJK", "Noto Sans SC", "Source Han Sans", "WenQuanYi")):
                chosen = name
                break
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "path"
    plt.rcParams["figure.facecolor"] = "none"
    plt.rcParams["axes.facecolor"] = "none"


_setup_font()


def _color(score: float) -> str:
    if score < 40:
        return "#2b6cb0"
    if score < 47.5:
        return "#3f7f93"
    if score < 52.5:
        return "#7b8494"
    if score < 60:
        return "#c47a12"
    return "#b83227"


def _fig_to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.04, transparent=True)
    plt.close(fig)
    return buf.getvalue()


def gauge_svg(score: float | None, label: str, delta: float | None = None) -> str:
    if score is None:
        score = 50.0
    score = max(0.0, min(100.0, float(score)))
    cx, cy, r = 130.0, 128.0, 92.0
    color = _color(score)

    def pt(angle_deg: float, radius: float = r) -> tuple[float, float]:
        rad = math.radians(angle_deg)
        return cx + radius * math.cos(rad), cy - radius * math.sin(rad)

    left = pt(180)
    right = pt(0)
    angle = 180.0 - score * 1.8
    end = pt(angle)
    bg = f"M {left[0]:.2f} {left[1]:.2f} A {r} {r} 0 0 1 {right[0]:.2f} {right[1]:.2f}"
    arc = f"M {left[0]:.2f} {left[1]:.2f} A {r} {r} 0 0 1 {end[0]:.2f} {end[1]:.2f}"
    needle = pt(angle, r - 16)

    ticks = []
    for value in (0, 25, 50, 75, 100):
        a = 180.0 - value * 1.8
        p1 = pt(a, r + 7)
        p2 = pt(a, r + 14)
        tx, ty = pt(a, r + 26)
        ticks.append(
            f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
            f'stroke="#cbd5e1" stroke-width="1.2" />'
            f'<text x="{tx:.1f}" y="{ty + 4:.1f}" text-anchor="middle" font-size="9" fill="#94a3b8">{value}</text>'
        )

    delta_text = ""
    if delta is not None:
        arrow = "▲" if delta > 0.05 else "▼" if delta < -0.05 else "•"
        arrow_color = "#b83227" if delta > 0.05 else "#1e8449" if delta < -0.05 else "#7b8494"
        delta_text = (
            f'<text x="{cx}" y="{cy + 39}" text-anchor="middle" font-size="11" fill="{arrow_color}">'
            f'{arrow} {abs(delta):.1f} 分 / 3个月</text>'
        )

    return f"""
<svg viewBox="0 0 260 172" role="img" aria-label="经济温度 {score:.1f}">
  <path d="{bg}" fill="none" stroke="#e8ecf1" stroke-width="13" stroke-linecap="round" />
  <path d="{arc}" fill="none" stroke="{color}" stroke-width="13" stroke-linecap="round" />
  {''.join(ticks)}
  <line x1="{cx}" y1="{cy}" x2="{needle[0]:.1f}" y2="{needle[1]:.1f}" stroke="#22303f" stroke-width="2.4" stroke-linecap="round" />
  <circle cx="{cx}" cy="{cy}" r="5.2" fill="#22303f" />
  <text x="{cx}" y="{cy - 10}" text-anchor="middle" font-size="41" font-weight="700" fill="#15202b" stroke="#ffffff" stroke-width="3" paint-order="stroke">{score:.1f}</text>
  <text x="{cx}" y="{cy + 11}" text-anchor="middle" font-size="12" fill="#64748b" letter-spacing="1" stroke="#ffffff" stroke-width="2.4" paint-order="stroke">{label}</text>
  {delta_text}
</svg>
"""


def radar_svg(pillars: list[dict[str, Any]], names: dict[str, str]) -> str:
    labels = [names.get(p["key"], p["key"]) for p in pillars]
    values = [float(p["score"]) if p["score"] is not None else 0.0 for p in pillars]
    n = len(labels)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]
    vals = values + values[:1]

    fig = plt.figure(figsize=(4.4, 3.9))
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75])
    ax.set_yticklabels(["25", "50", "75"], fontsize=7, color="#94a3b8")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9, color="#334155")
    ax.grid(color="#e2e8f0", linewidth=0.8)
    ax.spines["polar"].set_color("#e2e8f0")
    ax.plot(angles, vals, color="#b83227", linewidth=1.8)
    ax.fill(angles, vals, color="#b83227", alpha=0.13)
    ax.scatter(angles[:-1], values, color="#b83227", s=16, zorder=5)
    for angle, value in zip(angles[:-1], values):
        ax.text(angle, min(100, value + 9), f"{value:.0f}", ha="center", va="center", fontsize=8, color="#7f1d1d")
    return _fig_to_svg(fig)


def trend_svg(history: pd.Series, thresholds: dict[str, float]) -> str:
    if history is None or history.empty:
        return '<div class="empty">历史数据不足</div>'
    h = history.dropna()
    fig, ax = plt.subplots(figsize=(9.6, 3.0))
    ax.axhspan(45, 55, color="#eef2f6", zorder=0)
    ax.axhline(50, color="#cbd5e1", linewidth=1, linestyle=(0, (4, 4)), zorder=1)
    ax.plot(h.index, h.values, color="#22303f", linewidth=2.0, zorder=3)
    if len(h) >= 3:
        ax.plot(h.index, h.rolling(3, min_periods=2).mean(), color="#b83227", linewidth=1.3, linestyle="--", alpha=0.85, zorder=2)
    last_x, last_y = h.index[-1], float(h.iloc[-1])
    ax.scatter([last_x], [last_y], s=34, color=_color(last_y), zorder=5)
    ax.annotate(
        f"当前 {last_y:.1f}",
        xy=(last_x, last_y),
        xytext=(-8, 14),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color="#15202b",
        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#e2e8f0", lw=0.7),
    )
    ax.set_ylim(28, 72)
    ax.set_ylabel("0-100", fontsize=8, color="#94a3b8")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.tick_params(axis="both", labelsize=8, colors="#94a3b8")
    ax.grid(axis="y", color="#eef2f6", linewidth=0.9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#e2e8f0")
    fig.tight_layout()
    return _fig_to_svg(fig)


def sparklines_svg(panels: list[dict[str, Any]], months: int = 36) -> str:
    """2x3 小图：每个 panel 传 name / series / ref / unit / decimals。"""
    panels = [p for p in panels if p.get("series") is not None and not p["series"].empty][:6]
    if not panels:
        return '<div class="empty">暂无可用序列</div>'
    rows = 2
    cols = 3
    fig, axes = plt.subplots(rows, cols, figsize=(10.6, 5.3))
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(panels) :]:
        ax.axis("off")
    for ax, panel in zip(axes, panels):
        s = panel["series"].dropna()
        s = s[s.index >= (s.index.max() - pd.DateOffset(months=months))]
        if s.empty:
            ax.axis("off")
            continue
        ax.plot(s.index, s.values, color="#22303f", linewidth=1.45)
        ref = panel.get("ref")
        if ref is not None:
            ax.axhline(ref, color="#cbd5e1", linewidth=0.9, linestyle=(0, (3, 3)))
        last = float(s.iloc[-1])
        unit = panel.get("unit", "")
        decimals = int(panel.get("decimals", 1))
        color = "#b83227" if ref is not None and last > ref else "#1e8449" if ref is not None and last < ref else "#22303f"
        ax.scatter([s.index[-1]], [last], s=12, color=color, zorder=4)
        ax.set_title(f"{panel['name']}  {last:,.{decimals}f}{unit}", fontsize=9, color="#334155", loc="left", pad=6)
        ax.tick_params(axis="both", labelsize=7, colors="#94a3b8", length=0)
        ax.grid(axis="y", color="#f1f4f8", linewidth=0.8)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#e8ecf1")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=12))
    fig.tight_layout(h_pad=1.5, w_pad=1.4)
    return _fig_to_svg(fig)
