"""Stage 2: 固有表現抽出（GiNZA / spaCy）で氏名を拾う。

ルール（Stage 1）は「氏名: 山田 太郎」のようなラベル付きしか拾えない。
文中に現れる氏名（「山田太郎さんから依頼があった」）は文脈を読む必要があり、ここが受け持つ。
誤検知（地名・会社名を人名と取る等）があるので、confidence は不確実帯に置き、
最終判断は Stage 3 か policy に委ねる。

`ja_ginza` が入っていなければこの段階は無効（/healthz に出る）。
"""

from __future__ import annotations

import re
from typing import Any

from llm_guard.detectors.base import Finding, Kind

_HONORIFIC_AFTER = re.compile(
    r"^\s?(さん|様|さま|氏|殿|君|くん|ちゃん|先生|部長|課長|係長|主任|社長)"
)
_LABEL_BEFORE = re.compile(
    r"(氏名|名前|担当|申請者|依頼者|報告者|お客様|契約者|宛|様)\s?[:：]?\s?$"
)
_SPACE = re.compile(r"[ 　]")

# GiNZA の固有表現ラベル（関根の拡張固有表現階層）のうち、人名として扱うもの
PERSON_LABELS = {"Person"}


class NERDetector:
    name = "ner"

    def __init__(self, model: str = "ja_ginza", preload: bool = False) -> None:
        self._model_name = model
        self._nlp: Any | None = None
        self._available: bool | None = None
        if preload:
            self.warmup()

    def available(self) -> bool:
        if self._available is None:
            try:
                import spacy  # noqa: F401
                import spacy.util

                self._available = spacy.util.is_package(self._model_name)
            except ImportError:
                self._available = False
        return self._available

    def loaded(self) -> bool:
        return self._nlp is not None

    def warmup(self) -> None:
        if self._nlp is None and self.available():
            import spacy

            self._nlp = spacy.load(self._model_name, disable=["parser", "lemmatizer"])

    def ready(self) -> bool:
        return self.available()

    def detect(self, text: str) -> list[Finding]:
        if not text.strip():
            return []
        self.warmup()
        if self._nlp is None:
            return []
        doc = self._nlp(text)
        findings: list[Finding] = []
        for ent in doc.ents:
            if ent.label_ not in PERSON_LABELS:
                continue
            start, end = ent.start_char, ent.end_char
            value = text[start:end]
            confidence = self._confidence(text, value, start, end)
            findings.append(
                Finding(
                    kind=Kind.PERSON_NAME,
                    start=start,
                    end=end,
                    text=value,
                    confidence=confidence,
                    stage=self.name,
                    rule=f"ginza:{ent.label_}",
                )
            )
        return findings

    @staticmethod
    def _confidence(text: str, value: str, start: int, end: int) -> float:
        """姓＋名の形（空白区切り、または3文字以上）なら高め。単独の姓（2文字以下）は低め。
        直後の敬称や直前のラベルがあれば確定に近づける。"""
        compact = _SPACE.sub("", value)
        if _SPACE.search(value) or len(compact) >= 3:
            base = 0.80
        else:
            base = 0.50
        if _HONORIFIC_AFTER.match(text[end : end + 4]) or _LABEL_BEFORE.search(
            text[max(0, start - 8) : start]
        ):
            base = min(0.92, base + 0.15)
        return base
