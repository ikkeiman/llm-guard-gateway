"""合成評価データの生成。

Faker（ja_JP）で作った架空の個人情報を、業務っぽい文のテンプレート（問い合わせ・議事録・申請文・日報）に
埋め込む。陽性（個人情報あり）と陰性（なし）を同数作り、陰性には「個人情報に見えるが違うもの」を
意図的に混ぜる（人名に見える地名、電話番号に見える製品コード、伏せ字入りの番号、全角数字の金額など）。

使い方: python eval/generate_dataset.py --n 500 --seed 42 --output eval/datasets/synthetic_v1.jsonl
実在の個人のデータは一切含まない。
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from faker import Faker

# ---- 個人情報の生成 -------------------------------------------------------------


def my_number_valid(rng: random.Random) -> str:
    body = [rng.randint(0, 9) for _ in range(11)]
    total = 0
    for n in range(1, 12):
        p = body[11 - n]
        q = n + 1 if n <= 6 else n - 5
        total += p * q
    rem = total % 11
    check = 0 if rem <= 1 else 11 - rem
    digits = "".join(map(str, body)) + str(check)
    style = rng.choice(["plain", "spaced", "hyphen"])
    if style == "spaced":
        return f"{digits[:4]} {digits[4:8]} {digits[8:]}"
    if style == "hyphen":
        return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"
    return digits


def to_fullwidth(s: str) -> str:
    table = {ord("0") + i: ord("０") + i for i in range(10)}
    table[ord("-")] = ord("－")
    return s.translate(table)


@dataclass
class Piece:
    text: str
    kind: str | None = None  # None なら個人情報ではない


@dataclass
class Record:
    pieces: list[Piece] = field(default_factory=list)
    genre: str = ""
    note: str = ""

    def render(self) -> dict:
        text = ""
        spans = []
        for p in self.pieces:
            if p.kind:
                spans.append({"start": len(text), "end": len(text) + len(p.text), "kind": p.kind})
            text += p.text
        kinds = sorted({s["kind"] for s in spans})
        return {
            "text": text,
            "has_pii": bool(spans),
            "kinds": kinds,
            "spans": spans,
            "genre": self.genre,
            "note": self.note,
        }


class Gen:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.fake = Faker("ja_JP")
        Faker.seed(seed)

    # 個人情報の部品
    def name(self) -> Piece:
        n = self.fake.name()  # "姓 名"
        if self.rng.random() < 0.4:
            n = n.replace(" ", "")
        return Piece(n, "person_name")

    def phone(self) -> Piece:
        kind = self.rng.choice(["mobile", "mobile", "landline", "tollfree", "ip"])
        r = self.rng
        if kind == "mobile":
            s = f"0{r.choice('789')}0-{r.randint(1000, 9999)}-{r.randint(1000, 9999)}"
        elif kind == "landline":
            s = f"0{r.randint(1, 9)}{r.randint(1, 9)}-{r.randint(100, 999)}-{r.randint(1000, 9999)}"
        elif kind == "tollfree":
            s = f"0120-{r.randint(100, 999)}-{r.randint(100, 999)}"
        else:
            s = f"050-{r.randint(1000, 9999)}-{r.randint(1000, 9999)}"
        if r.random() < 0.15:
            s = to_fullwidth(s)
        return Piece(s, "phone")

    def email(self) -> Piece:
        return Piece(self.fake.email(), "email")

    def address(self, newline: bool = False) -> Piece:
        pref = self.fake.prefecture()
        city = self.fake.city()
        town = self.fake.town()
        block = f"{self.rng.randint(1, 5)}-{self.rng.randint(1, 30)}-{self.rng.randint(1, 20)}"
        building = ""
        if self.rng.random() < 0.4:
            building = f" {self.fake.building_name()}{self.rng.randint(101, 1210)}号室"
        sep = "\n" if newline else ""
        return Piece(f"{pref}{city}{sep}{town}{block}{building}", "postal_address")

    def postal_and_address(self) -> list[Piece]:
        code = f"〒{self.rng.randint(100, 999)}-{self.rng.randint(1000, 9999)}"
        return [Piece(code, "postal_address"), Piece(" "), self.address()]

    def my_number(self) -> Piece:
        return Piece(my_number_valid(self.rng), "my_number")

    def credit_card(self) -> Piece:
        num = self.fake.credit_card_number(card_type="visa16")
        if self.rng.random() < 0.6:
            num = "-".join(num[i : i + 4] for i in range(0, 16, 4))
        return Piece(num, "credit_card")

    def bank_account(self) -> Piece:
        kind = self.rng.choice(["普通", "当座"])
        return Piece(f"{kind} {self.rng.randint(1000000, 9999999)}", "bank_account")

    # 個人情報ではないが、紛らわしい部品（陰性用）
    def hard_negative(self) -> Piece:
        r = self.rng
        choices = [
            lambda: (
                f"{r.choice(['金沢', '福島', '宮崎', '松本', '大田', '長野', '千葉', '山口'])}支店"
            ),
            lambda: (
                f"製品コード {r.choice(['AB', 'XZ', 'MK'])}-"
                f"{r.randint(1000, 9999)}-{r.randint(1000, 9999)}"
            ),
            lambda: f"注文番号 {r.randint(2024, 2026)}-{r.randint(100000, 999999)}",
            lambda: f"伝票 No.{r.randint(10000000, 99999999)}",
            lambda: f"090-****-{r.randint(1000, 9999)}",  # 伏せ字済みの番号
            lambda: f"内線 {r.randint(1000, 9999)}",
            lambda: f"{to_fullwidth(str(r.randint(10, 999)))}万円",
            lambda: (
                f"{r.randint(2024, 2026)}年{r.randint(1, 12)}月{r.randint(1, 28)}日 "
                f"{r.randint(9, 18)}:{r.choice(['00', '30'])}"
            ),
            lambda: (
                f"株式会社{self.fake.last_name()}{r.choice(['商事', '工業', '物産', 'システムズ'])}"
            ),
            lambda: f"会議室 {r.choice('ABC')}-{r.randint(1, 9)}0{r.randint(1, 9)}",
            lambda: f"型番 {r.randint(100, 999)}-{r.randint(1000, 9999)}",  # 郵便番号に見える
            lambda: (
                f"{r.choice(['東京都', '大阪府', '福岡県', '宮城県'])}"
                f"{r.choice(['内', 'の店舗', '方面'])}"
            ),
            lambda: f"バージョン {r.randint(1, 9)}.{r.randint(0, 20)}.{r.randint(0, 99)}",
            lambda: f"{r.randint(10, 99)}件の問い合わせ",
        ]
        return Piece(r.choice(choices)())

    # ジャンル別のテンプレート。{pii} の位置に部品を入れる
    def template(self, genre: str, pii: list[Piece] | None) -> Record:
        r = self.rng
        rec = Record(genre=genre)
        neg = pii is None
        p = (lambda: self.hard_negative()) if neg else None

        def pick(i: int) -> Piece:
            return pii[i] if not neg else p()

        if genre == "inquiry":
            rec.pieces = [
                Piece(
                    r.choice(
                        [
                            "お世話になっております。",
                            "お問い合わせの件です。",
                            "至急ご確認ください。",
                        ]
                    )
                ),
                Piece(r.choice(["先日の", "本日の", "昨日いただいた"])),
                pick(0),
                Piece(r.choice(["について、", "の件で、", "に関して、"])),
                Piece(
                    r.choice(
                        [
                            "折り返しのご連絡をお願いします。",
                            "状況を教えてください。",
                            "対応をお願いします。",
                        ]
                    )
                ),
                Piece(r.choice([" 連絡先: ", " ご連絡は ", " 返信先 "])),
                pick(1) if (neg or len(pii) > 1) else Piece("担当窓口まで"),
                Piece(r.choice(["", " までお願いします。", "。"])),
            ]
        elif genre == "minutes":
            rec.pieces = [
                Piece(r.choice(["■議事録 ", "【定例】", "打合せメモ "])),
                Piece(
                    r.choice(["新システム移行", "問い合わせ対応フロー", "請求書処理", "来期予算"])
                ),
                Piece("\n- 決定事項: "),
                Piece(
                    r.choice(["次回までにドラフトを作る", "運用開始は来月", "担当を2名体制にする"])
                ),
                Piece("\n- 参加者から: "),
                pick(0),
                Piece(r.choice([" に確認する", " の対応を優先する", " を次回議題にする"])),
                Piece("\n- 備考: "),
                pick(1) if (neg or len(pii) > 1) else Piece("特になし"),
            ]
        elif genre == "application":
            rec.pieces = [
                Piece(r.choice(["【申請】", "申請書 ", "変更届 "])),
                Piece(r.choice(["口座変更", "住所変更", "経費精算", "出張申請", "備品購入"])),
                Piece("\n"),
                Piece(r.choice(["申請内容: ", "対象: ", "内容: "])),
                pick(0),
                Piece("\n"),
                Piece(
                    r.choice(["理由: 転居のため", "理由: 業務上必要なため", "理由: 更新時期のため"])
                ),
                Piece("\n"),
                Piece(r.choice(["補足: ", "備考: ", ""])),
                pick(1) if (neg or len(pii) > 1) else Piece("なし"),
            ]
        else:  # daily report
            rec.pieces = [
                Piece(r.choice(["日報 ", "本日の報告 ", "活動報告 "])),
                Piece(r.choice(["午前は資料作成、午後は", "終日", "午後から"])),
                Piece(r.choice(["訪問対応。", "電話対応。", "社内調整。"])),
                Piece(r.choice([" 訪問先: ", " 対応: ", " メモ: "])),
                pick(0),
                Piece(r.choice(["。次回は来週。", "。再訪予定。", "。要フォロー。"])),
                Piece(r.choice([" 課題: ", " 所感: "])),
                pick(1) if (neg or len(pii) > 1) else Piece("特になし"),
            ]
        return rec

    def positive(self) -> Record:
        r = self.rng
        genre = r.choice(["inquiry", "minutes", "application", "daily"])
        # 1〜2種類の個人情報を入れる。氏名は単独でも「個人情報」として扱う
        menu = [
            ("name", lambda: [self.name()]),
            ("name_phone", lambda: [self.name(), self.phone()]),
            ("phone", lambda: [self.phone()]),
            ("email", lambda: [self.email()]),
            ("name_email", lambda: [self.name(), self.email()]),
            ("address", lambda: [self.address()]),
            ("address_newline", lambda: [self.address(newline=True)]),
            ("postal_address", lambda: [Piece(""), *self.postal_and_address()]),
            ("my_number", lambda: [self.my_number()]),
            ("name_my_number", lambda: [self.name(), self.my_number()]),
            ("credit_card", lambda: [self.credit_card()]),
            ("bank_account", lambda: [self.name(), self.bank_account()]),
        ]
        label, make = r.choice(menu)
        pieces = make()
        if label == "postal_address":
            # 郵便番号＋住所は1つの塊として1番目に入れる
            combined = "".join(p.text for p in pieces)
            pieces = [Piece(combined, "postal_address")]
        rec = self.template(genre, pieces)
        rec.note = label
        return rec

    def negative(self) -> Record:
        genre = self.rng.choice(["inquiry", "minutes", "application", "daily"])
        rec = self.template(genre, None)
        rec.note = "hard_negative"
        return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="総件数（陽性・陰性を半々）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default="eval/datasets/synthetic_v1.jsonl")
    args = ap.parse_args()

    g = Gen(args.seed)
    records = []
    for i in range(args.n // 2):
        records.append({"id": f"pos-{i:04d}", **g.positive().render()})
    for i in range(args.n - args.n // 2):
        records.append({"id": f"neg-{i:04d}", **g.negative().render()})
    g.rng.shuffle(records)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pos = sum(1 for r in records if r["has_pii"])
    print(f"{out}: {len(records)} 件（陽性 {pos} / 陰性 {len(records) - pos}）, seed={args.seed}")


if __name__ == "__main__":
    main()
