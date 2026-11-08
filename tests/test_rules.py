import pytest

from llm_guard.detectors.rules import RulesDetector
from llm_guard.normalize import normalize_for_matching
from llm_guard.validators import jp_phone_digits, luhn, my_number_check_digit


def kinds(findings):
    return sorted({f.kind.value for f in findings})


# ---- 検証関数 -------------------------------------------------------------


def test_my_number_check_digit_accepts_valid_and_rejects_others():
    # 上11桁 12345678901 に対する検査用数字は 8
    assert my_number_check_digit("123456789018")
    assert not my_number_check_digit("123456789010")
    assert not my_number_check_digit("12345678901")  # 11桁


def test_luhn():
    assert luhn("4111 1111 1111 1111")  # テスト用カード番号（Luhn 一致）
    assert not luhn("4111 1111 1111 1112")
    assert not luhn("1234")  # 桁が足りない


def test_jp_phone_digits():
    assert jp_phone_digits("090-1234-5678")
    assert jp_phone_digits("052-123-4567")
    assert not jp_phone_digits("1234-5678")


# ---- 正規化 ---------------------------------------------------------------


def test_normalize_keeps_length_and_positions():
    s = "ＴＥＬ：０９０－１２３４－５６７８　です"
    n = normalize_for_matching(s)
    assert len(n) == len(s)
    assert n.startswith("TEL:090-1234-5678 ")


# ---- 検出 -----------------------------------------------------------------


@pytest.fixture
def det(rules):
    return RulesDetector(rules)


def test_detects_mobile_phone_with_context_boost(det):
    f = det.detect("連絡先は 090-1234-5678 です")
    assert kinds(f) == ["phone"]
    assert f[0].text == "090-1234-5678"
    assert f[0].confidence >= 0.95


def test_fullwidth_phone_returns_original_text_span(det):
    text = "電話：０８０−９８７６−５４３２"
    f = det.detect(text)
    assert kinds(f) == ["phone"]
    assert text[f[0].start : f[0].end] == "０８０−９８７６−５４３２"


def test_landline_requires_separators(det):
    assert kinds(det.detect("TEL 052-123-4567")) == ["phone"]
    assert det.detect("注文番号 0521234567 を確認") == []  # 数字だけの10桁は拾わない


def test_email(det):
    f = det.detect("送付先: taro.yamada+test@example.co.jp まで")
    assert kinds(f) == ["email"]
    assert f[0].text == "taro.yamada+test@example.co.jp"


def test_my_number_only_when_check_digit_matches(det):
    assert kinds(det.detect("マイナンバー 1234 5678 9018")) == ["my_number"]
    assert det.detect("マイナンバー 1234 5678 9010") == []


def test_my_number_without_context_is_uncertain(det):
    f = det.detect("管理番号 123456789018")
    assert kinds(f) == ["my_number"]
    assert 0.4 <= f[0].confidence < 0.9


def test_credit_card_luhn(det):
    assert kinds(det.detect("カード番号 4111-1111-1111-1111")) == ["credit_card"]
    assert det.detect("4111-1111-1111-1112") == []


def test_address_with_block_number(det):
    f = det.detect("住所 愛知県名古屋市中区栄3-5-12 サンプルビル4F")
    assert "postal_address" in kinds(f)
    assert any(x.confidence >= 0.9 for x in f if x.kind == "postal_address")


def test_address_across_newline(det):
    f = det.detect("東京都千代田区\n丸の内1-1-1")
    assert "postal_address" in kinds(f)


def test_area_only_mention_stays_low(det):
    f = det.detect("来週は大阪府大阪市で展示会があります")
    assert all(x.confidence < 0.4 for x in f)


def test_postal_code_marked(det):
    f = det.detect("〒460-0008")
    assert kinds(f) == ["postal_address"]
    assert f[0].confidence >= 0.9


def test_bank_account(det):
    assert kinds(det.detect("普通 1234567")) == ["bank_account"]
    assert kinds(det.detect("支店番号 001 口座番号 7654321")) == ["bank_account"]


def test_labeled_person_name(det):
    f = det.detect("氏名: 山田 太郎\n所属: 営業部")
    assert kinds(f) == ["person_name"]
    assert f[0].text == "山田 太郎"


def test_plain_business_text_has_no_findings(det):
    text = "本日の会議では第3四半期の売上見込みと、新製品のリリース日程について議論した。"
    assert det.detect(text) == []


def test_postal_code_inside_address_is_deduped(det):
    f = det.detect("〒460-0008 愛知県名古屋市中区栄3-5-12")
    addr = [x for x in f if x.kind == "postal_address"]
    # 〒付き郵便番号と住所本体の2件。重複した包含はない
    assert len(addr) == 2


def test_mobile_with_separators_is_confirmed_but_plain_digits_are_uncertain(det):
    sep = det.detect("090-1234-5678")
    plain = det.detect("09012345678")
    assert sep[0].confidence >= 0.9
    assert 0.4 <= plain[0].confidence < 0.9
