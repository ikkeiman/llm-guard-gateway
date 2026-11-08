"""保留キュー（review モード）。

判定が review になったリクエストを SQLite に置き、人が承認したら転送、却下したら破棄する。
原文（リクエスト本体）は保留中だけ保持し、解決した時点で消す。残すのは状態と要約だけ。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_queue (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,              -- pending | approved | rejected
  request_json TEXT,                 -- 原文。解決時に NULL にする
  masked_request_json TEXT,          -- マスク済み。解決時に NULL にする
  summary_json TEXT NOT NULL,        -- 決定理由と検出の種類（原文なし）
  resolved_ts TEXT,
  resolution TEXT                    -- approve:masked | approve:original | reject
);
"""


class ReviewQueue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def enqueue(self, request: dict, masked_request: dict | None, summary: dict) -> str:
        rid = uuid.uuid4().hex
        with self._conn() as c:
            c.execute(
                "INSERT INTO review_queue (id, ts, status, request_json, masked_request_json, "
                "summary_json) VALUES (?,?,?,?,?,?)",
                (
                    rid,
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    "pending",
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(masked_request, ensure_ascii=False) if masked_request else None,
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
        return rid

    def list_pending(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, ts, status, summary_json, "
                "masked_request_json IS NOT NULL AS has_masked "
                "FROM review_queue WHERE status = 'pending' ORDER BY ts"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "status": r["status"],
                "has_masked": bool(r["has_masked"]),
                "summary": json.loads(r["summary_json"]),
            }
            for r in rows
        ]

    def get(self, rid: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM review_queue WHERE id = ?", (rid,)).fetchone()
        if r is None:
            return None
        return {
            "id": r["id"],
            "ts": r["ts"],
            "status": r["status"],
            "request": json.loads(r["request_json"]) if r["request_json"] else None,
            "masked_request": (
                json.loads(r["masked_request_json"]) if r["masked_request_json"] else None
            ),
            "summary": json.loads(r["summary_json"]),
            "resolved_ts": r["resolved_ts"],
            "resolution": r["resolution"],
        }

    def resolve(self, rid: str, resolution: str) -> None:
        status = "rejected" if resolution == "reject" else "approved"
        with self._conn() as c:
            c.execute(
                "UPDATE review_queue SET status = ?, resolved_ts = ?, resolution = ?, "
                "request_json = NULL, masked_request_json = NULL WHERE id = ?",
                (status, datetime.now(UTC).isoformat(timespec="milliseconds"), resolution, rid),
            )
