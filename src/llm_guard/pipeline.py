"""検査パイプライン。各段階を順に走らせ、Policy Engine に判定を委ねる。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import BaseModel

from llm_guard.config import Policy
from llm_guard.detectors.base import Detector, Finding


class InspectionResult(BaseModel):
    decision: str
    findings: list[Finding]
    stages_run: list[str]
    timings_ms: dict[str, float]
    total_ms: float
    reason: str = ""
    masked_text: str | None = None


@dataclass
class Guard:
    policy: Policy
    detectors: list[Detector] = field(default_factory=list)

    def inspect(self, text: str) -> InspectionResult:
        t0 = time.perf_counter()
        findings: list[Finding] = []
        stages_run: list[str] = []
        timings: dict[str, float] = {}
        for det in self.detectors:
            if not det.ready():
                continue
            ts = time.perf_counter()
            findings.extend(det.detect(text))
            timings[det.name] = round((time.perf_counter() - ts) * 1000, 3)
            stages_run.append(det.name)
        # Policy Engine は次のステップで実装。ここでは暫定の判定
        strong = [f for f in findings if f.confidence >= self.policy.thresholds.uncertain_low]
        decision = "mask" if strong else "allow"
        return InspectionResult(
            decision=decision,
            findings=findings,
            stages_run=stages_run,
            timings_ms=timings,
            total_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
