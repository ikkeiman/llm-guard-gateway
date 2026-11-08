"""検出箇所をプレースホルダに置き換える。

同じ値には同じ番号を振る（<PERSON_NAME_1> が2回出てくれば同一人物）ので、
外部 LLM は「誰が」を区別したまま文脈を扱える。逆変換は既定オフ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_guard.detectors.base import Finding, Kind

PLACEHOLDER_NAMES: dict[Kind, str] = {
    Kind.MY_NUMBER: "MY_NUMBER",
    Kind.PHONE: "PHONE",
    Kind.POSTAL_ADDRESS: "ADDRESS",
    Kind.EMAIL: "EMAIL",
    Kind.PERSON_NAME: "PERSON_NAME",
    Kind.CREDIT_CARD: "CREDIT_CARD",
    Kind.BANK_ACCOUNT: "BANK_ACCOUNT",
    Kind.OTHER_SENSITIVE: "SENSITIVE",
}


@dataclass
class MaskMap:
    """1リクエスト内で共有する、プレースホルダ ↔ 元の値 の対応。

    複数メッセージをまたいで同じ番号を使う。
    """

    _by_value: dict[tuple[Kind, str], str] = field(default_factory=dict)
    _by_placeholder: dict[str, str] = field(default_factory=dict)
    _counters: dict[Kind, int] = field(default_factory=dict)

    def placeholder_for(self, kind: Kind, value: str) -> str:
        key = (kind, value)
        if key not in self._by_value:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            ph = f"<{PLACEHOLDER_NAMES[kind]}_{self._counters[kind]}>"
            self._by_value[key] = ph
            self._by_placeholder[ph] = value
        return self._by_value[key]

    def restore(self, text: str) -> str:
        for ph, value in self._by_placeholder.items():
            text = text.replace(ph, value)
        return text

    def __len__(self) -> int:
        return len(self._by_placeholder)


def merge_spans(findings: list[Finding]) -> list[Finding]:
    """重なるスパンを1つにまとめる。残す kind は confidence が高い方（同点なら長い方）。"""
    ordered = sorted(findings, key=lambda f: (f.start, -(f.end - f.start)))
    merged: list[Finding] = []
    for f in ordered:
        if merged and f.start < merged[-1].end:
            last = merged[-1]
            winner = max((last, f), key=lambda x: (x.confidence, x.end - x.start))
            merged[-1] = winner.model_copy(
                update={"start": min(last.start, f.start), "end": max(last.end, f.end)}
            )
        else:
            merged.append(f)
    return merged


def mask_text(text: str, findings: list[Finding], mask_map: MaskMap | None = None) -> str:
    mask_map = mask_map if mask_map is not None else MaskMap()
    out: list[str] = []
    cursor = 0
    for f in merge_spans(findings):
        out.append(text[cursor : f.start])
        out.append(mask_map.placeholder_for(f.kind, text[f.start : f.end]))
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)
