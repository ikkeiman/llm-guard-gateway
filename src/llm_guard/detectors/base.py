"""各検査段階が実装する共通インターフェース。"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Kind(StrEnum):
    MY_NUMBER = "my_number"
    PHONE = "phone"
    POSTAL_ADDRESS = "postal_address"
    EMAIL = "email"
    PERSON_NAME = "person_name"
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    OTHER_SENSITIVE = "other_sensitive"


class Finding(BaseModel):
    """検出1件。`text` は原文の該当部分で、マスキングにだけ使い、監査ログには残さない。"""

    kind: Kind
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    stage: str
    rule: str | None = None
    detail: str | None = None

    def overlaps(self, other: Finding) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Finding) -> bool:
        return self.start <= other.start and other.end <= self.end


@runtime_checkable
class Detector(Protocol):
    """段階の追加・差し替えは、この Protocol を満たすクラスを用意して設定で有効にするだけでよい。"""

    name: str

    def detect(self, text: str) -> list[Finding]: ...

    def ready(self) -> bool: ...
