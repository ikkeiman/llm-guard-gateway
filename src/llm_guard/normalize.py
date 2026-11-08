"""検査用の文字正規化。

全角数字・全角英字・全角記号を半角に寄せるが、1文字→1文字の置換だけを行い、
文字列の長さと各文字の位置を変えない。検出したスパンの位置をそのまま原文に適用するため。
"""

from __future__ import annotations

_FULLWIDTH_DIGITS = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH_UPPER = {ord("Ａ") + i: ord("A") + i for i in range(26)}
_FULLWIDTH_LOWER = {ord("ａ") + i: ord("a") + i for i in range(26)}
_SYMBOLS = {
    ord("－"): ord("-"),  # 全角ハイフンマイナス
    ord("‐"): ord("-"),  # ハイフン
    ord("‑"): ord("-"),  # ノンブレーキングハイフン
    ord("‒"): ord("-"),  # フィギュアダッシュ
    ord("–"): ord("-"),  # エンダッシュ
    ord("—"): ord("-"),  # エムダッシュ
    ord("―"): ord("-"),  # ホリゾンタルバー
    ord("−"): ord("-"),  # マイナス記号
    ord("＠"): ord("@"),
    ord("．"): ord("."),
    ord("，"): ord(","),
    ord("："): ord(":"),
    ord("（"): ord("("),
    ord("）"): ord(")"),
    ord("　"): ord(" "),  # 全角スペース
}
# 注意: 長音「ー」(U+30FC) は日本語の一部なので変換しない

_TABLE = {**_FULLWIDTH_DIGITS, **_FULLWIDTH_UPPER, **_FULLWIDTH_LOWER, **_SYMBOLS}


def normalize_for_matching(text: str) -> str:
    """位置を保ったまま、検査に使う表記へ寄せる。len(result) == len(text) を保証する。"""
    return text.translate(_TABLE)
