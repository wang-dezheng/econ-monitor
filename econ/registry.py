"""指标注册表：定义指标口径、维度、权重与打分锚点。

打分方法：
- level：按锚点做分段线性映射。适合 PMI、CPI、房价等有“合理区间”的指标。
- z：相对最近 5 年的稳健 z 分数（中位数 / MAD），再映射到 0-100。
  适合增速类指标，避免结构性下台阶被误判为“永久衰退”。
- transform：先把原始序列做变换再打分。
  pct3      = 3 个月涨跌幅（%）
  diff3_bp  = 3 个月变化（bp，原始单位为 %）
  minus100  = 指数减 100（把“上年同月=100”转成年率 %）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Indicator:
    key: str
    name: str
    pillar: str
    weight: float
    unit: str = ""
    decimals: int = 1
    freq: str = "M"          # M 月度 / Q 季度
    method: str = "z"        # z / level
    transform: str = "none"  # none / pct3 / diff3_bp / minus100
    anchors: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    source: str = ""
    note: str = ""
    direction: int = 1       # z 分数方向：+1 越高越好，-1 越高越差
    raw_key: str = ""        # 采集序列的键名（默认与 key 相同）

    @property
    def base_key(self) -> str:
        return self.raw_key or self.key

    @property
    def anchor_x(self) -> list[float]:
        return [float(a) for a, _ in self.anchors]

    @property
    def anchor_y(self) -> list[float]:
        return [float(b) for _, b in self.anchors]


INDICATORS: list[Indicator] = [
    # ---------------- 增长动能 ----------------
    Indicator(
        "pmi_mfg", "制造业 PMI", "growth", 0.18, "", 1, "M", "level", "none",
        ((42, 2), (45, 10), (47, 25), (49, 42), (50, 50), (51, 58), (52, 68), (54, 82), (57, 96)),
        "国家统计局", "50 为荣枯线；高于 50 表示扩张。",
    ),
    Indicator(
        "pmi_nonmfg", "非制造业 PMI", "growth", 0.08, "", 1, "M", "level", "none",
        ((40, 2), (44, 12), (47, 28), (49, 42), (50, 50), (51, 58), (53, 72), (55, 84), (58, 96)),
        "国家统计局", "服务业与建筑业的景气度。",
    ),
    Indicator(
        "gdp_yoy", "GDP 同比", "growth", 0.10, "%", 1, "Q", "z", "none",
        source="国家统计局", note="季度实际增速，相对自身近 5 年水平打分。",
    ),
    Indicator(
        "ip_yoy", "规上工业增加值同比", "growth", 0.16, "%", 1, "M", "z", "none",
        source="国家统计局", note="生产端高频指标。",
    ),
    Indicator(
        "retail_yoy", "社会消费品零售总额同比", "growth", 0.16, "%", 1, "M", "z", "none",
        source="国家统计局", note="消费端高频指标。",
    ),
    Indicator(
        "fai_yoy", "固定资产投资同比", "growth", 0.12, "%", 1, "M", "level", "none",
        ((-20, 2), (-10, 15), (-5, 30), (0, 45), (3, 60), (6, 75), (10, 90)),
        "国家统计局", "投资端高频指标，含基建、制造业、地产。",
    ),
    Indicator(
        "exports_yoy", "出口同比（美元）", "growth", 0.12, "%", 1, "M", "z", "none",
        source="海关总署", note="外需与出口链景气度。",
    ),
    Indicator(
        "consumer_confidence", "消费者信心指数", "growth", 0.08, "", 1, "M", "level", "none",
        ((80, 5), (85, 20), (88, 35), (90, 50), (92, 62), (95, 75), (100, 88), (105, 96)),
        "国家统计局", "预期与消费意愿的领先指标。",
    ),

    # ---------------- 物价水平 ----------------
    Indicator(
        "cpi_yoy", "CPI 同比", "prices", 0.55, "%", 1, "M", "level", "none",
        ((-1, 3), (0, 12), (0.5, 28), (1, 42), (2, 65), (3, 88), (4, 50), (5, 15)),
        "国家统计局", "2% 左右为温和通胀；过低有通缩压力，过高有政策收紧压力。",
    ),
    Indicator(
        "ppi_yoy", "PPI 同比", "prices", 0.45, "%", 1, "M", "level", "none",
        ((-8, 2), (-5, 10), (-3, 22), (-1, 38), (0, 48), (1, 58), (3, 70), (5, 75), (8, 50)),
        "国家统计局", "工业品价格，反映企业盈利与需求冷暖。",
    ),

    # ---------------- 货币信用 ----------------
    Indicator(
        "m2_yoy", "M2 同比", "money", 0.25, "%", 1, "M", "z", "none",
        source="中国人民银行", note="广义货币供给。",
    ),
    Indicator(
        "m1_yoy", "M1 同比", "money", 0.25, "%", 1, "M", "z", "none",
        source="中国人民银行", note="企业活期资金，领先于投资和补库存。",
    ),
    Indicator(
        "m1_m2_gap", "M1-M2 剪刀差", "money", 0.20, "pct", 1, "M", "z", "none",
        source="中国人民银行", note="正值扩大通常意味着资金活化、需求改善。",
    ),
    Indicator(
        "loan_yoy", "新增人民币贷款同比", "money", 0.20, "%", 1, "M", "level", "none",
        ((-50, 5), (-20, 20), (-10, 40), (0, 50), (10, 60), (30, 75), (50, 90)),
        "中国人民银行", "信贷投放力度，负值表示同比少增。",
    ),
    Indicator(
        "lpr_chg_3m", "LPR(1Y) 3 个月变化", "money", 0.10, "bp", 0, "M", "level", "diff3_bp",
        ((-30, 80), (-15, 70), (-5, 58), (0, 50), (5, 35), (15, 20)),
        "中国人民银行", "降息为宽松信号；这里衡量 3 个月内的政策利率变化。",
    ),

    # ---------------- 地产链 ----------------
    Indicator(
        "home_breadth", "70 城新房环比上涨城市占比", "housing", 0.40, "%", 0, "M", "level", "none",
        ((0, 3), (10, 15), (20, 30), (30, 45), (40, 58), (50, 70), (60, 82), (80, 95)),
        "国家统计局 / 东方财富", "房价扩散指数：上涨城市越多，地产链越健康。",
    ),
    Indicator(
        "home_price_yoy", "70 城新房价格同比（均值）", "housing", 0.30, "%", 1, "M", "level", "minus100",
        ((-8, 3), (-5, 12), (-3, 25), (-1, 40), (0, 50), (1, 60), (3, 72), (5, 85)),
        "国家统计局 / 东方财富", "70 城新建商品住宅价格指数的平均值。",
    ),
    Indicator(
        "tier1_secondhand_mom", "一线二手房环比（均值）", "housing", 0.30, "%", 1, "M", "level", "minus100",
        ((-2, 5), (-1, 18), (-0.5, 35), (0, 50), (0.3, 62), (0.6, 75), (1, 90)),
        "国家统计局 / 东方财富", "北京、上海、广州、深圳二手住宅环比均值，领先于全国。",
    ),

    # ---------------- 外部环境 ----------------
    Indicator(
        "us_curve", "美债 10Y-2Y 利差", "external", 0.18, "pct", 2, "D", "level", "none",
        ((-1.5, 3), (-1, 10), (-0.5, 25), (0, 40), (0.5, 55), (1, 68), (1.5, 80), (2, 90)),
        "美国财政部", "倒挂通常被视为衰退预警；转正并陡峭化也不总是好事。",
    ),
    Indicator(
        "us10y_chg_3m", "美债 10Y 收益率 3 个月变化", "external", 0.12, "bp", 0, "D", "level", "diff3_bp",
        ((-100, 70), (-50, 62), (-20, 55), (0, 50), (20, 42), (50, 30), (100, 15)),
        "美国财政部", "美债利率快速上行会收紧全球金融条件。", raw_key="us_10y",
    ),
    Indicator(
        "us_cpi_yoy", "美国 CPI 同比", "external", 0.18, "%", 1, "M", "level", "none",
        ((0, 65), (1, 70), (2, 65), (2.5, 58), (3, 45), (4, 25), (5, 12), (7, 3)),
        "美国劳工部", "影响美联储路径与全球利率。",
    ),
    Indicator(
        "usdcnh_chg_3m", "美元兑离岸人民币 3 个月变化", "external", 0.22, "%", 1, "D", "level", "pct3",
        ((-5, 70), (-2, 62), (-1, 55), (0, 50), (1, 42), (2, 32), (5, 18)),
        "东方财富", "数值为正表示人民币贬值，通常对应资本流出与风险偏好下降。", raw_key="usdcnh",
    ),
    Indicator(
        "copper_chg_3m", "沪铜 3 个月涨跌", "external", 0.15, "%", 1, "D", "level", "pct3",
        ((-15, 15), (-8, 30), (-3, 42), (0, 50), (3, 60), (8, 75), (15, 88)),
        "上海期货交易所", "铜是“铜博士”，反映全球制造业需求。", raw_key="copper",
    ),
    Indicator(
        "brent_chg_3m", "原油 3 个月涨跌", "external", 0.15, "%", 1, "D", "level", "pct3",
        ((-30, 30), (-15, 42), (-5, 50), (0, 55), (5, 50), (15, 40), (30, 25)),
        "上海国际能源交易中心", "油价大幅波动对中国这个进口国偏负面；温和上行反映需求。", raw_key="brent",
    ),
]

INDICATOR_MAP = {item.key: item for item in INDICATORS}

PILLAR_ORDER = ["growth", "prices", "money", "housing", "external"]

PILLAR_ICONS = {
    "growth": "▲",
    "prices": "◈",
    "money": "◉",
    "housing": "⌂",
    "external": "◎",
}
