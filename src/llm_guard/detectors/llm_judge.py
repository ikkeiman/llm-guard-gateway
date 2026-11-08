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
import time
from typing import Any

import httpx

from llm_guard.detectors.base import Finding
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
文と、機械的な検査が見つけた「候補」が与えられます。候補が実在の個人の情報として扱うべきものか、
または文に社外に出してはいけない機微情報（健康状態、信条、未公開の取引条件や人事情報など）があるかを判定してください。

個人情報として扱うもの（氏名が一緒に無くても該当します）:
- 個人の氏名（フルネーム、または文脈から特定の人と分かる姓）
- 電話番号、メールアドレス、住所（都道府県から番地まで）、口座番号、個人番号、カード番号

該当しないもの:
- 会社名、支店名、部署名、地名だけの言及（「長野支店」「東京都内」）
- 製品コード、注文番号、伝票番号、内線番号、日付、金額、バージョン番号
- 一部が伏せ字（****）になっている番号（すでに匿名化済み）
- 架空の例や一般論（「氏名を入力してください」）

必ず次の JSON だけを返してください。説明文は不要です。
{"sensitive": true または false, "kinds": [該当する種類の配列], "reason": "20字以内の理由"}
kinds に使える値: my_number, phone, postal_address, email, person_name,
  credit_card, bank_account, other_sensitive
"""

FEW_SHOT: list[tuple[str, dict[str, Any]]] = [
    (
        "文:\n訪問先: 長野支店。所感: 株式会社林物産の担当者が交代予定\n\n"
        "候補:\n- person_name: 長野支店",
        {"sensitive": False, "kinds": [], "reason": "組織名と地名のみ"},
    ),
    (
        "文:\n山田太郎に資料を送る。先方は来週まで出張とのこと\n\n候補:\n- person_name: 山田太郎",
        {"sensitive": True, "kinds": ["person_name"], "reason": "特定個人の氏名"},
    ),
    (
        "文:\n申請内容: 大阪府大阪市北区梅田1-2-3 へ送付\n\n"
        "候補:\n- postal_address: 大阪府大阪市北区梅田1-2-3",
        {"sensitive": True, "kinds": ["postal_address"], "reason": "番地までの住所"},
    ),
    (
        "文:\n問い合わせ番号 2026-004512 の件、090-****-1234 へ折り返し済み\n\n候補:\n- なし",
        {"sensitive": False, "kinds": [], "reason": "伏せ字済み番号と管理番号"},
    ),
]


def build_user_message(text: str, candidates: list[Finding]) -> str:
    """文と候補を1つのメッセージにする。候補は種類と該当箇所だけで、confidence は見せない。"""
    if candidates:
        lines = [f"- {c.kind.value}: {c.text}" for c in candidates]
    else:
        lines = ["- なし"]
    return "文:\n" + text + "\n\n候補:\n" + "\n".join(lines)


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
        self._reachable_cache: bool | None = None
        self._reachable_checked_at = 0.0
        self.last_meta: dict[str, Any] = {}  # 直近の応答の計測値（所要時間・トークン数）。診断用

    def reachable(self) -> bool:
        """Ollama に届くか。30 秒キャッシュする。

        届かないときは Stage 3 を「不在」として飛ばす（policy.uncertain_without_judge に従う）。
        届いたのに応答が壊れた・遅いときだけ「判断不能」（policy.on_judge_error）になる。
        不在と失敗を区別するのは、Ollama を立てていない環境でも既定の mask で動くようにするため。
        """
        now = time.monotonic()
        if self._reachable_cache is not None and now - self._reachable_checked_at < 30:
            return self._reachable_cache
        try:
            ok = self._client.get(f"{self.base_url}/api/tags", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            ok = False
        self._reachable_cache, self._reachable_checked_at = ok, now
        return ok

    def _messages(self, text: str, candidates: list[Finding]) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for q, a in FEW_SHOT:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": json.dumps(a, ensure_ascii=False)})
        msgs.append({"role": "user", "content": build_user_message(text, candidates)})
        return msgs

    def __call__(self, text: str, candidates: list[Finding] | None = None) -> JudgeVerdict:
        candidates = candidates or []
        last_error = "unknown"
        for _attempt in range(self.max_retries + 1):
            try:
                r = self._client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": self._messages(text, candidates),
                        "stream": False,
                        "format": "json",
                        # num_predict: JSON モードで停止せず空白を出し続ける挙動への保険。
                        # 返す JSON は 100 トークン未満で足りる
                        "options": {"temperature": 0, "num_predict": 160},
                        "keep_alive": "10m",
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
                data = r.json()
                content = data.get("message", {}).get("content", "")
                self.last_meta = {
                    k: data.get(k)
                    for k in (
                        "total_duration",
                        "load_duration",
                        "prompt_eval_count",
                        "prompt_eval_duration",
                        "eval_count",
                        "eval_duration",
                        "done_reason",
                    )
                }
                self.last_meta["content"] = content
            except ValueError:
                content = ""
            verdict = _parse(content)
            if verdict is not None:
                return verdict
            last_error = "invalid_json"
        return JudgeVerdict(error=last_error)
