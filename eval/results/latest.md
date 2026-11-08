# 評価結果（合成データでの参考値）

- 実行日: 2026-11-08
- データ: `eval/datasets/synthetic_v1.jsonl`（500 件、seed 42、陽性と陰性が半々）
- 環境: CPython 3.12.3, x86_64, CPU のみ
- 計測方法: `eval/run_eval.py`。HTTP を介さずパイプラインを直接呼び出し

合成データなので、実データでの精度を示すものではない。見逃し率と止めすぎ率の**トレードオフの形**と、段階を足したときの**変化の方向**を見るためのもの。

## 全体

| 設定 | 見逃し率 ↓ | 止めすぎ率 ↓ | 判定の内訳 | p50 | p95 |
|---|---|---|---|---|---|
| rules のみ | 7.6% | 0.4% | allow 268, block 73, mask 159 | 0.03 ms | 0.05 ms |
| rules + ner | 0.0% | 2.0% | allow 245, block 73, mask 182 | 12.87 ms | 17.47 ms |
| rules + ner + llm(on_uncertain) | 未実測 | 未実測 | Ollama（http://localhost:11434）に接続できず | - | - |
| rules + ner + llm(always) | 未実測 | 未実測 | Ollama（http://localhost:11434）に接続できず | - | - |

## 種類別（文書単位）

### rules のみ

| 種類 | 件数 | 再現率 | 適合率 |
|---|---|---|---|
| bank_account | 21 | 100.0% | 100.0% |
| credit_card | 28 | 100.0% | 100.0% |
| email | 38 | 100.0% | 100.0% |
| my_number | 45 | 100.0% | 100.0% |
| person_name | 103 | 0.0% | - |
| phone | 32 | 100.0% | 100.0% |
| postal_address | 67 | 100.0% | 98.5% |

段階ごとの p50: rules 0.02 ms（500 回）
見逃しの例: pos-0000 (name), pos-0085 (name), pos-0215 (name), pos-0064 (name), pos-0090 (name)
止めすぎの例: neg-0108 → postal_address

### rules + ner

| 種類 | 件数 | 再現率 | 適合率 |
|---|---|---|---|
| bank_account | 21 | 100.0% | 100.0% |
| credit_card | 28 | 100.0% | 100.0% |
| email | 38 | 100.0% | 100.0% |
| my_number | 45 | 100.0% | 100.0% |
| person_name | 103 | 99.0% | 86.4% |
| phone | 32 | 100.0% | 100.0% |
| postal_address | 67 | 100.0% | 98.5% |

段階ごとの p50: rules 0.06 ms（500 回）, ner 12.77 ms（500 回）
止めすぎの例: neg-0197 → person_name, neg-0043 → person_name, neg-0221 → person_name, neg-0108 → postal_address, neg-0163 → person_name

