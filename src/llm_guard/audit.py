"""監査ログ（SQLite）。1リクエスト1行。

原文は保存しない。保存するのは 決定・走った段階・検出の種類と位置と confidence・所要時間 だけ。
ログ自体が個人情報の保管場所になるのを避けるため。
あとから「どの種類の検出が多いか」「Stage 3 がどれだけ呼ばれたか」を集計し、
評価データに足すべきケースの当たりを付ける用途を想定している。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  decision TEXT NOT NULL,
  stages TEXT NOT NULL,
  findings_json TEXT NOT NULL,
  timings_json TEXT NOT NULL,
  total_ms REAL NOT NULL,
  judge_used INTEGER NOT NULL DEFAULT 0,
  judge_error TEXT,
  n_messages INTEGER NOT NULL DEFAULT 1,
  review_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (ts);
"""


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def record(
        self,
        *,
        endpoint: str,
        decision: str,
        stages: list[str],
        findings: list[dict],
        timings_ms: dict[str, float],
        total_ms: float,
        judge_used: bool = False,
        judge_error: str | None = None,
        n_messages: int = 1,
        review_id: str | None = None,
    ) -> str:
        for f in findings:
            assert "text" not in f, "監査ログに原文を入れてはいけない"
        rid = uuid.uuid4().hex
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    endpoint,
                    decision,
                    ",".join(stages),
                    json.dumps(findings, ensure_ascii=False),
                    json.dumps(timings_ms),
                    total_ms,
                    int(judge_used),
                    judge_error,
                    n_messages,
                    review_id,
                ),
            )
        return rid

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["findings"] = json.loads(d.pop("findings_json"))
            d["timings_ms"] = json.loads(d.pop("timings_json"))
            d["stages"] = d["stages"].split(",") if d["stages"] else []
            out.append(d)
        return out

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
