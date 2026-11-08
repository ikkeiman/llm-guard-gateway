"""Policy Engine。各段階の Finding を集約し、policy.yaml の閾値とモードに従って判定する。

判定の考え方:
- confidence >= uncertain_high の検出は「確定」。mode（mask/block/review）で扱う
- uncertain_low <= confidence < uncertain_high は「不確実」。Stage 3（ローカル LLM 判定）に回すか、
  Stage 3 が無効なら uncertain_without_judge に従う
- それ未満は無視する（ログには残る）
- kinds.<kind>.min_action で、種類ごとに最低限の強さを上書きできる
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_guard.config import ACTION_SEVERITY, Action, KindPolicy, Policy
from llm_guard.detectors.base import Finding


@dataclass
class JudgeVerdict:
    """Stage 3 の結果。error が入っていれば判断不能。"""

    sensitive: bool = False
    kinds: list[str] = field(default_factory=list)
    reason: str = ""
    error: str | None = None


@dataclass
class Decision:
    action: Action
    to_mask: list[Finding]  # マスク対象（確定＋Stage 3 で昇格した不確実検出）
    ignored: list[Finding]  # 判定に使わなかった低 confidence の検出
    reason: str
    judge_needed: bool = False  # 呼び出し側が Stage 3 を走らせるべきか
    judge_used: bool = False


def _stronger(a: Action, b: Action) -> Action:
    return a if ACTION_SEVERITY[a] >= ACTION_SEVERITY[b] else b


def _apply_kind_minimum(policy: Policy, action: Action, findings: list[Finding]) -> Action:
    for f in findings:
        kp = policy.kinds.get(f.kind.value)
        if kp is not None:
            action = _stronger(action, kp.min_action)
    return action


def split(
    policy: Policy, findings: list[Finding]
) -> tuple[list[Finding], list[Finding], list[Finding]]:
    t = policy.thresholds
    confirmed = [f for f in findings if f.confidence >= t.uncertain_high]
    uncertain = [f for f in findings if t.uncertain_low <= f.confidence < t.uncertain_high]
    low = [f for f in findings if f.confidence < t.uncertain_low]
    return confirmed, uncertain, low


def provisional(policy: Policy, findings: list[Finding]) -> Action:
    """確定検出だけから暫定判定を出す。

    Stage 1 の後で block が確定するなら、以降の段階を省略するために使う。
    """
    confirmed, _, _ = split(policy, findings)
    if not confirmed:
        return "allow"
    return _apply_kind_minimum(policy, policy.mode, confirmed)


def decide(policy: Policy, findings: list[Finding], verdict: JudgeVerdict | None) -> Decision:
    """最終判定。verdict は Stage 3 を走らせた結果。走らせていなければ None。"""
    confirmed, uncertain, low = split(policy, findings)
    judge_mode = policy.stages.llm_judge
    reasons: list[str] = []

    action: Action = "allow"
    to_mask: list[Finding] = []

    if confirmed:
        action = _apply_kind_minimum(policy, policy.mode, confirmed)
        to_mask.extend(confirmed)
        reasons.append(f"確定検出 {len(confirmed)} 件")

    judge_needed = False
    if judge_mode == "always":
        judge_needed = True
    elif judge_mode == "on_uncertain" and uncertain:
        judge_needed = True

    if judge_needed and verdict is None:
        # 呼び出し側がまだ Stage 3 を走らせていない。暫定の判定を返す
        return Decision(action, to_mask, low, "; ".join(reasons), judge_needed=True)

    if verdict is not None:
        if verdict.error:
            action = _stronger(action, policy.on_judge_error)
            reasons.append(f"Stage 3 判断不能 ({verdict.error}) → {policy.on_judge_error}")
            # 不確実検出は、判断がつかない以上マスク候補に含めておく
            to_mask.extend(uncertain)
        elif verdict.sensitive:
            if uncertain:
                action = _apply_kind_minimum(policy, _stronger(action, policy.mode), uncertain)
                to_mask.extend(uncertain)
                reasons.append(f"Stage 3 が機微と判断、不確実検出 {len(uncertain)} 件を昇格")
            elif not confirmed:
                action = _stronger(action, policy.on_judge_only_detection)
                reasons.append(
                    "Stage 3 のみが機微と判断（位置が特定できない）"
                    f"→ {policy.on_judge_only_detection}"
                )
            else:
                reasons.append("Stage 3 も機微と判断")
        else:
            locked = [
                f
                for f in uncertain
                if not policy.kinds.get(f.kind.value, KindPolicy()).judge_can_release
            ]
            released = [f for f in uncertain if f not in locked]
            if released:
                reasons.append(f"Stage 3 が機微でないと判断、不確実検出 {len(released)} 件を解放")
                low = low + released
            if locked:
                action = _apply_kind_minimum(policy, _stronger(action, policy.mode), locked)
                to_mask.extend(locked)
                reasons.append(
                    f"検証済みの番号 {len(locked)} 件は Stage 3 の判断に関わらず維持"
                    "（judge_can_release: false）"
                )
    elif uncertain:
        # Stage 3 が off、または不要と判断された
        fallback = policy.uncertain_without_judge
        if fallback != "allow":
            action = _apply_kind_minimum(policy, _stronger(action, fallback), uncertain)
            to_mask.extend(uncertain)
            reasons.append(
                f"不確実検出 {len(uncertain)} 件を {fallback} として扱う（Stage 3 なし）"
            )
        else:
            low = low + uncertain
            reasons.append(f"不確実検出 {len(uncertain)} 件を無視（Stage 3 なし）")

    if not reasons:
        reasons.append("検出なし")
    return Decision(
        action=action,
        to_mask=to_mask,
        ignored=low,
        reason="; ".join(reasons),
        judge_needed=judge_needed,
        judge_used=verdict is not None,
    )
