"""Stage 1/2 と Stage 3 のつなぎ方を、偽の judge で確認する。"""

from llm_guard.config import load_policy, load_rules
from llm_guard.detectors.rules import RulesDetector
from llm_guard.pipeline import Guard
from llm_guard.policy import JudgeVerdict

RULES = load_rules("config/rules.yaml")
POLICY = load_policy("config/policy.yaml")


def make_guard(verdict: JudgeVerdict, **policy_overrides) -> tuple[Guard, list[str]]:
    calls: list[str] = []

    def judge(text: str) -> JudgeVerdict:
        calls.append(text)
        return verdict

    policy = POLICY.model_copy(
        update={"stages": POLICY.stages.model_copy(update=policy_overrides.get("stages", {}))}
    )
    return Guard(policy=policy, detectors=[RulesDetector(RULES)], judge=judge), calls


def test_judge_is_called_only_for_uncertain_findings():
    guard, calls = make_guard(JudgeVerdict(sensitive=True, kinds=["postal_address"]))
    # 郵便番号なし・ラベルなしの住所は 0.70 → 不確実帯 → Stage 3 へ
    r = guard.inspect("東京都千代田区丸の内1-1-1 に送付")
    assert calls == ["東京都千代田区丸の内1-1-1 に送付"]
    assert r.decision == "mask" and "llm_judge" in r.stages_run
    assert r.masked_text == "<ADDRESS_1> に送付"


def test_judge_not_called_when_nothing_uncertain():
    guard, calls = make_guard(JudgeVerdict(sensitive=True))
    r = guard.inspect("明日の会議は10時")
    assert calls == [] and r.decision == "allow"


def test_judge_not_called_when_block_is_already_certain():
    guard, calls = make_guard(JudgeVerdict(sensitive=True))
    r = guard.inspect("マイナンバー 1234-5678-9018 と 東京都千代田区丸の内1-1-1")
    assert r.decision == "block" and calls == []


def test_judge_says_not_sensitive_releases_uncertain():
    guard, calls = make_guard(JudgeVerdict(sensitive=False, reason="例文"))
    r = guard.inspect("東京都千代田区丸の内1-1-1 に送付")
    assert r.decision == "allow" and len(calls) == 1 and r.judge["sensitive"] is False


def test_judge_error_goes_to_review():
    guard, _ = make_guard(JudgeVerdict(error="timeout"))
    r = guard.inspect("東京都千代田区丸の内1-1-1 に送付")
    assert r.decision == "review" and "timeout" in r.reason


def test_judge_always_mode_detects_without_spans_and_reviews():
    guard, calls = make_guard(
        JudgeVerdict(sensitive=True, kinds=["other_sensitive"]), stages={"llm_judge": "always"}
    )
    r = guard.inspect("彼の健康診断の結果は要再検査だった")
    assert len(calls) == 1 and r.decision == "review"
