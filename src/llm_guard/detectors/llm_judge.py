"""Stage 3: ローカル LLM（Ollama）による判定。

ルールと固有表現抽出で判断がつかない（confidence が不確実帯の）文だけをここに回す。
柔軟に文脈を読めるが、遅く、出力が安定しないので、
- JSON で返させ、壊れていれば1回だけ再試行
- タイムアウトや再試行後の失敗は「判断不能」として policy.on_judge_error に委ねる
- 位置（span）は返さない。位置が要る判断は Stage 1/2 の検出を昇格させる形で行う
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from llm_guard.policy import JudgeVerdict

KINDS = [
    "my_number",
    "phone",
    "postal_address",
    "email",
    "person_name",
    "credit_card",
    "bank_account",
    "other_sensitive",
]

SYSTEM_PROMPT = """あなたは企業の情報セキュリティ担当です。
与えられた文に、次のいずれかが含まれるかを判定してください。
- 特定の個人を識別できる情報（氏名、電話番号、住所、メールアドレス、個人番号、カード番号、口座番号）
- 社外に出してはいけない機微情報（健康状態、信条、未公開の取引条件や人事情報など）

注意:
- 会社名、支店名、地名、製品コード、注文番号、日付、金額は個人情報ではありません
- 一部が伏せ字（****）になっている番号は、すでに匿名化されているので含まれるとみなしません
- 架空の例や一般論（「氏名を入力してください」）は含まれるとみなしません

必ず次の JSON だけを返してください。説明文は不要です。
{"sensitive": true または false, "kinds": [該当する種類の配列], "reason": "20字以内の理由"}
kinds に使える値: my_number, phone, postal_address, email, person_name,
  credit_card, bank_account, other_sensitive
"""

FEW_SHOT: list[tuple[str, dict[str, Any]]] = [
    (
        "訪問先: 長野支店。所感: 株式会社林物産の担当者が交代予定",
        {"sensitive": False, "kinds": [], "reason": "組織名と地名のみ"},
    ),
    (
        "山田太郎に資料を送る。先方は来週まで出張とのこと",
        {"sensitive": True, "kinds": ["person_name"], "reason": "特定個人の氏名"},
    ),
    (
        "問い合わせ番号 2026-004512 の件、090-****-1234 へ折り返し済み",
        {"sensitive": False, "kinds": [], "reason": "伏せ字済み番号と管理番号"},
    ),
]

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _parse(content: str) -> JudgeVerdict | None:
    m = _JSON_BLOCK.search(content)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sensitive"), bool):
        return None
    kinds = [k for k in data.get("kinds", []) if isinstance(k, str) and k in KINDS]
    reason = str(data.get("reason", ""))[:100]
    return JudgeVerdict(sensitive=data["sensitive"], kinds=kinds, reason=reason)


class OllamaJudge:
    """Ollama の /api/chat を呼ぶ。pipeline からは `judge(text) -> JudgeVerdict` として使う。"""

    name = "llm_judge"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 8.0,
        max_retries: int = 1,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def reachable(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/api/tags", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    def _messages(self, text: str) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for q, a in FEW_SHOT:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": json.dumps(a, ensure_ascii=False)})
        msgs.append({"role": "user", "content": text})
        return msgs

    def __call__(self, text: str) -> JudgeVerdict:
        last_error = "unknown"
        for _attempt in range(self.max_retries + 1):
            try:
                r = self._client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": self._messages(text),
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0},
                    },
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException:
                return JudgeVerdict(error="timeout")  # 待っても改善しないので再試行しない
            except httpx.HTTPError as e:
                return JudgeVerdict(error=f"connection: {type(e).__name__}")
            if r.status_code != 200:
                return JudgeVerdict(error=f"http {r.status_code}")
            try:
                content = r.json().get("message", {}).get("content", "")
            except ValueError:
                content = ""
            verdict = _parse(content)
            if verdict is not None:
                return verdict
            last_error = "invalid_json"
        return JudgeVerdict(error=last_error)
