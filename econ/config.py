"""配置加载。"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "app": {
        "title": "每日经济观察",
        "timezone": "Asia/Shanghai",
        "report_dir": "reports",
        "data_dir": "data",
        "log_dir": "logs",
        "history_months": 36,
    },
    "network": {
        "timeout": 18,
        "retries": 2,
        "proxy": "",
        "proxy_for": "overseas",
        "overseas_probe_timeout": 8,
    },
    "news": {
        "window_hours": 48,
        "official_window_days": 7,
        "max_articles": 500,
        "max_report_items": 14,
        "domestic": [],
        "overseas": [],
    },
    "pillars": {},
    "scoring": {
        "z_window_months": 60,
        "z_min_periods": 30,
        "z_scale": 16,
        "z_clip": 2.5,
        "stale_days": {"M": 75, "Q": 150, "D": 15},
        "drop_days": {"M": 120, "Q": 240, "D": 30},
    },
    "thresholds": {
        "temperature": {"cold": 40, "cool": 47.5, "warm": 52.5, "hot": 60},
        "news": {"negative": 45, "positive": 55},
    },
    "report": {"max_news": 14, "top_movers": 4, "open_after_run": False},
    "llm": {
        "enabled": "auto",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "ECON_LLM_API_KEY",
        "api_key": "",
        "timeout": 60,
        "max_tokens": 1200,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    cfg_path = Path(path).resolve()
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg = _deep_merge(DEFAULTS, raw)
    root = cfg_path.parent
    cfg["_root"] = str(root)
    cfg["_config_path"] = str(cfg_path)
    app = cfg["app"]
    app["report_dir"] = str((root / app["report_dir"]).resolve())
    app["data_dir"] = str((root / app["data_dir"]).resolve())
    app["log_dir"] = str((root / app["log_dir"]).resolve())
    return cfg
