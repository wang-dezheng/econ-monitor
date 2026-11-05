"""数据源连通性自检：python run.py --check"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .collect import macro, market, news
from .util import CN_TZ, now_cn


def _line(name: str, status: str, detail: str, width: int = 24) -> str:
    return f"{name:<{width}} {status:<8} {detail}"


def check(cfg: dict[str, Any], *, proxy_override: str | None = None) -> int:
    data_dir = Path(cfg["app"]["data_dir"])
    cache_dir = data_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    net = cfg.get("network", {})
    timeout = int(net.get("timeout", 18))
    proxy = proxy_override if proxy_override is not None else str(net.get("proxy", "") or "")
    domestic_proxy = proxy if proxy and str(net.get("proxy_for", "overseas")) == "all" else None

    print("\n=== 宏观数据 ===")
    macro_data = macro.collect_macro(cache_dir, offline=False)
    ok = 0
    for key, res in macro_data.get("indicators", {}).items():
        latest = res.get("latest")
        status = "缓存" if res.get("cached") else "OK" if res.get("ok") else "FAIL"
        detail = latest.strftime("%Y-%m-%d") if latest is not None else (res.get("error") or "")[:60]
        if res.get("ok"):
            ok += 1
        print(_line(key, status, detail))
    print(f"小计：{ok}/{len(macro_data.get('indicators', {}))} 可用")

    session = requests.Session()
    if domestic_proxy:
        session.proxies.update({"http": domestic_proxy, "https": domestic_proxy})

    print("\n=== 地产 / 行情 ===")
    housing = macro.collect_housing(cache_dir, session, timeout=timeout)
    hb = housing.get("series", {}).get("home_breadth")
    if hb is not None and not hb.empty:
        print(_line("70 城房价", "OK", f"最新 {hb.index.max():%Y-%m}，{housing.get('latest_cities', 0)} 城"))
    else:
        print(_line("70 城房价", "FAIL", (housing.get("error") or "")[:70]))
    market_data = market.collect_market(cache_dir, session)
    for item in market_data.get("snapshot", []):
        print(_line(item["name"], "OK", f"{item['price']:,.{item['decimals']}f}（{item['date']}）"))
    for key, err in market_data.get("errors", {}).items():
        print(_line(key, "FAIL", err[:70]))

    print("\n=== 新闻源 ===")
    news_data = news.collect_news(cfg, cache_dir, offline=False, proxy_override=proxy_override)
    domestic_ok = 0
    overseas_ok = 0
    for status in news_data.get("statuses", []):
        flag = "OK" if status.get("ok") else "FAIL"
        region = "境内" if status.get("region") == "domestic" else "境外"
        detail = f"{status.get('count', 0)} 条" if status.get("ok") else (status.get("error") or "")[:60]
        print(_line(f"[{region}] {status.get('name')}", flag, detail, width=30))
        if status.get("ok"):
            if status.get("region") == "domestic":
                domestic_ok += 1
            else:
                overseas_ok += 1
    print(f"\n新闻源：境内 {domestic_ok} 个可用；境外 {overseas_ok} 个可用。")
    if overseas_ok == 0:
        print("提示：境外新闻源当前不可达。开 VPN 后在 config.yaml 填 proxy，或部署到境外/香港服务器。")
    print(f"检查时间：{now_cn():%Y-%m-%d %H:%M:%S}（{CN_TZ}）")
    return 0
