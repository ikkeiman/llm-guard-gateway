# 評価結果（合成データでの参考値）

- 実行日: 2026-11-08
- データ: `eval/datasets/synthetic_v1.jsonl`（500 件、seed 42、陽性と陰性が半々）
- 環境: CPython 3.12.16, Windows AMD64。Stage 1/2 は CPU、Stage 3 は Ollama 側の実行環境
- 計測方法: `eval/run_eval.py`。HTTP を介さずパイプラインを直接呼び出し

合成データなので、実データでの精度を示すものではない。見逃し率と止めすぎ率の**トレードオフの形**と、段階を足したときの**変化の方向**を見るためのもの。

## 全体

| 設定 | 見逃し率 ↓ | 止めすぎ率 ↓ | 判定の内訳 | p50 | p95 |
|---|---|---|---|---|---|
| rules のみ | 7.6% | 0.4% | allow 268, block 73, mask 159 | 0.05 ms | 0.13 ms |
| rules + ner | 0.0% | 2.0% | allow 245, block 73, mask 182 | 17.79 ms | 23.82 ms |
| rules + ner + llm(on_uncertain) | 2.8% | 0.0% | allow 257, block 73, mask 170 | 22.34 ms | 511.65 ms |
| rules + ner + llm(always) | 2.8% | 10.0% | allow 232, block 73, mask 170, review 25 | 408.54 ms | 509.17 ms |

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

段階ごとの p50: rules 0.05 ms（500 回）
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

段階ごとの p50: rules 0.08 ms（500 回）, ner 17.64 ms（500 回）
止めすぎの例: neg-0197 → person_name, neg-0043 → person_name, neg-0221 → person_name, neg-0108 → postal_address, neg-0163 → person_name

### rules + ner + llm(on_uncertain)

| 種類 | 件数 | 再現率 | 適合率 |
|---|---|---|---|
| bank_account | 21 | 100.0% | 100.0% |
| credit_card | 28 | 100.0% | 100.0% |
| email | 38 | 100.0% | 100.0% |
| my_number | 45 | 100.0% | 100.0% |
| person_name | 103 | 99.0% | 95.3% |
| phone | 32 | 100.0% | 100.0% |
| postal_address | 67 | 89.6% | 100.0% |

段階ごとの p50: rules 0.08 ms（500 回）, ner 18.11 ms（500 回）, llm_judge 397.55 ms（217 回）
見逃しの例: pos-0002 (address), pos-0139 (address), pos-0129 (address_newline), pos-0198 (address), pos-0107 (address_newline)

### rules + ner + llm(always)

| 種類 | 件数 | 再現率 | 適合率 |
|---|---|---|---|
| bank_account | 21 | 100.0% | 100.0% |
| credit_card | 28 | 100.0% | 100.0% |
| email | 38 | 100.0% | 100.0% |
| my_number | 45 | 100.0% | 100.0% |
| person_name | 103 | 99.0% | 95.3% |
| phone | 32 | 100.0% | 100.0% |
| postal_address | 67 | 89.6% | 100.0% |

段階ごとの p50: rules 0.08 ms（500 回）, ner 16.91 ms（500 回）, llm_judge 390.39 ms（500 回）
見逃しの例: pos-0002 (address), pos-0139 (address), pos-0129 (address_newline), pos-0198 (address), pos-0107 (address_newline)
止めすぎの例: neg-0216 → -, neg-0032 → -, neg-0028 → -, neg-0184 → -, neg-0140 → -

