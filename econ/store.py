"""SQLite 持久化：保存每天的结论，便于看长期变化。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .util import now_cn


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    report_date TEXT NOT NULL,
    composite REAL,
    growth REAL,
    prices REAL,
    money REAL,
    housing REAL,
    external REAL,
    news_score REAL,
    policy_score REAL,
    regime TEXT,
    verdict TEXT,
    payload TEXT
);
CREATE TABLE IF NOT EXISTS indicators (
    run_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL,
    score REAL,
    status TEXT,
    period TEXT,
    PRIMARY KEY (run_id, key)
);
CREATE TABLE IF NOT EXISTS news (
    run_id TEXT NOT NULL,
    ts REAL,
    title TEXT,
    url TEXT,
    source TEXT,
    region TEXT,
    score REAL,
    label TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    run_id TEXT NOT NULL,
    name TEXT,
    region TEXT,
    ok INTEGER,
    count INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(report_date);
CREATE INDEX IF NOT EXISTS idx_news_run ON news(run_id);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def previous_run(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def save_run(
        self,
        *,
        run_id: str,
        report_date: str,
        composite: float | None,
        pillars: dict[str, float | None],
        news_score: float | None,
        policy_score: float | None,
        regime: str,
        verdict: str,
        payload: dict[str, Any],
        indicators: list[dict[str, Any]],
        news_items: list[dict[str, Any]],
        source_statuses: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO runs
            (run_id, created_at, report_date, composite, growth, prices, money, housing, external,
             news_score, policy_score, regime, verdict, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                now_cn().isoformat(),
                report_date,
                composite,
                pillars.get("growth"),
                pillars.get("prices"),
                pillars.get("money"),
                pillars.get("housing"),
                pillars.get("external"),
                news_score,
                policy_score,
                regime,
                verdict,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        for ind in indicators:
            self.conn.execute(
                "INSERT OR REPLACE INTO indicators (run_id, key, value, score, status, period) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    ind.get("key"),
                    ind.get("value"),
                    ind.get("score"),
                    ind.get("status"),
                    ind.get("period"),
                ),
            )
        for item in news_items:
            self.conn.execute(
                "INSERT INTO news (run_id, ts, title, url, source, region, score, label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    item.get("ts"),
                    item.get("title"),
                    item.get("url"),
                    item.get("source"),
                    item.get("region"),
                    item.get("sentiment"),
                    item.get("label"),
                ),
            )
        for src in source_statuses:
            self.conn.execute(
                "INSERT INTO sources (run_id, name, region, ok, count, error) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    src.get("name"),
                    src.get("region"),
                    1 if src.get("ok") else 0,
                    src.get("count", 0),
                    src.get("error", ""),
                ),
            )
        self.conn.commit()

    def recent_composites(self, limit: int = 120) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT report_date, composite, growth, prices, money, housing, external FROM runs ORDER BY report_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows][::-1]
