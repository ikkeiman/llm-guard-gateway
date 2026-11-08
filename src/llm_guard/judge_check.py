"""Stage 3（Ollama 判定）の疎通確認。1文だけ判定して、接続・所要時間・結果を表示する。

使い方: python -m llm_guard.judge_check "山田太郎に資料を送る"
評価が進まないときに、Ollama に届いているか・1件に何秒かかるかを切り分けるためのもの。
"""

from __future__ import annotations

import sys
import time

import httpx

from llm_guard.config import Settings, load_policy
from llm_guard.detectors.llm_judge import OllamaJudge


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "山田太郎に資料を送る"
    settings = Settings.from_env()
    policy = load_policy(settings.policy_path)
    model = settings.ollama_model or policy.llm_judge.model
    timeout = policy.llm_judge.timeout_seconds
    print(f"Ollama: {settings.ollama_base_url}  model: {model}  timeout: {timeout}s")

    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
        names = [m.get("name") for m in r.json().get("models", [])]
        print(f"接続: OK（HTTP {r.status_code}）  モデル一覧: {names}")
        if model not in names:
            print(f"  注意: {model} が一覧にない。`ollama pull {model}` が必要")
    except httpx.HTTPError as e:
        print(f"接続: 失敗（{type(e).__name__}: {e}）")
        print("  Ollama が起動しているか、OLLAMA_BASE_URL が正しいかを確認")
        return 1

    judge = OllamaJudge(settings.ollama_base_url, model, timeout_seconds=timeout, max_retries=0)
    print(f"判定中: {text!r}")
    t0 = time.perf_counter()
    verdict = judge(text)
    elapsed = time.perf_counter() - t0
    print(f"所要時間: {elapsed:.1f} 秒")
    if verdict.error:
        print(f"結果: 判断不能（{verdict.error}）")
        if verdict.error == "timeout":
            print(
                f"  {timeout} 秒で打ち切られた。GPU なしでは初回のモデル読み込みと"
                " few-shot プロンプトの処理に時間がかかる。"
                " config/policy.yaml の llm_judge.timeout_seconds を 60〜120 に上げて再実行"
            )
        return 2
    print(f"結果: sensitive={verdict.sensitive} kinds={verdict.kinds} reason={verdict.reason!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
