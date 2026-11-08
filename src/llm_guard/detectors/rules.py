"""Stage 1: 正規表現と検証関数によるルール検査。

速くて確実だが、形式が決まっているものしか拾えない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llm_guard.config import Rule, RuleSet
from llm_guard.detectors.base import Finding, Kind
from llm_guard.normalize import normalize_for_matching
from llm_guard.validators import VALIDATORS


@dataclass
class _Compiled:
    rule: Rule
    regex: re.Pattern[str]
    keywords: re.Pattern[str] | None


class RulesDetector:
    name = "rules"

    def __init__(self, ruleset: RuleSet) -> None:
        self._rules: list[_Compiled] = []
        for rule in ruleset.rules:
            if rule.validator not in VALIDATORS:
                raise ValueError(f"未知の validator: {rule.validator} (rule={rule.name})")
            Kind(rule.kind)  # 未知の kind なら ValueError
            keywords = None
            if rule.context_keywords:
                keywords = re.compile("|".join(re.escape(k) for k in rule.context_keywords))
            self._rules.append(_Compiled(rule, re.compile(rule.pattern), keywords))

    def ready(self) -> bool:
        return True

    def detect(self, text: str) -> list[Finding]:
        norm = normalize_for_matching(text)
        findings: list[Finding] = []
        for c in self._rules:
            validate = VALIDATORS[c.rule.validator]
            for m in c.regex.finditer(norm):
                start, end = m.span(c.rule.group)
                if start == end:
                    continue
                matched = norm[start:end]
                if not validate(matched):
                    continue
                confidence = c.rule.confidence
                if c.keywords is not None and c.rule.confidence_with_context is not None:
                    lo = max(0, start - c.rule.context_window)
                    hi = min(len(norm), end + c.rule.context_window)
                    if c.keywords.search(norm[lo:hi]):
                        confidence = c.rule.confidence_with_context
                findings.append(
                    Finding(
                        kind=Kind(c.rule.kind),
                        start=start,
                        end=end,
                        text=text[start:end],  # 原文の表記のまま返す
                        confidence=confidence,
                        stage=self.name,
                        rule=c.rule.name,
                    )
                )
        return _dedupe(findings)


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """同じ kind で、別の検出に完全に含まれるものは落とす（郵便番号が住所の中にある等）。"""
    findings.sort(key=lambda f: (f.start, -(f.end - f.start), -f.confidence))
    kept: list[Finding] = []
    for f in findings:
        if any(k.kind == f.kind and k.contains(f) and k is not f for k in kept):
            continue
        kept.append(f)
    return kept
