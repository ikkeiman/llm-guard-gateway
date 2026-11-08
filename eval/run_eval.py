"""評価ハーネス。

合成データに対して、設定の組み合わせごとに
見逃し率・止めすぎ率・種類別の再現率と適合率・応答時間 を測る。

- 見逃し率   = 陽性（個人情報あり）のうち decision が allow になった割合
- 止めすぎ率 = 陰性（個人情報なし）のうち decision が allow 以外になった割合
- 種類別の再現率/適合率は文書単位（その種類が文書に「ある」と判定したか）

既定では HTTP を介さずパイプラインを直接呼ぶ
（計測したいのは判定の時間であって HTTP の時間ではないため）。
Stage 3 を含む設定は Ollama に接続できるときだけ実行し、できなければ「未実測」と出力する。

使い方: python eval/run_eval.py --configs rules_only,rules_ner --output eval/results/latest.md
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_guard.config import Policy, Settings, load_policy  # noqa: E402
from llm_guard.factory import build_guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# 設定の組み合わせ。base は config/policy.yaml で、段階の ON/OFF だけ上書きする
CONFIGS: dict[str, dict] = {
    "rules_only": {"stages": {"rules": True, "ner": False, "llm_judge": "off"}},
    "rules_ner": {"stages": {"rules": True, "ner": True, "llm_judge": "off"}},
    "rules_ner_judge": {"stages": {"rules": True, "ner": True, "llm_judge": "on_uncertain"}},
    "judge_always": {"stages": {"rules": True, "ner": True, "llm_judge": "always"}},
}
LABELS = {
    "rules_only": "rules のみ",
    "rules_ner": "rules + ner",
    "rules_ner_judge": "rules + ner + llm(on_uncertain)",
    "judge_always": "rules + ner + llm(always)",
}


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def ollama_reachable(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/tags", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


def evaluate(name: str, policy: Policy, settings: Settings, records: list[dict]) -> dict:
    guard = build_guard(policy, settings)
    missing = [d.name for d in guard.detectors if not d.ready()]
    pos = [r for r in records if r["has_pii"]]
    neg = [r for r in records if not r["has_pii"]]

    misses = 0
    overblocks = 0
    decisions = Counter()
    tp, fn, fp = Counter(), Counter(), Counter()
    total_ms: list[float] = []
    stage_ms: dict[str, list[float]] = defaultdict(list)
    miss_examples: list[str] = []
    overblock_examples: list[str] = []

    for r in records:
        res = guard.inspect(r["text"])
        decisions[res.decision] += 1
        total_ms.append(res.total_ms)
        for s, ms in res.timings_ms.items():
            stage_ms[s].append(ms)
        detected = {f.kind.value for f in res.acted_findings}
        truth = set(r["kinds"])
        if r["has_pii"] and res.decision == "allow":
            misses += 1
            if len(miss_examples) < 5:
                miss_examples.append(f"{r['id']} ({r['note']})")
        if not r["has_pii"] and res.decision != "allow":
            overblocks += 1
            if len(overblock_examples) < 5:
                kinds = ",".join(sorted(detected)) or "-"
                overblock_examples.append(f"{r['id']} → {kinds}")
        for k in truth:
            if k in detected:
                tp[k] += 1
            else:
                fn[k] += 1
        for k in detected - truth:
            fp[k] += 1

    per_kind = {}
    for k in sorted(set(tp) | set(fn) | set(fp)):
        recall = tp[k] / (tp[k] + fn[k]) if (tp[k] + fn[k]) else None
        precision = tp[k] / (tp[k] + fp[k]) if (tp[k] + fp[k]) else None
        per_kind[k] = {"recall": recall, "precision": precision, "support": tp[k] + fn[k]}

    return {
        "name": name,
        "missing_stages": missing,
        "n_pos": len(pos),
        "n_neg": len(neg),
        "miss_rate": misses / len(pos) if pos else 0.0,
        "overblock_rate": overblocks / len(neg) if neg else 0.0,
        "decisions": dict(decisions),
        "per_kind": per_kind,
        "p50_ms": percentile(total_ms, 0.5),
        "p95_ms": percentile(total_ms, 0.95),
        "mean_ms": statistics.fmean(total_ms) if total_ms else 0.0,
        "stage_p50_ms": {s: percentile(v, 0.5) for s, v in stage_ms.items()},
        "stage_calls": {s: len(v) for s, v in stage_ms.items()},
        "miss_examples": miss_examples,
        "overblock_examples": overblock_examples,
    }


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def render(
    results: list[dict], skipped: dict[str, str], dataset: Path, n: int, seed_note: str
) -> str:
    today = date.today().isoformat()
    lines = [
        "# 評価結果（合成データでの参考値）",
        "",
        f"- 実行日: {today}",
        f"- データ: `{dataset.relative_to(ROOT).as_posix()}`（{n} 件、{seed_note}）",
        f"- 環境: {platform.python_implementation()} {platform.python_version()}, "
        f"{platform.system()} {platform.machine()}。"
        "Stage 1/2 は CPU、Stage 3 は Ollama 側の実行環境",
        "- 計測方法: `eval/run_eval.py`。HTTP を介さずパイプラインを直接呼び出し",
        "",
        "合成データなので、実データでの精度を示すものではない。"
        "見逃し率と止めすぎ率の**トレードオフの形**と、段階を足したときの**変化の方向**を見るためのもの。",
        "",
        "## 全体",
        "",
        "| 設定 | 見逃し率 ↓ | 止めすぎ率 ↓ | 判定の内訳 | p50 | p95 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        dec = ", ".join(f"{k} {v}" for k, v in sorted(r["decisions"].items()))
        label = LABELS[r["name"]]
        if r["missing_stages"]:
            label += f"（{', '.join(r['missing_stages'])} 未ロード）"
        lines.append(
            f"| {label} | {pct(r['miss_rate'])} | {pct(r['overblock_rate'])} | {dec} "
            f"| {r['p50_ms']:.2f} ms | {r['p95_ms']:.2f} ms |"
        )
    for name, why in skipped.items():
        lines.append(f"| {LABELS[name]} | 未実測 | 未実測 | {why} | - | - |")
    lines += ["", "## 種類別（文書単位）", ""]
    for r in results:
        lines += [
            f"### {LABELS[r['name']]}",
            "",
            "| 種類 | 件数 | 再現率 | 適合率 |",
            "|---|---|---|---|",
        ]
        for k, v in r["per_kind"].items():
            lines.append(f"| {k} | {v['support']} | {pct(v['recall'])} | {pct(v['precision'])} |")
        lines.append("")
        lines.append(
            "段階ごとの p50: "
            + ", ".join(
                f"{s} {ms:.2f} ms（{r['stage_calls'][s]} 回）"
                for s, ms in r["stage_p50_ms"].items()
            )
        )
        if r["miss_examples"]:
            lines.append(f"見逃しの例: {', '.join(r['miss_examples'])}")
        if r["overblock_examples"]:
            lines.append(f"止めすぎの例: {', '.join(r['overblock_examples'])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "eval/datasets/synthetic_v1.jsonl"))
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--output", default=str(ROOT / "eval/results/latest.md"))
    ap.add_argument("--policy", default=str(ROOT / "config/policy.yaml"))
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 件だけ（動作確認用）")
    args = ap.parse_args()

    settings = Settings.from_env()
    settings.policy_path = Path(args.policy)
    settings.rules_path = ROOT / "config/rules.yaml"
    base = load_policy(args.policy)
    dataset = Path(args.dataset)
    records = [json.loads(line) for line in dataset.open(encoding="utf-8")]
    if args.limit:
        records = records[: args.limit]

    judge_ok = None
    results, skipped = [], {}
    for name in args.configs.split(","):
        name = name.strip()
        overrides = CONFIGS[name]
        policy = base.model_copy(
            update={"stages": base.stages.model_copy(update=overrides["stages"])}
        )
        if policy.stages.llm_judge != "off":
            if judge_ok is None:
                judge_ok = ollama_reachable(settings.ollama_base_url)
            if not judge_ok:
                skipped[name] = f"Ollama（{settings.ollama_base_url}）に接続できず"
                continue
        t0 = time.perf_counter()
        res = evaluate(name, policy, settings, records)
        print(
            f"{name:16s} miss={pct(res['miss_rate'])} overblock={pct(res['overblock_rate'])} "
            f"p50={res['p50_ms']:.1f}ms p95={res['p95_ms']:.1f}ms ({time.perf_counter() - t0:.1f}s)"
        )
        results.append(res)
    for name, why in skipped.items():
        print(f"{name:16s} 未実測: {why}")

    md = render(results, skipped, dataset, len(records), "seed 42、陽性と陰性が半々")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
