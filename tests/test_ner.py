import pytest

from llm_guard.detectors.ner import NERDetector

det = NERDetector()
pytestmark = pytest.mark.skipif(
    not det.available(), reason="ja_ginza が未インストール（uv sync --extra ner）"
)


def names(text):
    return [(f.text, round(f.confidence, 2)) for f in det.detect(text)]


def test_detects_full_name_in_prose():
    found = names("担当の山田太郎さんから折り返しの依頼があった。")
    assert found and found[0][0] == "山田太郎"
    assert found[0][1] >= 0.9  # 直後に「さん」があるので確定に近い


def test_full_name_without_honorific_is_uncertain():
    found = names("山田太郎に資料を送る")
    assert found and found[0][0] == "山田太郎"
    assert 0.4 <= found[0][1] < 0.9


def test_single_surname_is_low_confidence():
    found = names("佐藤が同席する")
    assert all(c < 0.8 for _, c in found)


def test_place_names_are_not_persons():
    found = names("金沢支店と福島営業所の売上を比較する")
    assert found == []


def test_empty_text():
    assert det.detect("   ") == []


def test_not_ready_detector_is_skipped_gracefully():
    d = NERDetector(model="ja_not_installed_model")
    assert d.available() is False
    assert d.detect("山田太郎") == []


def test_org_and_place_suffixes_are_filtered():
    assert names("訪問先: 長野支店。所感: 福岡県内の店舗") == []


def test_trailing_newline_is_not_part_of_the_name():
    found = names("対象: 山田太郎\n理由: 転居")
    assert found and found[0][0] == "山田太郎"
