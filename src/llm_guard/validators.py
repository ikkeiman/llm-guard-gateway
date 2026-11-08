"""Stage 1 の正規表現に続けて適用する検証関数。桁の並びだけでなく中身の整合性を見る。"""

from __future__ import annotations

from collections.abc import Callable


def digits_only(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def my_number_check_digit(s: str) -> bool:
    """個人番号（12桁）のチェックディジット検証。

    下11桁ではなく上11桁 P1..P11 に重み Q を掛けて足し、11 で割った余りから検査用数字を求める。
    Qn = n+1 (n<=6), n-5 (n>=7)。n は右から数えた位置。余りが 0 か 1 なら検査用数字は 0。
    """
    d = digits_only(s)
    if len(d) != 12:
        return False
    body, check = d[:11], int(d[11])
    total = 0
    for n in range(1, 12):
        p = int(body[11 - n])  # 右から n 番目
        q = n + 1 if n <= 6 else n - 5
        total += p * q
    remainder = total % 11
    expected = 0 if remainder <= 1 else 11 - remainder
    return expected == check


def luhn(s: str) -> bool:
    """クレジットカード番号などの Luhn チェック。13〜19桁のみ対象。"""
    d = digits_only(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def jp_phone_digits(s: str) -> bool:
    """日本の電話番号は 0 から始まる 10 桁（固定・IP）か 11 桁（携帯・一部）。"""
    d = digits_only(s)
    return d.startswith("0") and len(d) in (10, 11)


def always(_: str) -> bool:
    return True


VALIDATORS: dict[str, Callable[[str], bool]] = {
    "my_number_check_digit": my_number_check_digit,
    "luhn": luhn,
    "jp_phone_digits": jp_phone_digits,
    "always": always,
}
