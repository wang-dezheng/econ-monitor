"""每日经济观察 · 入口。

用法：
  python run.py                 # 采集 + 生成今日报告
  python run.py --open          # 生成后自动打开浏览器
  python run.py --check         # 只检查数据源连通性
  python run.py --offline       # 完全离线，用本地缓存
  python run.py --no-overseas   # 跳过境外新闻源
  python run.py --proxy http://127.0.0.1:7890
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("TQDM_MININTERVAL", "9999")

warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from econ.check import check  # noqa: E402
from econ.config import load_config  # noqa: E402
from econ.pipeline import run  # noqa: E402
from econ.util import setup_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="每日经济观察：经济走势自动判断")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--open", action="store_true", help="生成后自动打开 HTML 报告")
    parser.add_argument("--offline", action="store_true", help="完全离线，使用本地缓存")
    parser.add_argument("--no-overseas", action="store_true", help="跳过境外新闻源")
    parser.add_argument("--no-llm", action="store_true", help="不使用大模型解读")
    parser.add_argument("--proxy", default=None, help="临时覆盖代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--check", action="store_true", help="只检查数据源连通性")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"读取配置失败：{exc}")
        return 2

    logger = setup_logging(Path(cfg["app"]["log_dir"]), args.verbose)

    try:
        if args.check:
            return check(cfg, proxy_override=args.proxy)
        result = run(
            args.config,
            offline=args.offline,
            no_overseas=args.no_overseas,
            no_llm=args.no_llm,
            open_after=args.open,
            proxy_override=args.proxy,
        )
        print("\n" + "=" * 56)
        print(f"经济温度：{result['composite']} · {result['temperature']} · {result['regime']}")
        print(f"新闻情绪：{result['news_score']}")
        print(f"判断：{result['report']['narrative'].get('verdict', '')}")
        print(f"看板：{result['html']}")
        print(f"日报：{result['markdown']}")
        print("=" * 56)
        return 0
    except KeyboardInterrupt:
        logger.warning("已中断")
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("运行失败：%s", exc)
        print(f"\n运行失败：{type(exc).__name__}: {exc}")
        print("可先运行 python run.py --check 检查数据源；或加 --offline 使用缓存。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
