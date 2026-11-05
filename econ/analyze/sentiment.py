"""新闻情绪与政策信号打分。

不依赖大模型：用“宏观相关词 + 情绪短语 + 否定/程度副词 + 数字幅度”做可解释打分。
每条新闻都能看到命中了哪些词，方便人工复核。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from ..util import CN_TZ, clamp, tanh

# ---------------------------- 词典 ----------------------------

POS: dict[str, float] = {
    "超预期": 2.5, "好于预期": 2.5, "好于市场预期": 2.5, "超出市场预期": 2.5, "强于预期": 2.4, "高于预期": 2.2,
    "大幅增长": 2.4, "强劲增长": 2.4, "快速增长": 2.0, "显著增长": 2.0, "持续增长": 1.6,
    "由降转增": 2.0, "扭亏为盈": 2.0, "降幅收窄": 1.5, "跌幅收窄": 1.5,
    "失业率下降": 2.0, "就业改善": 1.7, "通胀回落": 1.2,
    "回升": 1.4, "回暖": 1.7, "复苏": 1.9, "扩张": 1.5, "改善": 1.4, "向好": 1.4,
    "企稳": 1.2, "反弹": 1.1, "转正": 1.7, "创新高": 1.7, "走强": 1.1, "上扬": 0.9,
    "加快": 0.8, "提速": 0.8, "提振": 1.4, "发力": 0.9, "加码": 0.9,
    "供需两旺": 2.0, "订单饱满": 1.7, "满产": 1.4, "扩产": 1.1, "开工率上升": 1.4,
    "盈利改善": 1.7, "利润增长": 1.4, "收入增长": 1.4,
    "消费回暖": 1.9, "销售回升": 1.7, "出口增长": 1.4, "投资增长": 1.4,
    "外资流入": 1.4, "资金流入": 1.1, "风险偏好上升": 1.1, "信心增强": 1.4,
    "预期改善": 1.4, "景气回升": 1.7, "PMI回升": 1.9, "CPI回升": 1.3, "PPI回升": 1.3,
    "价格企稳": 1.3, "去库存结束": 1.4, "补库存": 1.4, "稳中有进": 1.4,
    "PMI升至": 1.2, "站上50": 1.5, "释放长期流动性": 2.0, "降准降息": 3.0,
    "下调存款准备金率": 3.0, "下调政策利率": 2.8,
    "总体平稳": 0.9, "韧性": 0.9, "亮点": 1.0, "利好": 1.8, "突破": 0.9,
    "大涨": 1.8, "上涨": 0.7, "增长": 0.5, "增收": 0.8, "增持": 0.4,
}

NEG: dict[str, float] = {
    "低于预期": -2.5, "低于市场预期": -2.5, "不及市场预期": -2.5, "弱于市场预期": -2.3,
    "不及预期": -2.5, "弱于预期": -2.3, "差于预期": -2.4,
    "大幅下滑": -2.5, "显著下降": -2.2, "持续下降": -1.7, "负增长": -1.9,
    "萎缩": -1.9, "收缩": -1.7, "衰退": -2.4, "低迷": -1.7, "疲软": -1.7,
    "走弱": -1.4, "恶化": -1.9, "放缓": -1.1, "减速": -1.1, "回落": -0.9,
    "下降": -0.8, "下滑": -1.2, "承压": -1.1, "遇冷": -1.4, "遇阻": -1.1,
    "困难": -0.9, "风险": -0.7, "压力": -0.7, "担忧": -1.1, "恐慌": -1.7,
    "暴跌": -2.4, "大跌": -1.9, "熔断": -2.4, "崩盘": -2.8,
    "违约": -1.9, "爆雷": -2.4, "破产": -2.1, "倒闭": -1.9, "裁员": -1.9,
    "失业上升": -2.1, "失业率上升": -2.1, "就业恶化": -2.1, "通缩": -2.1,
    "滞胀": -2.4, "硬着陆": -2.4, "债务危机": -2.4, "地方债风险": -1.9,
    "房地产风险": -1.7, "烂尾": -1.9, "断供": -1.9, "停摆": -1.9,
    "供应链中断": -1.9, "出口下降": -1.7, "出口下滑": -1.9, "订单下降": -1.7,
    "产能过剩": -1.4, "价格战": -1.4, "内卷": -0.9, "利润下降": -1.7,
    "亏损": -1.7, "成本上升": -1.1, "通胀压力": -1.4, "加息": -1.7,
    "收紧": -1.4, "去杠杆": -1.4, "严监管": -0.9, "调控": -0.7,
    "限购": -0.9, "提高首付": -1.4, "降幅扩大": -1.4, "由增转降": -2.0,
    "供大于求": -1.1, "涨幅回落": -0.5, "下跌": -1.0, "减少": -0.6,
    "CPI下降": -1.0, "PMI下降": -1.5, "PMI降至": -1.2, "跌破50": -1.5,
    "需求不足": -1.4, "订单不足": -1.4, "需求疲弱": -1.4, "房地产投资下降": -1.8, "房企违约": -2.2, "失业": -1.2,
}

POS_EN: dict[str, float] = {
    "beats expectations": 2.5, "better than expected": 2.5, "stronger than expected": 2.4,
    "strong growth": 2.2, "accelerates": 1.4, "accelerating": 1.4, "rebounds": 1.7,
    "rebound": 1.5, "recovery": 1.7, "recovers": 1.5, "expands": 1.4, "expansion": 1.4,
    "improves": 1.4, "resilient": 1.1, "resilience": 1.1, "rate cut": 2.0,
    "cuts rates": 2.0, "cut rates": 2.0, "stimulus": 1.7, "eases": 1.3, "easing": 1.4,
    "trade deal": 1.9, "tariff cut": 1.9, "record high": 1.4, "upside surprise": 2.4,
    "hiring surge": 1.9, "inflation cools": 1.9, "soft landing": 1.7, "boosts": 1.3,
    "boost": 1.2, "growth": 0.5, "rises": 0.6, "gains": 0.6,
}

NEG_EN: dict[str, float] = {
    "misses expectations": -2.5, "worse than expected": -2.5, "weaker than expected": -2.4,
    "slumps": -2.2, "slump": -2.0, "contracts": -1.9, "contraction": -1.9, "recession": -2.4,
    "slowdown": -1.4, "slowing": -1.2, "weak": -1.1, "falls": -1.0, "falling": -1.0,
    "plunges": -2.4, "plunge": -2.2, "layoffs": -2.1, "jobless": -1.4, "default": -2.1,
    "crisis": -1.9, "tariff": -0.9, "sanctions": -1.9, "sanction": -1.7,
    "inflation accelerates": -2.0, "hot inflation": -1.9, "rate hike": -2.0,
    "hikes rates": -2.0, "tightening": -1.4, "debt ceiling": -1.4, "bankruptcy": -2.1,
    "selloff": -1.7, "war": -1.4, "conflict": -1.2, "downturn": -1.8,
    "stagflation": -2.3, "deflation": -2.0,
}

EASING: dict[str, float] = {
    "降准": 3.0, "降息": 3.0, "下调利率": 2.6, "下调LPR": 3.0, "降低LPR": 2.6,
    "下调房贷利率": 2.4, "宽松": 2.0, "释放流动性": 2.0, "流动性投放": 1.8,
    "净投放": 1.0, "再贷款": 1.4, "专项债": 1.2, "增发国债": 1.8,
    "特别国债": 1.8, "积极财政": 2.0, "加大财政": 1.7, "减税降费": 2.0,
    "补贴": 1.1, "以旧换新": 1.3, "设备更新": 1.1, "收储": 1.7,
    "保交楼": 1.7, "白名单": 1.1, "稳增长": 2.0, "扩内需": 2.0,
    "促消费": 1.7, "支持民营": 1.3, "放松限购": 2.0, "取消限购": 2.2,
    "降低首付": 2.0, "刺激": 1.7, "救市": 1.7, "国家队": 1.3,
    "降费": 1.2, "宽松周期": 1.8, "降息周期": 2.2,
}

TIGHTENING: dict[str, float] = {
    "加息": 2.4, "上调利率": 2.2, "收紧": 1.8, "去杠杆": 1.8,
    "严监管": 1.3, "压降": 1.2, "整顿": 1.3, "处罚": 1.2,
    "风险处置": 1.0, "限购": 1.2, "提高首付": 1.6, "调控": 1.0,
    "打破刚兑": 1.4, "防风险": 0.9, "降杠杆": 1.5, "紧缩": 1.8,
    "上调金融机构外汇存款准备金率": 1.8, "上调外汇存款准备金率": 1.8, "上调存款准备金率": 1.5,
}

# 政策宽松/收紧也计入总体情绪，但权重略低，避免与政策信号重复
for _k, _v in EASING.items():
    POS.setdefault(_k, _v * 0.8)
for _k, _v in TIGHTENING.items():
    NEG.setdefault(_k, -_v * 0.8)

SENTIMENT = {**POS, **NEG, **POS_EN, **NEG_EN}
POLICY = {**{k: v for k, v in EASING.items()}, **{k: -v for k, v in TIGHTENING.items()}}

STRONG_MACRO = [
    "经济", "GDP", "CPI", "PPI", "PMI", "央行", "降准", "降息", "加息", "财政",
    "货币", "信贷", "社融", "出口", "进口", "关税", "房地产", "楼市", "房价",
    "就业", "失业", "制造业", "消费", "投资", "美联储", "利率", "汇率", "人民币",
    "国债", "通胀", "通缩", "债务", "地方债", "政治局", "国常会", "国务院",
    "发改委", "统计局", "财政部", "证监会", "贸易", "制裁", "衰退", "银行",
    "保险", "债券", "股市", "美股", "港股", "A股", "黄金", "原油", "铜",
    "大宗商品", "供应链", "十五五", "新质生产力", "民营经济", "以旧换新",
    "专项债", "特别国债", "稳增长", "逆回购", "流动性", "贷款", "存款",
    "外汇", "储备", "工业", "零售", "固定资产投资", "商品房", "土地",
    "化债", "城投", "美债", "美元", "欧洲央行", "日本央行", "IMF",
    "世界银行", "全球经济", "贸易战", "反倾销", "地缘", "战争", "停火",
    "economy", "inflation", "recession", "fed", "tariff", "gdp", "pmi", "cpi",
]
WEAK_MACRO = [
    "增长", "下降", "回升", "政策", "会议", "报告", "数据", "市场", "价格",
    "订单", "利润", "企业", "行业", "需求", "供给", "预期", "风险", "融资",
]
CHINA_WORDS = [
    "中国", "国内", "全国", "央行", "人民银行", "财政", "统计局", "发改委", "国务院", "人民币",
    "a股", "港股", "恒指", "沪深", "楼市", "房地产", "社融", "信贷", "m1", "m2",
    "地方债", "城投", "化债", "十五五", "以旧换新", "专项债", "特别国债", "降准", "降息",
    "lpr", "mlf", "逆回购", "收储", "保交楼", "住建部", "商务部", "海关总署", "工信部",
    "证监会", "国常会", "政治局", "国家统计局", "财政部", "中国人民银行",
]
GLOBAL_WORDS = [
    "美国", "美联储", "欧洲", "欧元区", "日本", "英国", "全球", "imf", "世界银行",
    "关税", "贸易", "地缘", "战争", "停火", "美债", "美元", "fed", "ecb", "china",
    "euro", "eurozone", "global", "u.s.", "tariff", "trade", "recession", "inflation",
]
ADMIN_WORDS = ["会见", "主持召开", "出席", "调研", "座谈", "大讲堂", "党校", "升旗", "签约", "揭牌", "慰问", "致辞", "开幕式", "发布会"]
LOW_VALUE = ["国库现金定存", "记账式", "贴现国债", "中标利率", "招标", "发行公告", "兑付", "到期", "发行利率", "边际倍数", "发行规模", "公开市场", "签署合作文件", "合作备忘录"]
CORPORATE = [
    "涨停", "跌停", "龙虎榜", "减持", "增持", "中标", "签约", "定增",
    "可转债", "股东大会", "董事长", "总经理", "股份", "集团", "子公司",
    "业绩预告", "净利润", "营收", "个股", "概念股", "游资", "主力资金",
    "券商", "基金", "私募", "公募", "持仓", "调仓", "上市", "IPO", "董秘",
    "实控人", "质押", "商誉", "并购", "重组", "板块", "题材",
    "ETF", "涨超", "涨逾", "港股通", "双11", "成交", "电商", "速卖通", "比特币",
    "期货", "主力", "收盘", "开盘", "高开", "低开", "涨幅", "跌幅",
    "汽车股", "科技股", "银行股", "地产股", "消费股", "中概股", "轮融资",
]
POLITICAL_NOISE = [
    "受贿", "公诉", "检察机关", "纪委", "落马", "双开", "中期选举", "共和党", "民主党",
    "万斯", "特朗普", "拜登", "党组", "党委", "传达学习", "全会精神", "主题教育", "党建", "召开会议",
]
MARKET_WORDS = ["股市", "美股", "港股", "A股", "指数", "涨停", "跌停", "板块", "基金", "券商", "黄金", "原油", "美元"]
MARKETISH = MARKET_WORDS + ["地缘"]
FOREIGN_MINOR = ["澳大利亚", "加拿大", "印尼", "韩国", "印度", "巴西", "俄罗斯", "沙特", "越南", "新西兰"]
CORE_GEO = ["中国", "美国", "美联储", "欧洲", "欧元区", "日本", "英国", "全球", "imf", "世界银行", "关税", "制裁", "战争", "停火", "贸易战"]

IMPACT = [
    "降准", "降息", "加息", "GDP", "CPI", "PPI", "PMI", "社融", "信贷",
    "美联储", "关税", "制裁", "政治局", "国常会", "中央经济工作会议",
    "房地产", "就业", "失业", "汇率", "违约", "债务", "衰退", "通缩",
    "战争", "出口", "消费", "投资", "财政", "货币政策", "十五五",
    "特别国债", "专项债", "LPR", "MLF", "逆回购", "贸易战", "停火",
]

CATEGORY_WORDS: dict[str, list[str]] = {
    "政策": ["央行", "降准", "降息", "财政", "政治局", "国常会", "国务院", "发改委",
             "统计局", "财政部", "证监会", "监管", "政策", "十五五", "专项债",
             "特别国债", "减税", "补贴", "以旧换新", "民营经济", "policy", "stimulus"],
    "地产": ["房地产", "楼市", "房价", "开发商", "保交楼", "土地", "商品房",
             "二手房", "新房", "地产", "房贷", "限购", "property", "housing", "real estate"],
    "物价": ["CPI", "PPI", "通胀", "通缩", "价格", "油价", "铜价", "大宗商品",
             "inflation", "deflation", "prices"],
    "货币": ["M1", "M2", "社融", "信贷", "贷款", "利率", "LPR", "流动性",
             "逆回购", "国债收益率", "汇率", "人民币", "美元", "外汇",
             "fed", "rate", "yield", "bond", "currency", "yuan"],
    "海外": ["美联储", "美国", "欧洲", "日本", "关税", "制裁", "贸易", "地缘",
             "战争", "全球", "IMF", "世界银行", "美债", "停火",
             "u.s.", "europe", "japan", "global", "tariff", "trade", "war"],
    "增长": ["GDP", "PMI", "工业", "制造业", "消费", "零售", "投资", "出口",
             "进口", "就业", "失业", "经济", "增长", "订单", "利润",
             "gdp", "pmi", "growth", "recession", "jobs", "unemployment", "retail", "exports"],
    "市场": ["股市", "A股", "港股", "美股", "债券", "黄金", "原油", "铜",
             "汇率", "期货", "大宗商品", "stocks", "equities", "oil", "copper", "gold"],
}

NEGATIONS = ("不", "未", "无", "没有", "并未", "尚未", "难以", "不会", "不再", "并非")
STRONG_MODS = ("大幅", "显著", "明显", "急剧", "快速", "强劲", "持续", "全面", "猛烈")
WEAK_MODS = ("小幅", "略微", "轻微", "温和", "短暂", "微")
EN_NEGATIONS = re.compile(r"\b(not|no|without|hardly|barely|unlikely|isn't|aren't|won't)\b", re.I)
EN_STRONG = re.compile(r"\b(sharply|significantly|strongly|surges?|soars?|plunges?)\b", re.I)
EN_WEAK = re.compile(r"\b(slightly|marginally|modestly|mildly)\b", re.I)

_PHRASES = sorted(SENTIMENT.keys(), key=len, reverse=True)
_POLICY_PHRASES = sorted(POLICY.keys(), key=len, reverse=True)


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(not (span[1] <= a or span[0] >= b) for a, b in occupied)


def _scan(text: str, phrases: list[str], lexicon: dict[str, float], title: bool) -> tuple[float, list[tuple[str, float]]]:
    if not text:
        return 0.0, []
    raw = 0.0
    hits: list[tuple[str, float]] = []
    occupied: list[tuple[int, int]] = []
    lower = text.lower()
    for phrase in phrases:
        is_en = bool(re.search(r"[a-zA-Z]", phrase))
        hay = lower if is_en else text
        needle = phrase.lower() if is_en else phrase
        for m in re.finditer(re.escape(needle), hay):
            span = m.span()
            if _overlaps(span, occupied):
                continue
            weight = lexicon[phrase]
            before = hay[max(0, span[0] - 36) : span[0]] if is_en else text[max(0, span[0] - 4) : span[0]]
            # 否定
            negated = False
            if is_en:
                negated = bool(EN_NEGATIONS.search(before))
            else:
                negated = any(token in before for token in NEGATIONS)
            if negated:
                weight = -weight * 0.85
            # 程度
            factor = 1.0
            if is_en:
                if EN_STRONG.search(before):
                    factor = 1.4
                elif EN_WEAK.search(before):
                    factor = 0.65
            else:
                if any(token in before for token in STRONG_MODS):
                    factor = 1.4
                elif any(token in before for token in WEAK_MODS):
                    factor = 0.65
            value = weight * factor * (1.7 if title else 1.0)
            raw += value
            hits.append((phrase, value))
            occupied.append(span)
    return raw, hits


def _magnitude(text: str) -> float:
    """把“增长 36.3% / 下降 9.7%”里的数字幅度折成少量加减分。"""
    extra = 0.0
    pattern = re.compile(
        r"(增长|上涨|回升|扩大|下降|下滑|萎缩|收缩|减少|回落)\s*(?:了|约|近)?\s*(\d+(?:\.\d+)?)\s*%"
    )
    for m in pattern.finditer(text):
        value = min(2.5, float(m.group(2)) / 12.0)
        extra += value if m.group(1) in ("增长", "上涨", "回升", "扩大") else -value
    return extra


def _is_relevant(title: str, summary: str, official: bool) -> bool:
    if any(k in title for k in POLITICAL_NOISE):
        return False
    if any(k in title for k in FOREIGN_MINOR) and not any(k in title for k in CORE_GEO):
        return False
    if official:
        return True
    text = title.lower()
    # 先过“中国/全球宏观”这道门，过滤掉个股、单一商品、外企财报等噪音
    if not any(k.lower() in text for k in CHINA_WORDS + GLOBAL_WORDS):
        return False
    strong = [k for k in STRONG_MACRO if k.lower() in text]
    weak = [k for k in WEAK_MACRO if k.lower() in text]
    corporate = [k for k in CORPORATE if k.lower() in (title + " " + summary[:80]).lower()]
    if corporate:
        return False
    if strong:
        # 纯股市/商品/地缘行情，缺少宏观词时丢弃
        if all(k in MARKETISH for k in strong) and not any(
            k in text for k in ("经济", "政策", "数据", "央行", "美联储", "china", "fed", "统计局", "财政")
        ):
            return False
        return True
    if len(weak) >= 2 and not corporate:
        return True
    return False


def _categories(title: str, summary: str) -> list[str]:
    text = title + " " + summary[:120]
    scores: dict[str, int] = {}
    for cat, words in CATEGORY_WORDS.items():
        score = sum(1 for w in words if w.lower() in text.lower())
        if score:
            scores[cat] = score
    if not scores:
        return ["其他"]
    return [k for k, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]]


def _label(score: float) -> str:
    if score > 0.12:
        return "利好"
    if score < -0.12:
        return "利空"
    return "中性"


def analyze_article(item: dict[str, Any]) -> dict[str, Any] | None:
    title = item.get("title", "")
    summary = item.get("summary", "")
    if not _is_relevant(title, summary, bool(item.get("official"))):
        return None
    raw_title, hits_title = _scan(title, _PHRASES, SENTIMENT, True)
    raw_summary, hits_summary = _scan(summary, _PHRASES, SENTIMENT, False)
    raw = raw_title + raw_summary + _magnitude(title + " " + summary[:160])
    sentiment = tanh(raw / 5.0)
    policy_raw, policy_hits = _scan(title + " " + summary, _POLICY_PHRASES, POLICY, True)
    policy = tanh(policy_raw / 3.0)
    hits = sorted(hits_title + hits_summary, key=lambda x: abs(x[1]), reverse=True)
    keywords = []
    for phrase, value in hits[:4]:
        if phrase not in [k for k, _ in keywords]:
            keywords.append((phrase, value))
    impact = sum(1 for w in IMPACT if w.lower() in (title + summary).lower())
    published = item.get("published") or ""
    age_h = 24.0
    try:
        dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        age_h = max(0.0, (datetime.now(CN_TZ) - dt).total_seconds() / 3600.0)
    except Exception:  # noqa: BLE001
        pass
    recency = math.exp(-age_h / 48.0)
    importance = float(item.get("weight", 1.0)) * (1.0 + 0.45 * impact) * (0.35 + 0.65 * recency)
    if item.get("official"):
        importance *= 1.35
    if any(w in title for w in ADMIN_WORDS):
        importance *= 0.5
    if any(w in title for w in LOW_VALUE):
        importance *= 0.35
    if item.get("region") == "overseas":
        importance *= 0.8
    if re.search(r"\d+(?:\.\d+)?\s*%", title) or "同比" in title:
        importance *= 1.15
    cats = _categories(title, summary)
    if cats == ["市场"]:
        importance *= 0.7
    out = dict(item)
    out.update(
        {
            "sentiment": round(sentiment, 3),
            "label": _label(sentiment),
            "policy": round(policy, 3),
            "keywords": [{"word": k, "weight": round(v, 2)} for k, v in keywords],
            "categories": cats,
            "impact": impact,
            "importance": round(importance, 3),
            "age_hours": round(age_h, 1),
        }
    )
    return out


def _pick_diverse(items: list[dict], limit: int, max_per_category: int = 5, max_overseas: int = 2) -> list[dict]:
    out: list[dict] = []
    counts: dict[str, int] = {}
    overseas = 0
    for item in items:
        cats = item.get("categories") or ["其他"]
        cat = cats[0]
        if counts.get(cat, 0) >= max_per_category:
            continue
        if item.get("region") == "overseas":
            if overseas >= max_overseas:
                continue
            overseas += 1
        out.append(item)
        counts[cat] = counts.get(cat, 0) + 1
        if len(out) >= limit:
            break
    if len(out) < limit:
        chosen = {id(x) for x in out}
        for item in items:
            if id(item) not in chosen:
                out.append(item)
            if len(out) >= limit:
                break
    return out


def analyze_news(items: list[dict[str, Any]], max_items: int = 14) -> dict[str, Any]:
    analyzed = [a for a in (analyze_article(x) for x in items) if a is not None]
    analyzed.sort(key=lambda x: x.get("importance", 0), reverse=True)

    # 聚合时限制纯市场新闻数量，避免股市波动主导宏观判断
    market = [x for x in analyzed if (x.get("categories") or [""])[0] == "市场"]
    other = [x for x in analyzed if (x.get("categories") or [""])[0] != "市场"]
    pool = other + market[: max(8, int(len(analyzed) * 0.25))]
    pool = pool[:120]

    total_w = 0.0
    total_s = 0.0
    policy_w = 0.0
    policy_s = 0.0
    for item in pool:
        w = item["importance"] * (1.0 + 0.6 * abs(item["sentiment"]))
        total_w += w
        total_s += item["sentiment"] * w
        if abs(item["policy"]) > 0.12:
            pw = item["importance"] * (2.0 if item.get("official") else 1.0)
            policy_w += pw
            policy_s += item["policy"] * pw

    mean_sent = total_s / total_w if total_w else 0.0
    news_score = 50.0 + 50.0 * tanh(2.2 * mean_sent)
    policy_mean = policy_s / policy_w if policy_w else 0.0
    policy_score = 50.0 + 35.0 * tanh(1.6 * policy_mean)
    if policy_score >= 56:
        policy_label = "偏宽松"
    elif policy_score <= 44:
        policy_label = "偏收紧"
    else:
        policy_label = "中性"

    positive = sorted(
        [x for x in analyzed if x["sentiment"] > 0.12],
        key=lambda x: x["sentiment"] * x["importance"],
        reverse=True,
    )[:8]
    negative = sorted(
        [x for x in analyzed if x["sentiment"] < -0.12],
        key=lambda x: -x["sentiment"] * x["importance"],
        reverse=True,
    )[:8]
    policy_items = sorted(
        [x for x in analyzed if abs(x["policy"]) > 0.2],
        key=lambda x: abs(x["policy"]) * x["importance"],
        reverse=True,
    )[:6]

    top = _pick_diverse(analyzed, max_items)
    counts = {
        "total": len(analyzed),
        "positive": sum(1 for x in analyzed if x["label"] == "利好"),
        "negative": sum(1 for x in analyzed if x["label"] == "利空"),
        "neutral": sum(1 for x in analyzed if x["label"] == "中性"),
        "domestic": sum(1 for x in analyzed if x.get("region") == "domestic"),
        "overseas": sum(1 for x in analyzed if x.get("region") == "overseas"),
        "official": sum(1 for x in analyzed if x.get("official")),
    }
    return {
        "articles": analyzed,
        "pool_size": len(pool),
        "news_score": round(clamp(news_score, 0, 100), 1),
        "news_sentiment": round(mean_sent, 3),
        "policy_score": round(clamp(policy_score, 0, 100), 1),
        "policy_label": policy_label,
        "positive": positive,
        "negative": negative,
        "policy_items": policy_items,
        "top": top,
        "counts": counts,
    }
