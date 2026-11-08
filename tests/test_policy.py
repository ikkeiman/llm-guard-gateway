from llm_guard.config import Policy
from llm_guard.detectors.base import Finding, Kind
from llm_guard.policy import JudgeVerdict, decide, provisional


def f(kind: Kind, conf: float, start=0, end=5) -> Finding:
    return Finding(
        kind=kind, start=start, end=end, text="x" * (end - start), confidence=conf, stage="t"
    )


def test_no_findings_is_allow(policy):
    d = decide(policy, [], None)
    assert d.action == "allow" and d.to_mask == []


def test_confirmed_phone_follows_mode_mask(policy):
    d = decide(policy, [f(Kind.PHONE, 0.95)], None)
    assert d.action == "mask" and len(d.to_mask) == 1


def test_my_number_min_action_escalates_to_block(policy):
    d = decide(policy, [f(Kind.MY_NUMBER, 0.98)], None)
    assert d.action == "block"
    assert provisional(policy, [f(Kind.MY_NUMBER, 0.98)]) == "block"


def test_block_mode_blocks_everything_confirmed():
    p = Policy(mode="block")
    assert decide(p, [f(Kind.EMAIL, 0.95)], None).action == "block"


def test_uncertain_requests_judge_when_on_uncertain(policy):
    d = decide(policy, [f(Kind.POSTAL_ADDRESS, 0.7)], None)
    assert d.judge_needed is True
    assert d.action == "allow"  # まだ暫定


def test_judge_sensitive_promotes_uncertain(policy):
    d = decide(
        policy,
        [f(Kind.POSTAL_ADDRESS, 0.7)],
        JudgeVerdict(sensitive=True, kinds=["postal_address"]),
    )
    assert d.action == "mask" and len(d.to_mask) == 1 and d.judge_used


def test_judge_not_sensitive_ignores_uncertain(policy):
    d = decide(policy, [f(Kind.POSTAL_ADDRESS, 0.7)], JudgeVerdict(sensitive=False))
    assert d.action == "allow" and d.to_mask == [] and len(d.ignored) == 1


def test_judge_error_falls_back_to_review(policy):
    d = decide(policy, [f(Kind.POSTAL_ADDRESS, 0.7)], JudgeVerdict(error="timeout"))
    assert d.action == "review"


def test_judge_only_detection_without_spans_goes_to_review():
    p = Policy(stages={"llm_judge": "always"})
    d = decide(p, [], JudgeVerdict(sensitive=True, kinds=["other_sensitive"]))
    assert d.action == "review"


def test_uncertain_without_judge_uses_fallback():
    p = Policy(stages={"llm_judge": "off"}, uncertain_without_judge="mask")
    d = decide(p, [f(Kind.POSTAL_ADDRESS, 0.7)], None)
    assert d.action == "mask" and len(d.to_mask) == 1
    p2 = Policy(stages={"llm_judge": "off"}, uncertain_without_judge="allow")
    assert decide(p2, [f(Kind.POSTAL_ADDRESS, 0.7)], None).action == "allow"


def test_low_confidence_is_ignored(policy):
    d = decide(policy, [f(Kind.POSTAL_ADDRESS, 0.3)], None)
    assert d.action == "allow" and len(d.ignored) == 1 and not d.judge_needed


def test_threshold_order_is_validated():
    import pytest

    with pytest.raises(ValueError):
        Policy(thresholds={"block_at": 0.5, "uncertain_low": 0.6, "uncertain_high": 0.7})


def test_judge_can_release_false_keeps_uncertain_finding(policy):
    # policy.yaml では my_number / credit_card が judge_can_release: false
    d = decide(policy, [f(Kind.MY_NUMBER, 0.7)], JudgeVerdict(sensitive=False))
    assert d.action == "block" and len(d.to_mask) == 1
    d2 = decide(policy, [f(Kind.POSTAL_ADDRESS, 0.7)], JudgeVerdict(sensitive=False))
    assert d2.action == "allow" and d2.to_mask == []
