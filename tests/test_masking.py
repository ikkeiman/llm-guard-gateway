from llm_guard.detectors.base import Finding, Kind
from llm_guard.masking import MaskMap, mask_text, merge_spans


def span(text, sub, kind, conf=0.9):
    i = text.index(sub)
    return Finding(kind=kind, start=i, end=i + len(sub), text=sub, confidence=conf, stage="t")


def test_same_value_gets_same_placeholder_across_messages():
    mm = MaskMap()
    t1 = "山田太郎さんに電話 090-1234-5678"
    t2 = "山田太郎さんの件、折り返し済み"
    m1 = mask_text(
        t1, [span(t1, "山田太郎", Kind.PERSON_NAME), span(t1, "090-1234-5678", Kind.PHONE)], mm
    )
    m2 = mask_text(t2, [span(t2, "山田太郎", Kind.PERSON_NAME)], mm)
    assert m1 == "<PERSON_NAME_1>さんに電話 <PHONE_1>"
    assert m2 == "<PERSON_NAME_1>さんの件、折り返し済み"
    assert len(mm) == 2


def test_different_values_get_incrementing_numbers():
    mm = MaskMap()
    t = "鈴木一郎と佐藤花子"
    out = mask_text(
        t, [span(t, "鈴木一郎", Kind.PERSON_NAME), span(t, "佐藤花子", Kind.PERSON_NAME)], mm
    )
    assert out == "<PERSON_NAME_1>と<PERSON_NAME_2>"


def test_restore_puts_values_back():
    mm = MaskMap()
    t = "連絡先 taro@example.com"
    masked = mask_text(t, [span(t, "taro@example.com", Kind.EMAIL)], mm)
    assert masked == "連絡先 <EMAIL_1>"
    assert mm.restore("送信先は <EMAIL_1> です") == "送信先は taro@example.com です"


def test_overlapping_spans_are_merged_keeping_higher_confidence():
    t = "〒100-0005 東京都千代田区丸の内1-1-1"
    whole = Finding(
        kind=Kind.POSTAL_ADDRESS, start=0, end=len(t), text=t, confidence=0.7, stage="t"
    )
    code = span(t, "〒100-0005", Kind.POSTAL_ADDRESS, conf=0.9)
    merged = merge_spans([whole, code])
    assert len(merged) == 1
    assert (merged[0].start, merged[0].end) == (0, len(t))
    assert mask_text(t, [whole, code]) == "<ADDRESS_1>"
